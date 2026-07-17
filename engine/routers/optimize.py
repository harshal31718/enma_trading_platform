"""Parameter optimization API routes (A-006).

Provides endpoints to run and query parameter optimization jobs against
the existing backtest engine.
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from config.mongo import get_database
from services.optimizer import list_objectives, run_optimization, OptimizerConfig

router = APIRouter()
logger = logging.getLogger(__name__)


class OptimizeRequest(BaseModel):
    jobId: str = ""
    strategyFile: str
    exchange: str = "Binance Futures"
    symbol: str
    timeframe: str
    startDate: str
    endDate: str
    capital: float
    leverage: int = 10
    feeRate: float = 0.0005
    slippagePct: float | None = None
    fundingEnabled: bool = False
    fundingRate: float | None = None
    riskParams: dict = {}
    objective: str = "sharpe"
    maxCombinations: int = 0  # 0 = full grid
    paramGrid: dict  # see services/optimizer.py _expand_param_range spec


class ObjectiveListResponse(BaseModel):
    objectives: list[str]


@router.get("/objectives")
async def list_optimization_objectives():
    """Return the list of available objective functions."""
    return {"success": True, "data": {"objectives": list_objectives()}}


@router.post("/run")
async def start_optimization(req: OptimizeRequest):
    """Run a parameter optimization across the specified grid."""
    if not req.paramGrid:
        raise HTTPException(status_code=400, detail="paramGrid must not be empty")

    available = list_objectives()
    if req.objective not in available:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown objective '{req.objective}'. Available: {available}",
        )

    job_id = req.jobId or (
        f"opt_{req.strategyFile.split('/')[-1]}_"
        f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    )

    config = OptimizerConfig(
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
        risk_params=req.riskParams,
        objective=req.objective,
        max_combinations=req.maxCombinations,
    )

    try:
        result = await run_optimization(
            config=config,
            param_grid=req.paramGrid,
            job_id=job_id,
        )
        return {"success": True, "data": result}
    except Exception as e:
        logger.error(f"Optimization {job_id} failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{job_id}/status")
async def get_optimization_status(job_id: str):
    """Check the status of an optimization run."""
    try:
        db = get_database()
        doc = await db.backtestResults.find_one(
            {"jobId": job_id, "type": "optimization"},
            {"_id": 0, "jobId": 1, "status": 1, "objective": 1,
             "totalCombinations": 1, "errorCount": 1, "updatedAt": 1},
        )
        if not doc:
            return {"success": True, "data": {"status": "not_found"}}
        if isinstance(doc.get("updatedAt"), datetime):
            doc["updatedAt"] = doc["updatedAt"].isoformat()
        return {"success": True, "data": doc}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{job_id}/results")
async def get_optimization_results(job_id: str):
    """Return the full results of a completed optimization."""
    try:
        db = get_database()
        doc = await db.optimizationResults.find_one(
            {"jobId": job_id},
            {"_id": 0},
        )
        if not doc:
            return {"success": True, "data": {"status": "not_found"}}
        if isinstance(doc.get("createdAt"), datetime):
            doc["createdAt"] = doc["createdAt"].isoformat()
        return {"success": True, "data": doc}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
