"""Plan 5 Step 5.6 (ENG-7) — restart recovery.

Currently-open positions already self-heal for free via
`_reconcile_exchange_state`'s existing Case 1 (exchange is truth for what's
open right now) the first time each symbol's candle loop runs after a
restart — no new code needed there, verified by the existing reconcile tests.

What was missing: realized PnL from trades that already closed *before* the
restart isn't on the exchange position endpoint at all, so `start_session`
always re-seeded `session["pnl"]` at 0.0 even for a session that had already
banked real gains/losses. `_seed_pnl_from_event_log` (`core/live_bot_manager.py`)
closes that gap by replaying this session's own execution event log — these
tests exercise it directly (hermetic, stubbed `fetch_events`) rather than the
full `start_session` (which does real network/UDS/strategy-import work).

Run inside the container::

    docker exec enma_trading_platform-engine-1 pytest /app/tests/test_session_resume.py
"""
import asyncio

import pytest

import services.event_log as event_log_module
from services.event_log import fetch_events
import core.live_bot_manager as live_bot_manager_module
from core.live_bot_manager import _seed_pnl_from_event_log


SID = "sess_resume"


def _ev(seq, event_type, **payload):
    return {"seq": seq, "eventType": event_type, "payload": payload}


# ── fetch_events: hermetic Mongo cursor stub ────────────────────────────────

class _FakeCursor:
    def __init__(self, docs):
        self._docs = docs

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for doc in self._docs:
            yield doc


class _FakeCollection:
    def __init__(self, docs_by_session_symbol):
        self._docs = docs_by_session_symbol  # (session_id, symbol) -> [docs]

    def find(self, query):
        session_id = query["sessionId"]
        symbol = query.get("symbol")
        if symbol is not None:
            docs = self._docs.get((session_id, symbol), [])
        else:
            docs = [d for (sid, _sym), ds in self._docs.items() if sid == session_id for d in ds]
        return _FakeSortableCursor(docs)


class _FakeSortableCursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, field, direction):
        return _FakeCursor(sorted(self._docs, key=lambda d: d[field]))


class _FakeDb:
    def __init__(self, docs_by_session_symbol):
        self.executionEvents = _FakeCollection(docs_by_session_symbol)


def _stub_db(monkeypatch, docs_by_session_symbol):
    fake_db = _FakeDb(docs_by_session_symbol)
    monkeypatch.setattr(event_log_module, "get_database", lambda: fake_db)
    return fake_db


def test_fetch_events_returns_docs_sorted_by_seq(monkeypatch):
    docs = {
        (SID, "BTCUSDT"): [
            {"seq": 2, "eventType": "fill", "payload": {"side": "exit"}},
            {"seq": 1, "eventType": "fill", "payload": {"side": "entry"}},
        ],
    }
    _stub_db(monkeypatch, docs)

    result = asyncio.get_event_loop().run_until_complete(fetch_events(SID, "BTCUSDT"))
    assert [d["seq"] for d in result] == [1, 2]


def test_fetch_events_scoped_to_session_and_symbol(monkeypatch):
    docs = {
        (SID, "BTCUSDT"): [{"seq": 1, "eventType": "fill", "payload": {}}],
        (SID, "ETHUSDT"): [{"seq": 1, "eventType": "fill", "payload": {}}],
        ("other_session", "BTCUSDT"): [{"seq": 1, "eventType": "fill", "payload": {}}],
    }
    _stub_db(monkeypatch, docs)

    result = asyncio.get_event_loop().run_until_complete(fetch_events(SID, "BTCUSDT"))
    assert len(result) == 1


# ── _seed_pnl_from_event_log: the resume acceptance check ───────────────────

def test_seed_pnl_sums_realized_pnl_across_symbols(monkeypatch):
    docs = {
        (SID, "BTCUSDT"): [
            _ev(1, "fill", side="entry", qty=1.0, price=100.0),
            _ev(2, "fill", side="exit", qty=1.0, price=110.0, realizedPnl=9.5),
        ],
        (SID, "ETHUSDT"): [
            _ev(1, "fill", side="entry", qty=1.0, price=50.0),
            _ev(2, "fill", side="exit", qty=1.0, price=45.0, realizedPnl=-5.0),
        ],
    }
    _stub_db(monkeypatch, docs)

    total = asyncio.get_event_loop().run_until_complete(
        _seed_pnl_from_event_log(SID, ["BTCUSDT", "ETHUSDT"])
    )
    assert total == pytest.approx(4.5)


def test_seed_pnl_ignores_still_open_positions():
    """An open position contributes no realized PnL to the seed — that's the
    exchange reconcile's job (Case 1), not the event log's."""
    async def _fake_fetch(session_id, symbol):
        return [_ev(1, "fill", side="entry", qty=1.0, price=100.0)]

    real_fetch = live_bot_manager_module.fetch_events
    live_bot_manager_module.fetch_events = _fake_fetch
    try:
        total = asyncio.get_event_loop().run_until_complete(
            _seed_pnl_from_event_log(SID, ["BTCUSDT"])
        )
    finally:
        live_bot_manager_module.fetch_events = real_fetch
    assert total == pytest.approx(0.0)


def test_seed_pnl_one_symbol_failure_does_not_abort_the_others():
    async def _fake_fetch(session_id, symbol):
        if symbol == "BTCUSDT":
            raise RuntimeError("simulated Mongo read failure")
        return [_ev(1, "fill", side="entry", qty=1.0, price=100.0),
                _ev(2, "fill", side="exit", qty=1.0, price=103.0, realizedPnl=2.7)]

    real_fetch = live_bot_manager_module.fetch_events
    live_bot_manager_module.fetch_events = _fake_fetch
    try:
        total = asyncio.get_event_loop().run_until_complete(
            _seed_pnl_from_event_log(SID, ["BTCUSDT", "ETHUSDT"])
        )
    finally:
        live_bot_manager_module.fetch_events = real_fetch
    assert total == pytest.approx(2.7)


def test_seed_pnl_no_events_returns_zero(monkeypatch):
    _stub_db(monkeypatch, {})
    total = asyncio.get_event_loop().run_until_complete(
        _seed_pnl_from_event_log(SID, ["BTCUSDT"])
    )
    assert total == pytest.approx(0.0)
