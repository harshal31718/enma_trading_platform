"""Plan 9 Step 9.10 (QNT-11) regression: `LadderedTransactionCostModel`
(engine/core/models/cost.py) — the opt-in fill-model ladder layering
volatility-scaled slippage + square-root market impact on top of the base
constant `slippage_pct`.

Also covers the `DefaultTransactionCostModel.adverse_fill()` signature
widening (added an optional `qty` param so the ladder can compute impact
without a second call-site change) — must stay byte-identical for the
default model regardless of whether `qty` is passed.

Run inside the container::

    docker exec enma_trading_platform-engine-1 pytest /app/tests/test_laddered_cost_model.py
"""
import numpy as np
import pytest

from core.models.cost import DefaultTransactionCostModel, LadderedTransactionCostModel


class _FakeStrategy:
    def __init__(self, price=100.0, slippage_pct=0.0005, timeframe="1h", candles=None, atr=1.0):
        self.price = price
        self.slippage_pct = slippage_pct
        self.timeframe = timeframe
        self.candles = candles if candles is not None else np.empty((0, 6))
        self._atr_value = atr

    def _atr(self, period=14):
        return self._atr_value


def _candles(n, close=100.0, volume=1000.0):
    ts = np.arange(n) * 3_600_000.0
    return np.column_stack([
        ts, np.full(n, close), np.full(n, close), np.full(n, close), np.full(n, close), np.full(n, volume),
    ]).astype(np.float64)


# ── DefaultTransactionCostModel: qty param is a pure no-op ────────────────────

def test_default_adverse_fill_unaffected_by_qty_param():
    cm = DefaultTransactionCostModel()
    s = _FakeStrategy(price=100.0, slippage_pct=0.001)
    assert cm.adverse_fill(s, 100.0, "buy") == cm.adverse_fill(s, 100.0, "buy", qty=5.0)
    assert cm.adverse_fill(s, 100.0, "sell") == cm.adverse_fill(s, 100.0, "sell", qty=5.0)
    assert cm.adverse_fill(s, 100.0, "buy", qty=5.0) == pytest.approx(100.0 * 1.001)


# ── LadderedTransactionCostModel: volatility component ─────────────────────────

def test_zero_atr_and_zero_qty_matches_base_slippage_only():
    cm = LadderedTransactionCostModel()
    s = _FakeStrategy(price=100.0, slippage_pct=0.001, atr=0.0)
    out = cm.adverse_fill(s, 100.0, "buy")
    assert out == pytest.approx(100.0 * 1.001)  # only base slippage, no vol/impact component


def test_higher_atr_widens_the_fill():
    cm = LadderedTransactionCostModel()
    cm.vol_slip_mult = 0.5
    low_vol = _FakeStrategy(price=100.0, slippage_pct=0.0, atr=1.0)   # ATR% = 1%
    high_vol = _FakeStrategy(price=100.0, slippage_pct=0.0, atr=5.0)  # ATR% = 5%
    fill_low = cm.adverse_fill(low_vol, 100.0, "buy")
    fill_high = cm.adverse_fill(high_vol, 100.0, "buy")
    assert fill_high > fill_low > 100.0


def test_atr_pct_guards_against_zero_price():
    cm = LadderedTransactionCostModel()
    s = _FakeStrategy(price=0.0, atr=1.0)
    assert cm._atr_pct(s) == 0.0


def test_atr_pct_guards_against_exception():
    cm = LadderedTransactionCostModel()
    class _Broken(_FakeStrategy):
        def _atr(self, period=14):
            raise RuntimeError("no indicator data")
    s = _Broken(price=100.0)
    assert cm._atr_pct(s) == 0.0


# ── LadderedTransactionCostModel: impact component ──────────────────────────────

def test_no_impact_when_qty_not_provided():
    cm = LadderedTransactionCostModel()
    cm.vol_slip_mult = 0.0
    s = _FakeStrategy(price=100.0, slippage_pct=0.0, atr=0.0, candles=_candles(30))
    out = cm.adverse_fill(s, 100.0, "buy")  # no qty kwarg
    assert out == pytest.approx(100.0)


def test_larger_qty_produces_larger_impact():
    cm = LadderedTransactionCostModel()
    cm.vol_slip_mult, cm.impact_mult = 0.0, 0.1
    s = _FakeStrategy(price=100.0, slippage_pct=0.0, atr=0.0, candles=_candles(30, volume=1000.0))
    small = cm.adverse_fill(s, 100.0, "buy", qty=1.0)
    large = cm.adverse_fill(s, 100.0, "buy", qty=1000.0)
    assert large > small > 100.0


def test_zero_adv_disables_impact_component():
    cm = LadderedTransactionCostModel()
    cm.vol_slip_mult, cm.impact_mult = 0.0, 0.1
    s = _FakeStrategy(price=100.0, slippage_pct=0.0, atr=0.0, candles=_candles(30, volume=0.0))
    out = cm.adverse_fill(s, 100.0, "buy", qty=100.0)
    assert out == pytest.approx(100.0)  # adv=0 -> impact skipped, not a divide-by-zero crash


def test_adv_quote_uses_trailing_24h_window_for_hourly_timeframe():
    cm = LadderedTransactionCostModel()
    s = _FakeStrategy(price=100.0, timeframe="1h", candles=_candles(100, close=50.0, volume=10.0))
    # ~24 hourly candles * (volume=10 * close=50) = 24 * 500 = 12000
    assert cm._adv_quote(s) == pytest.approx(24 * 500.0, rel=0.05)


def test_adv_quote_empty_candles_returns_zero():
    cm = LadderedTransactionCostModel()
    s = _FakeStrategy(price=100.0, candles=np.empty((0, 6)))
    assert cm._adv_quote(s) == 0.0


# ── Sell side widens downward, symmetric to buy ────────────────────────────────

def test_sell_side_fills_lower_with_wider_effective_slippage():
    cm = LadderedTransactionCostModel()
    cm.vol_slip_mult, cm.impact_mult = 0.5, 0.0
    s = _FakeStrategy(price=100.0, slippage_pct=0.0, atr=2.0)  # ATR% = 2%
    out = cm.adverse_fill(s, 100.0, "sell")
    assert out < 100.0
    assert out == pytest.approx(100.0 * (1.0 - 0.5 * 0.02))
