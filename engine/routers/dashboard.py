from fastapi import APIRouter, Query
from config.mongo import get_database

router = APIRouter()


def _safe_float(value, default=0.0):
    """Coerce a metric value to float; tolerate None/strings/bad input."""
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


@router.get("/stats")
async def get_dashboard_stats(userId: str = Query(default=None)):
    db = get_database()
    _filter = {"status": "completed"}
    if userId:
        _filter["userId"] = userId
    total_runs = await db.backtestResults.count_documents(_filter)
    completed_cursor = db.backtestResults.find(
        _filter,
        {
            "jobId": 1,
            "strategyName": 1,
            "metrics.winRate": 1,
            "metrics.netProfit": 1,
            "metrics.sharpeRatio": 1,
            "metrics.sortinoRatio": 1,
            "metrics.profitFactor": 1,
            "metrics.maxDrawdown": 1,
            "metrics.expectancy": 1,
            "updatedAt": 1,
            "_id": 0,
        },
    )
    completed_runs = await completed_cursor.to_list(length=1000)

    stats = {
        "totalRuns": total_runs,
        "bestStrategy": "N/A",
        "averageWinRate": "0.00",
        "avgProfitFactor": "0.00",
        "avgSharpe": "0.00",
        "avgSortino": "0.00",
        "worstDrawdown": "0.00",
        "avgExpectancy": "0.00",
        "latestRunId": None,
    }
    leaderboard = []

    if completed_runs:
        strategy_groups = {}
        total_win_rate = 0.0
        profit_factors = []
        sharpes = []
        sortinos = []
        drawdowns = []
        expectancies = []
        latest_run_id = None
        latest_updated_at = None

        for run in completed_runs:
            s_name = run.get("strategyName")
            m = run.get("metrics", {})

            win_rate = _safe_float(m.get("winRate"))
            net_profit = _safe_float(m.get("netProfit"))
            sharpe = _safe_float(m.get("sharpeRatio"))
            sortino = _safe_float(m.get("sortinoRatio"))
            profit_factor = _safe_float(m.get("profitFactor"))
            max_drawdown = _safe_float(m.get("maxDrawdown"))
            expectancy = _safe_float(m.get("expectancy"))

            total_win_rate += win_rate
            profit_factors.append(profit_factor)
            sharpes.append(sharpe)
            sortinos.append(sortino)
            drawdowns.append(max_drawdown)
            expectancies.append(expectancy)

            # Track the most-recent completed run by updatedAt
            run_updated = run.get("updatedAt")
            if run_updated is not None:
                if latest_updated_at is None or run_updated > latest_updated_at:
                    latest_updated_at = run_updated
                    latest_run_id = run.get("jobId")

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

        n = len(completed_runs)
        stats["averageWinRate"] = f"{(total_win_rate / n):.2f}"
        stats["avgProfitFactor"] = f"{(sum(profit_factors) / n):.2f}"
        stats["avgSharpe"] = f"{(sum(sharpes) / n):.2f}"
        stats["avgSortino"] = f"{(sum(sortinos) / n):.2f}"
        # worstDrawdown: the most-negative maxDrawdown across runs (maxDrawdown is
        # stored as a non-positive pct string; "worst" = deepest trough = min).
        stats["worstDrawdown"] = f"{(min(drawdowns) if drawdowns else 0.0):.2f}"
        stats["avgExpectancy"] = f"{(sum(expectancies) / n):.2f}"
        stats["latestRunId"] = latest_run_id

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


@router.get("/performance-calendar")
async def get_performance_calendar(userId: str = Query(default=None)):
    """Day-level P&L aggregation across ALL completed backtest trades.

    Queries the `backtestTrades` collection (minimal projection) and groups by
    `exitAt` date (YYYY-MM-DD). Returns total pnl and trade count per day,
    sorted by date ascending.
    """
    db = get_database()
    _trade_filter = {}
    if userId:
        _trade_filter["userId"] = userId
    cursor = db.backtestTrades.find(
        _trade_filter,
        {"exitAt": 1, "pnl": 1, "_id": 0},
    )
    trades = await cursor.to_list(length=100_000)

    by_day = {}
    for t in trades:
        exit_at = t.get("exitAt")
        if not exit_at:
            continue
        # exitAt is stored as ISO string; slice the YYYY-MM-DD prefix
        if isinstance(exit_at, str):
            day = exit_at[:10]
        else:
            # Defensive: convert datetime/other to ISO if needed
            try:
                day = exit_at.isoformat()[:10]
            except AttributeError:
                continue

        try:
            pnl_value = float(t.get("pnl", 0))
        except (ValueError, TypeError):
            pnl_value = 0.0

        if day not in by_day:
            by_day[day] = {"date": day, "pnl": 0.0, "trades": 0}
        by_day[day]["pnl"] = round(by_day[day]["pnl"] + pnl_value, 2)
        by_day[day]["trades"] += 1

    days = sorted(by_day.values(), key=lambda x: x["date"])
    return {
        "success": True,
        "data": {"days": days},
    }
