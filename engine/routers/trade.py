from typing import Literal
from uuid import uuid4

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


class OCOFuturesRequest(BaseModel):
    symbol: str
    side: Literal["BUY", "SELL"]
    quantity: float
    stopPrice: float | None = None
    takeProfitPrice: float | None = None


class OrderWithTpSlRequest(BaseModel):
    symbol: str
    side: Literal["BUY", "SELL"]
    type: Literal["MARKET", "LIMIT"]
    quantity: float
    price: float | None = None
    stopLoss: float | None = None
    takeProfit: float | None = None


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
        # Fetch open algo orders and merge them
        try:
            algo_data = await send_signed_request(
                "GET", "/fapi/v1/openAlgoOrders", x_binance_api_key, x_binance_api_secret
            )
            normalized_algo = []
            for ao in algo_data:
                normalized_ao = {
                    **ao,
                    "orderId": ao.get("algoId"),
                    "clientOrderId": ao.get("clientAlgoId"),
                    "type": ao.get("orderType"),
                    "status": ao.get("orderStatus"),
                    "stopPrice": ao.get("triggerPrice"),
                    "time": ao.get("createTime"),
                    "updateTime": ao.get("updateTime"),
                    "origQty": ao.get("quantity"),
                }
                normalized_algo.append(normalized_ao)
            data.extend(normalized_algo)
        except Exception as e:
            print(f"Failed to fetch open algo orders: {e}")

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
        try:
            data = await send_signed_request(
                "DELETE", "/fapi/v1/order", x_binance_api_key, x_binance_api_secret,
                params={"symbol": binance_symbol, "orderId": orderId},
            )
            return {"success": True, "data": data}
        except httpx.HTTPStatusError as exc:
            try:
                err_json = exc.response.json()
                if err_json.get("code") in [-2013, -4120]:
                    # Standard order doesn't exist or is not supported; try canceling as an algo order
                    algo_data = await send_signed_request(
                        "DELETE", "/fapi/v1/algoOrder", x_binance_api_key, x_binance_api_secret,
                        params={"symbol": binance_symbol, "algoId": orderId},
                    )
                    return {"success": True, "data": algo_data}
            except Exception:
                pass
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


@router.get("/klines")
async def get_klines(symbol: str, interval: str, limit: int = 200):
    url = "https://fapi.binance.com/fapi/v1/klines"
    params = {"symbol": symbol.replace("-", ""), "interval": interval, "limit": limit}
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url, params=params)
    resp.raise_for_status()
    return {"success": True, "data": resp.json()}


@router.post("/order/oco_futures")
async def place_oco_futures(
    payload: OCOFuturesRequest,
    x_binance_api_key: str = Header(..., alias="X-Binance-API-Key"),
    x_binance_api_secret: str = Header(..., alias="X-Binance-API-Secret"),
):
    """Place optional STOP_MARKET and/or TAKE_PROFIT_MARKET close orders for an existing position.

    Uses dedicated /fapi/v1/algoOrder endpoint to place conditional orders.
    Both legs are placed with closePosition=true so they close the entire position.
    At least one of stopPrice or takeProfitPrice must be provided.
    The shared ocoId prefix lets the client correlate the orders.
    """
    if payload.stopPrice is None and payload.takeProfitPrice is None:
        raise HTTPException(status_code=400, detail="At least one of stopPrice or takeProfitPrice is required")

    try:
        binance_symbol = payload.symbol.replace("-", "")
        oco_id = f"oco_{uuid4().hex[:8]}_"
        # SL/TP close the position — side must be opposite to entry
        close_side = "SELL" if payload.side == "BUY" else "BUY"
        placed_orders = []

        if payload.stopPrice is not None:
            sl_params = {
                "algoType": "CONDITIONAL",
                "symbol": binance_symbol,
                "side": close_side,
                "type": "STOP_MARKET",
                "triggerPrice": f"{payload.stopPrice:.2f}",
                "workingType": "MARK_PRICE",
                "closePosition": "true",
                "clientAlgoId": f"{oco_id}sl",
            }
            sl_order = await send_signed_request(
                "POST", "/fapi/v1/algoOrder", x_binance_api_key, x_binance_api_secret, params=sl_params
            )
            placed_orders.append({"orderId": sl_order.get("algoId"), "type": "STOP_MARKET", "clientOrderId": f"{oco_id}sl"})

        if payload.takeProfitPrice is not None:
            tp_params = {
                "algoType": "CONDITIONAL",
                "symbol": binance_symbol,
                "side": close_side,
                "type": "TAKE_PROFIT_MARKET",
                "triggerPrice": f"{payload.takeProfitPrice:.2f}",
                "workingType": "MARK_PRICE",
                "closePosition": "true",
                "clientAlgoId": f"{oco_id}tp",
            }
            tp_order = await send_signed_request(
                "POST", "/fapi/v1/algoOrder", x_binance_api_key, x_binance_api_secret, params=tp_params
            )
            placed_orders.append({"orderId": tp_order.get("algoId"), "type": "TAKE_PROFIT_MARKET", "clientOrderId": f"{oco_id}tp"})

        return {
            "success": True,
            "data": {"ocoId": oco_id, "orders": placed_orders},
        }
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


@router.get("/order")
async def get_order_status(
    symbol: str,
    orderId: str,
    x_binance_api_key: str = Header(..., alias="X-Binance-API-Key"),
    x_binance_api_secret: str = Header(..., alias="X-Binance-API-Secret"),
):
    try:
        binance_symbol = symbol.replace("-", "")
        try:
            data = await send_signed_request(
                "GET", "/fapi/v1/order", x_binance_api_key, x_binance_api_secret,
                params={"symbol": binance_symbol, "orderId": orderId},
            )
            return {"success": True, "data": data}
        except httpx.HTTPStatusError as exc:
            try:
                err_json = exc.response.json()
                if err_json.get("code") in [-2013, -4120]:
                    # Standard order doesn't exist or is not supported; query as an algo order
                    algo_data = await send_signed_request(
                        "GET", "/fapi/v1/algoOrder", x_binance_api_key, x_binance_api_secret,
                        params={"algoId": orderId},
                    )
                    # Normalize algo order data to match standard order shape
                    normalized = {
                        **algo_data,
                        "status": algo_data.get("algoStatus"),
                        "clientOrderId": algo_data.get("clientAlgoId"),
                        "orderId": algo_data.get("algoId"),
                        "type": algo_data.get("orderType"),
                        "stopPrice": algo_data.get("triggerPrice"),
                        "origQty": algo_data.get("quantity"),
                    }
                    return {"success": True, "data": normalized}
            except Exception:
                pass
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


@router.delete("/all-orders")
async def cancel_all_orders(
    symbol: str,
    x_binance_api_key: str = Header(..., alias="X-Binance-API-Key"),
    x_binance_api_secret: str = Header(..., alias="X-Binance-API-Secret"),
):
    try:
        binance_symbol = symbol.replace("-", "")
        # Cancel standard open orders
        std_data = await send_signed_request(
            "DELETE", "/fapi/v1/allOpenOrders", x_binance_api_key, x_binance_api_secret,
            params={"symbol": binance_symbol},
        )
        # Cancel open algo orders
        try:
            algo_data = await send_signed_request(
                "DELETE", "/fapi/v1/algoOpenOrders", x_binance_api_key, x_binance_api_secret,
                params={"symbol": binance_symbol},
            )
        except Exception as e:
            print(f"Failed to cancel open algo orders: {e}")
            algo_data = None

        return {"success": True, "data": {"cancelled": True, "standard": std_data, "algo": algo_data}}
    except httpx.HTTPStatusError as exc:
        try:
            body = exc.response.json()
            msg = body.get("msg", str(exc))
        except Exception:
            msg = str(exc)
        raise HTTPException(status_code=400, detail=msg)
    except httpx.RequestError as exc:
        raise HTTPException(status_code=500, detail=f"Engine could not reach Binance: {exc}")


@router.post("/order/with_tp_sl")
async def place_order_with_tp_sl(
    payload: OrderWithTpSlRequest,
    x_binance_api_key: str = Header(..., alias="X-Binance-API-Key"),
    x_binance_api_secret: str = Header(..., alias="X-Binance-API-Secret"),
):
    """Place an entry order (LIMIT or MARKET) plus optional STOP_MARKET / TAKE_PROFIT_MARKET exits.

    Uses dedicated /fapi/v1/algoOrder endpoint to place conditional orders.
    SL/TP close orders always use the opposite side with closePosition=true.
    A shared tpsl_ prefix lets the client correlate the legs.
    """
    try:
        binance_symbol = payload.symbol.replace("-", "")
        tpsl_id = f"tpsl_{uuid4().hex[:8]}_"
        close_side = "SELL" if payload.side == "BUY" else "BUY"

        # 1. Entry order (standard order)
        entry_params: dict = {
            "symbol": binance_symbol,
            "side": payload.side,
            "type": payload.type,
            "quantity": f"{payload.quantity:.3f}",
        }
        if payload.type == "LIMIT":
            if payload.price is None:
                raise HTTPException(status_code=400, detail="price is required for LIMIT orders")
            entry_params["price"] = f"{payload.price:.2f}"
            entry_params["timeInForce"] = "GTC"

        entry_order = await send_signed_request(
            "POST", "/fapi/v1/order", x_binance_api_key, x_binance_api_secret, params=entry_params
        )

        result: dict = {
            "tpslId": tpsl_id,
            "entry": {"orderId": entry_order.get("orderId"), "type": payload.type},
            "sl": None,
            "tp": None,
        }

        # 2. Stop-loss (STOP_MARKET algo order)
        if payload.stopLoss is not None:
            sl_params = {
                "algoType": "CONDITIONAL",
                "symbol": binance_symbol,
                "side": close_side,
                "type": "STOP_MARKET",
                "triggerPrice": f"{payload.stopLoss:.2f}",
                "workingType": "MARK_PRICE",
                "closePosition": "true",
                "clientAlgoId": f"{tpsl_id}sl",
            }
            sl_order = await send_signed_request(
                "POST", "/fapi/v1/algoOrder", x_binance_api_key, x_binance_api_secret, params=sl_params
            )
            result["sl"] = {"orderId": sl_order.get("algoId"), "type": "STOP_MARKET", "clientOrderId": f"{tpsl_id}sl"}

        # 3. Take-profit (TAKE_PROFIT_MARKET algo order)
        if payload.takeProfit is not None:
            tp_params = {
                "algoType": "CONDITIONAL",
                "symbol": binance_symbol,
                "side": close_side,
                "type": "TAKE_PROFIT_MARKET",
                "triggerPrice": f"{payload.takeProfit:.2f}",
                "workingType": "MARK_PRICE",
                "closePosition": "true",
                "clientAlgoId": f"{tpsl_id}tp",
            }
            tp_order = await send_signed_request(
                "POST", "/fapi/v1/algoOrder", x_binance_api_key, x_binance_api_secret, params=tp_params
            )
            result["tp"] = {"orderId": tp_order.get("algoId"), "type": "TAKE_PROFIT_MARKET", "clientOrderId": f"{tpsl_id}tp"}

        return {"success": True, "data": result}
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
