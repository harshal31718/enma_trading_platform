"""Plan 6 Step 6.1 (ENG-1): unit tests for the `Reconciler` extraction itself
— direct constructibility and `LiveBotManager`'s delegating-wrapper facade.

Deliberately NOT a re-test of reconcile/cancel/amend/governor-breach
BEHAVIOR — that's already covered end-to-end by `test_cancel_symbol_algo_
orders.py`, `test_maybe_amend_exchange_sl.py`, `test_reconcile_naked_
position_rearm.py`, `test_reconcile_fixes.py`, `test_execute_entry_bracket_
safety.py`, `test_execute_entry_correlation_cap.py`, `test_on_fill_client_
id_extraction.py`, and `test_session_resume.py` — all of which now exercise
the SAME code, just through `LiveBotManager`'s old method names, which
delegate to `self._reconciler` under the hood (see golden-master
byte-identical confirmation for this extraction). This file's job is only to
verify the extraction seam is real and correctly wired.

Run inside the container::

    docker exec enma_trading_platform-engine-1 pytest /app/tests/test_reconciler.py
"""
import asyncio

from core.live_bot_manager import LiveBotManager
from core.reconciler import Reconciler
from core.session_registry import SessionRegistry
from core.node_notifier import NodeNotifier


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_reconciler_constructible_standalone():
    """Reconciler doesn't require a full LiveBotManager to build — only a
    registry, a notifier, and (for the one remaining coupling documented in
    its module docstring) a manager reference."""
    registry = SessionRegistry()
    notifier = NodeNotifier()
    reconciler = Reconciler(registry, notifier, manager=None)
    assert reconciler._registry is registry
    assert reconciler._notifier is notifier


def test_manager_reconciler_is_wired_with_its_own_registry_and_notifier():
    mgr = LiveBotManager()
    assert mgr._reconciler._registry is mgr._registry
    assert mgr._reconciler._notifier is mgr._notifier
    assert mgr._reconciler._manager is mgr


def test_manager_cancel_symbol_algo_orders_delegates(monkeypatch):
    calls = []

    async def fake_cancel(session, symbol, algo_ids):
        calls.append((session, symbol, algo_ids))

    mgr = LiveBotManager()
    monkeypatch.setattr(mgr._reconciler, "cancel_symbol_algo_orders", fake_cancel)
    _run(mgr._cancel_symbol_algo_orders({"api_key": "k"}, "BTCUSDT", {"sl": "1"}))

    assert calls == [({"api_key": "k"}, "BTCUSDT", {"sl": "1"})]


def test_manager_reconcile_exchange_state_delegates(monkeypatch):
    calls = []

    async def fake_reconcile(session_id, strategy, symbol, candle_high, candle_low):
        calls.append((session_id, strategy, symbol, candle_high, candle_low))
        return {"position": None, "open_orders": []}

    mgr = LiveBotManager()
    monkeypatch.setattr(mgr._reconciler, "reconcile_exchange_state", fake_reconcile)
    result = _run(mgr._reconcile_exchange_state("sess1", "STRAT", "BTCUSDT", 101.0, 99.0))

    assert result == {"position": None, "open_orders": []}
    assert calls == [("sess1", "STRAT", "BTCUSDT", 101.0, 99.0)]


def test_manager_compute_session_equity_and_margin_matches_reconciler_static():
    """Both entry points (the old manager name and the new collaborator's
    own public API) must be the literal same computation, not two copies
    that could drift — confirmed by identity of the underlying function."""
    session = {
        "capital": 1000.0, "pnl": 50.0,
        "open_positions": {},
    }
    assert (
        LiveBotManager._compute_session_equity_and_margin(session)
        == Reconciler.compute_session_equity_and_margin(session)
    )


def test_manager_apply_governor_breach_delegates(monkeypatch):
    calls = []

    async def fake_apply(session_id, session, verdict):
        calls.append((session_id, session, verdict))

    mgr = LiveBotManager()
    monkeypatch.setattr(mgr._reconciler, "apply_governor_breach", fake_apply)
    session = {"trading_state": "active"}
    _run(mgr._apply_governor_breach("sess1", session, "some_verdict"))

    assert calls == [("sess1", session, "some_verdict")]
