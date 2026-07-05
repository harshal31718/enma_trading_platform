import logging
from typing import Literal
from uuid import uuid4

import httpx
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel

from services.binance_testnet import send_signed_request
from services import manual_trade_stream
from utils.symbols import clamp_leverage

logger = logging.getLogger(__name__)

router = APIRouter()


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
async def verify_keys(
    payload: VerifyKeysRequest,
    x_binance_mode: str = Header("testnet", alias="X-Binance-Mode"),
):
    try:
        await send_signed_request(
            "GET", "/fapi/v2/account",
            payload.binanceApiKey, payload.binanceApiSecret,
            mode=x_binance_mode,
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
    x_binance_mode: str = Header("testnet", alias="X-Binance-Mode"),
):
    try:
        data = await send_signed_request(
            "GET", "/fapi/v2/account",
            x_binance_api_key, x_binance_api_secret,
            mode=x_binance_mode,
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
    x_binance_mode: str = Header("testnet", alias="X-Binance-Mode"),
    symbol: str = None,
):
    try:
        params = {}
        if symbol:
            params["symbol"] = symbol
        data = await send_signed_request(
            "GET", "/fapi/v2/positionRisk",
            x_binance_api_key, x_binance_api_secret,
            params=params if params else None,
            mode=x_binance_mode,
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
    x_binance_mode: str = Header("testnet", alias="X-Binance-Mode"),
):
    try:
        data = await send_signed_request(
            "GET", "/fapi/v1/openOrders",
            x_binance_api_key, x_binance_api_secret,
            mode=x_binance_mode,
        )
        try:
            algo_data = await send_signed_request(
                "GET", "/fapi/v1/openAlgoOrders",
                x_binance_api_key, x_binance_api_secret,
                mode=x_binance_mode,
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
            logger.error("Failed to fetch open algo orders: %s", e)

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
    x_binance_mode: str = Header("testnet", alias="X-Binance-Mode"),
):
    effective = await clamp_leverage(
        payload.leverage, "Binance Futures", payload.symbol,
        api_key=x_binance_api_key, api_secret=x_binance_api_secret,
        mode=x_binance_mode,
    )
    try:
        data = await send_signed_request(
            "POST", "/fapi/v1/leverage",
            x_binance_api_key, x_binance_api_secret,
            params={"symbol": payload.symbol, "leverage": effective},
            mode=x_binance_mode,
        )
        return {"success": True, "data": data, "effectiveLeverage": effective}
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
    x_binance_mode: str = Header("testnet", alias="X-Binance-Mode"),
):
    try:
        params = {
            "symbol": payload.symbol,
            "side": payload.side.upper(),
            "type": payload.type.upper(),
            "quantity": _fmt_qty(payload.quantity),
        }
        if payload.type.upper() == "LIMIT":
            if payload.price is None:
                raise HTTPException(status_code=400, detail="price is required for LIMIT orders")
            params["price"] = _fmt_price(payload.price)
            params["timeInForce"] = "GTC"
        data = await send_signed_request(
            "POST", "/fapi/v1/order",
            x_binance_api_key, x_binance_api_secret,
            params=params,
            mode=x_binance_mode,
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
    x_binance_mode: str = Header("testnet", alias="X-Binance-Mode"),
):
    try:
        positions = await send_signed_request(
            "GET", "/fapi/v2/positionRisk",
            x_binance_api_key, x_binance_api_secret,
            params={"symbol": payload.symbol},
            mode=x_binance_mode,
        )
        position_amt = 0.0
        for p in positions:
            if p.get("symbol") == payload.symbol:
                position_amt = float(p.get("positionAmt", 0))
                break

        if position_amt == 0:
            raise HTTPException(status_code=400, detail="No open position to close for this symbol")

        close_side = "SELL" if position_amt > 0 else "BUY"
        params = {
            "symbol": payload.symbol,
            "side": close_side,
            "type": "MARKET",
            "quantity": _fmt_qty(abs(position_amt)),
            "reduceOnly": "true",
        }
        data = await send_signed_request(
            "POST", "/fapi/v1/order",
            x_binance_api_key, x_binance_api_secret,
            params=params,
            mode=x_binance_mode,
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
    x_binance_mode: str = Header("testnet", alias="X-Binance-Mode"),
):
    try:
        try:
            data = await send_signed_request(
                "DELETE", "/fapi/v1/order",
                x_binance_api_key, x_binance_api_secret,
                params={"symbol": symbol, "orderId": orderId},
                mode=x_binance_mode,
            )
            return {"success": True, "data": data}
        except httpx.HTTPStatusError as exc:
            try:
                err_json = exc.response.json()
                if err_json.get("code") in [-2013, -4120]:
                    algo_data = await send_signed_request(
                        "DELETE", "/fapi/v1/algoOrder",
                        x_binance_api_key, x_binance_api_secret,
                        params={"symbol": symbol, "algoId": orderId},
                        mode=x_binance_mode,
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
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url, params=params)
    resp.raise_for_status()
    return {"success": True, "data": resp.json()}


@router.post("/order/oco_futures")
async def place_oco_futures(
    payload: OCOFuturesRequest,
    x_binance_api_key: str = Header(..., alias="X-Binance-API-Key"),
    x_binance_api_secret: str = Header(..., alias="X-Binance-API-Secret"),
    x_binance_mode: str = Header("testnet", alias="X-Binance-Mode"),
):
    if payload.stopPrice is None and payload.takeProfitPrice is None:
        raise HTTPException(status_code=400, detail="At least one of stopPrice or takeProfitPrice is required")

    try:
        oco_id = f"oco_{uuid4().hex[:8]}_"
        close_side = "SELL" if payload.side == "BUY" else "BUY"
        placed_orders = []

        if payload.stopPrice is not None:
            sl_params = {
                "algoType": "CONDITIONAL",
                "symbol": payload.symbol,
                "side": close_side,
                "type": "STOP_MARKET",
                "triggerPrice": _fmt_price(payload.stopPrice),
                "workingType": "MARK_PRICE",
                "closePosition": "true",
                "clientAlgoId": f"{oco_id}sl",
            }
            sl_order = await send_signed_request(
                "POST", "/fapi/v1/algoOrder",
                x_binance_api_key, x_binance_api_secret,
                params=sl_params,
                mode=x_binance_mode,
            )
            placed_orders.append({"orderId": sl_order.get("algoId"), "type": "STOP_MARKET", "clientOrderId": f"{oco_id}sl"})

        if payload.takeProfitPrice is not None:
            tp_params = {
                "algoType": "CONDITIONAL",
                "symbol": payload.symbol,
                "side": close_side,
                "type": "TAKE_PROFIT_MARKET",
                "triggerPrice": _fmt_price(payload.takeProfitPrice),
                "workingType": "MARK_PRICE",
                "closePosition": "true",
                "clientAlgoId": f"{oco_id}tp",
            }
            tp_order = await send_signed_request(
                "POST", "/fapi/v1/algoOrder",
                x_binance_api_key, x_binance_api_secret,
                params=tp_params,
                mode=x_binance_mode,
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
    x_binance_mode: str = Header("testnet", alias="X-Binance-Mode"),
):
    try:
        try:
            data = await send_signed_request(
                "GET", "/fapi/v1/order",
                x_binance_api_key, x_binance_api_secret,
                params={"symbol": symbol, "orderId": orderId},
                mode=x_binance_mode,
            )
            return {"success": True, "data": data}
        except httpx.HTTPStatusError as exc:
            try:
                err_json = exc.response.json()
                if err_json.get("code") in [-2013, -4120]:
                    algo_data = await send_signed_request(
                        "GET", "/fapi/v1/algoOrder",
                        x_binance_api_key, x_binance_api_secret,
                        params={"algoId": orderId},
                        mode=x_binance_mode,
                    )
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
    x_binance_mode: str = Header("testnet", alias="X-Binance-Mode"),
):
    try:
        std_data = await send_signed_request(
            "DELETE", "/fapi/v1/allOpenOrders",
            x_binance_api_key, x_binance_api_secret,
            params={"symbol": symbol},
            mode=x_binance_mode,
        )
        try:
            algo_data = await send_signed_request(
                "DELETE", "/fapi/v1/algoOpenOrders",
                x_binance_api_key, x_binance_api_secret,
                params={"symbol": symbol},
                mode=x_binance_mode,
            )
        except Exception as e:
            logger.error("Failed to cancel open algo orders: %s", e)
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
    x_binance_mode: str = Header("testnet", alias="X-Binance-Mode"),
):
    try:
        tpsl_id = f"tpsl_{uuid4().hex[:8]}_"
        close_side = "SELL" if payload.side == "BUY" else "BUY"

        entry_params: dict = {
            "symbol": payload.symbol,
            "side": payload.side,
            "type": payload.type,
            "quantity": _fmt_qty(payload.quantity),
        }
        if payload.type == "LIMIT":
            if payload.price is None:
                raise HTTPException(status_code=400, detail="price is required for LIMIT orders")
            entry_params["price"] = _fmt_price(payload.price)
            entry_params["timeInForce"] = "GTC"

        entry_order = await send_signed_request(
            "POST", "/fapi/v1/order",
            x_binance_api_key, x_binance_api_secret,
            params=entry_params,
            mode=x_binance_mode,
        )

        result: dict = {
            "tpslId": tpsl_id,
            "entry": {"orderId": entry_order.get("orderId"), "type": payload.type},
            "sl": None,
            "tp": None,
            "warnings": [],
        }

        # SL and TP are best-effort — if they fail (e.g. "would immediately trigger"
        # because the price moved between signal and fill), the entry is still filled
        # and the position must be tracked. Never fail the whole call here.
        if payload.stopLoss is not None:
            sl_params = {
                "algoType": "CONDITIONAL",
                "symbol": payload.symbol,
                "side": close_side,
                "type": "STOP_MARKET",
                "triggerPrice": _fmt_price(payload.stopLoss),
                "workingType": "MARK_PRICE",
                "closePosition": "true",
                "clientAlgoId": f"{tpsl_id}sl",
            }
            try:
                sl_order = await send_signed_request(
                    "POST", "/fapi/v1/algoOrder",
                    x_binance_api_key, x_binance_api_secret,
                    params=sl_params,
                    mode=x_binance_mode,
                )
                result["sl"] = {"orderId": sl_order.get("algoId"), "type": "STOP_MARKET", "clientOrderId": f"{tpsl_id}sl"}
            except Exception as e:
                msg = e.response.json().get("msg", str(e)) if hasattr(e, "response") else str(e)
                logger.warning(f"SL placement failed for {payload.symbol}: {msg}")
                result["warnings"].append(f"SL skipped: {msg}")

        if payload.takeProfit is not None:
            tp_params = {
                "algoType": "CONDITIONAL",
                "symbol": payload.symbol,
                "side": close_side,
                "type": "TAKE_PROFIT_MARKET",
                "triggerPrice": _fmt_price(payload.takeProfit),
                "workingType": "MARK_PRICE",
                "closePosition": "true",
                "clientAlgoId": f"{tpsl_id}tp",
            }
            try:
                tp_order = await send_signed_request(
                    "POST", "/fapi/v1/algoOrder",
                    x_binance_api_key, x_binance_api_secret,
                    params=tp_params,
                    mode=x_binance_mode,
                )
                result["tp"] = {"orderId": tp_order.get("algoId"), "type": "TAKE_PROFIT_MARKET", "clientOrderId": f"{tpsl_id}tp"}
            except Exception as e:
                msg = e.response.json().get("msg", str(e)) if hasattr(e, "response") else str(e)
                logger.warning(f"TP placement failed for {payload.symbol}: {msg}")
                result["warnings"].append(f"TP skipped: {msg}")

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


def _fmt_num(value: float) -> str:
    s = f"{value:.8f}".rstrip('0').rstrip('.')
    return s if s else '0'

_fmt_qty = _fmt_num
_fmt_price = _fmt_num


def from_binance_symbol(symbol: str) -> str:
    if not symbol:
        return ""
    for quote in ("USDT", "USDC", "BUSD", "BTC", "ETH", "BNB"):
        if symbol.endswith(quote):
            base = symbol[:-len(quote)]
            return f"{base}-{quote}"
    return symbol


@router.get("/history-orders")
async def get_history_orders(
    symbol: str,
    limit: int = 100,
    x_binance_api_key: str = Header(..., alias="X-Binance-API-Key"),
    x_binance_api_secret: str = Header(..., alias="X-Binance-API-Secret"),
    x_binance_mode: str = Header("testnet", alias="X-Binance-Mode"),
):
    try:
        std_orders = await send_signed_request(
            "GET", "/fapi/v1/allOrders",
            x_binance_api_key, x_binance_api_secret,
            params={"symbol": symbol, "limit": limit},
            mode=x_binance_mode,
        )

        algo_orders = []
        try:
            algo_orders = await send_signed_request(
                "GET", "/fapi/v1/historicalAlgoOrders",
                x_binance_api_key, x_binance_api_secret,
                params={"symbol": symbol, "limit": limit},
                mode=x_binance_mode,
            )
        except Exception as e:
            logger.error("Failed to fetch historical algo orders: %s", e)

        normalized = []
        for o in std_orders:
            normalized.append({
                "orderId": str(o.get("orderId")),
                "clientOrderId": o.get("clientOrderId"),
                "symbol": from_binance_symbol(o.get("symbol")),
                "status": o.get("status"),
                "price": o.get("price"),
                "avgPrice": o.get("avgPrice"),
                "origQty": o.get("origQty"),
                "executedQty": o.get("executedQty"),
                "side": o.get("side"),
                "type": o.get("type"),
                "timeInForce": o.get("timeInForce"),
                "stopPrice": o.get("stopPrice"),
                "time": o.get("time"),
                "updateTime": o.get("updateTime"),
                "reduceOnly": o.get("reduceOnly"),
                "postOnly": o.get("postOnly"),
                "isAlgo": False,
            })

        for ao in algo_orders:
            normalized.append({
                "orderId": str(ao.get("algoId")),
                "clientOrderId": ao.get("clientAlgoId"),
                "symbol": from_binance_symbol(ao.get("symbol")),
                "status": ao.get("algoStatus"),
                "price": "0.00",
                "avgPrice": "0.00",
                "origQty": ao.get("quantity"),
                "executedQty": "0.00",
                "side": ao.get("side"),
                "type": ao.get("orderType"),
                "timeInForce": "GTC",
                "stopPrice": ao.get("triggerPrice"),
                "time": ao.get("time"),
                "updateTime": ao.get("updateTime"),
                "reduceOnly": ao.get("reduceOnly"),
                "postOnly": ao.get("postOnly"),
                "isAlgo": True,
            })

        return {"success": True, "data": normalized}
    except httpx.HTTPStatusError as exc:
        try:
            body = exc.response.json()
            msg = body.get("msg", str(exc))
        except Exception:
            msg = str(exc)
        raise HTTPException(status_code=400, detail=msg)
    except httpx.RequestError as exc:
        raise HTTPException(status_code=500, detail=f"Engine could not reach Binance: {exc}")


@router.get("/history-executions")
async def get_history_executions(
    symbol: str,
    limit: int = 100,
    x_binance_api_key: str = Header(..., alias="X-Binance-API-Key"),
    x_binance_api_secret: str = Header(..., alias="X-Binance-API-Secret"),
    x_binance_mode: str = Header("testnet", alias="X-Binance-Mode"),
):
    try:
        trades = await send_signed_request(
            "GET", "/fapi/v1/userTrades",
            x_binance_api_key, x_binance_api_secret,
            params={"symbol": symbol, "limit": limit},
            mode=x_binance_mode,
        )

        normalized = []
        for t in trades:
            normalized.append({
                "id": str(t.get("id")),
                "orderId": str(t.get("orderId")),
                "symbol": from_binance_symbol(t.get("symbol")),
                "side": t.get("side"),
                "price": t.get("price"),
                "qty": t.get("qty"),
                "commission": t.get("commission"),
                "commissionAsset": t.get("commissionAsset"),
                "time": t.get("time"),
                "realizedPnl": t.get("realizedPnl"),
                "maker": t.get("maker"),
            })

        return {"success": True, "data": normalized}
    except httpx.HTTPStatusError as exc:
        try:
            body = exc.response.json()
            msg = body.get("msg", str(exc))
        except Exception:
            msg = str(exc)
        raise HTTPException(status_code=400, detail=msg)
    except httpx.RequestError as exc:
        raise HTTPException(status_code=500, detail=f"Engine could not reach Binance: {exc}")


@router.get("/history-transactions")
async def get_history_transactions(
    symbol: str = None,
    limit: int = 100,
    x_binance_api_key: str = Header(..., alias="X-Binance-API-Key"),
    x_binance_api_secret: str = Header(..., alias="X-Binance-API-Secret"),
    x_binance_mode: str = Header("testnet", alias="X-Binance-Mode"),
):
    try:
        params = {"limit": limit}
        if symbol:
            params["symbol"] = symbol
        income = await send_signed_request(
            "GET", "/fapi/v1/income",
            x_binance_api_key, x_binance_api_secret,
            params=params,
            mode=x_binance_mode,
        )

        normalized = []
        for i in income:
            normalized.append({
                "tranId": str(i.get("tranId")),
                "symbol": from_binance_symbol(i.get("symbol")) if i.get("symbol") else "",
                "incomeType": i.get("incomeType"),
                "income": i.get("income"),
                "asset": i.get("asset"),
                "time": i.get("time"),
            })

        return {"success": True, "data": normalized}
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
    x_binance_mode: str = Header("testnet", alias="X-Binance-Mode"),
):
    try:
        data = await send_signed_request(
            "POST", "/fapi/v1/marginType",
            x_binance_api_key, x_binance_api_secret,
            params={"symbol": payload.symbol, "marginType": "ISOLATED"},
            mode=x_binance_mode,
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
        if code == -4046:
            return {"success": True, "data": {"code": 200, "msg": "success"}}
        raise HTTPException(status_code=400, detail=msg)
    except httpx.RequestError as exc:
        raise HTTPException(status_code=500, detail=f"Engine could not reach Binance: {exc}")


@router.post("/stream/start")
async def start_trade_stream(
    userId: str = Query(...),
    x_binance_api_key: str = Header(..., alias="X-Binance-API-Key"),
    x_binance_api_secret: str = Header(..., alias="X-Binance-API-Secret"),
):
    """Start (or heartbeat-refresh) this user's manual-trading User Data
    Stream — real-time order/account push over WebSocket, so the client can
    stop REST-polling account/positions/open-orders at high frequency. See
    workspace/docs/features/live-trading/SPEC.md."""
    await manual_trade_stream.start_for_user(userId, x_binance_api_key, x_binance_api_secret)
    return {"success": True}


@router.post("/stream/stop")
async def stop_trade_stream(userId: str = Query(...)):
    await manual_trade_stream.stop_for_user(userId)
    return {"success": True}
