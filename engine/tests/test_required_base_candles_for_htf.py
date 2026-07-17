"""Plan 24 Step S-3 regression: `required_base_candles_for_htf()`
(`engine/utils/timeframes.py`) — estimates how many base-timeframe candles
are needed to form `pd + 2` completed HTF buckets, so a structurally
unsatisfiable tf/timeframe combo (e.g. tf="weekly" on a 1h-timeframe
backtest with a short date range) can be flagged instead of silently
producing zero trades forever.

Run inside the container::

    docker exec enma_trading_platform-engine-1 pytest /app/tests/test_required_base_candles_for_htf.py
"""
import pytest

from utils.timeframes import required_base_candles_for_htf


def test_daily_htf_on_1h_base_needs_twelve_days_worth():
    # pd=10 -> pd+2=12 daily buckets; 1h base -> 24 candles/day
    result = required_base_candles_for_htf("daily", 10, "1h")
    assert result == 12 * 24


def test_weekly_htf_on_1h_base_needs_far_more_candles():
    result = required_base_candles_for_htf("weekly", 10, "1h")
    assert result == pytest.approx(12 * 7 * 24, abs=1)


def test_monthly_htf_on_1d_base():
    result = required_base_candles_for_htf("monthly", 10, "1d")
    assert result == 12 * 30


def test_same_timeframe_needs_exactly_pd_plus_2():
    result = required_base_candles_for_htf("1h", 10, "1h")
    assert result == 12


def test_unrecognized_htf_label_returns_none():
    assert required_base_candles_for_htf("fortnightly", 10, "1h") is None


def test_unrecognized_base_timeframe_returns_none():
    assert required_base_candles_for_htf("daily", 10, "7h") is None


def test_case_insensitive():
    assert required_base_candles_for_htf("DAILY", 10, "1H") == required_base_candles_for_htf("daily", 10, "1h")


def test_higher_pd_needs_more_candles():
    small = required_base_candles_for_htf("daily", 5, "1h")
    large = required_base_candles_for_htf("daily", 20, "1h")
    assert large > small
