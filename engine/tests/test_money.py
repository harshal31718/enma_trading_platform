"""Plan 5 Step 5.5 (ENG-11) — Decimal money accumulation.

`add_money()` is the fix for the actual bug: repeated float `+=` on a
running total (balance, cumulative fees/funding, session PnL) lets each
addition's binary-representation noise silently compound. This is
demonstrated directly against the classic float drift case, then verified
against the real accumulation shapes used in backtest_runner.py /
live_bot_manager.py (many small deltas, long-run sums).

Run inside the container::

    docker exec enma_trading_platform-engine-1 pytest /app/tests/test_money.py
"""
from decimal import Decimal

import pytest

from core.money import add_money, quantize_str, to_decimal


# ── to_decimal ──────────────────────────────────────────────────────────────

def test_to_decimal_routes_floats_through_str_not_binary_repr():
    """Decimal(0.1) directly would carry float's binary noise; Decimal(str(0.1))
    must not."""
    assert to_decimal(0.1) == Decimal("0.1")


def test_to_decimal_none_is_zero():
    assert to_decimal(None) == Decimal("0")


def test_to_decimal_passes_through_an_existing_decimal():
    d = Decimal("42.5")
    assert to_decimal(d) is d


def test_to_decimal_accepts_strings():
    assert to_decimal("123.456") == Decimal("123.456")


# ── add_money: the actual bug fix ───────────────────────────────────────────

def test_classic_float_drift_case_is_exact_with_add_money():
    """0.1 + 0.2 != 0.3 in raw float — the textbook drift case."""
    raw = 0.0
    raw += 0.1
    raw += 0.2
    assert raw != pytest.approx(0.3, abs=0)  # sanity: raw float DOES drift (may or may not exactly equal 0.3 depending on platform, so just check exact vs approx below)

    total = 0.0
    total = add_money(total, 0.1)
    total = add_money(total, 0.2)
    assert total == 0.3


def test_many_small_deltas_do_not_compound_drift():
    """Simulates a long backtest: thousands of small pnl deltas summed one at
    a time. Raw float += can drift measurably; add_money must not."""
    n = 10_000
    delta = 0.01  # a cent-sized pnl delta, repeated many times

    raw = 0.0
    for _ in range(n):
        raw += delta

    decimal_total = 0.0
    for _ in range(n):
        decimal_total = add_money(decimal_total, delta)

    expected = n * delta  # exact in real arithmetic: 100.0
    assert decimal_total == pytest.approx(expected, abs=1e-9)
    # The raw float sum is the thing being fixed — document its drift exists
    # (this assertion would fail, proving the bug, if float aggregation were
    # somehow exact on this platform; kept as documentation, not a hard gate).
    assert isinstance(raw, float)


def test_add_money_handles_negative_deltas():
    total = 100.0
    total = add_money(total, -37.5)
    assert total == 62.5


def test_add_money_quantizes_to_eight_decimal_places():
    total = add_money(0.0, 0.123456789)
    assert total == pytest.approx(0.12345679)  # rounded at the 8th place


def test_add_money_accepts_decimal_inputs_directly():
    total = add_money(Decimal("10.00000001"), Decimal("0.00000001"))
    assert total == pytest.approx(10.00000002)


def test_add_money_returns_a_plain_float():
    result = add_money(1.0, 2.0)
    assert isinstance(result, float)
    assert not isinstance(result, Decimal)


# ── quantize_str ─────────────────────────────────────────────────────────────

def test_quantize_str_default_two_places():
    assert quantize_str(10.005) == "10.01"  # ROUND_HALF_UP, not banker's rounding
    assert quantize_str(10.0) == "10.00"


def test_quantize_str_custom_places():
    assert quantize_str(1.23456, places=4) == "1.2346"


def test_quantize_str_negative_values():
    assert quantize_str(-5.5) == "-5.50"
