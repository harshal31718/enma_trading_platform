"""Tests for Phase 2 fill realism (F-011 / F-012).

Pure-function tests — no DB / engine / live dependencies.  Run inside the
container with::

    docker exec enma_trading_platform-engine-1 pytest /app/tests/test_phase2_fills.py
"""
import pytest
from services.fill_model import (
    gap_through_stop_price,
    bounded_exit_price,
    bounded_entry_price,
)


# ── F-011 gap-through ────────────────────────────────────────────────────────

class TestGapThroughLong:
    def test_no_gap_when_candle_traded_at_or_below_stop(self):
        # candle opened above the stop, traded down to it — not a gap
        out = gap_through_stop_price(
            is_long=True, stop_price=100.0,
            candle_open=105.0, candle_low=99.0, candle_high=110.0,
        )
        assert out is None

    def test_gap_when_candle_opened_below_stop(self):
        # candle gapped DOWN through the stop (open < stop)
        out = gap_through_stop_price(
            is_long=True, stop_price=100.0,
            candle_open=95.0, candle_low=90.0, candle_high=98.0,
        )
        assert out == 95.0   # fill at the candle open

    def test_no_gap_when_candle_opened_above_stop(self):
        # normal scenario: open above stop, stop is in range
        out = gap_through_stop_price(
            is_long=True, stop_price=100.0,
            candle_open=110.0, candle_low=101.0, candle_high=115.0,
        )
        assert out is None


class TestGapThroughShort:
    def test_no_gap_when_candle_traded_at_or_above_stop(self):
        out = gap_through_stop_price(
            is_long=False, stop_price=100.0,
            candle_open=95.0, candle_low=90.0, candle_high=110.0,
        )
        assert out is None

    def test_gap_when_candle_opened_above_stop(self):
        out = gap_through_stop_price(
            is_long=False, stop_price=100.0,
            candle_open=105.0, candle_low=102.0, candle_high=108.0,
        )
        assert out == 105.0

    def test_no_gap_when_candle_opened_below_stop(self):
        out = gap_through_stop_price(
            is_long=False, stop_price=100.0,
            candle_open=90.0, candle_low=85.0, candle_high=99.0,
        )
        assert out is None


# ── F-012 bounded exits ──────────────────────────────────────────────────────

class TestBoundedExitLong:
    def test_in_range_stop(self):
        # stop sits inside [open, high] — bounded = stop (no change)
        out = bounded_exit_price(
            is_long=True, proposed_price=100.0,
            candle_open=95.0, candle_low=92.0, candle_high=110.0,
        )
        assert out == 100.0

    def test_stop_above_high_clamps_to_high(self):
        # stop above candle high (gap-up scenario post-F-011) — bounded = high
        out = bounded_exit_price(
            is_long=True, proposed_price=120.0,
            candle_open=95.0, candle_low=92.0, candle_high=110.0,
        )
        assert out == 110.0

    def test_stop_below_open_returns_stop(self):
        # stop below open but inside [low, high] — the stop traded, so the
        # fill is the stop itself (NOT nudged up to the open; that was the bug).
        out = bounded_exit_price(
            is_long=True, proposed_price=90.0,
            candle_open=95.0, candle_low=88.0, candle_high=100.0,
        )
        assert out == 90.0


class TestBoundedExitShort:
    def test_in_range_stop(self):
        out = bounded_exit_price(
            is_long=False, proposed_price=100.0,
            candle_open=105.0, candle_low=90.0, candle_high=110.0,
        )
        assert out == 100.0

    def test_stop_below_low_clamps_to_low(self):
        out = bounded_exit_price(
            is_long=False, proposed_price=85.0,
            candle_open=105.0, candle_low=90.0, candle_high=110.0,
        )
        assert out == 90.0

    def test_stop_above_open_returns_stop(self):
        # short stop above open but inside [low, high] — the stop traded, so
        # the fill is the stop itself (NOT capped down to the open; that bug
        # made every short stop-loss fill better than its stop).
        out = bounded_exit_price(
            is_long=False, proposed_price=120.0,
            candle_open=105.0, candle_low=100.0, candle_high=125.0,
        )
        assert out == 120.0


# ── F-012 bounded entry (sanity, not used by runner yet) ─────────────────────

class TestBoundedEntry:
    def test_long_entry_pays_slippage_up(self):
        out = bounded_entry_price(
            is_long=True, candle_open=100.0,
            candle_low=98.0, candle_high=105.0, slippage_pct=0.0005,
        )
        # long pays more — adverse
        assert out > 100.0
        assert abs(out - 100.05) < 1e-9

    def test_short_entry_receives_less_slippage(self):
        out = bounded_entry_price(
            is_long=False, candle_open=100.0,
            candle_low=98.0, candle_high=105.0, slippage_pct=0.0005,
        )
        # short receives less — adverse
        assert out < 100.0
        assert abs(out - 99.95) < 1e-9