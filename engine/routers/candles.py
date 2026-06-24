from fastapi import APIRouter

from core.constants import FUTURES_SYMBOLS
from services.candle_manager import get_cached_candles_summary
from utils.symbols import get_all_rules, get_all_symbols

router = APIRouter()


@router.get("/symbols")
async def get_symbols():
    rules = get_all_rules("Binance Futures")
    all_symbols = get_all_symbols("Binance Futures")
    return {
        "success": True,
        "data": {
            "futures": FUTURES_SYMBOLS,
            "all": all_symbols,
            "spot": [],
            "rules": rules,
        },
    }


@router.get("/cached")
async def get_cached_candles():
    summary = await get_cached_candles_summary()
    return {"success": True, "data": {"cached": summary}}
