from fastapi import APIRouter

from core.constants import FUTURES_SYMBOLS
from services.candle_manager import get_cached_candles_summary

router = APIRouter()


@router.get("/symbols")
async def get_symbols():
    return {"success": True, "data": {"futures": FUTURES_SYMBOLS, "spot": []}}


@router.get("/cached")
async def get_cached_candles():
    summary = await get_cached_candles_summary()
    return {"success": True, "data": {"cached": summary}}
