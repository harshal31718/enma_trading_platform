"""Plan 21 Step 21.4 (A-6, M-5) regression: `LiveAdapter.execute_entry()`'s
bracket-safety behavior.

M-5 — reject entry outright when the computed SL lands on the wrong side of
the reference price (long: sl >= ref; short: sl <= ref) instead of the old
behavior of silently dropping the SL and entering naked with no future
re-check. TP-invalid stays lower-stakes: drop TP, still enter.

A-6 — the F-018 emergency-exit path (fires when entry filled but SL
placement failed) now retries the emergency MARKET close up to 3x with
backoff, books the REAL fill price via `_extract_fill_price` ->
`_query_real_fill_price` (not the fabricated entry price), and on total
failure records NOTHING and leaves `strategy.position` untouched (still
None) rather than fabricating a close — mirrors Plan 5.2's
real-fills-not-fabricated-closes invariant for the emergency path.

Drives the real `LiveAdapter.execute_entry` directly against a stubbed
Binance signed-request layer, same harness shape as
`test_execute_flip_idempotency.py` / `test_live_fill_booking.py`.

Run inside the container::

    docker exec enma_trading_platform-engine-1 pytest /app/tests/test_execute_entry_bracket_safety.py
"""
import asyncio
from datetime import datetime, timezone

import pytest

import services.binance_testnet as binance_mod
import core.live_bot_manager as lbm_module
from core.live_bot_manager import LiveBotManager, LiveAdapter
from core.reconciler import Reconciler

SYM = "FAKEUSDT"


class _FakeExecutionModel:
    def exit_fee(self, strategy, qty, price):
        return abs(qty) * price * 0.0005


class _FakeStrategy:
    def __init__(self, stop_loss=None, take_profit=None):
        self.position = None
        self.stop_loss = stop_loss
        self.take_profit = take_profit
        self.buy = 1.0
        self.sell = None
        self.entry_tag = ""
        self.exit_tag = ""
        self.execution_model = _FakeExecutionModel()
        self.balance = 1000.0
        self.leverage = 1


def _make_session():
    return {
        "open_positions": {},
        "pnl": 0.0, "strategy_name": "X", "api_key": "k", "api_secret": "s", "user_id": "",
        "trading_state": "active",
    }


class _Notified:
    def __init__(self):
        self.calls = []

    async def __call__(self, session_id, payload):
        self.calls.append(payload)


@pytest.fixture(autouse=True)
def _stub_side_effects(monkeypatch):
    async def _noop_record_trade(*args, **kwargs):
        return None
    monkeypatch.setattr(lbm_module, "record_trade", _noop_record_trade)

    async def _noop_append_event(*args, **kwargs):
        return 1
    monkeypatch.setattr(lbm_module, "append_event", _noop_append_event)


def _run_entry(adapter, strat, **overrides):
    kwargs = dict(
        strategy=strat, symbol=SYM, direction="long", qty=1.0, ref_price=100.0,
        time_t=datetime.now(timezone.utc), index_t=0,
    )
    kwargs.update(overrides)
    return asyncio.get_event_loop().run_until_complete(adapter.execute_entry(**kwargs))


def _make_mgr_adapter(monkeypatch, notified=None):
    mgr = LiveBotManager()
    sid = "sess_entry_bracket"
    mgr.sessions[sid] = _make_session()
    monkeypatch.setattr(mgr._notifier, "notify", notified or _Notified())
    return mgr, LiveAdapter(mgr, sid)


# ── M-5: invalid SL rejects the entry outright, no order ever placed ───────

def test_long_invalid_sl_rejects_entry_and_places_no_order(monkeypatch):
    async def fake_signed(*args, **kwargs):
        raise AssertionError("no Binance call should happen — entry must be rejected pre-order")

    monkeypatch.setattr(binance_mod, "send_signed_request", fake_signed)

    mgr, adapter = _make_mgr_adapter(monkeypatch)
    # SL at 105 is ABOVE the ref price of 100 for a long — invalid (already
    # "triggered" relative to entry).
    strat = _FakeStrategy(stop_loss=(1.0, 105.0), take_profit=(1.0, 110.0))

    ok = _run_entry(adapter, strat, direction="long", ref_price=100.0)

    assert ok is False
    assert strat.position is None
    assert strat.buy is None
    assert strat.sell is None
    # Local state fully cleared so next candle's exit-check can't misread it.
    assert strat.stop_loss is None
    assert strat.take_profit is None
    assert SYM not in mgr.sessions["sess_entry_bracket"]["open_positions"]


def test_short_invalid_sl_rejects_entry_and_places_no_order(monkeypatch):
    async def fake_signed(*args, **kwargs):
        raise AssertionError("no Binance call should happen — entry must be rejected pre-order")

    monkeypatch.setattr(binance_mod, "send_signed_request", fake_signed)

    mgr, adapter = _make_mgr_adapter(monkeypatch)
    # SL at 95 is BELOW the ref price of 100 for a short — invalid.
    strat = _FakeStrategy(stop_loss=(1.0, 95.0))

    ok = _run_entry(adapter, strat, direction="short", ref_price=100.0)

    assert ok is False
    assert strat.position is None
    assert strat.stop_loss is None


def test_valid_sl_invalid_tp_still_enters_with_tp_dropped(monkeypatch):
    """TP on the wrong side is lower-stakes — drop it, still place the entry
    and the (valid) SL."""
    calls = {"entry": 0, "sl": 0, "tp": 0}

    async def fake_signed(method, path, api_key, api_secret, params=None, mode="testnet"):
        if method == "POST" and path == "/fapi/v1/order":
            calls["entry"] += 1
            return {"orderId": 1, "avgPrice": "100.0", "status": "FILLED"}
        if method == "POST" and path == "/fapi/v1/algoOrder" and params.get("type") == "STOP_MARKET":
            calls["sl"] += 1
            return {"algoId": "111"}
        if method == "POST" and path == "/fapi/v1/algoOrder" and params.get("type") == "TAKE_PROFIT_MARKET":
            calls["tp"] += 1
            raise AssertionError("TP must be dropped before ever reaching Binance")
        raise AssertionError(f"unexpected call {method} {path} {params}")

    monkeypatch.setattr(binance_mod, "send_signed_request", fake_signed)

    mgr, adapter = _make_mgr_adapter(monkeypatch)
    # SL valid (below ref for a long); TP at 90 is BELOW ref for a long — invalid.
    strat = _FakeStrategy(stop_loss=(1.0, 95.0), take_profit=(1.0, 90.0))

    ok = _run_entry(adapter, strat, direction="long", ref_price=100.0)

    assert ok is True
    assert calls["entry"] == 1
    assert calls["sl"] == 1
    assert calls["tp"] == 0
    assert strat.take_profit is None
    assert strat.position is not None


# ── A-6: emergency-exit retry ladder + real-fill booking ───────────────────

def test_sl_failure_emergency_close_succeeds_first_try_books_real_price(monkeypatch):
    calls = {"entry": 0, "sl": 0, "close": 0}

    async def fake_signed(method, path, api_key, api_secret, params=None, mode="testnet"):
        if method == "POST" and path == "/fapi/v1/order" and params.get("reduceOnly") != "true":
            calls["entry"] += 1
            return {"orderId": 1, "avgPrice": "100.0", "status": "FILLED"}
        if method == "POST" and path == "/fapi/v1/algoOrder":
            calls["sl"] += 1
            raise RuntimeError("simulated SL placement rejection")
        if method == "POST" and path == "/fapi/v1/order" and params.get("reduceOnly") == "true":
            calls["close"] += 1
            # Real fill differs from the entry price — proves the real
            # price is booked, not a fabricated == entry-price close.
            return {"orderId": 2, "avgPrice": "97.5", "status": "FILLED"}
        raise AssertionError(f"unexpected call {method} {path} {params}")

    monkeypatch.setattr(binance_mod, "send_signed_request", fake_signed)

    notified = _Notified()
    mgr, adapter = _make_mgr_adapter(monkeypatch, notified)
    strat = _FakeStrategy(stop_loss=(1.0, 95.0))

    ok = _run_entry(adapter, strat, direction="long", ref_price=100.0)

    assert ok is False
    assert calls["entry"] == 1
    assert calls["sl"] == 1
    assert calls["close"] == 1  # succeeded on the first attempt, no retry needed
    # Booked as closed — never left resident as an open position.
    assert SYM not in mgr.sessions["sess_entry_bracket"]["open_positions"]
    close_events = [c for c in notified.calls if c.get("event") == "position:close"]
    assert len(close_events) == 1
    assert close_events[0]["eventData"]["exitPrice"] == "97.5"
    assert close_events[0]["eventData"]["exitReason"] == "emergency_exit"


def test_sl_failure_emergency_close_retries_then_succeeds(monkeypatch):
    """First two close attempts raise, third succeeds — proves the retry
    ladder (up to 3 attempts) actually retries rather than giving up early."""
    calls = {"close_attempts": 0}

    async def fake_signed(method, path, api_key, api_secret, params=None, mode="testnet"):
        if method == "POST" and path == "/fapi/v1/order" and params.get("reduceOnly") != "true":
            return {"orderId": 1, "avgPrice": "100.0", "status": "FILLED"}
        if method == "POST" and path == "/fapi/v1/algoOrder":
            raise RuntimeError("simulated SL placement rejection")
        if method == "POST" and path == "/fapi/v1/order" and params.get("reduceOnly") == "true":
            calls["close_attempts"] += 1
            if calls["close_attempts"] < 3:
                raise RuntimeError(f"simulated transient close failure #{calls['close_attempts']}")
            return {"orderId": 2, "avgPrice": "96.0", "status": "FILLED"}
        raise AssertionError(f"unexpected call {method} {path} {params}")

    monkeypatch.setattr(binance_mod, "send_signed_request", fake_signed)

    async def _fast_sleep(*args, **kwargs):
        return None
    monkeypatch.setattr(lbm_module.asyncio, "sleep", _fast_sleep)

    notified = _Notified()
    mgr, adapter = _make_mgr_adapter(monkeypatch, notified)
    strat = _FakeStrategy(stop_loss=(1.0, 95.0))

    ok = _run_entry(adapter, strat, direction="long", ref_price=100.0)

    assert ok is False
    assert calls["close_attempts"] == 3
    close_events = [c for c in notified.calls if c.get("event") == "position:close"]
    assert len(close_events) == 1
    assert close_events[0]["eventData"]["exitPrice"] == "96.0"


def test_sl_failure_emergency_close_total_failure_records_nothing(monkeypatch):
    """All 3 emergency-close attempts fail -> no trade recorded, no position
    fabricated as closed, strategy.position left untouched (still None —
    reconcile owns restoring it), and a loud CRITICAL notification fires."""
    calls = {"close_attempts": 0}
    record_calls = {"n": 0}

    async def fake_signed(method, path, api_key, api_secret, params=None, mode="testnet"):
        if method == "POST" and path == "/fapi/v1/order" and params.get("reduceOnly") != "true":
            return {"orderId": 1, "avgPrice": "100.0", "status": "FILLED"}
        if method == "POST" and path == "/fapi/v1/algoOrder":
            raise RuntimeError("simulated SL placement rejection")
        if method == "POST" and path == "/fapi/v1/order" and params.get("reduceOnly") == "true":
            calls["close_attempts"] += 1
            raise RuntimeError(f"simulated persistent close failure #{calls['close_attempts']}")
        raise AssertionError(f"unexpected call {method} {path} {params}")

    monkeypatch.setattr(binance_mod, "send_signed_request", fake_signed)

    async def _fast_sleep(*args, **kwargs):
        return None
    monkeypatch.setattr(lbm_module.asyncio, "sleep", _fast_sleep)

    async def _counting_record_trade(*args, **kwargs):
        record_calls["n"] += 1
    monkeypatch.setattr(lbm_module, "record_trade", _counting_record_trade)

    notified = _Notified()
    mgr, adapter = _make_mgr_adapter(monkeypatch, notified)
    strat = _FakeStrategy(stop_loss=(1.0, 95.0))

    ok = _run_entry(adapter, strat, direction="long", ref_price=100.0)

    assert ok is False
    assert calls["close_attempts"] == 3
    # Nothing fabricated: no trade recorded, no close event emitted.
    assert record_calls["n"] == 0
    close_events = [c for c in notified.calls if c.get("event") == "position:close"]
    assert len(close_events) == 0
    # strategy.position is left exactly as it was (None) — reconcile's
    # Case 1 restores it from the real exchange state next candle.
    assert strat.position is None
    # A loud CRITICAL-level alert was sent instead of silence.
    error_logs = [
        c for c in notified.calls
        if c.get("event") == "log" and c.get("eventData", {}).get("type") == "error"
    ]
    assert any("UNPROTECTED" in c["eventData"]["message"] for c in error_logs)


def test_emergency_close_cancels_any_already_placed_algo_orders(monkeypatch):
    """A-4 integration: the defensive `_cancel_symbol_algo_orders` call must
    fire during the emergency-close path even though nothing should
    normally be resting yet (SL fails before TP is ever attempted) — cheap
    and correct regardless."""
    cancel_calls = {"n": 0}

    async def fake_signed(method, path, api_key, api_secret, params=None, mode="testnet"):
        if method == "POST" and path == "/fapi/v1/order" and params.get("reduceOnly") != "true":
            return {"orderId": 1, "avgPrice": "100.0", "status": "FILLED"}
        if method == "POST" and path == "/fapi/v1/algoOrder":
            raise RuntimeError("simulated SL placement rejection")
        if method == "POST" and path == "/fapi/v1/order" and params.get("reduceOnly") == "true":
            return {"orderId": 2, "avgPrice": "97.5", "status": "FILLED"}
        if method == "GET" and path == "/fapi/v1/openAlgoOrders":
            return []
        raise AssertionError(f"unexpected call {method} {path} {params}")

    monkeypatch.setattr(binance_mod, "send_signed_request", fake_signed)

    mgr, adapter = _make_mgr_adapter(monkeypatch)

    async def _counting_cancel(self, session, symbol, algo_ids=None):
        cancel_calls["n"] += 1
    monkeypatch.setattr(Reconciler, "cancel_symbol_algo_orders", _counting_cancel)

    strat = _FakeStrategy(stop_loss=(1.0, 95.0))
    ok = _run_entry(adapter, strat, direction="long", ref_price=100.0)

    assert ok is False
    assert cancel_calls["n"] == 1
