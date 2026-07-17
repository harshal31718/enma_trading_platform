"""Plan 21 Step 21.1 (A-2) regression: `_extract_fill_client_id()` — the
helper `_on_fill` (the user-data-stream fill callback registered per symbol
in `_run_symbol_loop`) uses to read a client/algo id off an
`ORDER_TRADE_UPDATE` `o` payload.

Before the fix, `_on_fill` read `order_data.get("clientOrderId", "") or
order_data.get("i", "")`. Binance's real payload has no `"clientOrderId"`
key (the field is `"c"`), so that lookup was always `""`, falling back to
`"i"` — Binance's numeric `orderId`, an **int** in the JSON. The subsequent
`client_algo_id.startswith("tpsl_")` then raised `AttributeError` on every
genuinely-delivered FILLED/PARTIALLY_FILLED frame. That exception was caught
by the outer per-callback try/except and logged as `callback error`, and
critically the `_reconcile_exchange_state()` call at the end of `_on_fill`
never ran — the event-driven fill path (F-020) was dead code even when
Binance emitted the event, reproducing F7's observed ~50-55s fill-detection
lag.

`_run_symbol_loop` itself is a large, deeply embedded method with heavy
external dependencies (Binance leverage-bracket calls, TimescaleDB warmup
candle fetches, Node internal-route calls) — per this repo's own testing
convention (see `test_symbol_state_lock.py`), we test the extracted,
independently-callable unit directly rather than driving the whole method.

Run inside the container::

    docker exec enma_trading_platform-engine-1 pytest /app/tests/test_on_fill_client_id_extraction.py
"""
from core.live_bot_manager import _extract_fill_client_id


def test_uses_c_key_when_present():
    """Binance's real field name — the common case."""
    order_data = {"c": "tpsl_abc123_sl", "i": 987654321}
    assert _extract_fill_client_id(order_data) == "tpsl_abc123_sl"


def test_falls_back_to_orderid_when_c_is_missing():
    """No "c" key at all — degrade to the numeric orderId, as a string."""
    order_data = {"i": 987654321}
    result = _extract_fill_client_id(order_data)
    assert result == "987654321"
    assert isinstance(result, str)


def test_never_raises_on_int_orderid_startswith_check():
    """The exact regression: the pre-fix code crashed here with
    AttributeError: 'int' object has no attribute 'startswith'."""
    order_data = {"i": 42}  # no "c" key — the real-world crashing shape
    client_algo_id = _extract_fill_client_id(order_data)
    # Must not raise, and must correctly report "not a tracked tpsl_ order".
    assert client_algo_id.startswith("tpsl_") is False


def test_missing_clientorderid_key_never_used_as_empty_string_fallback():
    """Old code checked the WRONG key ("clientOrderId") which never exists
    on the real payload, silently always taking the empty-string branch and
    masking a present "c" value from ever being seen in that first lookup.
    Confirms the fix reads "c" directly, not the non-existent legacy key."""
    order_data = {"clientOrderId": "should_be_ignored", "c": "tpsl_real_id", "i": 1}
    assert _extract_fill_client_id(order_data) == "tpsl_real_id"


def test_empty_payload_returns_empty_string_not_crash():
    assert _extract_fill_client_id({}) == ""
