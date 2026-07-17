"""Plan 21 Step 21.4 (A-7) regression: `LiveBotManager._reconcile_exchange_state()`'s
naked-position detector/re-arm, added to reconcile Case 3 (both engine and
exchange agree a position is open).

Before this fix, nothing verified an open position still had a live
protective stop on the exchange. Restored orphans (Case 1 with no open
algo orders), TP/SL-placement 400s, and A-6 emergency-close-failure
survivors could all run naked indefinitely, silently. This mirrors
freqtrade's per-iteration missing-stoploss re-placement, with a bounded
retry count before giving up and force-closing for safety.

Drives the real `_reconcile_exchange_state` method directly (a proper
`LiveBotManager` method, not an embedded closure) against a stubbed
Binance signed-request layer.

Run inside the container::

    docker exec enma_trading_platform-engine-1 pytest /app/tests/test_reconcile_naked_position_rearm.py
"""
import asyncio

import pytest

import services.binance_testnet as binance_mod
import core.live_bot_manager as lbm_module
from core.live_bot_manager import LiveBotManager, _NAKED_POSITION_MAX_REARM_ATTEMPTS
from core.position import Position

SYM = "FAKEUSDT"
SID = "sess1"


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class _FakeExecutionModel:
    def exit_fee(self, strategy, qty, price):
        return abs(qty) * price * 0.0005


class _FakeStrategy:
    def __init__(self, position, stop_loss):
        self.position = position
        self.stop_loss = stop_loss
        self.take_profit = None
        self._pending_flip = None
        self.index = 0
        self.price = 100.0
        self.balance = 1000.0
        self.leverage = 1
        self.entry_tag = ""
        self.exit_tag = ""
        self.execution_model = _FakeExecutionModel()

    @property
    def is_long(self):
        return self.position is not None and self.position.type == "long"

    @property
    def is_short(self):
        return self.position is not None and self.position.type == "short"


def _session():
    return {
        "api_key": "k", "api_secret": "s",
        "open_positions": {SYM: {
            "algo_ids": {"sl": None, "tp": None},
            "timestamp": "2026-01-01T00:00:00+00:00",
        }},
        "pnl": 0.0, "strategy_name": "X", "user_id": "",
        "order_semaphores": {},
    }


def _position(entry=100.0, direction="long", qty=1.0):
    return Position(direction, qty, entry, leverage=1.0, isolated_wallet=entry * qty)


def _position_risk_response(symbol, amt, entry=100.0):
    return [{"symbol": symbol, "positionAmt": str(amt), "entryPrice": str(entry),
             "unRealizedProfit": "0", "markPrice": str(entry), "leverage": "1",
             "isolatedWallet": str(entry), "liquidationPrice": "0"}]


@pytest.fixture(autouse=True)
def _stub_side_effects(monkeypatch):
    async def _noop(*args, **kwargs):
        return 1
    monkeypatch.setattr(lbm_module, "append_event", _noop)

    async def _noop_notify(self, session_id, payload):
        return None
    monkeypatch.setattr(LiveBotManager, "_notify_node", _noop_notify)

    async def _noop_record_trade(*args, **kwargs):
        return None
    monkeypatch.setattr(lbm_module, "record_trade", _noop_record_trade)


def test_naked_position_gets_sl_rearmed(monkeypatch):
    """Position open on both sides, strategy wants a stop, but no live SL
    algo order exists on the exchange -> re-arm it."""
    calls = {"posted_sl": []}

    async def fake_signed(method, path, api_key, api_secret, params=None, mode="testnet"):
        if method == "GET" and path == "/fapi/v2/positionRisk":
            return _position_risk_response(SYM, 1.0)
        if method == "GET" and path == "/fapi/v1/openOrders":
            return []
        if method == "GET" and path == "/fapi/v1/openAlgoOrders":
            return []  # nothing resting — naked
        if method == "POST" and path == "/fapi/v1/algoOrder":
            calls["posted_sl"].append(params["triggerPrice"])
            return {"algoId": "777"}
        raise AssertionError(f"unexpected call {method} {path} {params}")

    monkeypatch.setattr(binance_mod, "send_signed_request", fake_signed)

    mgr = LiveBotManager()
    mgr.sessions[SID] = _session()
    strat = _FakeStrategy(_position(), stop_loss=(1.0, 95.0))

    _run(mgr._reconcile_exchange_state(SID, strat, SYM))

    assert len(calls["posted_sl"]) == 1
    assert mgr.sessions[SID]["open_positions"][SYM]["algo_ids"]["sl"] == "777"
    # Successful re-arm resets the failure counter.
    assert mgr.sessions[SID].get("_naked_position_rearm_attempts", {}).get(SYM) is None


def test_position_with_live_sl_is_left_alone(monkeypatch):
    """A live STOP_MARKET order already exists for the symbol -> no re-arm
    attempted at all."""
    async def fake_signed(method, path, api_key, api_secret, params=None, mode="testnet"):
        if method == "GET" and path == "/fapi/v2/positionRisk":
            return _position_risk_response(SYM, 1.0)
        if method == "GET" and path == "/fapi/v1/openOrders":
            return []
        if method == "GET" and path == "/fapi/v1/openAlgoOrders":
            return [{"algoId": "111", "clientAlgoId": "tpsl_abc_sl", "symbol": SYM,
                      "orderType": "STOP_MARKET", "orderStatus": "NEW", "triggerPrice": "95",
                      "quantity": "1", "side": "SELL", "createTime": 0}]
        if method == "POST" and path == "/fapi/v1/algoOrder":
            raise AssertionError("should not re-arm when a live SL already exists")
        raise AssertionError(f"unexpected call {method} {path} {params}")

    monkeypatch.setattr(binance_mod, "send_signed_request", fake_signed)

    mgr = LiveBotManager()
    mgr.sessions[SID] = _session()
    strat = _FakeStrategy(_position(), stop_loss=(1.0, 95.0))

    _run(mgr._reconcile_exchange_state(SID, strat, SYM))  # must not raise


def test_no_stop_loss_set_skips_naked_check_entirely(monkeypatch):
    """Strategy has no stop_loss configured at all -> the naked-position
    check doesn't apply (nothing to be "naked" relative to)."""
    async def fake_signed(method, path, api_key, api_secret, params=None, mode="testnet"):
        if method == "GET" and path == "/fapi/v2/positionRisk":
            return _position_risk_response(SYM, 1.0)
        if method == "GET" and path == "/fapi/v1/openOrders":
            return []
        if method == "GET" and path == "/fapi/v1/openAlgoOrders":
            return []
        if method == "POST" and path == "/fapi/v1/algoOrder":
            raise AssertionError("should not re-arm when strategy.stop_loss is None")
        raise AssertionError(f"unexpected call {method} {path} {params}")

    monkeypatch.setattr(binance_mod, "send_signed_request", fake_signed)

    mgr = LiveBotManager()
    mgr.sessions[SID] = _session()
    strat = _FakeStrategy(_position(), stop_loss=None)

    _run(mgr._reconcile_exchange_state(SID, strat, SYM))


def test_rearm_failure_increments_counter_without_force_closing_early(monkeypatch):
    """A single re-arm failure must not force-close — only after
    _NAKED_POSITION_MAX_REARM_ATTEMPTS consecutive failures."""
    close_calls = {"n": 0}

    async def fake_signed(method, path, api_key, api_secret, params=None, mode="testnet"):
        if method == "GET" and path == "/fapi/v2/positionRisk":
            return _position_risk_response(SYM, 1.0)
        if method == "GET" and path == "/fapi/v1/openOrders":
            return []
        if method == "GET" and path == "/fapi/v1/openAlgoOrders":
            return []
        if method == "POST" and path == "/fapi/v1/algoOrder":
            raise RuntimeError("simulated Binance rejection")
        if method == "POST" and path == "/fapi/v1/order":
            close_calls["n"] += 1
            return {"orderId": 1, "avgPrice": "100.0", "status": "FILLED"}
        raise AssertionError(f"unexpected call {method} {path} {params}")

    monkeypatch.setattr(binance_mod, "send_signed_request", fake_signed)

    mgr = LiveBotManager()
    mgr.sessions[SID] = _session()
    strat = _FakeStrategy(_position(), stop_loss=(1.0, 95.0))

    _run(mgr._reconcile_exchange_state(SID, strat, SYM))

    assert close_calls["n"] == 0  # not force-closed after just one failure
    assert mgr.sessions[SID]["_naked_position_rearm_attempts"][SYM] == 1


def test_rearm_failure_n_times_force_closes(monkeypatch):
    """After _NAKED_POSITION_MAX_REARM_ATTEMPTS consecutive failed re-arm
    attempts (simulated via N separate reconcile passes, matching how the
    real per-candle loop would call this repeatedly), force-close the
    position for safety rather than let it keep running naked."""
    close_calls = {"n": 0}

    async def fake_signed(method, path, api_key, api_secret, params=None, mode="testnet"):
        if method == "GET" and path == "/fapi/v2/positionRisk":
            # Once force-closed, report flat so a hypothetical extra pass
            # wouldn't try to re-close; not exercised here but keeps the
            # stub honest.
            return [] if close_calls["n"] > 0 else _position_risk_response(SYM, 1.0)
        if method == "GET" and path == "/fapi/v1/openOrders":
            return []
        if method == "GET" and path == "/fapi/v1/openAlgoOrders":
            return []
        if method == "POST" and path == "/fapi/v1/algoOrder":
            raise RuntimeError("simulated Binance rejection")
        if method == "POST" and path == "/fapi/v1/order":
            close_calls["n"] += 1
            return {"orderId": 1, "avgPrice": "100.0", "status": "FILLED"}
        raise AssertionError(f"unexpected call {method} {path} {params}")

    monkeypatch.setattr(binance_mod, "send_signed_request", fake_signed)

    mgr = LiveBotManager()
    mgr.sessions[SID] = _session()
    strat = _FakeStrategy(_position(), stop_loss=(1.0, 95.0))

    for _ in range(_NAKED_POSITION_MAX_REARM_ATTEMPTS):
        _run(mgr._reconcile_exchange_state(SID, strat, SYM))

    assert close_calls["n"] == 1
    # Counter reset after the force-close so a future new position on this
    # symbol doesn't inherit a stale failure count.
    assert mgr.sessions[SID]["_naked_position_rearm_attempts"].get(SYM) is None
