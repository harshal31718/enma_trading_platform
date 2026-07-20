"""Live-session lifecycle state: the session dict, per-session stop signals/
tasks/order semaphores, and the per-(session, symbol) state lock.

Extracted from `LiveBotManager` (Plan 6 Step 6.1, ENG-1) as a behavior-
preserving move. `LiveBotManager` still exposes `sessions`/`_stop_signals`/
`_tasks`/`_order_semaphores`/`_symbol_state_locks`/`_get_symbol_lock` as thin
delegating properties/methods so every existing call site (and every test
that pokes those attributes directly, e.g. `mgr.sessions[sid] = ...`) keeps
working unchanged — this extraction moves the storage and locking logic into
an independently testable collaborator without touching the ~90 call sites
scattered through `start_session`/`stop_session`/`_run_symbol_loop`/etc.

Deliberately NOT done here (real scope left open, see Plan 6 Step 6.1's own
notes): typing `sessions[id]`'s value as a real object instead of a raw
`dict`. That touches hundreds of `session["key"]` reads/writes across the
whole file and is a materially larger, separate piece of work.
"""
from __future__ import annotations

import asyncio


class SessionRegistry:
    """Owns live-session state: the session dict + per-session async
    primitives (stop event, task list, order semaphore, per-symbol lock)."""

    def __init__(self):
        self.sessions: dict[str, dict] = {}
        self.stop_signals: dict[str, asyncio.Event] = {}
        self.tasks: dict[str, list[asyncio.Task]] = {}
        # Limit concurrent Binance testnet calls per session to avoid overwhelming
        # the testnet when many symbols fire signals on the same candle close.
        self.order_semaphores: dict[str, asyncio.Semaphore] = {}
        # Plan 5 Step 5.4 (ENG-3): the per-candle loop (reconcile -> check_exits
        # -> evaluate_and_route) and the user-data WS fill callback (_on_fill,
        # which also calls _reconcile_exchange_state) both mutate the same
        # strategy.position / session["pnl"] / session["open_positions"] state
        # and can interleave at any await point — a fill landing mid-candle-
        # loop is a real double-close/double-count race. One lock per
        # (session_id, symbol) serializes them.
        self.symbol_state_locks: dict[tuple[str, str], asyncio.Lock] = {}

    def get_symbol_lock(self, session_id: str, symbol: str) -> asyncio.Lock:
        key = (session_id, symbol)
        lock = self.symbol_state_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self.symbol_state_locks[key] = lock
        return lock
