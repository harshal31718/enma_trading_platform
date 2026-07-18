"""Plan 9 QNT-4 (opt-in liquidation fee) regression.

`engine/CLAUDE.md` documents "a liquidation forfeits exactly the isolated
margin — no exit fee or slippage is added on top" as the INTENDED default
contract, not a bug (user product decision 2026-07-18: keep that default,
make an extra clearance-style fee available as an opt-in). Default
`liquidation_fee_pct=0.0` on `BacktestAdapter` must stay byte-identical to
the pre-QNT-4 path; a positive value adds `notional_at_entry *
liquidation_fee_pct` to the realized loss and to `total_fees`.

Run inside the container::

    docker exec enma_trading_platform-engine-1 pytest /app/tests/test_liquidation_fee.py
"""
import asyncio
from datetime import datetime, timezone

import numpy as np
import pytest

from services.backtest_runner import BacktestAdapter
from core.models import BacktestExecution
from core.models.cost import DefaultTransactionCostModel
from core.position import Position


class _FakeStrategy:
    def __init__(self, position):
        self.position = position
        self.balance = 10_000.0
        self.available_capital = 10_000.0
        self.available_margin = 10_000.0
        self.stop_loss = None
        self.take_profit = None
        self._pending_flip = None
        self.cost_model = DefaultTransactionCostModel()
        self.fee_rate = 0.0004
        self.slippage_pct = 0.0005
        # OHLCV [ts, open, high, low, close, volume] — only the open column
        # (index 1) is read by the non-liquidation branch.
        self.candles = np.zeros((20, 6))
        self.candles[:, 1] = 50_500.0

    def on_close_position(self, order):
        pass


def _active_trade(position, entry_index=0):
    return {
        "type": position.type,
        "symbol": "BTCUSDT",
        "qty": str(position.qty),
        "entryPrice": str(position.entry_price),
        "entryAt": datetime(2024, 1, 1, tzinfo=timezone.utc).isoformat(),
        "_entry_dt": datetime(2024, 1, 1, tzinfo=timezone.utc),
        "_entry_index": entry_index,
        "_mfe": 0.0,
        "_mae": 0.0,
        "leverage": position.leverage,
        "liqPrice": f"{position.liquidation_price:.4f}",
        "entryTag": "",
        "exitTag": "",
    }


def _adapter(liquidation_fee_pct=0.0):
    return BacktestAdapter(
        execution_model=BacktestExecution(), fee_rate=0.0004, slippage_pct=0.0005,
        funding_enabled=False, funding_rate=0.0001, symbol="BTCUSDT",
        liquidation_fee_pct=liquidation_fee_pct,
    )


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _exit_liquidation(adapter, position):
    strat = _FakeStrategy(position)
    _run(adapter.execute_exit(
        strat, "BTCUSDT", position.qty, position.liquidation_price, "liquidation",
        datetime(2024, 1, 1, tzinfo=timezone.utc), 10, 100.0, 90.0,
    ))
    return strat


# ── Default (0.0) stays byte-identical to the pre-QNT-4 path ──────────────

def test_default_fee_is_zero_loss_capped_at_margin():
    position = Position("long", qty=1.0, entry_price=50_000.0, leverage=10)
    margin = position.margin
    adapter = _adapter(liquidation_fee_pct=0.0)

    strat = _exit_liquidation(adapter, position)

    assert strat.balance == pytest.approx(10_000.0 - margin)
    assert adapter.total_fees == pytest.approx(0.0)


def test_default_fee_pnl_pct_is_exactly_minus_100():
    position = Position("long", qty=1.0, entry_price=50_000.0, leverage=10)
    adapter = _adapter(liquidation_fee_pct=0.0)
    adapter.active_trade = _active_trade(position)  # exercise _finalize_trade's pct field too

    strat = _exit_liquidation(adapter, position)

    assert float(adapter.trades[0]["pnlPct"]) == pytest.approx(-100.0)


# ── Opted in: extra clearance-style fee on top of margin ───────────────────

def test_opted_in_fee_adds_extra_loss_beyond_margin():
    position = Position("long", qty=1.0, entry_price=50_000.0, leverage=10)
    margin = position.margin
    notional = 1.0 * 50_000.0
    fee_pct = 0.01
    adapter = _adapter(liquidation_fee_pct=fee_pct)

    strat = _exit_liquidation(adapter, position)

    expected_extra = notional * fee_pct
    assert strat.balance == pytest.approx(10_000.0 - margin - expected_extra)
    assert adapter.total_fees == pytest.approx(expected_extra)


def test_opted_in_fee_makes_pnl_pct_worse_than_minus_100():
    position = Position("long", qty=1.0, entry_price=50_000.0, leverage=10)
    adapter = _adapter(liquidation_fee_pct=0.02)
    adapter.active_trade = _active_trade(position)

    strat = _exit_liquidation(adapter, position)

    assert float(adapter.trades[0]["pnlPct"]) < -100.0


def test_opted_in_fee_scales_with_short_position_notional_too():
    position = Position("short", qty=2.0, entry_price=30_000.0, leverage=5)
    notional = 2.0 * 30_000.0
    fee_pct = 0.005
    adapter = _adapter(liquidation_fee_pct=fee_pct)

    _exit_liquidation(adapter, position)

    assert adapter.total_fees == pytest.approx(notional * fee_pct)


def test_non_liquidation_exit_is_unaffected_by_the_fee_param():
    """Sanity check: liquidation_fee_pct must only ever engage on
    reason=="liquidation" — a normal SL/TP close must be byte-identical
    regardless of this param's value."""
    position_a = Position("long", qty=1.0, entry_price=50_000.0, leverage=10)
    position_b = Position("long", qty=1.0, entry_price=50_000.0, leverage=10)
    adapter_off = _adapter(liquidation_fee_pct=0.0)
    adapter_on = _adapter(liquidation_fee_pct=0.05)

    strat_a = _FakeStrategy(position_a)
    strat_b = _FakeStrategy(position_b)
    _run(adapter_off.execute_exit(strat_a, "BTCUSDT", 1.0, 51_000.0, "take_profit",
                                   datetime(2024, 1, 1, tzinfo=timezone.utc), 10, 51_200.0, 49_800.0))
    _run(adapter_on.execute_exit(strat_b, "BTCUSDT", 1.0, 51_000.0, "take_profit",
                                  datetime(2024, 1, 1, tzinfo=timezone.utc), 10, 51_200.0, 49_800.0))

    assert strat_a.balance == pytest.approx(strat_b.balance)
    assert adapter_off.total_fees == pytest.approx(adapter_on.total_fees)
