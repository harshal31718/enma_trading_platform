"""Plan 5 Step 5.3 (ENG-10) tail (F2, part a): independently verify that
`execute_flip` is safe under order-placement failure/ambiguity WITHOUT its
own `newClientOrderId`, because it delegates the entire order lifecycle to
`execute_exit` + `execute_entry`, which are each already idempotent on their
own terms (Plan 20 / 5.2's real-fill-booking work).

Three compositions are verified, matching the three safe outcomes a flip can
land in:
  1. The exit leg fails outright -> `execute_flip` must return False without
     ever attempting the entry leg (no double-processing, no naked entry
     placed against a position that's still open).
  2. The exit leg succeeds; the entry leg hits an ambiguous (timeout-but-
     maybe-filled) failure -> `execute_entry`'s own query-by-client-id guard
     must still resolve it, and the flip must complete successfully with the
     REAL fill price, not fabricate/re-attempt a duplicate order.
  3. The exit leg succeeds; the entry leg genuinely fails (re-query finds
     nothing) -> the flip must return False leaving the strategy flat
     (`position is None`), never stuck half-flipped, and never silently
     retrying (which would double-place the entry).

Drives the real `LiveAdapter.execute_flip` (which is unmodified — only
`execute_reduce` gained a newClientOrderId in this same pass, see
`live_bot_manager.py`) against a stubbed Binance signed-request layer, same
harness shape as `test_live_fill_booking.py`.

Run inside the container::

    docker exec enma_trading_platform-engine-1 pytest /app/tests/test_execute_flip_idempotency.py
"""
import asyncio
from datetime import datetime, timezone

import pytest

import services.binance_testnet as binance_mod
import core.live_bot_manager as lbm_module
from core.live_bot_manager import LiveBotManager, LiveAdapter
from core.position import Position

SYM = "FAKEUSDT"


class _FakeExecutionModel:
    def exit_fee(self, strategy, qty, price):
        return abs(qty) * price * 0.0005


class _FakeStrategy:
    def __init__(self, position):
        self.position = position
        self.stop_loss = None
        self.take_profit = None
        self._pending_flip = None
        self.entry_tag = ""
        self.exit_tag = ""
        self.buy = None
        self.sell = None
        self.execution_model = _FakeExecutionModel()
        self.balance = 1000.0
        self.leverage = 10

    @property
    def is_long(self):
        return self.position is not None and self.position.type == "long"

    @property
    def is_short(self):
        return self.position is not None and self.position.type == "short"


def _make_session():
    return {
        "open_positions": {SYM: {"timestamp": datetime.now(timezone.utc).isoformat()}},
        "pnl": 0.0, "strategy_name": "X", "api_key": "k", "api_secret": "s", "user_id": "",
    }


def _make_position(entry=100.0, qty=1.0, direction="long", leverage=1.0):
    return Position(direction, qty, entry, leverage=leverage, isolated_wallet=entry * qty)


class _Notified:
    def __init__(self):
        self.calls = []

    async def __call__(self, session_id, payload):
        self.calls.append(payload)


@pytest.fixture(autouse=True)
def _stub_record_trade(monkeypatch):
    async def _noop(*args, **kwargs):
        return None
    monkeypatch.setattr(lbm_module, "record_trade", _noop)


@pytest.fixture(autouse=True)
def _stub_append_event(monkeypatch):
    async def _noop(*args, **kwargs):
        return 1
    monkeypatch.setattr(lbm_module, "append_event", _noop)


def _run_flip(adapter, strat, **overrides):
    kwargs = dict(
        strategy=strat, symbol=SYM, new_direction="short", new_qty=1.0, ref_price=100.0,
        time_t=datetime.now(timezone.utc), index_t=0, high_t=101.0, low_t=99.0,
        stop_loss=None, take_profit=None,
    )
    kwargs.update(overrides)
    return asyncio.get_event_loop().run_until_complete(adapter.execute_flip(**kwargs))


# ── 1. Exit leg fails -> no entry attempt, position stays open ─────────────

def test_flip_exit_failure_never_attempts_entry(monkeypatch):
    order_calls = {"n": 0}

    async def close_always_fails(method, path, api_key, api_secret, params=None, mode="testnet"):
        order_calls["n"] += 1
        raise RuntimeError("simulated Binance 500 on close")

    monkeypatch.setattr(binance_mod, "send_signed_request", close_always_fails)

    mgr = LiveBotManager()
    sid = "sess_flip_exit_fail"
    mgr.sessions[sid] = _make_session()
    monkeypatch.setattr(mgr, "_notify_node", _Notified())

    pos = _make_position(direction="long")
    strat = _FakeStrategy(pos)
    adapter = LiveAdapter(mgr, sid)

    ok = _run_flip(adapter, strat)

    assert ok is False
    # Exactly one order call attempted (the failed close) — entry never reached.
    assert order_calls["n"] == 1
    # Position stays open, in the ORIGINAL direction — no partial flip.
    assert strat.position is not None
    assert strat.position.type == "long"
    assert strat.position.is_open


# ── 2. Exit ok; entry ambiguous-timeout-but-actually-filled -> flip succeeds ─

def test_flip_entry_ambiguous_timeout_still_completes_the_flip(monkeypatch):
    calls = {"close": 0, "entry_post": 0, "entry_get": 0}

    async def fake_signed(method, path, api_key, api_secret, params=None, mode="testnet"):
        if method == "POST" and path == "/fapi/v1/order" and params.get("reduceOnly") == "true":
            calls["close"] += 1
            return {"orderId": 1, "avgPrice": "99.0", "status": "FILLED"}
        if method == "POST" and path == "/fapi/v1/order" and params.get("reduceOnly") is None:
            calls["entry_post"] += 1
            raise RuntimeError("simulated timeout on entry")
        if method == "GET" and path == "/fapi/v1/order":
            calls["entry_get"] += 1
            assert params["origClientOrderId"]
            return {"avgPrice": "101.25", "status": "FILLED"}
        raise AssertionError(f"unexpected call {method} {path} {params}")

    monkeypatch.setattr(binance_mod, "send_signed_request", fake_signed)

    mgr = LiveBotManager()
    sid = "sess_flip_entry_timeout"
    mgr.sessions[sid] = _make_session()
    notified = _Notified()
    monkeypatch.setattr(mgr, "_notify_node", notified)

    pos = _make_position(direction="long")
    strat = _FakeStrategy(pos)
    adapter = LiveAdapter(mgr, sid)

    ok = _run_flip(adapter, strat, new_direction="short", new_qty=1.0)

    assert ok is True
    assert calls["close"] == 1
    assert calls["entry_post"] == 1  # raised exactly once, not retried in-process
    assert calls["entry_get"] == 1   # resolved via the idempotent re-query
    assert strat.position is not None
    assert strat.position.type == "short"
    # Booked at the REAL re-queried fill price, not the ref_price estimate.
    open_events = [c for c in notified.calls if c.get("event") == "position:open"]
    assert len(open_events) == 1
    assert open_events[0]["eventData"]["price"] == "101.25"


# ── 3. Exit ok; entry genuinely fails -> flip leaves strategy flat, not stuck ─

def test_flip_entry_genuine_failure_leaves_flat_not_reentered(monkeypatch):
    calls = {"close": 0, "entry_post": 0, "entry_get": 0}

    async def fake_signed(method, path, api_key, api_secret, params=None, mode="testnet"):
        if method == "POST" and path == "/fapi/v1/order" and params.get("reduceOnly") == "true":
            calls["close"] += 1
            return {"orderId": 1, "avgPrice": "99.0", "status": "FILLED"}
        if method == "POST" and path == "/fapi/v1/order" and params.get("reduceOnly") is None:
            calls["entry_post"] += 1
            raise RuntimeError("simulated genuine network failure on entry")
        if method == "GET" and path == "/fapi/v1/order":
            calls["entry_get"] += 1
            return {}  # no fill ever found — the order truly never landed
        raise AssertionError(f"unexpected call {method} {path} {params}")

    monkeypatch.setattr(binance_mod, "send_signed_request", fake_signed)

    mgr = LiveBotManager()
    sid = "sess_flip_entry_genuine_fail"
    mgr.sessions[sid] = _make_session()
    monkeypatch.setattr(mgr, "_notify_node", _Notified())

    pos = _make_position(direction="long")
    strat = _FakeStrategy(pos)
    adapter = LiveAdapter(mgr, sid)

    ok = _run_flip(adapter, strat, new_direction="short", new_qty=1.0)

    assert ok is False
    assert calls["close"] == 1
    assert calls["entry_post"] == 1  # exactly one attempt — not retried into a duplicate order
    assert calls["entry_get"] == 1
    # Ended up FLAT, not stuck half-flipped and not silently re-entered.
    assert strat.position is None
