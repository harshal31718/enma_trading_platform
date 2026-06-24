import logging
from fastapi import APIRouter, Header, HTTPException
from typing import Dict, Any
from utils.risk_math import calculate_portfolio_var, calculate_correlation_matrix
from config.timescale import get_pool
from datetime import datetime, timedelta, timezone
import numpy as np

router = APIRouter()
logger = logging.getLogger(__name__)

async def fetch_close_prices(symbols: list[str]) -> dict[str, np.ndarray]:
    if not symbols:
        return {}
    pool = get_pool()
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    query = """
        SELECT symbol, close FROM candles
        WHERE timeframe = '1h'
        AND symbol = ANY($1)
        AND time >= $2
        ORDER BY time ASC
    """
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(query, symbols, cutoff)
        
        data = {}
        for r in rows:
            sym = r["symbol"]
            val = float(r["close"])
            if sym not in data:
                data[sym] = []
            data[sym].append(val)
        return {k: np.array(v, dtype=float) for k, v in data.items()}
    except Exception as e:
        logger.error(f"Error fetching close prices from TimescaleDB: {e}")
        return {}

@router.get("/live-metrics")
async def get_live_metrics(
    x_binance_api_key: str = Header(..., alias="X-Binance-API-Key"),
    x_binance_api_secret: str = Header(..., alias="X-Binance-API-Secret"),
    x_binance_mode: str = Header("testnet", alias="X-Binance-Mode"),
):
    from services.binance_testnet import send_signed_request
    import httpx
    
    try:
        # 1. Fetch live account status from Binance
        account_data = await send_signed_request(
            "GET", "/fapi/v2/account",
            x_binance_api_key, x_binance_api_secret,
            mode=x_binance_mode,
        )
        
        # 2. Extract portfolio margins & balances
        wallet_balance = float(account_data.get("totalWalletBalance", 0.0))
        margin_balance = float(account_data.get("totalMarginBalance", 0.0))
        initial_margin = float(account_data.get("totalInitialMargin", 0.0))
        
        # 3. Collect active positions and symbols
        active_symbols = []
        position_notionals = {}
        exposures = {}
        
        # Binance returns positions under "positions"
        for p in account_data.get("positions", []):
            amt = float(p.get("positionAmt", 0.0))
            if amt != 0.0:
                sym = p.get("symbol")
                entry_price = float(p.get("entryPrice", 0.0))
                notional = float(p.get("notional") or (amt * entry_price))
                side = "long" if amt > 0 else "short"
                lev = int(p.get("leverage", 1))
                
                active_symbols.append(sym)
                position_notionals[sym] = amt * entry_price
                exposures[sym] = {
                    "side": side,
                    "notional": f"{abs(notional):.2f}",
                    "leverage": str(lev)
                }
        
        # 4. Calculate Net Portfolio Leverage
        total_notional = sum(abs(float(exp["notional"])) for exp in exposures.values())
        net_leverage = total_notional / margin_balance if margin_balance > 0 else 0.0
        
        # 5. Fetch closing price histories (last 30 days) and compute VaR / correlation matrix
        price_histories = await fetch_close_prices(active_symbols)
        var95, cvar95 = calculate_portfolio_var(position_notionals, price_histories, confidence_level=0.95)
        var99, cvar99 = calculate_portfolio_var(position_notionals, price_histories, confidence_level=0.99)
        corr_matrix = calculate_correlation_matrix(price_histories)
        
        # Ensure all active symbols are present in the correlation matrix, even if empty
        formatted_corr = {}
        for s1 in active_symbols:
            formatted_corr[s1] = {}
            for s2 in active_symbols:
                val = corr_matrix.get(s1, {}).get(s2, 0.0 if s1 != s2 else 1.0)
                formatted_corr[s1][s2] = f"{val:.2f}"
        
        return {
            "success": True,
            "data": {
                "aggregateMarginUsed": f"{initial_margin:.2f}",
                "aggregateWalletBalance": f"{wallet_balance:.2f}",
                "netLeverage": f"{net_leverage:.2f}",
                "activeSymbols": active_symbols,
                "exposures": exposures,
                "valueAtRisk": {
                    "var95_1d": f"{var95:.2f}",
                    "var99_1d": f"{var99:.2f}",
                    "cvar95_1d": f"{cvar95:.2f}"
                },
                "correlationMatrix": formatted_corr
            }
        }
        
    except httpx.HTTPStatusError as exc:
        try:
            body = exc.response.json()
            msg = body.get("msg", str(exc))
        except Exception:
            msg = str(exc)
        raise HTTPException(status_code=400, detail=f"Binance API error: {msg}")
    except Exception as e:
        logger.error(f"Error computing live metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))
