"""Plan 8 Step 8.5 (ENG-14): strategy_name validation + visible failure on the
live-session start path.

Before this fix: `start_session` never validated `strategy_name` (unlike
`routers/strategies.py`'s `_validate_strategy_name`) and its dynamic
`importlib.import_module(f"strategies.{strategy_name}")` was wrapped in
nothing — since `start_session` runs as a fire-and-forget FastAPI background
task (the POST /algo/sessions request has already returned 200 "starting"
before this even executes), an invalid name or a failed import left the
session silently stuck at "starting" forever with zero signal reaching Node.
Same story for a per-symbol param validation failure inside
`_run_symbol_loop`, reached via a bare `asyncio.create_task()` with no
`add_done_callback` — the task just died, visible only in asyncio's own
"Task exception was never retrieved" logger.

Run inside the container::

    docker exec enma_trading_platform-engine-1 pytest /app/tests/test_strategy_load_failure.py
"""
import asyncio
import sys
import types

import pytest

from utils.strategy_names import is_valid_strategy_name


def test_is_valid_strategy_name_accepts_seeded_strategy_names():
    for name in ("MicroScalper", "AdaptiveTrend", "BestSupertrend",
                 "MicroMacroRSIDivergence", "MultiDivergence"):
        assert is_valid_strategy_name(name)


def test_is_valid_strategy_name_rejects_path_traversal_and_bad_shapes():
    assert not is_valid_strategy_name("../../etc")
    assert not is_valid_strategy_name("has spaces")
    assert not is_valid_strategy_name("123StartsWithDigit")
    assert not is_valid_strategy_name("")
    assert not is_valid_strategy_name(None)


def _ensure_importable():
    # Same stub-injection as test_start_session_risk_params_shape.py — this
    # test also drives a real `start_session()`/`_run_symbol_loop()` call.
    try:
        import core.live_bot_manager  # noqa: F401
        return
    except ModuleNotFoundError:
        pass

    for modname in ("websockets", "motor", "motor.motor_asyncio", "asyncpg"):
        if modname not in sys.modules:
            sys.modules[modname] = types.ModuleType(modname)
    sys.modules["motor"].motor_asyncio = sys.modules["motor.motor_asyncio"]

    class _FakeAsyncIOMotorClient:
        def __init__(self, *a, **kw):
            pass

    if not hasattr(sys.modules["motor.motor_asyncio"], "AsyncIOMotorClient"):
        sys.modules["motor.motor_asyncio"].AsyncIOMotorClient = _FakeAsyncIOMotorClient

    async def _fake_connect(*a, **kw):
        raise RuntimeError("stubbed websockets.connect — not implemented, test doesn't call it")

    if not hasattr(sys.modules["websockets"], "connect"):
        sys.modules["websockets"].connect = _fake_connect

    class _FakePool:
        pass

    if not hasattr(sys.modules["asyncpg"], "Pool"):
        sys.modules["asyncpg"].Pool = _FakePool

    async def _fake_create_pool(*a, **kw):
        raise RuntimeError("stubbed asyncpg.create_pool — not implemented, test doesn't call it")

    if not hasattr(sys.modules["asyncpg"], "create_pool"):
        sys.modules["asyncpg"].create_pool = _fake_create_pool


_ensure_importable()

import core.live_bot_manager as lbm_module
from core.live_bot_manager import LiveBotManager


class _FakeUDS:
    def __init__(self, *a, **kw):
        pass

    async def start(self):
        pass

    async def stop(self):
        pass


def _base_session_config(**overrides):
    cfg = {
        "session_id": "sess_load_fail",
        "strategy_name": "MicroScalper",
        "symbols": ["FAKEUSDT"],
        "timeframe": "1m",
        "params": {},
        "capital": "1000",
        "leverage": 1,
        "fee_rate": 0.0005,
        "risk_params": {},
        "user_id": "u1",
        "api_key": "",
        "api_secret": "",
    }
    cfg.update(overrides)
    return cfg


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_invalid_strategy_name_notifies_error_and_never_registers_session(monkeypatch):
    monkeypatch.setattr(lbm_module, "UserDataStreamManager", _FakeUDS)
    mgr = LiveBotManager()
    notified = []

    async def _fake_notify(session_id, data):
        notified.append((session_id, data))

    monkeypatch.setattr(mgr._notifier, "notify", _fake_notify)

    cfg = _base_session_config(strategy_name="../../etc")
    _run(mgr.start_session(cfg))

    assert "sess_load_fail" not in mgr.sessions
    assert len(notified) == 1
    session_id, data = notified[0]
    assert session_id == "sess_load_fail"
    assert data["status"] == "error"
    assert "Invalid strategy_name" in data["errorMessage"]


def test_nonexistent_strategy_notifies_error_and_never_registers_session(monkeypatch):
    monkeypatch.setattr(lbm_module, "UserDataStreamManager", _FakeUDS)
    mgr = LiveBotManager()
    notified = []

    async def _fake_notify(session_id, data):
        notified.append((session_id, data))

    monkeypatch.setattr(mgr._notifier, "notify", _fake_notify)

    # Passes the name-shape regex but no such strategy module exists.
    cfg = _base_session_config(strategy_name="NoSuchStrategyXYZ")
    _run(mgr.start_session(cfg))

    assert "sess_load_fail" not in mgr.sessions
    assert len(notified) == 1
    session_id, data = notified[0]
    assert data["status"] == "error"
    assert "Failed to load strategy" in data["errorMessage"]


def test_valid_strategy_still_starts_normally(monkeypatch):
    monkeypatch.setattr(lbm_module, "UserDataStreamManager", _FakeUDS)
    mgr = LiveBotManager()
    notified = []

    async def _fake_notify(session_id, data):
        notified.append((session_id, data))

    monkeypatch.setattr(mgr._notifier, "notify", _fake_notify)

    cfg = _base_session_config()
    _run(mgr.start_session(cfg))

    assert "sess_load_fail" in mgr.sessions
    # No error notify should have fired for the load path itself.
    assert not any(d.get("status") == "error" for _, d in notified)

    for task in mgr._tasks.get("sess_load_fail", []):
        task.cancel()


def test_unknown_param_notifies_error_and_returns_without_raising(monkeypatch):
    monkeypatch.setattr(lbm_module, "UserDataStreamManager", _FakeUDS)
    mgr = LiveBotManager()
    notified = []

    async def _fake_notify(session_id, data):
        notified.append((session_id, data))

    monkeypatch.setattr(mgr._notifier, "notify", _fake_notify)

    # Start the session first so `_run_symbol_loop`'s `self.sessions.get(session_id)`
    # lookups resolve, same as a real launch.
    cfg = _base_session_config(params={})
    _run(mgr.start_session(cfg))
    for task in mgr._tasks.get("sess_load_fail", []):
        task.cancel()
    notified.clear()

    import strategies.MicroScalper as ms_module

    # Call _run_symbol_loop directly with a param that doesn't exist on
    # MicroScalper's PARAMS — must return cleanly (no exception) before ever
    # reaching the leverage-clamp network call further down the function.
    _run(mgr._run_symbol_loop(
        "sess_load_fail", ms_module.MicroScalper, "FAKEUSDT",
        {"not_a_real_param": 999}, "1m", 100.0, 1, 0.0005, {},
    ))

    assert len(notified) == 1
    session_id, data = notified[0]
    assert data["event"] == "log"
    assert data["eventData"]["type"] == "error"
    assert "invalid strategy params" in data["eventData"]["message"]
    assert "not_a_real_param" in data["eventData"]["message"]
