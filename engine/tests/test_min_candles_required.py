"""Tests for `_get_min_candles_required` (live_bot_manager) — Plan 8 Step 8.3 (ENG-8).

Previously scanned every PARAMS entry for the largest numeric value regardless
of what it represented (a threshold, a multiplier, or an actual candle-lookback
window all pooled into one max() call), then applied a hardcoded x3 buffer that
contradicted its own docstring's "2x". Fixed to read the strategy's own
declared `MIN_WARMUP_CANDLES` — the same value `services/backtest_runner.py`
already uses to size the backtest's warmup period — giving live/backtest
parity instead of a second, independently-wrong computation.
"""
from core.live_bot_manager import _get_min_candles_required
from core.market_data_feed import MAX_CANDLES_RETAINED


class _FakeStrategy:
    def __init__(self, min_warmup_candles=None, params=None):
        if min_warmup_candles is not None:
            self.MIN_WARMUP_CANDLES = min_warmup_candles
        self.PARAMS = params or {}


def test_uses_the_strategy_declared_min_warmup_candles():
    strategy = _FakeStrategy(min_warmup_candles=210)
    assert _get_min_candles_required(strategy) == 210


def test_floors_at_50_even_if_the_strategy_declares_less():
    # MicroScalper declares MIN_WARMUP_CANDLES = 25 — the live gate still
    # enforces the same >= 50 floor services/backtest_runner.py applies.
    strategy = _FakeStrategy(min_warmup_candles=25)
    assert _get_min_candles_required(strategy) == 50


def test_falls_back_to_50_when_the_attribute_is_missing():
    strategy = _FakeStrategy()
    assert _get_min_candles_required(strategy) == 50


def test_ignores_unrelated_large_numeric_params_entirely():
    # Regression: MicroMacroRSIDivergence's max_pivot_bars=500 (a bar-distance
    # sanity cap, not a lookback window) previously dominated the old
    # largest-numeric-param scan and produced an unreachable 1500 requirement.
    # The fixed function must not look at PARAMS at all.
    strategy = _FakeStrategy(
        min_warmup_candles=30,
        params={"max_pivot_bars": {"type": "int", "default": 500, "min": 5, "max": 500}},
    )
    # 30 floors to 50 (same floor as backtest_runner.py) — the point is that
    # the result is nowhere near 500 (the unrelated param) or 1500 (the old
    # x3-buffered scan), not that it equals the raw declared value.
    assert _get_min_candles_required(strategy) == 50


def test_seeded_strategy_values_all_stay_under_the_retained_candle_cap():
    # The concrete failure this step fixes: AdaptiveTrend's declared 210 and
    # every other seeded strategy's declared MIN_WARMUP_CANDLES must be
    # reachable given MarketDataFeed's retention cap.
    for min_warmup in (25, 30, 50, 60, 210):
        strategy = _FakeStrategy(min_warmup_candles=min_warmup)
        assert _get_min_candles_required(strategy) <= MAX_CANDLES_RETAINED


def test_a_strategy_declaring_more_than_the_retention_cap_is_still_computed_correctly():
    # The function itself doesn't clamp to the cap — that's a session-start
    # visibility check in live_bot_manager.py's warmup block, not this
    # function's job. It must still return the true (possibly unreachable)
    # requirement so that check can detect the mismatch.
    strategy = _FakeStrategy(min_warmup_candles=600)
    assert _get_min_candles_required(strategy) == 600
    assert _get_min_candles_required(strategy) > MAX_CANDLES_RETAINED
