"""Plan 13 (informative / multi-timeframe contract) regression:
`BaseStrategy.htf()` (engine/core/strategy.py) — as-of alignment of a
higher-timeframe candle series onto the base timeframe's timestamps.

Covers the plan's own verification gate:
  - alignment correctness: a hand-built HTF series aligns to base timestamps
    with the correct as-of value.
  - no-lookahead: a base candle never sees an HTF candle that closes after
    (or at the same instant it would still be in-progress relative to) that
    base candle's own open time.
  - default [] / no htf() call is a no-op (golden-master safety net, single
    assertion here — the real proof is backtest_runner.py's Plan 13 wiring
    only fetching for `informative_timeframes != []`).

Run inside the container::

    docker exec enma_trading_platform-engine-1 pytest /app/tests/test_informative_alignment.py
"""
import numpy as np
import pytest

from core.strategy import BaseStrategy


def _candle(ts_ms, o, c, h, l, v):
    return [float(ts_ms), float(o), float(c), float(h), float(l), float(v)]


def _base_series(start_ms, step_ms, n, price_start=100.0):
    """n base candles, 1 unit price increment each, `step_ms` apart."""
    return np.array([
        _candle(start_ms + i * step_ms, price_start + i, price_start + i, price_start + i, price_start + i, 1.0)
        for i in range(n)
    ], dtype=np.float64)


def _htf_series(start_ms, step_ms, n, price_start=1000.0):
    return np.array([
        _candle(start_ms + i * step_ms, price_start + i, price_start + i, price_start + i, price_start + i, 1.0)
        for i in range(n)
    ], dtype=np.float64)


def _strategy_with_htf(base_candles, htf_tf, htf_raw):
    s = BaseStrategy()
    s.informative_timeframes = [htf_tf]
    s._htf_raw = {htf_tf: htf_raw}
    s.prepare(base_candles)
    return s


def test_alignment_picks_last_closed_htf_bar():
    """4 base 15m candles spanning one 1h HTF bar's lifetime; the HTF bar
    (open at t=0, closes at t=3_600_000) must only become visible on the
    base candle whose own open time is >= the HTF close time."""
    HOUR = 3_600_000
    QUARTER = 900_000  # 15m
    base = _base_series(start_ms=0, step_ms=QUARTER, n=8)  # covers 0..1h45m
    htf = _htf_series(start_ms=0, step_ms=HOUR, n=1)  # one HTF bar: opens t=0, closes t=1h

    s = _strategy_with_htf(base, "1h", htf)
    aligned = s.htf("1h")

    # Base candles at t=0,15m,30m,45m (indices 0-3) open BEFORE the HTF bar's
    # close (t=1h) -> no closed HTF bar yet -> NaN.
    for i in range(4):
        assert np.all(np.isnan(aligned[i])), f"index {i} should be NaN (HTF bar not yet closed)"

    # Base candle at t=1h (index 4) opens exactly at the HTF bar's close time
    # -> that HTF bar is now visible.
    assert not np.isnan(aligned[4]).any()
    assert aligned[4][1] == htf[0][1]  # open
    assert aligned[4][2] == htf[0][2]  # close

    # Every later base candle (5, 6, 7) still sees the same (only) closed HTF bar.
    for i in range(5, 8):
        assert aligned[i][2] == htf[0][2]


def test_no_lookahead_multiple_htf_bars():
    """3 HTF bars; each base candle must only ever see the LATEST already-
    closed HTF bar, never one that closes at or after its own open time."""
    HOUR = 3_600_000
    QUARTER = 900_000
    base = _base_series(start_ms=0, step_ms=QUARTER, n=13)  # 0 .. 3h
    htf = _htf_series(start_ms=0, step_ms=HOUR, n=3)  # bars close at 1h, 2h, 3h

    s = _strategy_with_htf(base, "1h", htf)
    aligned = s.htf("1h")
    base_times = base[:, 0]
    htf_close_times = htf[:, 0] + HOUR

    for i, t in enumerate(base_times):
        row = aligned[i]
        if np.isnan(row).any():
            # No closed HTF bar yet — verify that's actually true.
            assert not np.any(htf_close_times <= t)
            continue
        # The assigned HTF bar's close time must be <= this base candle's
        # open time (never looks into the future), and must be the LATEST
        # such bar (no stale under-assignment either).
        assigned_open = row[1]
        assigned_idx = int(assigned_open - 1000.0)  # price_start=1000, +i per bar
        assigned_close_time = htf_close_times[assigned_idx]
        assert assigned_close_time <= t
        later_closed = [ct for ct in htf_close_times if ct <= t and ct > assigned_close_time]
        assert later_closed == [], f"index {i}: a more recent closed HTF bar was available but not used"


def test_htf_without_raw_data_returns_all_nan():
    """A declared timeframe with no fetched data (fetch failure case) must
    degrade to all-NaN, not raise — matching an indicator with insufficient
    warmup, not a crash."""
    base = _base_series(start_ms=0, step_ms=900_000, n=5)
    s = _strategy_with_htf(base, "1h", np.empty((0, 6), dtype=np.float64))
    aligned = s.htf("1h")
    assert aligned.shape == (5, 6)
    assert np.all(np.isnan(aligned))


def test_htf_result_cached_within_one_prepare_call():
    base = _base_series(start_ms=0, step_ms=900_000, n=5)
    htf = _htf_series(start_ms=0, step_ms=3_600_000, n=2)
    s = _strategy_with_htf(base, "1h", htf)
    first = s.htf("1h")
    second = s.htf("1h")
    assert first is second  # same object -> cached, not recomputed


def test_htf_cache_cleared_on_next_prepare_call():
    base = _base_series(start_ms=0, step_ms=900_000, n=5)
    htf = _htf_series(start_ms=0, step_ms=3_600_000, n=2)
    s = _strategy_with_htf(base, "1h", htf)
    first = s.htf("1h")
    s.prepare(base)  # re-prepare (e.g. live rolling-window refresh)
    second = s.htf("1h")
    assert first is not second  # cache invalidated, recomputed fresh
    assert np.array_equal(first, second, equal_nan=True)  # same inputs -> same result


def test_default_informative_timeframes_is_empty_noop():
    s = BaseStrategy()
    assert s.informative_timeframes == []
    assert s._htf_raw == {}
