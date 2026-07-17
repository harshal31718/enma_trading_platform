"""Plan 9 Step 9.7 (QNT-5) regression: `BacktestAdapter.charge_funding()`'s
opt-in historical-funding-events branch (`services/backtest_runner.py`).

Default (`historical_funding_events=None`) must stay byte-identical to the
pre-9.7 flat-rate/fixed-8h-boundary path. When events are provided, each
REAL event's own signed rate (and mark price, when available) is charged
exactly once, walking `last_funding_dt` forward event-by-event instead of
boundary-by-boundary.

Run inside the container::

    docker exec enma_trading_platform-engine-1 pytest /app/tests/test_historical_funding.py
"""
import asyncio
from datetime import datetime, timezone

import numpy as np
import pytest

from services.backtest_runner import BacktestAdapter
from core.models import BacktestExecution


class _FakePosition:
    def __init__(self, is_long=True, qty=2.0):
        self.type = "long" if is_long else "short"
        self.qty = qty


class _FakeStrategy:
    def __init__(self, is_long=True, qty=2.0):
        self.position = _FakePosition(is_long, qty)
        self.balance = 10_000.0


def _adapter(funding_rate=0.0001, events=None, funding_enabled=True):
    a = BacktestAdapter(
        execution_model=BacktestExecution(), fee_rate=0.0004, slippage_pct=0.0005,
        funding_enabled=funding_enabled, funding_rate=funding_rate, symbol="BTCUSDT",
        historical_funding_events=events,
    )
    return a


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ── Default path (events=None) stays exactly as before ────────────────────────

def test_default_flat_rate_path_unaffected_by_new_param():
    a = _adapter(funding_rate=0.0001, events=None)
    assert a.historical_funding_events is None
    strat = _FakeStrategy(is_long=True, qty=2.0)
    a.last_funding_dt = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)

    _run(a.charge_funding(strat, close_t=50_000.0, time_t=datetime(2024, 1, 1, 8, 0, tzinfo=timezone.utc)))

    # One flat-rate boundary crossed (00:00 -> 08:00): funding = qty*price*rate
    expected = 2.0 * 50_000.0 * 0.0001
    assert a.total_funding == pytest.approx(expected)
    assert strat.balance == pytest.approx(10_000.0 - expected)
    assert a.last_funding_dt == datetime(2024, 1, 1, 8, 0, tzinfo=timezone.utc)


def test_funding_disabled_charges_nothing_regardless_of_events():
    events = np.array([[1_704_067_200_000.0, 0.0005, 50_000.0]])  # 2024-01-01T00:00Z
    a = _adapter(events=events, funding_enabled=False)
    strat = _FakeStrategy()
    a.last_funding_dt = datetime(2023, 12, 31, tzinfo=timezone.utc)
    _run(a.charge_funding(strat, close_t=50_000.0, time_t=datetime(2024, 1, 2, tzinfo=timezone.utc)))
    assert a.total_funding == 0.0
    assert strat.balance == 10_000.0


# ── Historical events path ─────────────────────────────────────────────────────

def test_historical_event_charges_its_own_signed_rate_and_mark_price():
    event_ms = datetime(2024, 1, 1, 8, 0, tzinfo=timezone.utc).timestamp() * 1000.0
    events = np.array([[event_ms, 0.0005, 48_000.0]])  # rate=0.05%, markPrice=48000 (differs from close_t)
    a = _adapter(events=events)
    strat = _FakeStrategy(is_long=True, qty=1.5)
    a.last_funding_dt = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)

    _run(a.charge_funding(strat, close_t=50_000.0, time_t=datetime(2024, 1, 1, 9, 0, tzinfo=timezone.utc)))

    expected = 1.5 * 48_000.0 * 0.0005  # uses the event's OWN mark_price, not close_t
    assert a.total_funding == pytest.approx(expected)
    assert strat.balance == pytest.approx(10_000.0 - expected)


def test_missing_mark_price_falls_back_to_close_t():
    event_ms = datetime(2024, 1, 1, 8, 0, tzinfo=timezone.utc).timestamp() * 1000.0
    events = np.array([[event_ms, 0.0003, np.nan]])  # mark_price NULL in DB
    a = _adapter(events=events)
    strat = _FakeStrategy(is_long=True, qty=1.0)
    a.last_funding_dt = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)

    _run(a.charge_funding(strat, close_t=52_000.0, time_t=datetime(2024, 1, 1, 9, 0, tzinfo=timezone.utc)))

    assert a.total_funding == pytest.approx(1.0 * 52_000.0 * 0.0003)


def test_short_position_receives_when_rate_is_positive():
    # side_sign = -1 for short -> positive funding_rate means the short
    # RECEIVES (balance increases), mirroring the flat-rate branch's sign.
    event_ms = datetime(2024, 1, 1, 8, 0, tzinfo=timezone.utc).timestamp() * 1000.0
    events = np.array([[event_ms, 0.0004, 50_000.0]])
    a = _adapter(events=events)
    strat = _FakeStrategy(is_long=False, qty=1.0)
    a.last_funding_dt = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)

    _run(a.charge_funding(strat, close_t=50_000.0, time_t=datetime(2024, 1, 1, 9, 0, tzinfo=timezone.utc)))

    expected = -1.0 * 1.0 * 50_000.0 * 0.0004  # side_sign=-1 -> total_funding negative -> balance increases
    assert a.total_funding == pytest.approx(expected)
    assert strat.balance == pytest.approx(10_000.0 - expected)
    assert strat.balance > 10_000.0


def test_multiple_events_in_window_all_charged_and_cursor_advances():
    t0 = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
    events = np.array([
        [datetime(2024, 1, 1, 8, 0, tzinfo=timezone.utc).timestamp() * 1000.0, 0.0001, 50_000.0],
        [datetime(2024, 1, 1, 16, 0, tzinfo=timezone.utc).timestamp() * 1000.0, 0.0002, 51_000.0],
        [datetime(2024, 1, 2, 0, 0, tzinfo=timezone.utc).timestamp() * 1000.0, 0.0003, 52_000.0],
    ])
    a = _adapter(events=events)
    strat = _FakeStrategy(is_long=True, qty=1.0)
    a.last_funding_dt = t0

    # time_t only reaches 20:00 on day 1 -> first two events charged, third not yet.
    _run(a.charge_funding(strat, close_t=50_500.0, time_t=datetime(2024, 1, 1, 20, 0, tzinfo=timezone.utc)))

    expected = (1.0 * 50_000.0 * 0.0001) + (1.0 * 51_000.0 * 0.0002)
    assert a.total_funding == pytest.approx(expected)
    assert a.last_funding_dt == datetime(2024, 1, 1, 16, 0, tzinfo=timezone.utc)

    # Advancing further picks up the third event exactly once (no double-charge).
    _run(a.charge_funding(strat, close_t=52_500.0, time_t=datetime(2024, 1, 2, 1, 0, tzinfo=timezone.utc)))
    expected_total = expected + (1.0 * 52_000.0 * 0.0003)
    assert a.total_funding == pytest.approx(expected_total)
    assert a.last_funding_dt == datetime(2024, 1, 2, 0, 0, tzinfo=timezone.utc)


def test_no_events_in_window_charges_nothing_and_cursor_unchanged():
    far_future_ms = datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp() * 1000.0
    events = np.array([[far_future_ms, 0.0001, 50_000.0]])
    a = _adapter(events=events)
    strat = _FakeStrategy()
    start = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
    a.last_funding_dt = start

    _run(a.charge_funding(strat, close_t=50_000.0, time_t=datetime(2024, 1, 1, 9, 0, tzinfo=timezone.utc)))

    assert a.total_funding == 0.0
    assert a.last_funding_dt == start  # cursor unchanged — no event to advance to


def test_empty_events_array_is_treated_as_historical_mode_charging_nothing():
    """An empty (but non-None) array means 'historical mode, zero events
    fetched for this range' — distinct from None (flat-rate fallback).
    Must not crash and must not fall back to the flat-rate path."""
    a = _adapter(funding_rate=0.0001, events=np.empty((0, 3)))
    strat = _FakeStrategy()
    a.last_funding_dt = datetime(2024, 1, 1, tzinfo=timezone.utc)
    _run(a.charge_funding(strat, close_t=50_000.0, time_t=datetime(2024, 1, 2, tzinfo=timezone.utc)))
    assert a.total_funding == 0.0  # NOT the flat-rate fallback's nonzero charge
