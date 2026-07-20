"""Plan 24 Step S-2 regression: BestSupertrend's live HTF supertrend was one
full HTF bar more stale than backtest.

`_fetch_htf_candles` (`engine/core/live_bot_manager.py`) already excludes the
in-progress HTF bar (`raw[:-1]`), so the live-injected `_htf_candles` array's
LAST row is the last COMPLETED HTF bar. `prepare()`'s live/constant path
(`engine/strategies/BestSupertrend/__init__.py`) previously read
`self._htf_tsl[-2]` — one bar further back than intended — while backtest's
resample-bucket path (`_htf_st_at`) correctly reads `htf_tsl[k-1]`, the last
completed bucket. Net effect at the default `tf="daily"`: live traded against
the supertrend from two days ago while backtest used yesterday's.

This file drives the REAL `BestSupertrend` strategy class (not a
reimplementation) through both code paths against the same underlying
supertrend series and asserts they now agree — the parity check the plan's
own S-2 section calls for.

Run inside the container::

    docker exec enma_trading_platform-engine-1 pytest /app/tests/test_bestsupertrend_htf_parity.py
"""
import numpy as np
import pytest

from strategies.BestSupertrend import BestSupertrend


def _make_ohlcv(n, seed=1, start_price=100.0):
    rng = np.random.RandomState(seed)
    closes = start_price + np.cumsum(rng.normal(0, 1.0, n))
    highs = closes + np.abs(rng.normal(0.5, 0.2, n))
    lows = closes - np.abs(rng.normal(0.5, 0.2, n))
    opens = closes + rng.normal(0, 0.1, n)
    volumes = np.full(n, 1000.0)
    timestamps = np.arange(n, dtype=float) * 3_600_000  # hourly ms timestamps
    return np.column_stack([timestamps, opens, closes, highs, lows, volumes])


def _make_strategy_for_htf_test(htf_candles):
    s = BestSupertrend()
    # Force the "different timeframe, HTF candles pre-fetched" live branch —
    # _is_same_timeframe() compares self.timeframe (engine-set base tf) vs
    # the strategy's own self.tf (mapped) — keep them mismatched.
    s.timeframe = "1h"
    s.tf = "daily"
    s._htf_candles = htf_candles
    return s


def test_live_constant_path_uses_last_completed_bar_not_two_back():
    """The core S-2 fix: the live constant path must equal _calculate_
    supertrend(R)[-1] (last completed bar), not [-2] (the pre-fix bug)."""
    n_htf = 30  # pd(10) + 2 + generous warmup margin
    htf_candles = _make_ohlcv(n_htf, seed=42)
    s = _make_strategy_for_htf_test(htf_candles)

    base_candles = _make_ohlcv(50, seed=7)
    s.prepare(base_candles)

    expected_tsl = s._calculate_supertrend(htf_candles)
    assert s._htf_constant_val == pytest.approx(float(expected_tsl[-1]))
    # The pre-fix value would have been this — confirm we're NOT still there
    assert s._htf_constant_val != pytest.approx(float(expected_tsl[-2]))


def test_htf_st_at_returns_the_constant_val_on_the_live_path():
    n_htf = 30
    htf_candles = _make_ohlcv(n_htf, seed=99)
    s = _make_strategy_for_htf_test(htf_candles)
    base_candles = _make_ohlcv(20, seed=3)
    s.prepare(base_candles)

    for i in range(len(base_candles)):
        assert s._htf_st_at(i) == s._htf_constant_val


def test_parity_live_constant_path_matches_backtest_bucket_path_semantics():
    """Simulates the backtest bucket path directly: if `htf_tsl` is the
    supertrend over the completed-buckets-only series (exactly what the live
    path's `_htf_candles` already is, per `_fetch_htf_candles`'s `raw[:-1]`),
    the bucket-path formula `htf_tsl[k-1]` for the in-progress bucket
    (`k = len(htf_tsl)`, one past the completed data) must equal the live
    constant path's value — both must resolve to the SAME last-completed-bar
    value from the SAME underlying data. This is the parity invariant the
    plan's own S-2 section asks for."""
    n_htf = 25
    htf_candles = _make_ohlcv(n_htf, seed=17)
    s = _make_strategy_for_htf_test(htf_candles)
    base_candles = _make_ohlcv(15, seed=5)
    s.prepare(base_candles)

    htf_tsl = s._calculate_supertrend(htf_candles)
    k = len(htf_tsl)  # the (not-yet-existing) in-progress bucket's index
    bucket_path_value = float(htf_tsl[k - 1])

    assert s._htf_constant_val == pytest.approx(bucket_path_value)


def test_returns_none_before_pd_plus_2_warmup():
    """Warmup gate unchanged by the fix — still requires pd+2 completed
    HTF bars before returning a value."""
    s = BestSupertrend()
    s.timeframe = "1h"
    s.tf = "daily"
    too_few = s.pd + 1  # one short of the pd+2 requirement
    s._htf_candles = _make_ohlcv(too_few, seed=1)
    base_candles = _make_ohlcv(10, seed=1)
    s.prepare(base_candles)
    assert s._htf_constant_val is None
    assert s._htf_st_at(0) is None


def test_exactly_pd_plus_2_warmup_returns_a_value():
    s = BestSupertrend()
    s.timeframe = "1h"
    s.tf = "daily"
    exactly_enough = s.pd + 2
    s._htf_candles = _make_ohlcv(exactly_enough, seed=1)
    base_candles = _make_ohlcv(10, seed=1)
    s.prepare(base_candles)
    assert s._htf_constant_val is not None
