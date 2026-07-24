"""`enforce_min_trigger_distance` (utils/symbols.py) — the real fix for the
`-2021 Order would immediately trigger` entry -> reject -> emergency-close ->
re-entry loop found via live Testnet re-verification 2026-07-24 (session ran
sl_atr_mult=0.1 at 25-50x leverage; ATR stops landed within Binance's
CONDITIONAL-order rejection margin on nearly every entry).

Live-only concern (backtest never submits a real conditional order to be
rejected) — this function has zero reach into any golden-master-covered
code path; these are plain unit tests of the pure function plus the two
live call sites (execute_entry's SL/TP finalization, maybe_amend_exchange_sl's
tighten-and-amend).
"""
from utils.symbols import enforce_min_trigger_distance, MIN_TRIGGER_DISTANCE_PCT


def test_leaves_a_comfortably_clear_long_sl_untouched():
    # SL well below ref (2% away) — no widening needed.
    price = enforce_min_trigger_distance(98.0, 100.0, is_below=True)
    assert price == 98.0


def test_widens_a_too_tight_long_sl_further_below():
    # SL only 0.05% below ref (100 * 0.0005 = 0.05) — inside the 0.15% floor.
    price = enforce_min_trigger_distance(99.95, 100.0, is_below=True)
    expected = 100.0 - 100.0 * MIN_TRIGGER_DISTANCE_PCT
    assert abs(price - expected) < 1e-9
    assert price < 99.95  # pushed further away, not just left alone


def test_widens_a_too_tight_short_sl_further_above():
    price = enforce_min_trigger_distance(100.05, 100.0, is_below=False)
    expected = 100.0 + 100.0 * MIN_TRIGGER_DISTANCE_PCT
    assert abs(price - expected) < 1e-9
    assert price > 100.05


def test_widens_a_too_tight_long_tp_further_above():
    # A long's TP sits above ref — same "is_below=False" branch as a short's SL.
    price = enforce_min_trigger_distance(100.02, 100.0, is_below=False)
    assert price > 100.02


def test_degenerate_equal_price_is_left_for_the_wrong_side_check_to_reject():
    # price == ref_price is genuinely ambiguous — this function does not
    # fabricate a "corrected" value; it passes the price through unchanged
    # so the caller's own wrong-side/invalid-bracket check (M-5) rejects it.
    assert enforce_min_trigger_distance(100.0, 100.0, is_below=True) == 100.0
    assert enforce_min_trigger_distance(100.0, 100.0, is_below=False) == 100.0


def test_a_genuinely_wrong_side_price_is_never_corrected_onto_the_right_side():
    # A long's SL of 105 with ref=100 is invalid (above entry, M-5's exact
    # scenario) — this function must leave it alone, not silently move it
    # to a valid-looking 99.85. Masking a wrong-side bracket would defeat
    # M-5's whole purpose (reject invalid brackets loudly, never enter naked).
    assert enforce_min_trigger_distance(105.0, 100.0, is_below=True) == 105.0
    # Mirror case: a short's SL of 95 with ref=100 is invalid (below entry).
    assert enforce_min_trigger_distance(95.0, 100.0, is_below=False) == 95.0


def test_zero_or_negative_ref_price_is_a_safe_noop():
    assert enforce_min_trigger_distance(98.0, 0.0, is_below=True) == 98.0
    assert enforce_min_trigger_distance(98.0, -5.0, is_below=True) == 98.0


def test_zero_or_negative_price_is_a_safe_noop():
    assert enforce_min_trigger_distance(0.0, 100.0, is_below=True) == 0.0
    assert enforce_min_trigger_distance(-1.0, 100.0, is_below=True) == -1.0


def test_custom_min_distance_pct_is_respected():
    price = enforce_min_trigger_distance(99.9, 100.0, is_below=True, min_distance_pct=0.005)
    expected = 100.0 - 100.0 * 0.005
    assert abs(price - expected) < 1e-9
