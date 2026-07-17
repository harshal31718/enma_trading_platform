"""Plan 22 Step 22.2 regression: `LiveAdapter.execute_entry()`'s two new
pre-trade vetoes — the true cross-symbol portfolio open-risk budget (routed
through `SessionRiskGovernor.check_portfolio_risk`, superseding
`DefaultPortfolioModel.construct()`'s structurally-per-symbol
`max_portfolio_risk` check) and the liquidation-buffer guard
(`RiskModel.respects_liq_buffer`, previously decorative — zero pipeline call
sites per the Plan 21 audit).

`core/live_bot_manager.py` has a heavy TA-Lib/numpy/motor/asyncpg/websockets
dependency chain that doesn't fully install in this dev sandbox. Rather than
falling back to `ast.parse`-only, this file stubs the three genuinely
missing third-party modules (`websockets`, `motor`, `asyncpg`) just enough to
satisfy import-time requirements, then drives the REAL
`LiveAdapter.execute_entry` against a stubbed Binance signed-request layer —
same harness shape as `test_execute_entry_bracket_safety.py`. Inside the
actual container (where these packages are genuinely installed) the stubs
never engage — see `_ensure_importable()` below.

Run inside the container::

    docker exec enma_trading_platform-engine-1 pytest /app/tests/test_execute_entry_portfolio_risk_and_liq_buffer.py
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

import services.binance_testnet as binance_mod
import core.live_bot_manager as lbm_module
from core.live_bot_manager import LiveBotManager, LiveAdapter
from core.models.governor import SessionRiskGovernor
from core.position import Position

SYM = "FAKEUSDT"
OTHER_SYM = "OTHERUSDT"


class _FakeExecutionModel:
    def exit_fee(self, strategy, qty, price):
        return abs(qty) * price * 0.0005


class _FakeStrategy:
    def __init__(self, stop_loss=None, take_profit=None, leverage=1, position=None):
        self.position = position
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


def _make_session(risk_governor=None, strategy_instances=None):
    return {
        "open_positions": {},
        "pnl": 0.0, "strategy_name": "X", "api_key": "k", "api_secret": "s", "user_id": "",
        "trading_state": "active",
        "capital": 100_000.0,
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


def _run_entry(adapter, strat, **overrides):
    kwargs = dict(
        strategy=strat, symbol=SYM, direction="long", qty=1.0, ref_price=100.0,
        time_t=datetime.now(timezone.utc), index_t=0,
    )
    kwargs.update(overrides)
    return asyncio.get_event_loop().run_until_complete(adapter.execute_entry(**kwargs))


def _make_mgr_adapter(monkeypatch, session, notified=None):
    mgr = LiveBotManager()
    sid = "sess_portfolio_risk"
    mgr.sessions[sid] = session
    monkeypatch.setattr(mgr, "_notify_node", notified or _Notified())
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


# ── Portfolio open-risk budget (22.2) ───────────────────────────────────────

def test_no_governor_skips_the_new_checks_entirely(monkeypatch):
    """session["risk_governor"] is None (e.g. an older session, or 22.1
    genuinely disabled) — execute_entry must behave exactly as it did before
    22.2 existed, never touching the new code paths."""
    calls = {}
    monkeypatch.setattr(binance_mod, "send_signed_request", _fake_signed_happy_path(calls))
    session = _make_session(risk_governor=None)
    mgr, adapter = _make_mgr_adapter(monkeypatch, session)
    strat = _FakeStrategy(stop_loss=(1.0, 95.0))

    ok = _run_entry(adapter, strat, direction="long", ref_price=100.0)

    assert ok is True
    assert calls["entry"] == 1


def test_portfolio_risk_within_budget_enters_normally(monkeypatch):
    calls = {}
    monkeypatch.setattr(binance_mod, "send_signed_request", _fake_signed_happy_path(calls))
    gov = SessionRiskGovernor({"max_portfolio_risk": 0.06})
    session = _make_session(risk_governor=gov)
    mgr, adapter = _make_mgr_adapter(monkeypatch, session)
    # risk = |100-95|*1 = 5; equity = capital 100_000 -> 0.005% << 6% budget.
    strat = _FakeStrategy(stop_loss=(1.0, 95.0))

    ok = _run_entry(adapter, strat, direction="long", ref_price=100.0)

    assert ok is True
    assert calls["entry"] == 1


def test_portfolio_risk_past_budget_vetoes_no_order_placed(monkeypatch):
    async def fake_signed(*args, **kwargs):
        raise AssertionError("no Binance call should happen — entry must be vetoed pre-order")
    monkeypatch.setattr(binance_mod, "send_signed_request", fake_signed)

    gov = SessionRiskGovernor({"max_portfolio_risk": 0.06})
    session = _make_session(risk_governor=gov)
    session["capital"] = 100.0  # small equity so the candidate risk alone blows the budget
    mgr, adapter = _make_mgr_adapter(monkeypatch, session)
    notified = _Notified()
    monkeypatch.setattr(mgr, "_notify_node", notified)
    # risk = |100-50|*1 = 50; equity=100 -> 50% >> 6% budget.
    strat = _FakeStrategy(stop_loss=(1.0, 50.0))

    ok = _run_entry(adapter, strat, direction="long", ref_price=100.0)

    assert ok is False
    assert strat.position is None
    assert strat.buy is None
    assert strat.stop_loss is None
    assert strat.take_profit is None
    warn_logs = [
        c for c in notified.calls
        if c.get("event") == "log" and "portfolio open-risk budget" in c.get("eventData", {}).get("message", "")
    ]
    assert len(warn_logs) == 1


def test_portfolio_risk_names_contributing_symbols_in_the_veto_log(monkeypatch):
    """Acceptance criterion: the veto log names the contributing symbols —
    an already-open OTHERUSDT position must appear in the message."""
    async def fake_signed(*args, **kwargs):
        raise AssertionError("no Binance call should happen — entry must be vetoed pre-order")
    monkeypatch.setattr(binance_mod, "send_signed_request", fake_signed)

    other_strat = _FakeStrategy(stop_loss=(1.0, 190.0), position=Position("long", 1.0, 200.0))
    gov = SessionRiskGovernor({"max_portfolio_risk": 0.06})
    session = _make_session(risk_governor=gov, strategy_instances={OTHER_SYM: other_strat})
    # OTHERUSDT risk = |200-190|*1 = 10; candidate risk = |100-50|*1 = 50;
    # total 60 / equity 500 = 12% > 6% budget.
    session["capital"] = 500.0
    mgr, adapter = _make_mgr_adapter(monkeypatch, session)
    notified = _Notified()
    monkeypatch.setattr(mgr, "_notify_node", notified)
    strat = _FakeStrategy(stop_loss=(1.0, 50.0))

    ok = _run_entry(adapter, strat, direction="long", ref_price=100.0)

    assert ok is False
    warn_logs = [
        c for c in notified.calls
        if c.get("event") == "log" and "portfolio open-risk budget" in c.get("eventData", {}).get("message", "")
    ]
    assert len(warn_logs) == 1
    assert OTHER_SYM in warn_logs[0]["eventData"]["message"]


def test_portfolio_risk_disabled_via_zero_never_vetoes(monkeypatch):
    calls = {}
    monkeypatch.setattr(binance_mod, "send_signed_request", _fake_signed_happy_path(calls))
    gov = SessionRiskGovernor({"max_portfolio_risk": 0.0})
    session = _make_session(risk_governor=gov)
    session["capital"] = 1.0  # would blow any positive budget
    mgr, adapter = _make_mgr_adapter(monkeypatch, session)
    strat = _FakeStrategy(stop_loss=(1.0, 50.0))

    ok = _run_entry(adapter, strat, direction="long", ref_price=100.0)

    assert ok is True
    assert calls["entry"] == 1


# ── Liquidation-buffer guard (22.2) ─────────────────────────────────────────

def test_stop_inside_liquidation_buffer_vetoes_with_liq_price_in_log(monkeypatch):
    async def fake_signed(*args, **kwargs):
        raise AssertionError("no Binance call should happen — entry must be vetoed pre-order")
    monkeypatch.setattr(binance_mod, "send_signed_request", fake_signed)

    gov = SessionRiskGovernor({"max_portfolio_risk": 0.99})  # isolate the liq-buffer path
    session = _make_session(risk_governor=gov)
    mgr, adapter = _make_mgr_adapter(monkeypatch, session)
    notified = _Notified()
    monkeypatch.setattr(mgr, "_notify_node", notified)
    # entry=100, leverage=10 -> liq ~= 90.36, safe SL floor ~= 90.86 (0.5%
    # buffer). SL=90 is on the correct side of entry (M-5 passes) but still
    # inside the liquidation buffer.
    strat = _FakeStrategy(stop_loss=(1.0, 90.0), leverage=10)

    ok = _run_entry(adapter, strat, direction="long", ref_price=100.0)

    assert ok is False
    assert strat.position is None
    assert strat.stop_loss is None
    warn_logs = [
        c for c in notified.calls
        if c.get("event") == "log" and "liquidation" in c.get("eventData", {}).get("message", "").lower()
    ]
    assert len(warn_logs) == 1
    assert "liq" in warn_logs[0]["eventData"]["message"].lower()


def test_stop_outside_liquidation_buffer_enters_normally(monkeypatch):
    calls = {}
    monkeypatch.setattr(binance_mod, "send_signed_request", _fake_signed_happy_path(calls))
    gov = SessionRiskGovernor({"max_portfolio_risk": 0.99})
    session = _make_session(risk_governor=gov)
    mgr, adapter = _make_mgr_adapter(monkeypatch, session)
    # SL=95 is comfortably clear of the ~90.86 floor at leverage=10.
    strat = _FakeStrategy(stop_loss=(1.0, 95.0), leverage=10)

    ok = _run_entry(adapter, strat, direction="long", ref_price=100.0)

    assert ok is True
    assert calls["entry"] == 1


def test_liq_buffer_check_exception_fails_open_and_still_enters(monkeypatch):
    """An unexpected exception computing the liq-buffer check must never
    crash/block the whole entry pipeline — logs a warning and proceeds,
    unlike an actual computed violation (which vetoes)."""
    calls = {}
    monkeypatch.setattr(binance_mod, "send_signed_request", _fake_signed_happy_path(calls))
    gov = SessionRiskGovernor({"max_portfolio_risk": 0.99})
    session = _make_session(risk_governor=gov)
    mgr, adapter = _make_mgr_adapter(monkeypatch, session)
    strat = _FakeStrategy(stop_loss=(1.0, 95.0), leverage=10)

    def _raising_respects_liq_buffer(*a, **kw):
        raise RuntimeError("simulated unexpected failure")
    monkeypatch.setattr(strat.risk_model, "respects_liq_buffer", _raising_respects_liq_buffer)

    ok = _run_entry(adapter, strat, direction="long", ref_price=100.0)

    assert ok is True
    assert calls["entry"] == 1
