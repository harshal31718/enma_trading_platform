from fastapi import APIRouter
from config.mongo import get_database

router = APIRouter()


@router.get("/stats")
async def get_dashboard_stats():
    db = get_database()
    total_runs = await db.backtestResults.count_documents({"status": "completed"})
    completed_cursor = db.backtestResults.find(
        {"status": "completed"},
        {"strategyName": 1, "metrics.winRate": 1, "metrics.netProfit": 1, "metrics.sharpeRatio": 1, "_id": 0},
    )
    completed_runs = await completed_cursor.to_list(length=1000)

    stats = {
        "totalRuns": total_runs,
        "bestStrategy": "N/A",
        "averageWinRate": "0.00",
    }
    leaderboard = []

    if completed_runs:
        strategy_groups = {}
        total_win_rate = 0.0

        for run in completed_runs:
            s_name = run.get("strategyName")
            m = run.get("metrics", {})
            try:
                win_rate = float(m.get("winRate", 0.0))
            except (ValueError, TypeError):
                win_rate = 0.0
            try:
                net_profit = float(m.get("netProfit", 0.0))
            except (ValueError, TypeError):
                net_profit = 0.0
            try:
                sharpe = float(m.get("sharpeRatio", 0.0))
            except (ValueError, TypeError):
                sharpe = 0.0

            total_win_rate += win_rate

            if s_name not in strategy_groups:
                strategy_groups[s_name] = {
                    "runs": 0,
                    "totalWinRate": 0.0,
                    "totalNetProfit": 0.0,
                    "totalSharpe": 0.0,
                }

            g = strategy_groups[s_name]
            g["runs"] += 1
            g["totalWinRate"] += win_rate
            g["totalNetProfit"] += net_profit
            g["totalSharpe"] += sharpe

        stats["averageWinRate"] = f"{(total_win_rate / len(completed_runs)):.2f}"

        for name, g in strategy_groups.items():
            leaderboard.append({
                "strategyName": name,
                "runs": g["runs"],
                "averageWinRate": f"{(g['totalWinRate'] / g['runs']):.2f}",
                "averageNetProfit": f"{(g['totalNetProfit'] / g['runs']):.2f}",
                "averageSharpe": f"{(g['totalSharpe'] / g['runs']):.2f}",
            })

        leaderboard.sort(key=lambda x: float(x["averageNetProfit"]), reverse=True)
        if leaderboard:
            stats["bestStrategy"] = leaderboard[0]["strategyName"]

    return {
        "success": True,
        "data": {
            "stats": stats,
            "leaderboard": leaderboard,
        },
    }
