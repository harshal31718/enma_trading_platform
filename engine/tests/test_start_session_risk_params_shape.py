"""Plan 22 Step 22.7 regression: `LiveBotManager.start_session()`'s Session
Risk Governor / allocation config was reading `risk_params` at the WRONG
dict level since Plan 22 Step 22.1.

`risk_params` as sent by Node (`server/src/controllers/algo.controller.js`,
both `startSession` and `startChaos`) is shaped
`{symbol: {...resolved risk...}, ..., "default": {...resolved risk...}}` —
one `resolveStrategyRiskParams()` call per symbol, matching the existing
per-symbol-strategy-setup code's own `_risk_all.get(symbol) or
_risk_all.get("default")` pattern. But the governor_cfg cascade added in
22.1 and extended by 22.2/22.4/22.5/22.6/22.7 read `risk_params.get(...)`
directly on that WRAPPER dict — "max_session_dd", "governor",
"max_portfolio_risk", "var_limit_pct", "cvar_limit_pct", "correlation_cap",
"allocation" are never top-level keys of that shape, so every one of these
reads always returned `None` and silently fell through to the governor's
hardcoded default, regardless of what Zone 2 (or a wizard override)
actually configured. Found and fixed while wiring 22.7's Node cascade
through — this file proves the fix against the REAL Node-shaped payload,
not a flattened stand-in that would hide the bug again.

Run inside the container::

    docker exec enma_trading_platform-engine-1 pytest /app/tests/test_start_session_risk_params_shape.py
"""
import asyncio
import sys
import types

import pytest


def _ensure_importable():
    # Strategy files import `from engine.core...` (see strategies/MicroScalper/
    # __init__.py), resolved via the engine_alias hook conftest.py installs
    # globally for the test process. This function's remaining job is
    # stubbing optional deps for environments without them installed — only
    # needed because this test drives a REAL dynamic strategy import through
    # `start_session`, unlike the other stub-injection tests in this suite.
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
    """Stands in for UserDataStreamManager — start_session already wraps
    `await uds.start()` in try/except, but a real UDS would attempt a
    genuine Binance listen-key network call. Stub it out entirely."""
    def __init__(self, *a, **kw):
        pass

    async def start(self):
        pass

    async def stop(self):
        pass


def _real_node_shaped_risk_params(**default_overrides):
    """The actual shape `resolveStrategyRiskParams()` output takes once
    wrapped per-symbol by `algo.controller.js` — NOT a flat dict."""
    default_slice = {
        "risk_pct": 0.01, "rrr": 2.0, "max_session_dd": 0.20,
        "liq_buffer_pct": 0.005, "min_edge_mult": 0.0, "leverage": 1,
        "volatility_multiplier": 1.0, "max_exposure_notional": float("inf"),
        "custom_atr_mult": None,
    }
    default_slice.update(default_overrides)
    return {"FAKEUSDT": dict(default_slice), "default": dict(default_slice)}


def _run_start_session(monkeypatch, risk_params):
    monkeypatch.setattr(lbm_module, "UserDataStreamManager", _FakeUDS)
    mgr = LiveBotManager()
    session_id = "sess_shape_test"

    session_config = {
        "session_id": session_id,
        "strategy_name": "MicroScalper",
        "symbols": ["FAKEUSDT"],
        "timeframe": "1m",
        "params": {},
        "capital": "1000",
        "leverage": 1,
        "fee_rate": 0.0005,
        "risk_params": risk_params,
        "user_id": "u1",
        "api_key": "",
        "api_secret": "",
    }

    loop = asyncio.get_event_loop()
    loop.run_until_complete(mgr.start_session(session_config))
    session = mgr.sessions[session_id]
    # Background per-symbol loops were scheduled via asyncio.create_task but
    # cannot have executed yet (no await happened between task creation and
    # this point in the single-threaded event loop) — cancel before they run
    # a single line, so this test never touches real candle/exchange I/O.
    for task in mgr._tasks.get(session_id, []):
        task.cancel()
    return session


def test_max_session_dd_reaches_governor_from_real_node_shape(monkeypatch):
    risk_params = _real_node_shaped_risk_params(max_session_dd=0.11)
    session = _run_start_session(monkeypatch, risk_params)
    assert session["risk_governor"].max_session_dd == pytest.approx(0.11)


def test_max_portfolio_risk_reaches_governor_from_real_node_shape(monkeypatch):
    risk_params = _real_node_shaped_risk_params(max_portfolio_risk=0.03)
    session = _run_start_session(monkeypatch, risk_params)
    assert session["risk_governor"].max_portfolio_risk == pytest.approx(0.03)


def test_var_cvar_limits_reach_governor_from_real_node_shape(monkeypatch):
    risk_params = _real_node_shaped_risk_params(var_limit_pct=0.05, cvar_limit_pct=0.08)
    session = _run_start_session(monkeypatch, risk_params)
    assert session["risk_governor"].var_limit_pct == pytest.approx(0.05)
    assert session["risk_governor"].cvar_limit_pct == pytest.approx(0.08)


def test_correlation_cap_reaches_governor_from_real_node_shape(monkeypatch):
    risk_params = _real_node_shaped_risk_params(correlation_cap={"rho": 0.8, "max_cluster_exposure_pct": 0.3})
    session = _run_start_session(monkeypatch, risk_params)
    assert session["risk_governor"].correlation_rho == pytest.approx(0.8)
    assert session["risk_governor"].max_cluster_exposure_pct == pytest.approx(0.3)


def test_governor_only_fields_reach_governor_from_real_node_shape(monkeypatch):
    risk_params = _real_node_shaped_risk_params(
        max_daily_loss_pct=0.15, max_margin_utilization=0.65,
        breach_action="halted", auto_flatten_on_halt=True,
    )
    session = _run_start_session(monkeypatch, risk_params)
    gov = session["risk_governor"]
    assert gov.max_daily_loss_pct == pytest.approx(0.15)
    assert gov.max_margin_utilization == pytest.approx(0.65)
    assert gov.breach_action == "halted"
    assert gov.auto_flatten_on_halt is True


def test_allocation_flag_reaches_start_session_from_real_node_shape(monkeypatch):
    """Doesn't assert the actual InverseVolatilityPortfolio computation (that
    needs a live price-history fetch) — just proves `default_risk_params.get
    ("allocation")` sees "inverse_vol" from the real wrapped shape, by
    confirming it does NOT silently no-op the same way the pre-fix code did
    (would always read None -> "equal" path, no fetch attempted)."""
    import services.portfolio_risk as pr

    fetch_called = {"count": 0}

    async def _fake_fetch_close_prices(symbols):
        fetch_called["count"] += 1
        return {}

    monkeypatch.setattr(pr, "fetch_close_prices", _fake_fetch_close_prices)
    risk_params = _real_node_shaped_risk_params(allocation="inverse_vol")
    _run_start_session(monkeypatch, risk_params)
    assert fetch_called["count"] == 1  # proves the inverse_vol branch was actually entered


def test_defaults_apply_when_governor_fields_absent(monkeypatch):
    """No governor-only fields set -> governor still constructs with its own
    hardcoded defaults, same as before this fix (no regression on the
    already-working "nothing configured" path)."""
    risk_params = _real_node_shaped_risk_params()
    session = _run_start_session(monkeypatch, risk_params)
    gov = session["risk_governor"]
    assert gov.max_session_dd == pytest.approx(0.20)
    assert gov.var_limit_pct is None
    assert gov.correlation_rho is None
