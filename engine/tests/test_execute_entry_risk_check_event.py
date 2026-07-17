"""Plan 22 Step 22.3 regression: `LiveAdapter.execute_entry()`'s per-entry
`risk_check` event (resolved limits, computed sizing, minNotional resize)
and the 1.1x-inflation session-visible warning.

Same stub-injection approach as `test_execute_entry_portfolio_risk_and_liq_
buffer.py` / `test_kline_ws_url.py` — see those files' docstrings for why.

Run inside the container::

    docker exec enma_trading_platform-engine-1 pytest /app/tests/test_execute_entry_risk_check_event.py
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
        self.risk_pct = 0.02
        self.rrr = 2.0
        self.max_session_dd = 0.2
        self.max_portfolio_risk = 0.06
        self.liq_buffer_pct = 0.005
        from core.models.risk import DefaultRiskModel
        self.risk_model = DefaultRiskModel()


def _make_session():
    return {
        "open_positions": {},
        "pnl": 0.0, "strategy_name": "X", "api_key": "k", "api_secret": "s", "user_id": "",
        "trading_state": "active",
        "capital": 100_000.0,
        "risk_governor": None,
        "strategy_instances": {},
    }


class _Notified:
    def __init__(self):
        self.calls = []

    async def __call__(self, session_id, payload):
        self.calls.append(payload)


class _EventRecorder:
    def __init__(self):
        self.calls = []

    async def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return 1


@pytest.fixture(autouse=True)
def _stub_record_trade(monkeypatch):
    async def _noop_record_trade(*args, **kwargs):
        return None
    monkeypatch.setattr(lbm_module, "record_trade", _noop_record_trade)


def _run_entry(adapter, strat, **overrides):
    kwargs = dict(
        strategy=strat, symbol=SYM, direction="long", qty=1.0, ref_price=100.0,
        time_t=datetime.now(timezone.utc), index_t=0,
    )
    kwargs.update(overrides)
    return asyncio.get_event_loop().run_until_complete(adapter.execute_entry(**kwargs))


def _make_mgr_adapter(monkeypatch, session, notified=None):
    mgr = LiveBotManager()
    sid = "sess_risk_check"
    mgr.sessions[sid] = session
    monkeypatch.setattr(mgr, "_notify_node", notified or _Notified())
    return mgr, LiveAdapter(mgr, sid)


def _fake_signed_happy_path():
    async def fake_signed(method, path, api_key, api_secret, params=None, mode="testnet"):
        if method == "POST" and path == "/fapi/v1/order":
            return {"orderId": 1, "avgPrice": "100.0", "status": "FILLED"}
        if method == "POST" and path == "/fapi/v1/algoOrder":
            return {"algoId": "111"}
        raise AssertionError(f"unexpected call {method} {path} {params}")
    return fake_signed


def test_risk_check_event_appended_on_successful_entry(monkeypatch):
    monkeypatch.setattr(binance_mod, "send_signed_request", _fake_signed_happy_path())
    events = _EventRecorder()
    monkeypatch.setattr(lbm_module, "append_event", events)
    session = _make_session()
    mgr, adapter = _make_mgr_adapter(monkeypatch, session)
    strat = _FakeStrategy(stop_loss=(1.0, 95.0), take_profit=(1.0, 110.0))

    ok = _run_entry(adapter, strat, direction="long", ref_price=100.0)

    assert ok is True
    risk_check_calls = [c for c in events.calls if c.get("event_type") == "risk_check"]
    assert len(risk_check_calls) == 1
    payload = risk_check_calls[0]["payload"]
    assert payload["resolved_limits"]["risk_pct"] == 0.02
    assert payload["resolved_limits"]["max_portfolio_risk"] == 0.06
    assert payload["computed"]["direction"] == "long"
    assert payload["computed"]["sl_price"] == 95.0
    assert payload["computed"]["tp_price"] == 110.0
    assert payload["computed"]["final_qty"] > 0
    assert "qty_inflation_factor" in payload["computed"]


def test_risk_check_event_not_appended_when_entry_is_rejected(monkeypatch):
    """M-5 rejects an invalid SL before the order is ever placed — no
    risk_check snapshot for an entry that never actually happened."""
    async def fake_signed(*a, **kw):
        raise AssertionError("no Binance call should happen")
    monkeypatch.setattr(binance_mod, "send_signed_request", fake_signed)
    events = _EventRecorder()
    monkeypatch.setattr(lbm_module, "append_event", events)
    session = _make_session()
    mgr, adapter = _make_mgr_adapter(monkeypatch, session)
    # SL above ref for a long — invalid, M-5 rejects before qty/notional even matter.
    strat = _FakeStrategy(stop_loss=(1.0, 105.0))

    ok = _run_entry(adapter, strat, direction="long", ref_price=100.0)

    assert ok is False
    assert [c for c in events.calls if c.get("event_type") == "risk_check"] == []


def test_no_inflation_warning_when_qty_is_not_bumped(monkeypatch):
    monkeypatch.setattr(binance_mod, "send_signed_request", _fake_signed_happy_path())
    session = _make_session()
    mgr, adapter = _make_mgr_adapter(monkeypatch, session)
    notified = _Notified()
    monkeypatch.setattr(mgr, "_notify_node", notified)
    # Large qty, well above any minNotional floor — no bump expected.
    strat = _FakeStrategy(stop_loss=(1.0, 95.0))

    ok = _run_entry(adapter, strat, direction="long", ref_price=100.0, qty=100.0)

    assert ok is True
    inflation_warnings = [
        c for c in notified.calls
        if c.get("event") == "log" and "1.1x watch threshold" in c.get("eventData", {}).get("message", "")
    ]
    assert inflation_warnings == []


def test_inflation_warning_fires_past_1_point_1x(monkeypatch):
    """A qty just under the $20 (x reserve factor) minNotional floor forces
    clamp_and_round_qty to bump it to ~0.23 — chosen so the resulting ratio
    lands between 1.1x (this warning's threshold) and 1.3x (F-013's abort
    tolerance), so the entry still proceeds but with the warning firing."""
    monkeypatch.setattr(binance_mod, "send_signed_request", _fake_signed_happy_path())
    session = _make_session()
    mgr, adapter = _make_mgr_adapter(monkeypatch, session)
    notified = _Notified()
    monkeypatch.setattr(mgr, "_notify_node", notified)
    # entry=100, sl=95 -> stop_loss_pct=0.05 -> reserve_factor~1.105 ->
    # buffered_min_notional ~22.1 -> bumped qty ~0.23. 0.19 -> ratio ~1.21.
    strat = _FakeStrategy(stop_loss=(1.0, 95.0))

    ok = _run_entry(adapter, strat, direction="long", ref_price=100.0, qty=0.19)

    assert ok is True
    inflation_warnings = [
        c for c in notified.calls
        if c.get("event") == "log" and "1.1x watch threshold" in c.get("eventData", {}).get("message", "")
    ]
    assert len(inflation_warnings) == 1
