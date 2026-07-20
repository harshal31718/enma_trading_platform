"""Plan 6 Step 6.1 (ENG-1): unit tests for `SessionRegistry`, extracted from
`LiveBotManager` as a behavior-preserving move (golden-master byte-identical,
see `before_plan6.json`/`after_plan6_1c.json`). Also covers `LiveBotManager`'s
delegating properties, since that facade is what keeps every other call site
(and the rest of this test suite) working unchanged.

Run inside the container::

    docker exec enma_trading_platform-engine-1 pytest /app/tests/test_session_registry.py
"""
from core.live_bot_manager import LiveBotManager
from core.session_registry import SessionRegistry


def test_get_symbol_lock_same_key_returns_same_lock():
    reg = SessionRegistry()
    lock1 = reg.get_symbol_lock("sess1", "BTCUSDT")
    lock2 = reg.get_symbol_lock("sess1", "BTCUSDT")
    assert lock1 is lock2


def test_get_symbol_lock_different_keys_return_different_locks():
    reg = SessionRegistry()
    lock_a = reg.get_symbol_lock("sess1", "BTCUSDT")
    lock_b = reg.get_symbol_lock("sess1", "ETHUSDT")
    lock_c = reg.get_symbol_lock("sess2", "BTCUSDT")
    assert lock_a is not lock_b
    assert lock_a is not lock_c


def test_registry_dicts_start_empty():
    reg = SessionRegistry()
    assert reg.sessions == {}
    assert reg.stop_signals == {}
    assert reg.tasks == {}
    assert reg.order_semaphores == {}
    assert reg.symbol_state_locks == {}


def test_manager_properties_delegate_to_same_registry_objects():
    """The facade must expose the SAME dict objects, not copies — mutating
    via `mgr.sessions[...]` must be visible through `mgr._registry.sessions`
    and vice versa (this is what every existing test relies on implicitly)."""
    mgr = LiveBotManager()

    assert mgr.sessions is mgr._registry.sessions
    assert mgr._stop_signals is mgr._registry.stop_signals
    assert mgr._tasks is mgr._registry.tasks
    assert mgr._order_semaphores is mgr._registry.order_semaphores
    assert mgr._symbol_state_locks is mgr._registry.symbol_state_locks

    mgr.sessions["sess1"] = {"pnl": 0.0}
    assert mgr._registry.sessions["sess1"] == {"pnl": 0.0}

    mgr._registry.sessions["sess2"] = {"pnl": 5.0}
    assert mgr.sessions["sess2"] == {"pnl": 5.0}


def test_manager_get_symbol_lock_delegates_to_registry():
    mgr = LiveBotManager()
    lock = mgr._get_symbol_lock("sess1", "BTCUSDT")
    assert lock is mgr._registry.symbol_state_locks[("sess1", "BTCUSDT")]
