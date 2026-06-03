from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.constants import FUTURES_SYMBOLS, SUPPORTED_EXCHANGES, SUPPORTED_TIMEFRAMES
from services.candle_importer import import_candles

router = APIRouter()


class CandleImportRequest(BaseModel):
    jobId: str
    exchange: str
    symbol: str
    timeframe: str
    startDate: str
    endDate: str


@router.get("/symbols")
async def get_symbols():
    return {"success": True, "data": {"futures": FUTURES_SYMBOLS, "spot": []}}


@router.post("/import")
async def run_import(req: CandleImportRequest):
    if req.exchange not in SUPPORTED_EXCHANGES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported exchange '{req.exchange}'. Must be one of: {SUPPORTED_EXCHANGES}",
        )
    if req.timeframe not in SUPPORTED_TIMEFRAMES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported timeframe '{req.timeframe}'. Must be one of: {SUPPORTED_TIMEFRAMES}",
        )
    if req.symbol not in FUTURES_SYMBOLS:
        raise HTTPException(
            status_code=400,
            detail=f"Symbol '{req.symbol}' is not in the supported futures symbol list",
        )

    result = await import_candles(
        job_id=req.jobId,
        exchange=req.exchange,
        symbol=req.symbol,
        timeframe=req.timeframe,
        start_date=req.startDate,
        end_date=req.endDate,
    )

    return {"success": True, "data": result}
