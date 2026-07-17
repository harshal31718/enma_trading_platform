"""Plan 24 Step S-1 regression: `BaseStrategy.size_by_notional()`
(`engine/core/strategy.py`) previously sized to exactly `equity * pct`
capped only by `max_qty()` (leverage-based) — at `pct=1.0` and leverage=1,
this always sits exactly on the equity boundary, so adverse slippage + the
taker fee alone push `req_margin + fee` just over `free_balance`
(`EntryFill.affordable()`, `core/models/base.py`), rejecting EVERY entry.
This is why BestSupertrend (the only seeded strategy using
`size_by_notional`, via `NotionalPortfolio`) never traded at its own
default settings (`position_size_pct=1.0`, platform default `leverage=1`).

The fix sizes DOWN to the true affordable notional instead of letting the
downstream affordability check reject the entry outright.

Run inside the container::

    docker exec enma_trading_platform-engine-1 pytest /app/tests/test_size_by_notional_affordability.py
"""
import numpy as np
import pytest

from core.strategy import BaseStrategy


def _make_strategy(balance=10_000.0, leverage=1, fee_rate=0.0005, slippage_pct=0.0005, price=100.0):
    s = BaseStrategy()
    s.balance = balance
    s.leverage = leverage
    s.fee_rate = fee_rate
    s.slippage_pct = slippage_pct
    # `price` is a read-only property derived from the last candle's close
    # (index 2: [timestamp, open, close, high, low, volume]).
    s.candles = np.array([[0.0, price, price, price, price, 0.0]])
    return s


def _affordable(s, qty, price, leverage):
    """Mirrors execute_entry's real affordability check (backtest_runner.py)."""
    fill_price = price * (1.0 + s.slippage_pct)  # buy side, worst case
    notional = qty * fill_price
    req_margin = notional / max(leverage, 1)
    fee = notional * s.fee_rate
    return req_margin + fee <= s.balance


def test_pct_1_0_leverage_1_no_longer_rejected():
    """The exact bug: pct=1.0 at leverage=1 must now produce an affordable qty."""
    s = _make_strategy(balance=10_000.0, leverage=1)
    qty = s.size_by_notional(pct=1.0)
    assert qty > 0
    assert _affordable(s, qty, s.price, s.leverage)


def test_pct_1_0_leverage_1_qty_less_than_naive_equity_sizing():
    """Confirms the fix actually sizes DOWN — not a no-op."""
    s = _make_strategy(balance=10_000.0, leverage=1)
    naive_qty = (s.equity * 1.0) / s.price  # equity == balance, no position open
    qty = s.size_by_notional(pct=1.0)
    assert qty < naive_qty


def test_leverage_3_headroom_barely_needed_still_affordable():
    """At leverage=3 (golden_master.py's harness), pct=1.0 already had
    headroom pre-fix — confirms the fix doesn't wrongly shrink an
    already-affordable size below what max_qty() would allow."""
    s = _make_strategy(balance=10_000.0, leverage=3)
    qty = s.size_by_notional(pct=1.0)
    assert qty > 0
    assert _affordable(s, qty, s.price, s.leverage)
    # Should be very close to the naive equity*pct/price sizing (leverage=3
    # has ~3x margin headroom vs the tiny fee+slippage drag)
    naive_qty = (s.equity * 1.0) / s.price
    assert qty == pytest.approx(naive_qty, rel=0.01)


def test_pct_0_9_leverage_1_matches_new_bestsupertrend_default():
    """BestSupertrend's new default (0.9) at leverage=1 — some but not all
    headroom is needed."""
    s = _make_strategy(balance=10_000.0, leverage=1)
    qty = s.size_by_notional(pct=0.9)
    assert qty > 0
    assert _affordable(s, qty, s.price, s.leverage)


def test_zero_balance_returns_zero_not_negative():
    s = _make_strategy(balance=0.0, leverage=1)
    qty = s.size_by_notional(pct=1.0)
    assert qty == 0.0


def test_external_reserved_margin_reduces_affordable_qty():
    """Shared-wallet multi-symbol backtests (F-017): other symbols' reserved
    margin must reduce this symbol's affordable notional."""
    s = _make_strategy(balance=10_000.0, leverage=1)
    s._external_reserved_margin = 5_000.0
    qty = s.size_by_notional(pct=1.0)
    free_balance = s.balance - s._external_reserved_margin
    fill_price = s.price * (1.0 + s.slippage_pct)
    notional = qty * fill_price
    req_margin = notional / max(s.leverage, 1)
    fee = notional * s.fee_rate
    assert req_margin + fee <= free_balance + 1e-6


def test_still_capped_by_max_qty_when_leverage_provides_more_headroom_than_pct():
    """A small pct at high leverage should still be capped by max_qty(),
    not accidentally inflated by the affordability formula."""
    s = _make_strategy(balance=10_000.0, leverage=50)
    qty = s.size_by_notional(pct=0.1)
    naive_qty = (s.equity * 0.1) / s.price
    assert qty == pytest.approx(naive_qty, rel=1e-6)
