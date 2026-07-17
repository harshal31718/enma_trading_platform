"""Plan 21 Step 21.2 (A-8) regression: `_account_update_needs_reconcile()` —
the decision helper `_on_account_update` (registered per symbol in
`_run_symbol_loop`, alongside `_on_fill`) uses to decide whether an
ACCOUNT_UPDATE position delta warrants an immediate reconcile.

Binance emits ACCOUNT_UPDATE with a `P[]` position delta for EVERY position
change — plain orders, conditional/algo (`/fapi/v1/algoOrder`) TP-SL fills,
liquidations, manual closes — regardless of whether `ORDER_TRADE_UPDATE`
fires for algo orders the way `_on_fill`'s `tpsl_` client-id match depends
on. This is the event-type-agnostic fallback (finding A-8) that closes the
~60s staleness window documented in F7 and `CURRENT_STATE.md`, without
depending on Binance's algo-order event semantics at all.

`_run_symbol_loop` itself is a large, deeply embedded method with heavy
external dependencies — per this repo's own testing convention (see
`test_symbol_state_lock.py`, `test_on_fill_client_id_extraction.py`), we
test the extracted, independently-callable decision function directly
rather than driving the whole method.

Run inside the container::

    docker exec enma_trading_platform-engine-1 pytest /app/tests/test_account_update_reconcile_decision.py
"""
from core.live_bot_manager import _account_update_needs_reconcile


def test_exchange_open_local_flat_needs_reconcile():
    """The core F7 case: Binance shows a position (e.g. an algo-order fill
    the engine hasn't caught up on yet), engine thinks it's flat."""
    pos_data = {"s": "BTCUSDT", "pa": "0.015"}
    assert _account_update_needs_reconcile(pos_data, has_local_position=False) is True


def test_exchange_flat_local_open_needs_reconcile():
    """The mirror case: Binance shows flat (a conditional SL/TP just fired
    exchange-side), engine still thinks the position is open."""
    pos_data = {"s": "BTCUSDT", "pa": "0"}
    assert _account_update_needs_reconcile(pos_data, has_local_position=True) is True


def test_both_open_agree_no_reconcile():
    """Both sides already agree the position is open — a quantity-only
    change (partial fill, DCA add) is left to the next candle-close
    reconcile, not this callback."""
    pos_data = {"s": "BTCUSDT", "pa": "0.02"}
    assert _account_update_needs_reconcile(pos_data, has_local_position=True) is False


def test_both_flat_agree_no_reconcile():
    pos_data = {"s": "BTCUSDT", "pa": "0"}
    assert _account_update_needs_reconcile(pos_data, has_local_position=False) is False


def test_negative_position_amount_counts_as_open():
    """Short positions report a negative `pa` — must count as "open", not
    be misread as falsy/zero."""
    pos_data = {"s": "BTCUSDT", "pa": "-0.5"}
    assert _account_update_needs_reconcile(pos_data, has_local_position=False) is True
    assert _account_update_needs_reconcile(pos_data, has_local_position=True) is False


def test_missing_or_malformed_pa_treated_as_flat_not_a_crash():
    """A missing/unparseable `pa` field must degrade to "flat" (0.0) via
    `_safe_float`'s default, never raise."""
    assert _account_update_needs_reconcile({"s": "BTCUSDT"}, has_local_position=True) is True
    assert _account_update_needs_reconcile({"s": "BTCUSDT"}, has_local_position=False) is False
    assert _account_update_needs_reconcile(
        {"s": "BTCUSDT", "pa": "not-a-number"}, has_local_position=True,
    ) is True
