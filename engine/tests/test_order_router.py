"""`OrderRouter` unit tests (Plan 6 Step 6.1, ENG-1 — the fifth and final
`LiveBotManager`/`LiveAdapter` collaborator extraction).

Deliberately NOT a re-test of execute_entry/execute_reduce/execute_exit/
execute_flip BEHAVIOR — that's already covered end-to-end by the 20+
existing `test_execute_entry_*`/`test_execute_flip_*`/`test_entry_
unconfirmed_fill.py`/`test_live_fill_booking.py` etc. test files, which now
exercise the same code via `LiveAdapter.execute_*` calling through
`self._order_router` under the hood (golden-master byte-identical
confirmation for this extraction lives in the plan doc). This file's job is
to verify the extraction seam itself: the free helper functions (moved
verbatim from `live_bot_manager.py`) and `OrderRouter`'s own place/confirm
methods build the exact request shape and confirmation ladder the old
inline code did.

Run inside the container::

    docker exec enma_trading_platform-engine-1 pytest /app/tests/test_order_router.py
"""
import asyncio

import httpx
import pytest

import services.binance_testnet as binance_mod
from core.order_router import (
    OrderRouter,
    fmt_num,
    make_client_id,
    binance_error_detail,
    extract_fill_price,
    query_real_fill_price,
    uuid4_hex8,
)
from core.live_bot_manager import LiveAdapter, LiveBotManager


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ── free helper functions ────────────────────────────────────────────────

def test_fmt_num_strips_trailing_zeros():
    assert fmt_num(1.500000) == "1.5"
    assert fmt_num(1.0) == "1"
    assert fmt_num(0.00012345) == "0.00012345"


def test_fmt_num_zero_stays_zero():
    assert fmt_num(0.0) == "0"


def test_make_client_id_stays_under_binance_limit_for_long_symbols():
    cid = make_client_id("sessionid12345678", "KAITOUSDC", suffix="_emrg")
    assert len(cid) < 36
    assert cid.startswith("enma_")
    assert cid.endswith("_emrg")


def test_make_client_id_unique_across_calls():
    a = make_client_id("sess1", "BTCUSDT")
    b = make_client_id("sess1", "BTCUSDT")
    assert a != b


def test_uuid4_hex8_length():
    assert len(uuid4_hex8()) == 8


def test_extract_fill_price_real_value():
    assert extract_fill_price({"avgPrice": "100.50"}) == pytest.approx(100.50)


def test_extract_fill_price_zero_string_is_none():
    """The F7 regression: a truthy-but-zero avgPrice string must not be
    treated as a real fill."""
    assert extract_fill_price({"avgPrice": "0.00000000"}) is None


def test_extract_fill_price_missing_key_is_none():
    assert extract_fill_price({}) is None


def test_binance_error_detail_extracts_code_and_msg(monkeypatch):
    request = httpx.Request("POST", "https://testnet.binancefuture.com/fapi/v1/order")
    response = httpx.Response(400, json={"code": -4164, "msg": "Order's notional must be no smaller than 5"}, request=request)
    exc = httpx.HTTPStatusError("Bad Request", request=request, response=response)
    assert binance_error_detail(exc) == "-4164 Order's notional must be no smaller than 5"


def test_binance_error_detail_non_http_exception_falls_back_to_str():
    assert binance_error_detail(RuntimeError("boom")) == "boom"


def test_query_real_fill_price_uses_origclientorderid(monkeypatch):
    calls = []

    async def fake_signed(method, path, api_key, api_secret, params=None, mode="testnet"):
        calls.append((method, path, params, mode))
        return {"avgPrice": "99.25"}
    monkeypatch.setattr(binance_mod, "send_signed_request", fake_signed)

    price = _run(query_real_fill_price("k", "s", "BTCUSDT", "cid123"))
    assert price == pytest.approx(99.25)
    assert calls == [("GET", "/fapi/v1/order", {"symbol": "BTCUSDT", "origClientOrderId": "cid123"}, "testnet")]


def test_query_real_fill_price_swallows_exceptions(monkeypatch):
    async def fake_signed(*args, **kwargs):
        raise RuntimeError("network down")
    monkeypatch.setattr(binance_mod, "send_signed_request", fake_signed)

    assert _run(query_real_fill_price("k", "s", "BTCUSDT", "cid123")) is None


# ── OrderRouter ──────────────────────────────────────────────────────────

def test_place_market_order_builds_expected_params(monkeypatch):
    calls = []

    async def fake_signed(method, path, api_key, api_secret, params=None, mode="testnet"):
        calls.append((method, path, api_key, api_secret, params, mode))
        return {"orderId": 1, "avgPrice": "100.0"}
    monkeypatch.setattr(binance_mod, "send_signed_request", fake_signed)

    result = _run(OrderRouter.place_market_order("k", "s", "BTCUSDT", "BUY", 1.23456789, "cid1"))

    assert result == {"orderId": 1, "avgPrice": "100.0"}
    method, path, api_key, api_secret, params, mode = calls[0]
    assert (method, path, api_key, api_secret, mode) == ("POST", "/fapi/v1/order", "k", "s", "testnet")
    assert params == {
        "symbol": "BTCUSDT", "side": "BUY", "type": "MARKET",
        "quantity": "1.23456789", "newOrderRespType": "RESULT",
        "newClientOrderId": "cid1",
    }


def test_place_market_order_reduce_only_adds_flag(monkeypatch):
    calls = []

    async def fake_signed(method, path, api_key, api_secret, params=None, mode="testnet"):
        calls.append(params)
        return {}
    monkeypatch.setattr(binance_mod, "send_signed_request", fake_signed)

    _run(OrderRouter.place_market_order("k", "s", "BTCUSDT", "SELL", 1.0, "cid2", reduce_only=True))
    assert calls[0]["reduceOnly"] == "true"


def test_place_market_order_omits_reduce_only_by_default(monkeypatch):
    calls = []

    async def fake_signed(method, path, api_key, api_secret, params=None, mode="testnet"):
        calls.append(params)
        return {}
    monkeypatch.setattr(binance_mod, "send_signed_request", fake_signed)

    _run(OrderRouter.place_market_order("k", "s", "BTCUSDT", "BUY", 1.0, "cid3"))
    assert "reduceOnly" not in calls[0]


def test_place_algo_order_builds_conditional_params(monkeypatch):
    calls = []

    async def fake_signed(method, path, api_key, api_secret, params=None, mode="testnet"):
        calls.append((method, path, params, mode))
        return {"algoId": 42}
    monkeypatch.setattr(binance_mod, "send_signed_request", fake_signed)

    result = _run(OrderRouter.place_algo_order("k", "s", "BTCUSDT", "SELL", "STOP_MARKET", 95.5, "tpsl_abc_sl"))

    assert result == {"algoId": 42}
    method, path, params, mode = calls[0]
    assert (method, path, mode) == ("POST", "/fapi/v1/algoOrder", "testnet")
    assert params == {
        "algoType": "CONDITIONAL", "symbol": "BTCUSDT", "side": "SELL",
        "type": "STOP_MARKET", "triggerPrice": "95.5", "workingType": "MARK_PRICE",
        "closePosition": "true", "clientAlgoId": "tpsl_abc_sl",
    }


def test_confirm_fill_trusts_real_avgprice_without_requery(monkeypatch):
    async def fake_signed(*args, **kwargs):
        pytest.fail("must not re-query when avgPrice is already real")
    monkeypatch.setattr(binance_mod, "send_signed_request", fake_signed)

    price = _run(OrderRouter.confirm_fill({"avgPrice": "101.0"}, "k", "s", "BTCUSDT", "cid"))
    assert price == pytest.approx(101.0)


def test_confirm_fill_requeries_on_zero_avgprice(monkeypatch):
    async def fake_signed(method, path, api_key, api_secret, params=None, mode="testnet"):
        assert method == "GET"
        return {"avgPrice": "102.0"}
    monkeypatch.setattr(binance_mod, "send_signed_request", fake_signed)

    price = _run(OrderRouter.confirm_fill({"avgPrice": "0.00000000"}, "k", "s", "BTCUSDT", "cid"))
    assert price == pytest.approx(102.0)


def test_confirm_fill_returns_none_when_unconfirmed(monkeypatch):
    async def fake_signed(*args, **kwargs):
        return {"avgPrice": "0.00000000"}
    monkeypatch.setattr(binance_mod, "send_signed_request", fake_signed)

    assert _run(OrderRouter.confirm_fill({}, "k", "s", "BTCUSDT", "cid")) is None


# ── LiveAdapter wiring ───────────────────────────────────────────────────

def test_live_adapter_holds_an_order_router_instance():
    mgr = LiveBotManager()
    sid = "sess_order_router_wiring"
    mgr.sessions[sid] = {}
    adapter = LiveAdapter(mgr, sid)
    assert isinstance(adapter._order_router, OrderRouter)


def test_each_adapter_gets_its_own_order_router_but_same_type():
    """OrderRouter is stateless — no shared-instance requirement, just
    confirming construction never raises and each adapter is independently
    usable (unlike registry/notifier/reconciler, which must be the SAME
    instance as the manager's)."""
    mgr = LiveBotManager()
    sid = "sess_order_router_wiring_2"
    mgr.sessions[sid] = {}
    a1 = LiveAdapter(mgr, sid)
    a2 = LiveAdapter(mgr, sid)
    assert isinstance(a1._order_router, OrderRouter)
    assert isinstance(a2._order_router, OrderRouter)
