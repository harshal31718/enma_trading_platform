"""Plan 6 Step 6.4 (ENG-5, partial) regression: `LiveAdapter` resolves its
real collaborators (registry/notifier/reconciler) once in `__init__` instead
of chaining `self.manager.<attr>` through every method body.

Deliberately narrow scope (see the plan doc's own note): the constructor
still accepts a `manager` reference rather than the three collaborators
directly — a full injected-dependency signature was judged a materially
larger, riskier change for a live-only path with zero golden-master
coverage, and would break 19 existing tests that construct
`LiveAdapter(mgr, sid)` directly. This file only proves the INTERNAL
resolution is correct and that a monkeypatch on the real collaborator
classes (not `LiveBotManager`) is what now actually intercepts calls.

Run inside the container::

    docker exec enma_trading_platform-engine-1 pytest /app/tests/test_live_adapter_dependency_wiring.py
"""
import asyncio

from core.live_bot_manager import LiveBotManager, LiveAdapter
from core.reconciler import Reconciler


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_adapter_resolves_same_collaborator_instances_as_manager():
    mgr = LiveBotManager()
    adapter = LiveAdapter(mgr, "sess1")

    assert adapter._registry is mgr._registry
    assert adapter._notifier is mgr._notifier
    assert adapter._reconciler is mgr._reconciler


def test_patching_reconciler_class_intercepts_adapter_calls_not_manager_wrapper(monkeypatch):
    """Patching `LiveBotManager._cancel_symbol_algo_orders` (the OLD target)
    must no longer affect `LiveAdapter` — it now calls `self._reconciler.
    cancel_symbol_algo_orders` directly. Patching `Reconciler` itself is the
    correct interception point post-6.4."""
    mgr = LiveBotManager()
    adapter = LiveAdapter(mgr, "sess1")

    stale_calls = []

    async def stale_patch(self, session, symbol, algo_ids=None):
        stale_calls.append(1)
    monkeypatch.setattr(LiveBotManager, "_cancel_symbol_algo_orders", stale_patch)

    real_calls = []

    async def real_patch(self, session, symbol, algo_ids=None):
        real_calls.append(1)
    monkeypatch.setattr(Reconciler, "cancel_symbol_algo_orders", real_patch)

    _run(adapter._reconciler.cancel_symbol_algo_orders({}, "BTCUSDT", None))

    assert real_calls == [1]
    assert stale_calls == []
