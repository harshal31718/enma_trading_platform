"""Plan 22 Step 22.4 regression: `LiveAdapter.execute_entry()`'s account-wide
VaR/CVaR pre-trade veto (`SessionRiskGovernor.check_var`, fed by the shared
`services/portfolio_risk.compute_var_cvar` — same function the Zone 1
dashboard calls, see `test_portfolio_risk_shared_service.py`).

Same stub-injection harness as `test_execute_entry_portfolio_risk_and_liq_
buffer.py` / `test_kline_ws_url.py` — see those files' docstrings for why.

This file's acceptance-critical test is `test_var_breach_blocks_a_new_entry`
— proves a VaR breach "demonstrably blocks a new entry in a stubbed session"
(this step's own acceptance wording), with no order ever reaching the fake
Binance signed-request layer.

Run inside the container::

    docker exec enma_trading_platform-engine-1 pytest /app/tests/test_execute_entry_var_breach.py
"""
import asyncio
import sys
import types
from datetime import datetime, timezone

import numpy as np
import pytest


def _ensure_importable():
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

import services.binance_testnet as binance_mod
import services.portfolio_risk as pr
import core.live_bot_manager as lbm_module
from core.live_bot_manager import LiveBotManager, LiveAdapter
from core.models.governor import SessionRiskGovernor

SYM = "FAKEUSDT"


class _FakeExecutionModel:
    def exit_fee(self, strategy, qty, price):
        return abs(qty) * price * 0.0005


class _FakeStrategy:
    def __init__(self, stop_loss=None, take_profit=None, leverage=1):
        self.position = None
        self.stop_loss = stop_loss
        self.take_profit = take_profit
        self.buy = 1.0
        self.sell = None
        self.entry_tag = ""
        self.exit_tag = ""
        self.execution_model = _FakeExecutionModel()
        self.balance = 100_000.0
        self.leverage = leverage
        from core.models.risk import DefaultRiskModel
        self.risk_model = DefaultRiskModel()


def _make_session(risk_governor=None):
    return {
        "open_positions": {},
        "pnl": 0.0, "strategy_name": "X", "api_key": "k", "api_secret": "s", "user_id": "",
        "trading_state": "active",
        "capital": 100_000.0,
        "risk_governor": risk_governor,
        "strategy_instances": {},
    }


class _Notified:
    def __init__(self):
        self.calls = []

    async def __call__(self, session_id, payload):
        self.calls.append(payload)


@pytest.fixture(autouse=True)
def _stub_side_effects(monkeypatch):
    async def _noop_record_trade(*args, **kwargs):
        return None
    monkeypatch.setattr(lbm_module, "record_trade", _noop_record_trade)

    async def _noop_append_event(*args, **kwargs):
        return 1
    monkeypatch.setattr(lbm_module, "append_event", _noop_append_event)


@pytest.fixture(autouse=True)
def _clear_portfolio_risk_cache():
    pr.clear_caches()
    yield
    pr.clear_caches()


def _run_entry(adapter, strat, **overrides):
    kwargs = dict(
        strategy=strat, symbol=SYM, direction="long", qty=1.0, ref_price=100.0,
        time_t=datetime.now(timezone.utc), index_t=0,
    )
    kwargs.update(overrides)
    return asyncio.get_event_loop().run_until_complete(adapter.execute_entry(**kwargs))


def _make_mgr_adapter(monkeypatch, session, notified=None):
    mgr = LiveBotManager()
    sid = "sess_var_breach"
    mgr.sessions[sid] = session
    monkeypatch.setattr(mgr, "_notify_node", notified or _Notified())
    return mgr, LiveAdapter(mgr, sid)


def _fake_binance(account_data, order_calls):
    async def fake_signed(method, path, api_key, api_secret, params=None, mode="testnet"):
        if method == "GET" and path == "/fapi/v2/account":
            return account_data
        if method == "POST" and path == "/fapi/v1/order":
            order_calls["entry"] = order_calls.get("entry", 0) + 1
            return {"orderId": 1, "avgPrice": "100.0", "status": "FILLED"}
        if method == "POST" and path == "/fapi/v1/algoOrder":
            order_calls["algo"] = order_calls.get("algo", 0) + 1
            return {"algoId": "111"}
        raise AssertionError(f"unexpected call {method} {path} {params}")
    return fake_signed


def _fake_pool_with_prices(low=49000, high=51000, n=40):
    """Alternating up/down walk (not a monotone linspace) — `calculate_
    portfolio_var` clamps VaR to 0 whenever every daily log-return is
    positive (`var_pct = min(0.0, percentile)`), so a real test of a VaR
    *breach* needs genuine downside moves in the synthetic series, not just
    a wide absolute price range."""
    class _FakeConn:
        async def fetch(self, query, symbols, cutoff):
            base = np.linspace(low, high, n)
            wiggle = np.array([1.0 if i % 2 == 0 else 0.85 for i in range(n)])
            series = base * wiggle
            return [{"symbol": s, "close": float(v)} for s in symbols for v in series]

    class _FakeAcquire:
        async def __aenter__(self):
            return _FakeConn()

        async def __aexit__(self, *a):
            return False

    class _FakePool:
        def acquire(self):
            return _FakeAcquire()

    return _FakePool()


_ACCOUNT_WITH_LARGE_POSITION = {
    "positions": [
        {"symbol": "BTCUSDT", "positionAmt": "10.0", "entryPrice": "50000",
         "notional": "500000", "leverage": "5"},
    ]
}

_ACCOUNT_FLAT = {"positions": []}


def test_no_governor_never_calls_account_endpoint(monkeypatch):
    """No risk_governor at all -> the whole VaR block must be skipped, not
    just a no-op check — proves zero extra Binance calls for sessions that
    never had a governor in the first place (pre-22.1 behavior preserved)."""
    order_calls = {}
    monkeypatch.setattr(binance_mod, "send_signed_request", _fake_binance(_ACCOUNT_FLAT, order_calls))
    session = _make_session(risk_governor=None)
    mgr, adapter = _make_mgr_adapter(monkeypatch, session)
    strat = _FakeStrategy(stop_loss=(1.0, 95.0))

    ok = _run_entry(adapter, strat, direction="long", ref_price=100.0)

    assert ok is True
    assert order_calls["entry"] == 1


def test_governor_without_var_limits_never_calls_account_endpoint(monkeypatch):
    """Governor present but var_limit_pct/cvar_limit_pct both unset (default
    off) -> still opt-in, no wasted Binance/TimescaleDB round trip."""
    order_calls = {}
    monkeypatch.setattr(binance_mod, "send_signed_request", _fake_binance(_ACCOUNT_FLAT, order_calls))
    gov = SessionRiskGovernor({})  # var_limit_pct=None, cvar_limit_pct=None
    session = _make_session(risk_governor=gov)
    mgr, adapter = _make_mgr_adapter(monkeypatch, session)
    strat = _FakeStrategy(stop_loss=(1.0, 95.0))

    ok = _run_entry(adapter, strat, direction="long", ref_price=100.0)

    assert ok is True
    assert order_calls["entry"] == 1


def test_var_within_limit_enters_normally(monkeypatch):
    order_calls = {}
    monkeypatch.setattr(binance_mod, "send_signed_request", _fake_binance(_ACCOUNT_FLAT, order_calls))
    monkeypatch.setattr(pr, "get_pool", lambda: _fake_pool_with_prices())
    # Flat account (no existing positions) -> VaR/CVaR compute to 0 (no
    # notional to weight returns by) -> trivially within any positive limit.
    gov = SessionRiskGovernor({"var_limit_pct": 0.05})
    session = _make_session(risk_governor=gov)
    mgr, adapter = _make_mgr_adapter(monkeypatch, session)
    strat = _FakeStrategy(stop_loss=(1.0, 95.0))

    ok = _run_entry(adapter, strat, direction="long", ref_price=100.0)

    assert ok is True
    assert order_calls["entry"] == 1


def test_var_breach_blocks_a_new_entry(monkeypatch):
    """Acceptance criterion: a VaR breach demonstrably blocks a new entry —
    an account with a large existing position, a tiny var_limit_pct
    guarantees a breach relative to session equity (capital 100_000)."""
    order_calls = {}
    monkeypatch.setattr(binance_mod, "send_signed_request",
                         _fake_binance(_ACCOUNT_WITH_LARGE_POSITION, order_calls))
    # Wide, volatile price range so calculate_portfolio_var produces a
    # meaningfully large var_amount off a $500k notional position.
    monkeypatch.setattr(pr, "get_pool", lambda: _fake_pool_with_prices(low=30000, high=70000, n=60))
    gov = SessionRiskGovernor({"var_limit_pct": 0.0001})  # absurdly tight -> guaranteed breach
    session = _make_session(risk_governor=gov)
    notified = _Notified()
    mgr, adapter = _make_mgr_adapter(monkeypatch, session, notified=notified)
    strat = _FakeStrategy(stop_loss=(1.0, 95.0))

    ok = _run_entry(adapter, strat, direction="long", ref_price=100.0)

    assert ok is False
    assert "entry" not in order_calls  # no order ever reached Binance
    assert "algo" not in order_calls
    veto_logs = [
        c for c in notified.calls
        if c.get("event") == "log" and "var_limit" in c.get("eventData", {}).get("message", "")
    ]
    assert len(veto_logs) == 1
    assert strat.buy is None and strat.stop_loss is None  # M-5-style local-state clear on veto


def test_cvar_only_limit_can_also_breach(monkeypatch):
    order_calls = {}
    monkeypatch.setattr(binance_mod, "send_signed_request",
                         _fake_binance(_ACCOUNT_WITH_LARGE_POSITION, order_calls))
    monkeypatch.setattr(pr, "get_pool", lambda: _fake_pool_with_prices(low=30000, high=70000, n=60))
    gov = SessionRiskGovernor({"cvar_limit_pct": 0.0001})  # var_limit_pct unset, only cvar configured
    session = _make_session(risk_governor=gov)
    mgr, adapter = _make_mgr_adapter(monkeypatch, session)
    strat = _FakeStrategy(stop_loss=(1.0, 95.0))

    ok = _run_entry(adapter, strat, direction="long", ref_price=100.0)

    assert ok is False
    assert "entry" not in order_calls


def test_var_fetch_exception_fails_open(monkeypatch):
    """A Binance account-fetch failure (e.g. transient outage) must not
    block trading outright — same fail-open precedent as the liquidation-
    buffer check (22.2). Only the GET /fapi/v2/account call raises; the
    order/algoOrder POSTs still succeed normally, so a real fill completing
    through `execute_entry` proves the VaR check itself degraded to
    fail-open rather than vetoing on the fetch error."""
    order_calls = {}

    async def fake_signed(method, path, api_key, api_secret, params=None, mode="testnet"):
        if method == "GET" and path == "/fapi/v2/account":
            raise RuntimeError("simulated Binance outage")
        if method == "POST" and path == "/fapi/v1/order":
            order_calls["entry"] = order_calls.get("entry", 0) + 1
            return {"orderId": 1, "avgPrice": "100.0", "status": "FILLED"}
        if method == "POST" and path == "/fapi/v1/algoOrder":
            order_calls["algo"] = order_calls.get("algo", 0) + 1
            return {"algoId": "111"}
        raise AssertionError(f"unexpected call {method} {path} {params}")

    monkeypatch.setattr(binance_mod, "send_signed_request", fake_signed)
    gov = SessionRiskGovernor({"var_limit_pct": 0.05})
    session = _make_session(risk_governor=gov)
    mgr, adapter = _make_mgr_adapter(monkeypatch, session)
    strat = _FakeStrategy(stop_loss=(1.0, 95.0))

    ok = _run_entry(adapter, strat, direction="long", ref_price=100.0)

    assert ok is True  # fetch failure -> fail OPEN, entry proceeds
    assert order_calls["entry"] == 1
