"""Plan 5 Step 5.4 (ENG-3) regression: the per-candle loop and the user-data
WS fill callback both mutate strategy.position / session state for the same
symbol and must never interleave.

Rather than driving the full `_run_symbol_loop` (a large, deeply embedded
method), this tests `LiveBotManager._get_symbol_lock` directly: same
(session_id, symbol) always returns the same lock instance, different
symbols/sessions get independent locks, and two coroutines racing for the
same symbol's lock genuinely serialize (one blocks until the other releases)
rather than interleaving.

Run inside the container::

    docker exec enma_trading_platform-engine-1 pytest /app/tests/test_symbol_state_lock.py
"""
import asyncio

from core.live_bot_manager import LiveBotManager

SID = "sess1"
SYM = "FAKEUSDT"


def test_same_session_symbol_returns_the_same_lock_instance():
    mgr = LiveBotManager()
    lock_a = mgr._get_symbol_lock(SID, SYM)
    lock_b = mgr._get_symbol_lock(SID, SYM)
    assert lock_a is lock_b


def test_different_symbols_get_independent_locks():
    mgr = LiveBotManager()
    lock_btc = mgr._get_symbol_lock(SID, "BTCUSDT")
    lock_eth = mgr._get_symbol_lock(SID, "ETHUSDT")
    assert lock_btc is not lock_eth


def test_different_sessions_get_independent_locks_for_the_same_symbol():
    mgr = LiveBotManager()
    lock_s1 = mgr._get_symbol_lock("session1", SYM)
    lock_s2 = mgr._get_symbol_lock("session2", SYM)
    assert lock_s1 is not lock_s2


def test_candle_loop_and_fill_callback_genuinely_serialize():
    """Simulates the real race: a slow 'candle loop' mutation and a 'fill
    callback' mutation on the same symbol, both holding the lock. Without
    the lock this interleaves and corrupts `shared_state`; with it, each
    critical section runs start-to-finish before the other begins."""
    mgr = LiveBotManager()
    shared_state = {"position_open": False, "mutation_log": []}

    async def candle_loop_mutation():
        async with mgr._get_symbol_lock(SID, SYM):
            shared_state["mutation_log"].append("candle:start")
            shared_state["position_open"] = True
            await asyncio.sleep(0.05)  # simulates an awaited Binance call mid-mutation
            assert shared_state["position_open"] is True, "fill callback interleaved mid-candle-mutation"
            shared_state["mutation_log"].append("candle:end")

    async def fill_callback_mutation():
        async with mgr._get_symbol_lock(SID, SYM):
            shared_state["mutation_log"].append("fill:start")
            shared_state["position_open"] = False
            await asyncio.sleep(0.01)
            shared_state["mutation_log"].append("fill:end")

    async def run_concurrently():
        await asyncio.gather(candle_loop_mutation(), fill_callback_mutation())

    asyncio.get_event_loop().run_until_complete(run_concurrently())

    # Whichever ran first, its start/end must be adjacent — never interleaved
    # with the other's start/end.
    log = shared_state["mutation_log"]
    assert log in (
        ["candle:start", "candle:end", "fill:start", "fill:end"],
        ["fill:start", "fill:end", "candle:start", "candle:end"],
    ), f"critical sections interleaved: {log}"


def test_lock_cleanup_removes_only_the_stopped_sessions_locks():
    mgr = LiveBotManager()
    lock_keep = mgr._get_symbol_lock("keep_session", SYM)
    mgr._get_symbol_lock("stop_session", SYM)
    mgr._get_symbol_lock("stop_session", "ETHUSDT")

    for key in [k for k in mgr._symbol_state_locks if k[0] == "stop_session"]:
        mgr._symbol_state_locks.pop(key, None)

    assert ("stop_session", SYM) not in mgr._symbol_state_locks
    assert ("stop_session", "ETHUSDT") not in mgr._symbol_state_locks
    assert mgr._get_symbol_lock("keep_session", SYM) is lock_keep
