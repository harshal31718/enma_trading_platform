import logging
from fastapi import APIRouter, Header, HTTPException
import httpx

from services.portfolio_risk import compute_full_metrics

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/live-metrics")
async def get_live_metrics(
    x_binance_api_key: str = Header(..., alias="X-Binance-API-Key"),
    x_binance_api_secret: str = Header(..., alias="X-Binance-API-Secret"),
    x_binance_mode: str = Header("testnet", alias="X-Binance-Mode"),
):
    """Plan 22 Step 22.4: this route is now a thin formatter over
    `services/portfolio_risk.py`'s `compute_full_metrics` — the shared
    fetch/compute path the live Session Risk Governor's VaR check also
    goes through (`compute_var_cvar`, same underlying account fetch +
    price-history fetch + `calculate_portfolio_var` call). Response shape
    is unchanged from the pre-22.4 inline implementation.
    """
    try:
        m = await compute_full_metrics(x_binance_api_key, x_binance_api_secret, x_binance_mode)

        active_symbols = m["active_symbols"]
        formatted_corr = {}
        for s1 in active_symbols:
            formatted_corr[s1] = {}
            for s2 in active_symbols:
                val = m["correlation_matrix"].get(s1, {}).get(s2, 0.0 if s1 != s2 else 1.0)
                formatted_corr[s1][s2] = f"{val:.2f}"

        return {
            "success": True,
            "data": {
                "aggregateMarginUsed": f"{m['initial_margin']:.2f}",
                "aggregateWalletBalance": f"{m['wallet_balance']:.2f}",
                "netLeverage": f"{m['net_leverage']:.2f}",
                "activeSymbols": active_symbols,
                "exposures": m["exposures"],
                "valueAtRisk": {
                    "var95_1d": f"{m['var95']:.2f}",
                    "var99_1d": f"{m['var99']:.2f}",
                    "cvar95_1d": f"{m['cvar95']:.2f}",
                },
                "correlationMatrix": formatted_corr,
            },
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
