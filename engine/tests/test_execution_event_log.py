"""Plan 5 Step 5.1 (SYS-2/SRV-3) regression + acceptance check.

`services/event_log.append_event` is a best-effort Mongo writer (mirrors
`trade_recorder.record_trade`'s convention exactly) — these tests stub the
database to verify seq assignment and write-failure handling without a live
Mongo. `fold_events` is a pure function tested directly against hand-built
event sequences: the plan's own acceptance check is "replaying the event log
for a session reproduces its final PnL and open positions exactly."

Run inside the container::

    docker exec enma_trading_platform-engine-1 pytest /app/tests/test_execution_event_log.py
"""
import asyncio

import pytest

import services.event_log as event_log_module
from services.event_log import append_event, fold_events, reset_session_seq, _seq_counters


SID = "sess_evlog"
SYM = "FAKEUSDT"


@pytest.fixture(autouse=True)
def _clear_seq_counters():
    _seq_counters.clear()
    yield
    _seq_counters.clear()


class _FakeCollection:
    def __init__(self, fail=False):
        self.inserted = []
        self.fail = fail

    async def insert_one(self, doc):
        if self.fail:
            raise RuntimeError("simulated Mongo write failure")
        self.inserted.append(doc)


class _FakeDb:
    def __init__(self, fail=False):
        self.executionEvents = _FakeCollection(fail=fail)


def _stub_db(monkeypatch, fail=False):
    fake_db = _FakeDb(fail=fail)
    monkeypatch.setattr(event_log_module, "get_database", lambda: fake_db)
    return fake_db


# ── append_event: seq assignment + best-effort write ────────────────────────

def test_seq_is_monotonic_per_session_symbol(monkeypatch):
    _stub_db(monkeypatch)

    async def run():
        s1 = await append_event(session_id=SID, symbol=SYM, event_type="fill", payload={"side": "entry"})
        s2 = await append_event(session_id=SID, symbol=SYM, event_type="fill", payload={"side": "exit"})
        return s1, s2

    s1, s2 = asyncio.get_event_loop().run_until_complete(run())
    assert s1 == 1
    assert s2 == 2


def test_seq_is_independent_per_symbol(monkeypatch):
    _stub_db(monkeypatch)

    async def run():
        a1 = await append_event(session_id=SID, symbol="BTCUSDT", event_type="fill", payload={"side": "entry"})
        b1 = await append_event(session_id=SID, symbol="ETHUSDT", event_type="fill", payload={"side": "entry"})
        a2 = await append_event(session_id=SID, symbol="BTCUSDT", event_type="fill", payload={"side": "exit"})
        return a1, b1, a2

    a1, b1, a2 = asyncio.get_event_loop().run_until_complete(run())
    assert a1 == 1
    assert b1 == 1  # independent counter, not sharing BTCUSDT's sequence
    assert a2 == 2


def test_write_failure_is_swallowed_and_returns_none(monkeypatch):
    """Mirrors trade_recorder.record_trade's contract: a Mongo outage must
    never raise into the live-trading call path."""
    _stub_db(monkeypatch, fail=True)

    async def run():
        return await append_event(session_id=SID, symbol=SYM, event_type="fill", payload={"side": "entry"})

    result = asyncio.get_event_loop().run_until_complete(run())
    assert result is None


def test_appended_event_carries_the_assigned_seq_and_client_order_id(monkeypatch):
    fake_db = _stub_db(monkeypatch)

    async def run():
        return await append_event(
            session_id=SID, symbol=SYM, event_type="fill",
            payload={"side": "entry", "qty": 1.0, "price": 100.0},
            client_order_id="enma_abc123",
        )

    seq = asyncio.get_event_loop().run_until_complete(run())
    assert len(fake_db.executionEvents.inserted) == 1
    doc = fake_db.executionEvents.inserted[0]
    assert doc["seq"] == seq
    assert doc["sessionId"] == SID
    assert doc["symbol"] == SYM
    assert doc["clientOrderId"] == "enma_abc123"


def test_reset_session_seq_only_clears_that_session():
    _seq_counters[(SID, SYM)] = 5
    _seq_counters[("other_session", SYM)] = 7
    reset_session_seq(SID)
    assert (SID, SYM) not in _seq_counters
    assert _seq_counters[("other_session", SYM)] == 7


# ── fold_events: the plan's stated acceptance check ─────────────────────────

def _ev(seq, event_type, **payload):
    return {"seq": seq, "eventType": event_type, "payload": payload}


def test_fold_simple_entry_then_exit_reproduces_final_pnl():
    events = [
        _ev(1, "fill", side="entry", direction="long", qty=1.0, price=100.0),
        _ev(2, "fill", side="exit", qty=1.0, price=110.0, realizedPnl=9.5),
    ]
    state = fold_events(events)
    assert state["isOpen"] is False
    assert state["realizedPnl"] == pytest.approx(9.5)


def test_fold_multiple_round_trips_accumulates_realized_pnl():
    events = [
        _ev(1, "fill", side="entry", qty=1.0, price=100.0),
        _ev(2, "fill", side="exit", qty=1.0, price=110.0, realizedPnl=9.5),
        _ev(3, "fill", side="entry", qty=2.0, price=50.0),
        _ev(4, "fill", side="exit", qty=2.0, price=45.0, realizedPnl=-10.2),
    ]
    state = fold_events(events)
    assert state["isOpen"] is False
    assert state["realizedPnl"] == pytest.approx(9.5 - 10.2)


def test_fold_dca_add_weights_the_average_entry_price():
    events = [
        _ev(1, "fill", side="entry", qty=1.0, price=100.0),
        _ev(2, "fill", side="add", qty=1.0, price=120.0),
    ]
    state = fold_events(events)
    assert state["isOpen"] is True
    assert state["qty"] == pytest.approx(2.0)
    assert state["entryPrice"] == pytest.approx(110.0)  # (1*100 + 1*120) / 2


def test_fold_open_position_reports_still_open():
    events = [_ev(1, "fill", side="entry", qty=1.0, price=100.0)]
    state = fold_events(events)
    assert state["isOpen"] is True
    assert state["qty"] == pytest.approx(1.0)


def test_fold_close_failed_event_is_a_no_op():
    """A close_failed event must not flip the position flat — it documents
    a failed attempt, not a real state change (Step 5.2's whole point)."""
    events = [
        _ev(1, "fill", side="entry", qty=1.0, price=100.0),
        _ev(2, "close_failed", reason="stop_loss", error="simulated"),
    ]
    state = fold_events(events)
    assert state["isOpen"] is True


def test_fold_reconcile_adjustment_now_flat():
    events = [
        _ev(1, "fill", side="entry", qty=1.0, price=100.0),
        _ev(2, "reconcile_adjustment", nowFlat=True, realizedPnl=3.3, price=103.0),
    ]
    state = fold_events(events)
    assert state["isOpen"] is False
    assert state["realizedPnl"] == pytest.approx(3.3)


def test_fold_reconcile_adjustment_now_open():
    events = [_ev(1, "reconcile_adjustment", nowOpen=True, qty=2.0, price=200.0)]
    state = fold_events(events)
    assert state["isOpen"] is True
    assert state["qty"] == pytest.approx(2.0)
    assert state["entryPrice"] == pytest.approx(200.0)


def test_fold_is_order_dependent_on_seq_not_insertion_order():
    """Sanity check documenting the contract: fold_events trusts the caller
    to have pre-sorted by seq (it does not re-sort). Feeding it in seq order
    (as MongoDB `.sort("seq", 1)` guarantees) is what makes this meaningful."""
    in_seq_order = [
        _ev(1, "fill", side="entry", qty=1.0, price=100.0),
        _ev(2, "fill", side="exit", qty=1.0, price=90.0, realizedPnl=-10.0),
    ]
    assert fold_events(in_seq_order)["isOpen"] is False
    assert fold_events(in_seq_order)["realizedPnl"] == pytest.approx(-10.0)
