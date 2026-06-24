import hashlib
import random
from typing import Dict, Any
from config.mongo import get_database

async def run_monte_carlo_simulation(job_id: str) -> Dict[str, Any]:
    db = get_database()

    # Fetch the parent backtest capital so we can express each trade's PnL as a
    # fraction of the STARTING equity (equity-based return), not as ROE (return
    # on margin). pnlPct in backtestTrades is ROE which is leverage-amplified and
    # unsuitable for compounding equity paths — a 10x trade hitting a 1% move
    # shows pnlPct=10%, but the actual equity impact was 1%.
    parent = await db.backtestResults.find_one({"jobId": job_id}, {"capital": 1})
    capital = float(parent.get("capital", 10000.0)) if parent else 10000.0

    cursor = db.backtestTrades.find({"jobId": job_id})
    trades = await cursor.to_list(length=100000)

    default_dist = [
        {"drawdownPct": "10.00", "probability": "0.000"},
        {"drawdownPct": "20.00", "probability": "0.000"},
        {"drawdownPct": "30.00", "probability": "0.000"},
        {"drawdownPct": "40.00", "probability": "0.000"},
        {"drawdownPct": "50.00", "probability": "0.000"}
    ]

    if not trades:
        return {
            "ruinProbability": "0.000",
            "drawdownDistribution": default_dist
        }

    returns = []
    for t in trades:
        try:
            # Equity-based return: pnl as a fraction of starting capital.
            # This gives the correct equity-path compounding regardless of leverage.
            pnl = float(t.get("pnl", 0.0))
            val = pnl / capital
            returns.append(val)
        except (ValueError, TypeError):
            continue
            
    if not returns:
        return {
            "ruinProbability": "0.000",
            "drawdownDistribution": default_dist
        }

    # Seed random generator deterministically using jobId
    seed_int = int(hashlib.md5(job_id.encode()).hexdigest()[:8], 16)
    rng = random.Random(seed_int)
    
    N_RUNS = 2000
    T = len(returns)
    
    drawdown_breaches = {10.0: 0, 20.0: 0, 30.0: 0, 40.0: 0, 50.0: 0}
    ruin_breaches = 0  # using 30% as default ruin threshold
    
    for _ in range(N_RUNS):
        equity = 1.0
        peak = 1.0
        max_dd = 0.0
        
        # Draw T trades with replacement
        for _ in range(T):
            r = rng.choice(returns)
            equity *= (1.0 + r)
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak if peak > 0 else 0.0
            if dd > max_dd:
                max_dd = dd
                
        # Record drawdown threshold breaches
        for threshold in drawdown_breaches.keys():
            if max_dd >= (threshold / 100.0):
                drawdown_breaches[threshold] += 1
                
        if max_dd >= 0.30:
            ruin_breaches += 1
            
    ruin_prob = ruin_breaches / N_RUNS
    
    dist = [
        {"drawdownPct": f"{k:.2f}", "probability": f"{(v / N_RUNS):.3f}"}
        for k, v in sorted(drawdown_breaches.items())
    ]
    
    return {
        "ruinProbability": f"{ruin_prob:.3f}",
        "drawdownDistribution": dist
    }
