"""Tests for `check_warmup_sufficient` (backtest_runner) — Plan 9 / QNT-16.

Previously `warmup_period = max(strategy.MIN_WARMUP_CANDLES, min(50, len(rows) - 2))`
could exceed the number of candles actually loaded for a date range, making
`range(warmup_period, total_candles)` empty — the backtest "completed" with
zero trades and no warning, indistinguishable from a strategy that legitimately
found no signals. `check_warmup_sufficient` fails loud instead.
"""
import pytest

from services.backtest_runner import check_warmup_sufficient


def test_passes_when_enough_candles_exist():
    # 500 rows, warmup 200 -> range(200, 500) has 300 iterations. No raise.
    check_warmup_sufficient("BTCUSDT", warmup_period=200, num_rows=500, min_warmup_candles=200)


def test_passes_at_the_exact_boundary():
    # warmup_period == num_rows - 1 -> range still has exactly 1 iteration.
    check_warmup_sufficient("BTCUSDT", warmup_period=499, num_rows=500, min_warmup_candles=200)


def test_raises_when_warmup_equals_num_rows():
    # range(500, 500) is empty.
    with pytest.raises(RuntimeError, match="WARMUP_INSUFFICIENT"):
        check_warmup_sufficient("BTCUSDT", warmup_period=500, num_rows=500, min_warmup_candles=200)


def test_raises_when_warmup_exceeds_num_rows():
    # The concrete real-world case: AdaptiveTrend (MIN_WARMUP_CANDLES=210) run
    # over a short date range that only yields 60 candles.
    with pytest.raises(RuntimeError, match="WARMUP_INSUFFICIENT"):
        check_warmup_sufficient("BTCUSDT", warmup_period=210, num_rows=60, min_warmup_candles=210)


def test_error_message_names_the_symbol_and_both_counts():
    with pytest.raises(RuntimeError) as exc_info:
        check_warmup_sufficient("ETHUSDT", warmup_period=210, num_rows=60, min_warmup_candles=210)
    msg = str(exc_info.value)
    assert "ETHUSDT" in msg
    assert "210" in msg
    assert "60" in msg
