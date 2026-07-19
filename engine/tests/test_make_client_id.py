"""Regression tests for `_make_client_id` (live_bot_manager).

Found via live testnet chaos 2026-07-19: the old
`f"enma_{session_id[:8]}_{symbol}_{uuid4_hex8()}_emrg"` was 37 chars for a
9-char symbol (e.g. KAITOUSDC), so the F-018 emergency close failed with
`-4015 Client order id length should be less than 36 chars` on every symbol
>= 8 chars. The helper must guarantee every id stays < 36 chars.
"""
from core.live_bot_manager import _make_client_id

SESSION = "6a5c8388ffea64dfa3f78d26"  # a realistic 24-char session id


def test_length_under_36_for_the_regression_case():
    # KAITOUSDC + the _emrg suffix was the exact 37-char failure.
    cid = _make_client_id(SESSION, "KAITOUSDC", "_emrg")
    assert len(cid) < 36, f"{cid!r} is {len(cid)} chars"
    assert cid.endswith("_emrg")


def test_length_under_36_across_symbol_lengths_and_suffixes():
    symbols = ["BTC", "ETHUSDT", "KAITOUSDC", "1000XECUSDT", "AVAAIUSDT",
               "SUPERLONGSYMBOLUSDT", "X" * 40]
    for sym in symbols:
        for suffix in ("", "_emrg"):
            cid = _make_client_id(SESSION, sym, suffix)
            assert len(cid) < 36, f"{cid!r} ({sym}, {suffix!r}) is {len(cid)} chars"


def test_prefix_preserved_for_our_own_order_detection():
    # Nothing parses the symbol back out, but the enma_ prefix identifies our
    # orders — it must survive even when the symbol segment is dropped entirely.
    assert _make_client_id(SESSION, "BTCUSDT").startswith("enma_")
    assert _make_client_id(SESSION, "X" * 40, "_emrg").startswith("enma_")


def test_ids_are_unique():
    ids = {_make_client_id(SESSION, "ETHUSDT") for _ in range(200)}
    assert len(ids) == 200  # uuid8 guarantees uniqueness


def test_short_symbol_kept_intact():
    cid = _make_client_id(SESSION, "BTC")
    assert "_BTC_" in cid  # room is ample; the full symbol is preserved


def test_empty_symbol_still_valid():
    cid = _make_client_id(SESSION, "")
    assert cid.startswith("enma_")
    assert len(cid) < 36
