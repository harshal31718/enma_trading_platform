import logging
from datetime import datetime, timezone
from config.mongo import get_database
from services.backtest_runner import run_backtest_simulation

logger = logging.getLogger(__name__)

async def run_leverage_sensitivity(source_job_id: str) -> dict:
    db = get_database()
    
    # 1. Fetch parent backtest result
    parent = await db.backtestResults.find_one({"jobId": source_job_id})
    if not parent:
        raise ValueError(f"Parent backtest result not found: {source_job_id}")
        
    # Check if we already have all 5 simulations computed
    existing = await db.backtestLeverageScenarios.find({"sourceJobId": source_job_id}).to_list(length=100)
    if len(existing) == 5:
        return {
            "leverageSensitivity": [
                {
                    "leverage": s["leverage"],
                    "netProfitPct": s["netProfitPct"],
                    "maxDrawdownPct": s["maxDrawdownPct"]
                }
                for s in sorted(existing, key=lambda x: x["leverage"])
            ]
        }
        
    leverage_levels = [1, 2, 5, 10, 20]
    results = []
    
    # Resolve strategy file path
    strategy_name = parent.get("strategyName")
    strategy_doc = await db.strategies.find_one({"name": strategy_name})
    strategy_file = strategy_doc.get("filePath") if strategy_doc else f"strategies/{strategy_name}"
    
    for lev in leverage_levels:
        temp_job_id = f"{source_job_id}_lev_{lev}"
        try:
            # Re-run simulation with the target leverage
            sim_res = await run_backtest_simulation(
                job_id=temp_job_id,
                strategy_file=strategy_file,
                exchange=parent.get("exchange"),
                symbol=parent.get("symbol"),
                timeframe=parent.get("timeframe"),
                start_date=parent.get("startDate"),
                end_date=parent.get("endDate"),
                capital=float(parent.get("capital", 10000.0)),
                leverage=lev,
                fee_rate=float(parent.get("feeRate", 0.0005)),
                slippage_pct=float(parent.get("slippagePct") if parent.get("slippagePct") is not None else 0.0005),
                funding_enabled=bool(parent.get("fundingEnabled", False)),
                funding_rate=float(parent.get("fundingRate") if parent.get("fundingRate") is not None else 0.0001),
                alpha_params=parent.get("alphaParams") or {},
                risk_params=parent.get("riskParams") or {}
            )
            
            metrics = sim_res.get("metrics", {})
            # backtest_runner returns these metrics as pre-formatted strings
            # (e.g. "12.34"); cast to float before re-formatting.
            net_profit_pct = f"{float(metrics.get('netProfitPct', 0.0)):.2f}"
            # metric key is "maxDrawdown" (a signed pct string), not "maxDrawdownPct"
            max_dd_pct = f"{float(metrics.get('maxDrawdown', 0.0)):.2f}"
            
            # Persist in backtestLeverageScenarios
            scenario_doc = {
                "sourceJobId": source_job_id,
                "leverage": lev,
                "netProfitPct": net_profit_pct,
                "maxDrawdownPct": max_dd_pct,
                "metrics": metrics,
                "equityCurve": sim_res.get("equityCurve", []),
                "createdAt": datetime.now(timezone.utc),
                "updatedAt": datetime.now(timezone.utc)
            }
            
            await db.backtestLeverageScenarios.update_one(
                {"sourceJobId": source_job_id, "leverage": lev},
                {"$set": scenario_doc},
                upsert=True
            )
            
            results.append({
                "leverage": lev,
                "netProfitPct": net_profit_pct,
                "maxDrawdownPct": max_dd_pct
            })
            
        except Exception as e:
            logger.error(f"Failed running leverage sensitivity simulation for {lev}x: {e}")
            raise e
        finally:
            # Ensure database is cleaned of temporary job results
            await db.backtestResults.delete_one({"jobId": temp_job_id})
            await db.backtestTrades.delete_many({"jobId": temp_job_id})
            
    return {"leverageSensitivity": results}
