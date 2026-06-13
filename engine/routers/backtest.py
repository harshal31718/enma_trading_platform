from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import os
import redis.asyncio as aioredis
from datetime import datetime, timezone
import logging

from services.backtest_runner import run_backtest_simulation
from config.mongo import get_database

router = APIRouter()
logger = logging.getLogger(__name__)


class BacktestRequest(BaseModel):
    jobId: str
    strategyFile: str
    exchange: str
    symbol: str
    timeframe: str
    startDate: str
    endDate: str
    capital: float
    leverage: int
    feeRate: float
    # Simulation-realism overrides — server injects from saved exchange settings.
    # Optional with safe defaults so existing callers without these fields still work.
    slippagePct:    float = 0.0005
    fundingEnabled: bool  = False
    fundingRate:    float = 0.0001


class CancelRequest(BaseModel):
    jobId: str


@router.post("/run")
async def run_backtest(req: BacktestRequest):
    try:
        res = await run_backtest_simulation(
            job_id=req.jobId,
            strategy_file=req.strategyFile,
            exchange=req.exchange,
            symbol=req.symbol,
            timeframe=req.timeframe,
            start_date=req.startDate,
            end_date=req.endDate,
            capital=req.capital,
            leverage=req.leverage,
            fee_rate=req.feeRate,
            slippage_pct=req.slippagePct,
            funding_enabled=req.fundingEnabled,
            funding_rate=req.fundingRate,
        )
        return {"success": True, "data": res}
    except Exception as e:
        logger.error(f"Backtest {req.jobId} failed: {e}")

        db = get_database()

        parts = req.strategyFile.split("/")
        strategy_name = parts[1] if len(parts) >= 2 else req.strategyFile
        strategy_doc = await db.strategies.find_one({"name": strategy_name})
        strategy_id = str(strategy_doc["_id"]) if strategy_doc else None

        is_cancelled = str(e) == "JOB_CANCELLED"
        status = "cancelled" if is_cancelled else "failed"

        await db.backtestResults.update_one(
            {"jobId": req.jobId},
            {
                "$set": {
                    "jobId": req.jobId,
                    "strategyId": strategy_id,
                    "strategyName": strategy_name,
                    "exchange": req.exchange,
                    "symbol": req.symbol,
                    "timeframe": req.timeframe,
                    "startDate": req.startDate,
                    "endDate": req.endDate,
                    "capital": req.capital,
                    "leverage": req.leverage,
                    "feeRate": req.feeRate,
                    "status": status,
                    "error": str(e),
                    "updatedAt": datetime.now(timezone.utc),
                },
                "$setOnInsert": {
                    "createdAt": datetime.now(timezone.utc)
                }
            },
            upsert=True
        )

        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cancel")
async def cancel_backtest(req: CancelRequest):
    redis_url = os.getenv("REDIS_URL", "redis://redis:6379")
    r_client = aioredis.from_url(redis_url)
    await r_client.publish(f"backtest:cancel:{req.jobId}", "cancel")
    await r_client.aclose()

    db = get_database()
    await db.backtestResults.update_one(
        {"jobId": req.jobId},
        {"$set": {"status": "cancelled", "error": "Cancelled by user", "updatedAt": datetime.now(timezone.utc)}},
    )

    return {"success": True, "data": {"jobId": req.jobId, "status": "cancelled"}}
