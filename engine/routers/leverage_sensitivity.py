from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from services.leverage_sensitivity_runner import run_leverage_sensitivity
from services.monte_carlo import run_monte_carlo_simulation

router = APIRouter()

class LeverageSensitivityRequest(BaseModel):
    jobId: str

@router.post("/run/leverage-sensitivity")
async def trigger_simulations(req: LeverageSensitivityRequest):
    try:
        # 1. Run leverage sensitivity simulation re-running backtest 5x
        lev_res = await run_leverage_sensitivity(req.jobId)
        
        # 2. Run Monte Carlo bootstrap resampling
        mc_res = await run_monte_carlo_simulation(req.jobId)
        
        return {
            "success": True,
            "data": {
                "leverageSensitivity": lev_res["leverageSensitivity"],
                "monteCarlo": mc_res
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
