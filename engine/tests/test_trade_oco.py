"""Unit tests for the three new trade endpoints:
  POST /trade/order/oco_futures
  GET  /trade/order
  DELETE /trade/all-orders

The test module builds a minimal FastAPI app directly from the trade router,
bypassing the lifespan and API-key middleware that live in main.py.
send_signed_request is patched so no real Binance calls are made.
"""

import re
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.trade import router

# ── Test app (no lifespan, no API-key middleware) ──────────────────────────────

app = FastAPI()
app.include_router(router, prefix="/trade")

FAKE_CREDS = {
    "X-Binance-API-Key": "test_key",
    "X-Binance-API-Secret": "test_secret",
}

client = TestClient(app)

# ── Helpers ───────────────────────────────────────────────────────────────────

OCO_ID_RE = re.compile(r"^oco_[0-9a-f]{8}_$")


# ── POST /trade/order/oco_futures ─────────────────────────────────────────────


def _sl_response(client_order_id: str) -> dict:
    return {
        "orderId": 111111,
        "symbol": "BTCUSDT",
        "status": "NEW",
        "clientOrderId": client_order_id,
        "type": "STOP_MARKET",
    }


def _tp_response(client_order_id: str) -> dict:
    return {
        "orderId": 222222,
        "symbol": "BTCUSDT",
        "status": "NEW",
        "clientOrderId": client_order_id,
        "type": "TAKE_PROFIT_MARKET",
    }


@patch("routers.trade.send_signed_request", new_callable=AsyncMock)
def test_place_oco_futures_buy(mock_req):
    """BUY OCO: SL below market, TP above market."""
    # First call → SL order, second call → TP order
    mock_req.side_effect = lambda method, path, key, secret, params=None: (
        _sl_response(params["newClientOrderId"])
        if params.get("type") == "STOP_MARKET"
        else _tp_response(params["newClientOrderId"])
    )

    resp = client.post(
        "/trade/order/oco_futures",
        json={
            "symbol": "BTC-USDT",
            "side": "BUY",
            "quantity": 0.01,
            "stopPrice": 60000.00,
            "takeProfitPrice": 70000.00,
        },
        headers=FAKE_CREDS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True

    data = body["data"]
    oco_id = data["ocoId"]
    assert OCO_ID_RE.match(oco_id), f"ocoId format wrong: {oco_id!r}"

    orders = data["orders"]
    assert len(orders) == 2

    sl = next(o for o in orders if o["type"] == "STOP_MARKET")
    tp = next(o for o in orders if o["type"] == "TAKE_PROFIT_MARKET")

    assert sl["clientOrderId"] == f"{oco_id}sl"
    assert tp["clientOrderId"] == f"{oco_id}tp"
    assert sl["orderId"] == 111111
    assert tp["orderId"] == 222222


@patch("routers.trade.send_signed_request", new_callable=AsyncMock)
def test_place_oco_futures_sell(mock_req):
    """SELL OCO: TP below market, SL above market."""
    mock_req.side_effect = lambda method, path, key, secret, params=None: (
        _sl_response(params["newClientOrderId"])
        if params.get("type") == "STOP_MARKET"
        else _tp_response(params["newClientOrderId"])
    )

    resp = client.post(
        "/trade/order/oco_futures",
        json={
            "symbol": "BTC-USDT",
            "side": "SELL",
            "quantity": 0.005,
            "stopPrice": 70000.00,
            "takeProfitPrice": 60000.00,
        },
        headers=FAKE_CREDS,
    )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert OCO_ID_RE.match(data["ocoId"])
    assert len(data["orders"]) == 2


@patch("routers.trade.send_signed_request", new_callable=AsyncMock)
def test_place_oco_futures_binance_error(mock_req):
    """Engine propagates Binance error as HTTP 400."""
    import httpx

    mock_resp = MagicMock()
    mock_resp.status_code = 400
    mock_resp.json.return_value = {"code": -2010, "msg": "Account has insufficient balance"}
    mock_req.side_effect = httpx.HTTPStatusError(
        "400", request=AsyncMock(), response=mock_resp
    )

    resp = client.post(
        "/trade/order/oco_futures",
        json={
            "symbol": "BTC-USDT",
            "side": "BUY",
            "quantity": 0.01,
            "stopPrice": 60000,
            "takeProfitPrice": 70000,
        },
        headers=FAKE_CREDS,
    )

    assert resp.status_code == 400
    assert "insufficient balance" in resp.json()["detail"].lower()


@patch("routers.trade.send_signed_request", new_callable=AsyncMock)
def test_place_oco_unique_oco_ids(mock_req):
    """Each OCO call generates a distinct ocoId."""
    call_count = {"n": 0}

    def side_effect(method, path, key, secret, params=None):
        call_count["n"] += 1
        return {
            "orderId": call_count["n"],
            "clientOrderId": params.get("newClientOrderId", ""),
        }

    mock_req.side_effect = side_effect

    payload = {
        "symbol": "BTC-USDT",
        "side": "BUY",
        "quantity": 0.01,
        "stopPrice": 60000,
        "takeProfitPrice": 70000,
    }

    r1 = client.post("/trade/order/oco_futures", json=payload, headers=FAKE_CREDS)
    r2 = client.post("/trade/order/oco_futures", json=payload, headers=FAKE_CREDS)

    id1 = r1.json()["data"]["ocoId"]
    id2 = r2.json()["data"]["ocoId"]
    assert id1 != id2, "Two OCO submissions must produce different ocoIds"


@patch("routers.trade.send_signed_request", new_callable=AsyncMock)
def test_place_oco_clientorderid_format(mock_req):
    """clientOrderId for SL must end with 'sl', TP must end with 'tp'."""
    captured = {}

    def side_effect(method, path, key, secret, params=None):
        order_type = params.get("type")
        cid = params.get("newClientOrderId", "")
        captured[order_type] = cid
        return {"orderId": 1, "clientOrderId": cid}

    mock_req.side_effect = side_effect

    client.post(
        "/trade/order/oco_futures",
        json={
            "symbol": "BTC-USDT",
            "side": "BUY",
            "quantity": 0.01,
            "stopPrice": 60000,
            "takeProfitPrice": 70000,
        },
        headers=FAKE_CREDS,
    )

    assert captured["STOP_MARKET"].endswith("sl")
    assert captured["TAKE_PROFIT_MARKET"].endswith("tp")
    # Both share the same oco_ prefix
    assert captured["STOP_MARKET"][:-2] == captured["TAKE_PROFIT_MARKET"][:-2]


# ── GET /trade/order ──────────────────────────────────────────────────────────


@patch("routers.trade.send_signed_request", new_callable=AsyncMock)
def test_get_order_status(mock_req):
    mock_req.return_value = {
        "orderId": 12345,
        "symbol": "BTCUSDT",
        "status": "FILLED",
        "type": "STOP_MARKET",
        "clientOrderId": "oco_abc12345_sl",
    }

    resp = client.get(
        "/trade/order",
        params={"symbol": "BTC-USDT", "orderId": "12345"},
        headers=FAKE_CREDS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["orderId"] == 12345
    assert body["data"]["status"] == "FILLED"

    # Verify the symbol was converted BTC-USDT → BTCUSDT before calling Binance
    call_params = mock_req.call_args[1].get("params") or mock_req.call_args[0][4]
    assert call_params["symbol"] == "BTCUSDT"
    assert call_params["orderId"] == "12345"


@patch("routers.trade.send_signed_request", new_callable=AsyncMock)
def test_get_order_status_not_found(mock_req):
    import httpx

    mock_resp = MagicMock()
    mock_resp.status_code = 400
    mock_resp.json.return_value = {"code": -2013, "msg": "Order does not exist"}
    mock_req.side_effect = httpx.HTTPStatusError(
        "400", request=AsyncMock(), response=mock_resp
    )

    resp = client.get(
        "/trade/order",
        params={"symbol": "BTC-USDT", "orderId": "99999"},
        headers=FAKE_CREDS,
    )

    assert resp.status_code == 400
    assert "does not exist" in resp.json()["detail"].lower()


# ── DELETE /trade/all-orders ──────────────────────────────────────────────────


@patch("routers.trade.send_signed_request", new_callable=AsyncMock)
def test_cancel_all_orders(mock_req):
    mock_req.return_value = {"code": 200, "msg": "The operation of cancel all open order is done."}

    resp = client.delete(
        "/trade/all-orders",
        params={"symbol": "BTC-USDT"},
        headers=FAKE_CREDS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["cancelled"] is True

    # Verify symbol conversion and correct Binance endpoint
    args = mock_req.call_args
    assert args[0][1] == "/fapi/v1/allOpenOrders"
    call_params = args[1].get("params") or args[0][4]
    assert call_params["symbol"] == "BTCUSDT"


@patch("routers.trade.send_signed_request", new_callable=AsyncMock)
def test_cancel_all_orders_error(mock_req):
    import httpx

    mock_resp = MagicMock()
    mock_resp.status_code = 400
    mock_resp.json.return_value = {"code": -2011, "msg": "Unknown order sent"}
    mock_req.side_effect = httpx.HTTPStatusError(
        "400", request=AsyncMock(), response=mock_resp
    )

    resp = client.delete(
        "/trade/all-orders",
        params={"symbol": "BTC-USDT"},
        headers=FAKE_CREDS,
    )

    assert resp.status_code == 400
    assert "unknown order" in resp.json()["detail"].lower()
