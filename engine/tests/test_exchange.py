"""Plan 6 Step 6.2 (ENG-4): contract tests for the `Exchange` abstraction —
`BinanceFuturesTestnet`/`BinanceFuturesMainnet` must both route every method
to the correct Binance endpoint/HTTP method and their OWN `mode`, never a
hardcoded literal. Not wired to any existing call site yet (see
`exchange.py`'s own module docstring) — this only proves the interface
itself is correct and that both implementations satisfy the same contract.

Run inside the container::

    docker exec enma_trading_platform-engine-1 pytest /app/tests/test_exchange.py
"""
import asyncio

import pytest

import services.binance_testnet as binance_mod
from core.exchange import BinanceFuturesTestnet, BinanceFuturesMainnet


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


BOTH = [BinanceFuturesTestnet, BinanceFuturesMainnet]


def _capture_signed(monkeypatch, return_value=None):
    calls = []

    async def fake_signed(method, path, api_key, api_secret, params=None, mode="testnet"):
        calls.append({"method": method, "path": path, "api_key": api_key,
                       "api_secret": api_secret, "params": params, "mode": mode})
        return return_value

    monkeypatch.setattr(binance_mod, "send_signed_request", fake_signed)
    return calls


# ── Identity ─────────────────────────────────────────────────────────────

def test_testnet_and_mainnet_have_distinct_identity():
    testnet = BinanceFuturesTestnet()
    mainnet = BinanceFuturesMainnet()

    assert testnet.mode == "testnet"
    assert mainnet.mode == "mainnet"
    assert testnet.name != mainnet.name
    assert testnet.user_data_ws_base != mainnet.user_data_ws_base


@pytest.mark.parametrize("exchange_cls", BOTH)
def test_user_data_ws_url_appends_listen_key(exchange_cls):
    exchange = exchange_cls()
    url = exchange.user_data_ws_url("abc123")
    assert url == f"{exchange.user_data_ws_base}/abc123"


# ── Every method routes to the right endpoint + this instance's own mode ──

@pytest.mark.parametrize("exchange_cls", BOTH)
def test_place_order_routes_correctly(monkeypatch, exchange_cls):
    calls = _capture_signed(monkeypatch, return_value={"orderId": 1})
    exchange = exchange_cls()

    result = _run(exchange.place_order("k", "s", {"symbol": "BTCUSDT", "side": "BUY"}))

    assert result == {"orderId": 1}
    assert calls == [{"method": "POST", "path": "/fapi/v1/order", "api_key": "k",
                       "api_secret": "s", "params": {"symbol": "BTCUSDT", "side": "BUY"},
                       "mode": exchange.mode}]


@pytest.mark.parametrize("exchange_cls", BOTH)
def test_cancel_order_routes_correctly(monkeypatch, exchange_cls):
    calls = _capture_signed(monkeypatch)
    exchange = exchange_cls()

    _run(exchange.cancel_order("k", "s", {"symbol": "BTCUSDT", "orderId": 1}))

    assert calls[0]["method"] == "DELETE"
    assert calls[0]["path"] == "/fapi/v1/order"
    assert calls[0]["mode"] == exchange.mode


@pytest.mark.parametrize("exchange_cls", BOTH)
def test_query_order_routes_correctly(monkeypatch, exchange_cls):
    calls = _capture_signed(monkeypatch)
    exchange = exchange_cls()

    _run(exchange.query_order("k", "s", {"symbol": "BTCUSDT", "orderId": 1}))

    assert calls[0]["method"] == "GET"
    assert calls[0]["path"] == "/fapi/v1/order"
    assert calls[0]["mode"] == exchange.mode


@pytest.mark.parametrize("exchange_cls", BOTH)
def test_algo_order_place_cancel_query_route_correctly(monkeypatch, exchange_cls):
    calls = _capture_signed(monkeypatch)
    exchange = exchange_cls()

    _run(exchange.place_algo_order("k", "s", {"symbol": "BTCUSDT"}))
    _run(exchange.cancel_algo_order("k", "s", {"symbol": "BTCUSDT", "algoId": "1"}))
    _run(exchange.query_open_algo_orders("k", "s", {"symbol": "BTCUSDT"}))

    assert [c["method"] for c in calls] == ["POST", "DELETE", "GET"]
    assert all(c["path"] in ("/fapi/v1/algoOrder", "/fapi/v1/openAlgoOrders") for c in calls)
    assert calls[0]["path"] == "/fapi/v1/algoOrder"
    assert calls[1]["path"] == "/fapi/v1/algoOrder"
    assert calls[2]["path"] == "/fapi/v1/openAlgoOrders"
    assert all(c["mode"] == exchange.mode for c in calls)


@pytest.mark.parametrize("exchange_cls", BOTH)
def test_query_open_orders_position_risk_account_user_trades_route_correctly(monkeypatch, exchange_cls):
    calls = _capture_signed(monkeypatch)
    exchange = exchange_cls()

    _run(exchange.query_open_orders("k", "s", {"symbol": "BTCUSDT"}))
    _run(exchange.query_position_risk("k", "s", {"symbol": "BTCUSDT"}))
    _run(exchange.query_account("k", "s"))
    _run(exchange.query_user_trades("k", "s", {"symbol": "BTCUSDT", "limit": 20}))

    paths = [c["path"] for c in calls]
    assert paths == ["/fapi/v1/openOrders", "/fapi/v2/positionRisk", "/fapi/v2/account", "/fapi/v1/userTrades"]
    assert all(c["method"] == "GET" for c in calls)
    assert all(c["mode"] == exchange.mode for c in calls)


@pytest.mark.parametrize("exchange_cls", BOTH)
def test_set_leverage_and_margin_type_route_correctly(monkeypatch, exchange_cls):
    calls = _capture_signed(monkeypatch)
    exchange = exchange_cls()

    _run(exchange.set_leverage("k", "s", {"symbol": "BTCUSDT", "leverage": 10}))
    _run(exchange.set_margin_type("k", "s", {"symbol": "BTCUSDT", "marginType": "ISOLATED"}))

    assert calls[0]["path"] == "/fapi/v1/leverage"
    assert calls[1]["path"] == "/fapi/v1/marginType"
    assert all(c["method"] == "POST" for c in calls)
    assert all(c["mode"] == exchange.mode for c in calls)


@pytest.mark.parametrize("exchange_cls", BOTH)
def test_listen_key_lifecycle_routes_correctly(monkeypatch, exchange_cls):
    calls = _capture_signed(monkeypatch, return_value={"listenKey": "the-key"})
    exchange = exchange_cls()

    key = _run(exchange.create_listen_key("k", "s"))
    _run(exchange.keepalive_listen_key("k", "s"))
    _run(exchange.close_listen_key("k", "s"))

    assert key == "the-key"
    assert [(c["method"], c["path"]) for c in calls] == [
        ("POST", "/fapi/v1/listenKey"),
        ("PUT", "/fapi/v1/listenKey"),
        ("DELETE", "/fapi/v1/listenKey"),
    ]
    assert all(c["mode"] == exchange.mode for c in calls)


@pytest.mark.parametrize("exchange_cls", BOTH)
def test_no_call_site_can_ever_override_mode(monkeypatch, exchange_cls):
    """The whole point of the abstraction (ENG-4): callers never pass mode=
    themselves — it's impossible to accidentally cross-wire a testnet
    session onto a mainnet call or vice versa via a stray literal."""
    calls = _capture_signed(monkeypatch)
    exchange = exchange_cls()

    _run(exchange.place_order("k", "s", {"symbol": "BTCUSDT"}))

    assert calls[0]["mode"] == exchange.mode
