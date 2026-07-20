"""Plan 22 Step 22.5 regression: `LiveAdapter.execute_entry()`'s
correlation-adjusted concentration cap pre-trade veto
(`SessionRiskGovernor.check_correlation_concentration`, fed by the shared
`services/portfolio_risk.fetch_correlation_matrix` — reuses the same 60s
close-price cache `compute_var_cvar`/the Zone 1 dashboard already share).

Same stub-injection harness as `test_execute_entry_var_breach.py` /
`test_execute_entry_portfolio_risk_and_liq_buffer.py` — see those files'
docstrings for why. This file's acceptance-critical test is
`test_correlated_third_entry_vetoed_no_order_placed` — two open,
mutually-correlated positions already at the cluster cap; a third
correlated entry is vetoed with zero Binance order/algoOrder calls.

Run inside the container::

    docker exec enma_trading_platform-engine-1 pytest /app/tests/test_execute_entry_correlation_cap.py
"""
import asyncio
import sys
import types
from datetime import datetime, timezone

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

import numpy as np

import services.binance_testnet as binance_mod
import services.portfolio_risk as pr
import core.live_bot_manager as lbm_module
from core.live_bot_manager import LiveBotManager, LiveAdapter
from core.models.base import OrderPlan
from core.models.governor import SessionRiskGovernor
from core.position import Position

SYM = "SOLUSDT"
BTC = "BTCUSDT"
ETH = "ETHUSDT"


class _FakeExecutionModel:
    def exit_fee(self, strategy, qty, price):
        return abs(qty) * price * 0.0005


class _FakeStrategy:
    def __init__(self, stop_loss=None, take_profit=None, leverage=1):
        self.position = None
        self.stop_loss = stop_loss
        self.take_profit = take_profit
        # Plan 6 Step 6.3 phase (d3): compute_open_risk_breakdown() reads
        # active_bracket now, not stop_loss directly.
        self.active_bracket = (
            OrderPlan(
                direction=1, qty=stop_loss[0], entry_price=100.0,
                stop_loss=stop_loss[1], take_profit=take_profit[1] if take_profit else None,
            ) if stop_loss is not None else None
        )
        self.buy = 1.0
        self.sell = None
        self.entry_tag = ""
        self.exit_tag = ""
        self.execution_model = _FakeExecutionModel()
        self.balance = 100_000.0
        self.leverage = leverage
        from core.models.risk import DefaultRiskModel
        self.risk_model = DefaultRiskModel()


class _OpenSymbolStrategy:
    """Minimal strategy stand-in for an already-open OTHER symbol —
    execute_entry's correlation block only reads `.position` off it (and
    `_compute_open_risk_breakdown`, run earlier in the same call, reads
    `.stop_loss` — `None` means it contributes 0 to that unrelated check)."""
    def __init__(self, qty, entry_price):
        self.position = Position("long", qty, entry_price, leverage=1)
        self.stop_loss = None
        self.active_bracket = None  # Plan 6 Step 6.3 phase (d3): compute_open_risk_breakdown() reads this now


def _make_session(risk_governor=None, strategy_instances=None, capital=100_000.0):
    return {
        "open_positions": {},
        "pnl": 0.0, "strategy_name": "X", "api_key": "k", "api_secret": "s", "user_id": "",
        "trading_state": "active",
        "capital": capital,
        "risk_governor": risk_governor,
        "strategy_instances": strategy_instances or {},
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
        strategy=strat, symbol=SYM, direction="long", qty=20.0, ref_price=100.0,
        time_t=datetime.now(timezone.utc), index_t=0,
    )
    kwargs.update(overrides)
    return asyncio.get_event_loop().run_until_complete(adapter.execute_entry(**kwargs))


def _make_mgr_adapter(monkeypatch, session, notified=None):
    mgr = LiveBotManager()
    sid = "sess_corr_cap"
    mgr.sessions[sid] = session
    monkeypatch.setattr(mgr._notifier, "notify", notified or _Notified())
    return mgr, LiveAdapter(mgr, sid)


def _fake_signed_happy_path(calls):
    async def fake_signed(method, path, api_key, api_secret, params=None, mode="testnet"):
        if method == "POST" and path == "/fapi/v1/order":
            calls["entry"] = calls.get("entry", 0) + 1
            return {"orderId": 1, "avgPrice": "100.0", "status": "FILLED"}
        if method == "POST" and path == "/fapi/v1/algoOrder":
            calls["algo"] = calls.get("algo", 0) + 1
            return {"algoId": "111"}
        raise AssertionError(f"unexpected call {method} {path} {params}")
    return fake_signed


def _fake_pool_correlated():
    """BTCUSDT/ETHUSDT/SOLUSDT move in lockstep (identical series) ->
    pairwise correlation ~1.0, comfortably above any reasonable rho."""
    class _FakeConn:
        async def fetch(self, query, symbols, cutoff):
            base = np.linspace(100, 200, 40)
            return [{"symbol": s, "close": float(v)} for s in symbols for v in base]

    class _FakeAcquire:
        async def __aenter__(self):
            return _FakeConn()

        async def __aexit__(self, *a):
            return False

    class _FakePool:
        def acquire(self):
            return _FakeAcquire()

    return _FakePool()


def _fake_pool_uncorrelated():
    """Each symbol gets an independent random-ish walk -> near-zero
    pairwise correlation."""
    class _FakeConn:
        async def fetch(self, query, symbols, cutoff):
            rows = []
            for i, s in enumerate(symbols):
                seed = (i + 1) * 97
                series = 100 + np.sin(np.arange(40) * (seed % 7 + 1) * 0.3) * 10
                rows.extend({"symbol": s, "close": float(v)} for v in series)
            return rows

    class _FakeAcquire:
        async def __aenter__(self):
            return _FakeConn()

        async def __aexit__(self, *a):
            return False

    class _FakePool:
        def acquire(self):
            return _FakeAcquire()

    return _FakePool()


def test_no_governor_skips_the_check_entirely(monkeypatch):
    calls = {}
    monkeypatch.setattr(binance_mod, "send_signed_request", _fake_signed_happy_path(calls))
    session = _make_session(risk_governor=None)
    mgr, adapter = _make_mgr_adapter(monkeypatch, session)
    strat = _FakeStrategy(stop_loss=(1.0, 95.0))

    ok = _run_entry(adapter, strat, direction="long", ref_price=100.0)

    assert ok is True
    assert calls["entry"] == 1


def test_governor_without_correlation_cap_never_fetches_prices(monkeypatch):
    calls = {}
    monkeypatch.setattr(binance_mod, "send_signed_request", _fake_signed_happy_path(calls))

    def _boom(*a, **kw):
        raise AssertionError("get_pool must not be called — correlation_cap unset (opt-in)")
    monkeypatch.setattr(pr, "get_pool", _boom)

    gov = SessionRiskGovernor({})  # correlation_rho=None
    session = _make_session(risk_governor=gov)
    mgr, adapter = _make_mgr_adapter(monkeypatch, session)
    strat = _FakeStrategy(stop_loss=(1.0, 95.0))

    ok = _run_entry(adapter, strat, direction="long", ref_price=100.0)

    assert ok is True
    assert calls["entry"] == 1


def test_uncorrelated_entry_enters_normally(monkeypatch):
    calls = {}
    monkeypatch.setattr(binance_mod, "send_signed_request", _fake_signed_happy_path(calls))
    monkeypatch.setattr(pr, "get_pool", lambda: _fake_pool_uncorrelated())
    gov = SessionRiskGovernor({"correlation_cap": {"rho": 0.9, "max_cluster_exposure_pct": 0.4}})
    session = _make_session(
        risk_governor=gov,
        strategy_instances={BTC: _OpenSymbolStrategy(qty=10, entry_price=100.0)},
    )
    mgr, adapter = _make_mgr_adapter(monkeypatch, session)
    strat = _FakeStrategy(stop_loss=(1.0, 95.0))

    ok = _run_entry(adapter, strat, direction="long", ref_price=100.0)

    assert ok is True
    assert calls["entry"] == 1


def test_correlated_third_entry_vetoed_no_order_placed(monkeypatch):
    """Acceptance criterion: with two open BTC-correlated positions already
    at the cluster cap, a third correlated entry is vetoed — zero Binance
    order/algoOrder calls, local strategy state cleared (M-5-style)."""
    async def fake_signed(*args, **kwargs):
        raise AssertionError("no Binance call should happen — entry must be vetoed pre-order")
    monkeypatch.setattr(binance_mod, "send_signed_request", fake_signed)
    monkeypatch.setattr(pr, "get_pool", lambda: _fake_pool_correlated())

    gov = SessionRiskGovernor({"correlation_cap": {"rho": 0.8, "max_cluster_exposure_pct": 0.4}})
    session = _make_session(
        risk_governor=gov,
        strategy_instances={
            BTC: _OpenSymbolStrategy(qty=150, entry_price=100.0),  # 15,000 notional
            ETH: _OpenSymbolStrategy(qty=150, entry_price=100.0),  # 15,000 notional
        },
    )
    notified = _Notified()
    mgr, adapter = _make_mgr_adapter(monkeypatch, session, notified=notified)
    strat = _FakeStrategy(stop_loss=(1.0, 95.0))

    # candidate notional = qty 200 * ref_price 100 = 20,000
    # cluster = BTC(15k) + ETH(15k) + SOL(20k) = 50,000 / equity 100,000 = 50% > 40%
    ok = _run_entry(adapter, strat, direction="long", ref_price=100.0, qty=200.0)

    assert ok is False
    veto_logs = [
        c for c in notified.calls
        if c.get("event") == "log"
        and "correlation_concentration" in c.get("eventData", {}).get("message", "")
    ]
    assert len(veto_logs) == 1
    assert strat.buy is None and strat.stop_loss is None


def test_correlation_fetch_exception_fails_open(monkeypatch):
    calls = {}
    monkeypatch.setattr(binance_mod, "send_signed_request", _fake_signed_happy_path(calls))

    def _boom():
        raise RuntimeError("simulated TimescaleDB outage")
    monkeypatch.setattr(pr, "get_pool", _boom)

    gov = SessionRiskGovernor({"correlation_cap": {"rho": 0.8, "max_cluster_exposure_pct": 0.4}})
    session = _make_session(
        risk_governor=gov,
        strategy_instances={BTC: _OpenSymbolStrategy(qty=90, entry_price=100.0)},
    )
    mgr, adapter = _make_mgr_adapter(monkeypatch, session)
    strat = _FakeStrategy(stop_loss=(1.0, 95.0))

    ok = _run_entry(adapter, strat, direction="long", ref_price=100.0)

    assert ok is True  # fetch failure -> fail OPEN, entry proceeds
    assert calls["entry"] == 1
