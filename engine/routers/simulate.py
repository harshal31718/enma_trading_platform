"""Strategy Lab job endpoints (Plan 10 Phase 1).

Thin async-job-semantics router, same pattern as `routers/backtest.py`:
Node's worker POSTs here and awaits the response; the engine function itself
persists the full result (engine is sole writer of `labResults.results`/
`status`), so a success response needs no further write here — only the
failure path updates the doc, mirroring `backtest.py`'s own asymmetry.
"""
from datetime import datetime, timezone
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config.mongo import get_database
from services.monte_carlo import run_lab_simulation
from services.walk_forward import run_lab_walk_forward

router = APIRouter()
logger = logging.getLogger(__name__)


class LabSimulationRequest(BaseModel):
    simId: str
    sourceJobId: str
    userId: str = ""
    config: dict = {}
    configHash: str = ""


@router.post("/monte-carlo")
async def run_monte_carlo(req: LabSimulationRequest):
    try:
        results = await run_lab_simulation(
            sim_id=req.simId,
            source_job_id=req.sourceJobId,
            config=req.config,
            config_hash=req.configHash,
        )
        return {"success": True, "data": results}
    except Exception as e:
        logger.error(f"Lab simulation {req.simId} failed: {e}")
        db = get_database()
        await db.labResults.update_one(
            {"labId": req.simId},
            {"$set": {"status": "failed", "error": str(e), "updatedAt": datetime.now(timezone.utc)}},
        )
        raise HTTPException(status_code=500, detail=str(e))


class LabOptimizationRequest(BaseModel):
    labId: str
    userId: str = ""
    config: dict = {}
    configHash: str = ""


@router.post("/optimize")
async def run_walk_forward_optimization(req: LabOptimizationRequest):
    """Plan 10 Phase 3a — job-based walk-forward optimization. Same thin
    async-job-semantics pattern as `run_monte_carlo` above: the service
    persists the full result itself (engine sole writer), this handler only
    writes on the failure path."""
    try:
        results = await run_lab_walk_forward(
            lab_id=req.labId,
            config=req.config,
            config_hash=req.configHash,
        )
        return {"success": True, "data": results}
    except Exception as e:
        logger.error(f"Lab optimization {req.labId} failed: {e}")
        db = get_database()
        await db.labResults.update_one(
            {"labId": req.labId},
            {"$set": {"status": "failed", "error": str(e), "updatedAt": datetime.now(timezone.utc)}},
        )
        raise HTTPException(status_code=500, detail=str(e))
