import hashlib
import hmac
import time

import httpx
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from services.binance_testnet import send_signed_request

router = APIRouter()

BINANCE_TESTNET_BASE = "https://testnet.binancefuture.com"


class VerifyKeysRequest(BaseModel):
    binanceApiKey: str
    binanceApiSecret: str


class LeverageRequest(BaseModel):
    symbol: str
    leverage: int


class MarginTypeRequest(BaseModel):
    symbol: str
    marginType: str


class OrderRequest(BaseModel):
    symbol: str
    side: str       # BUY | SELL
    type: str       # LIMIT | MARKET
    quantity: float
    price: float | None = None


class ClosePositionRequest(BaseModel):
    symbol: str


@router.post("/verify")
async def verify_keys(payload: VerifyKeysRequest):
    try:
        await send_signed_request(
            "GET", "/fapi/v2/account", payload.binanceApiKey, payload.binanceApiSecret
        )
        return {"success": True}
    except httpx.HTTPStatusError as exc:
        try:
            error_body = exc.response.json()
            code = error_body.get("code", exc.response.status_code)
            message = error_body.get("msg", "Unknown Binance error")
        except Exception:
            code = exc.response.status_code
            message = exc.response.text

        raise HTTPException(
            status_code=400,
            detail={"code": code, "message": message},
        )
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Engine could not reach Binance: {exc}",
        )


@router.get("/account")
async def get_account(
    x_binance_api_key: str = Header(..., alias="X-Binance-API-Key"),
    x_binance_api_secret: str = Header(..., alias="X-Binance-API-Secret"),
):
    try:
        data = await send_signed_request(
            "GET", "/fapi/v2/account", x_binance_api_key, x_binance_api_secret
        )
        return {"success": True, "data": data}
    except httpx.HTTPStatusError as exc:
        try:
            body = exc.response.json()
            msg = body.get("msg", str(exc))
        except Exception:
            msg = str(exc)
        raise HTTPException(status_code=400, detail=msg)
    except httpx.RequestError as exc:
        raise HTTPException(status_code=500, detail=f"Engine could not reach Binance: {exc}")


@router.get("/positions")
async def get_positions(
    x_binance_api_key: str = Header(..., alias="X-Binance-API-Key"),
    x_binance_api_secret: str = Header(..., alias="X-Binance-API-Secret"),
    symbol: str = None,
):
    try:
        params = {}
        if symbol:
            params["symbol"] = symbol.replace("-", "")
        data = await send_signed_request(
            "GET", "/fapi/v2/positionRisk", x_binance_api_key, x_binance_api_secret,
            params=params if params else None,
        )
        return {"success": True, "data": data}
    except httpx.HTTPStatusError as exc:
        try:
            body = exc.response.json()
            msg = body.get("msg", str(exc))
        except Exception:
            msg = str(exc)
        raise HTTPException(status_code=400, detail=msg)
    except httpx.RequestError as exc:
        raise HTTPException(status_code=500, detail=f"Engine could not reach Binance: {exc}")


@router.get("/open-orders")
async def get_open_orders(
    x_binance_api_key: str = Header(..., alias="X-Binance-API-Key"),
    x_binance_api_secret: str = Header(..., alias="X-Binance-API-Secret"),
):
    try:
        data = await send_signed_request(
            "GET", "/fapi/v1/openOrders", x_binance_api_key, x_binance_api_secret
        )
        return {"success": True, "data": data}
    except httpx.HTTPStatusError as exc:
        try:
            body = exc.response.json()
            msg = body.get("msg", str(exc))
        except Exception:
            msg = str(exc)
        raise HTTPException(status_code=400, detail=msg)
    except httpx.RequestError as exc:
        raise HTTPException(status_code=500, detail=f"Engine could not reach Binance: {exc}")


@router.post("/leverage")
async def set_leverage(
    payload: LeverageRequest,
    x_binance_api_key: str = Header(..., alias="X-Binance-API-Key"),
    x_binance_api_secret: str = Header(..., alias="X-Binance-API-Secret"),
):
    try:
        binance_symbol = payload.symbol.replace("-", "")
        data = await send_signed_request(
            "POST", "/fapi/v1/leverage", x_binance_api_key, x_binance_api_secret,
            params={"symbol": binance_symbol, "leverage": payload.leverage},
        )
        return {"success": True, "data": data}
    except httpx.HTTPStatusError as exc:
        try:
            body = exc.response.json()
            msg = body.get("msg", str(exc))
        except Exception:
            msg = str(exc)
        raise HTTPException(status_code=400, detail=msg)
    except httpx.RequestError as exc:
        raise HTTPException(status_code=500, detail=f"Engine could not reach Binance: {exc}")


@router.post("/order")
async def place_order(
    payload: OrderRequest,
    x_binance_api_key: str = Header(..., alias="X-Binance-API-Key"),
    x_binance_api_secret: str = Header(..., alias="X-Binance-API-Secret"),
):
    try:
        binance_symbol = payload.symbol.replace("-", "")
        params = {
            "symbol": binance_symbol,
            "side": payload.side.upper(),
            "type": payload.type.upper(),
            "quantity": f"{payload.quantity:.3f}",
        }
        if payload.type.upper() == "LIMIT":
            if payload.price is None:
                raise HTTPException(status_code=400, detail="price is required for LIMIT orders")
            params["price"] = f"{payload.price:.2f}"
            params["timeInForce"] = "GTC"
        data = await send_signed_request(
            "POST", "/fapi/v1/order", x_binance_api_key, x_binance_api_secret, params=params
        )
        return {"success": True, "data": data}
    except HTTPException:
        raise
    except httpx.HTTPStatusError as exc:
        try:
            body = exc.response.json()
            msg = body.get("msg", str(exc))
        except Exception:
            msg = str(exc)
        raise HTTPException(status_code=400, detail=msg)
    except httpx.RequestError as exc:
        raise HTTPException(status_code=500, detail=f"Engine could not reach Binance: {exc}")


@router.post("/close-position")
async def close_position(
    payload: ClosePositionRequest,
    x_binance_api_key: str = Header(..., alias="X-Binance-API-Key"),
    x_binance_api_secret: str = Header(..., alias="X-Binance-API-Secret"),
):
    try:
        binance_symbol = payload.symbol.replace("-", "")

        # Read the current position size to know which side/qty flattens it.
        positions = await send_signed_request(
            "GET", "/fapi/v2/positionRisk", x_binance_api_key, x_binance_api_secret,
            params={"symbol": binance_symbol},
        )
        position_amt = 0.0
        for p in positions:
            if p.get("symbol") == binance_symbol:
                position_amt = float(p.get("positionAmt", 0))
                break

        if position_amt == 0:
            raise HTTPException(status_code=400, detail="No open position to close for this symbol")

        # Opposite side, full absolute size, reduceOnly so it can only flatten.
        close_side = "SELL" if position_amt > 0 else "BUY"
        params = {
            "symbol": binance_symbol,
            "side": close_side,
            "type": "MARKET",
            "quantity": f"{abs(position_amt):.3f}",
            "reduceOnly": "true",
        }
        data = await send_signed_request(
            "POST", "/fapi/v1/order", x_binance_api_key, x_binance_api_secret, params=params
        )
        return {"success": True, "data": data}
    except HTTPException:
        raise
    except httpx.HTTPStatusError as exc:
        try:
            body = exc.response.json()
            msg = body.get("msg", str(exc))
        except Exception:
            msg = str(exc)
        raise HTTPException(status_code=400, detail=msg)
    except httpx.RequestError as exc:
        raise HTTPException(status_code=500, detail=f"Engine could not reach Binance: {exc}")


@router.delete("/order")
async def cancel_order(
    symbol: str,
    orderId: str,
    x_binance_api_key: str = Header(..., alias="X-Binance-API-Key"),
    x_binance_api_secret: str = Header(..., alias="X-Binance-API-Secret"),
):
    try:
        binance_symbol = symbol.replace("-", "")
        data = await send_signed_request(
            "DELETE", "/fapi/v1/order", x_binance_api_key, x_binance_api_secret,
            params={"symbol": binance_symbol, "orderId": orderId},
        )
        return {"success": True, "data": data}
    except httpx.HTTPStatusError as exc:
        try:
            body = exc.response.json()
            msg = body.get("msg", str(exc))
        except Exception:
            msg = str(exc)
        raise HTTPException(status_code=400, detail=msg)
    except httpx.RequestError as exc:
        raise HTTPException(status_code=500, detail=f"Engine could not reach Binance: {exc}")


@router.get("/klines")
async def get_klines(symbol: str, interval: str, limit: int = 200):
    url = "https://fapi.binance.com/fapi/v1/klines"
    params = {"symbol": symbol.replace("-", ""), "interval": interval, "limit": limit}
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url, params=params)
    resp.raise_for_status()
    return {"success": True, "data": resp.json()}


@router.post("/margin-type")
async def set_margin_type(
    payload: MarginTypeRequest,
    x_binance_api_key: str = Header(..., alias="X-Binance-API-Key"),
    x_binance_api_secret: str = Header(..., alias="X-Binance-API-Secret"),
):
    # Isolated margin only — cross margin is removed platform-wide. The incoming
    # marginType is ignored; ISOLATED is always applied. See DECISIONS.md
    # "Isolated margin only (cross margin removed)".
    try:
        binance_symbol = payload.symbol.replace("-", "")
        data = await send_signed_request(
            "POST", "/fapi/v1/marginType", x_binance_api_key, x_binance_api_secret,
            params={"symbol": binance_symbol, "marginType": "ISOLATED"},
        )
        return {"success": True, "data": data}
    except httpx.HTTPStatusError as exc:
        try:
            body = exc.response.json()
            msg = body.get("msg", str(exc))
            code = body.get("code")
        except Exception:
            msg = str(exc)
            code = None
        # -4046: "No need to change margin type" — symbol is already ISOLATED.
        # This is the desired end state, so treat it as success.
        if code == -4046:
            return {"success": True, "data": {"code": 200, "msg": "success"}}
        raise HTTPException(status_code=400, detail=msg)
    except httpx.RequestError as exc:
        raise HTTPException(status_code=500, detail=f"Engine could not reach Binance: {exc}")
