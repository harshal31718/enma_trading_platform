from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import os
import redis.asyncio as aioredis
from datetime import datetime, timezone
import logging

from services.backtest_runner import run_backtest_simulation
from config.mongo import get_database
from config.timescale import get_pool

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
    # Strategy alpha parameters (Tier 3) — keyed by PARAMS name, clamped by runner.
    alphaParams:    dict  = {}
    # Risk model parameters (Tier 2) — override global settings for this run.
    riskParams:     dict  = {}


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
            alpha_params=req.alphaParams,
            risk_params=req.riskParams,
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


@router.get("/{job_id}/benchmark")
async def get_backtest_benchmark(job_id: str):
    """Buy & Hold benchmark series for a completed run.

    Reads the same TimescaleDB OHLCV candles the backtest used and returns a
    Buy & Hold equity path normalized to the run's starting capital
    (capital * close / first_close). The series is aligned 1:1 with the saved
    (downsampled) equity-curve timestamps so the client can overlay it directly,
    and it shares the equity dollar scale — no price-range/log handling needed.
    """
    db = get_database()
    result = await db.backtestResults.find_one({"jobId": job_id})
    if not result:
        raise HTTPException(status_code=404, detail="Backtest result not found")

    equity_curve = result.get("equityCurve") or []
    capital = float(result.get("capital") or 0)
    if not equity_curve or capital <= 0:
        return {"success": True, "data": {"benchmark": []}}

    # startDate/endDate stored on the doc are the actual first/last candle times,
    # so this window selects exactly the candle set the simulation replayed.
    start_dt = datetime.fromisoformat(result["startDate"])
    end_dt = datetime.fromisoformat(result["endDate"])

    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT time, close
            FROM candles
            WHERE exchange = $1 AND symbol = $2 AND timeframe = $3
              AND time >= $4 AND time <= $5
            ORDER BY time ASC
            """,
            result["exchange"], result["symbol"], result["timeframe"],
            start_dt, end_dt,
        )

    if not rows:
        return {"success": True, "data": {"benchmark": []}}

    # Equity-curve timestamps are candle times (same TimescaleDB source), so an
    # isoformat keyed lookup aligns the two series exactly.
    close_by_ts = {r["time"].isoformat(): float(r["close"]) for r in rows}

    # Reference = close at the first equity-curve point (matches the
    # buyHoldReturnPct reference in metrics: the first post-warmup close).
    first_close = close_by_ts.get(equity_curve[0]["timestamp"]) or float(rows[0]["close"])
    if first_close <= 0:
        return {"success": True, "data": {"benchmark": []}}

    benchmark = []
    last_val = capital
    for point in equity_curve:
        close = close_by_ts.get(point["timestamp"])
        if close is not None:
            last_val = capital * (close / first_close)
        # carry the last known value forward if a candle is ever missing,
        # keeping the series length identical to the equity curve
        benchmark.append({"timestamp": point["timestamp"], "buyHold": f"{last_val:.2f}"})

    return {"success": True, "data": {"benchmark": benchmark}}


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
