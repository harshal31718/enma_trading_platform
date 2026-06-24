"""I-06 (F-017) integration check: a multi-symbol backtest runs the shared-wallet
portfolio path end-to-end and returns a sane combined result.

    docker exec enma_trading_platform-engine-1 python -m scripts._portfolio_check
"""
import asyncio
import os
import sys

try:
    if not os.path.exists("/engine"):
        os.symlink("/app", "/engine")
except Exception:
    pass
sys.path.insert(0, "/")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


async def main():
    from config.timescale import init_pool, close_pool
    from config.mongo import close_mongo, get_database
    from services.backtest_runner import run_backtest_simulation

    await init_pool()
    try:
        capital = 10_000.0
        job_id = "portfolio_check_multi"
        out = await run_backtest_simulation(
            job_id=job_id,
            strategy_file="strategies/BestSupertrend/__init__.py",
            exchange="Binance Futures",
            symbol="BTCUSDT,ETHUSDT",
            timeframe="1h",
            start_date="2024-01-01",
            end_date="2024-03-01",
            capital=capital,
            leverage=3,
            fee_rate=0.0005,
            slippage_pct=0.0005,
            funding_enabled=False,
            funding_rate=0.0,
            alpha_params=None,
            risk_params={"risk_pct": 0.01, "rrr": 2.0,
                         "liq_buffer_pct": 0.005, "max_session_dd": 0.20},
        )
        m = out.get("metrics", {})
        db = get_database()
        doc = await db.backtestResults.find_one({"jobId": job_id})
        eq = (doc or {}).get("equityCurve", [])
        print(f"[portfolio] totalTrades={m.get('totalTrades')} "
              f"startingBalance={m.get('startingBalance')} "
              f"finishingBalance={m.get('finishingBalance')} "
              f"netProfit={m.get('netProfit')} "
              f"equityPoints={len(eq)}")

        # Assertions: the shared-wallet portfolio path executed and produced a
        # coherent combined result.
        assert m, "no metrics returned"
        assert m.get("startingBalance") == f"{capital:.2f}", \
            f"startingBalance should be full shared capital, got {m.get('startingBalance')}"
        assert int(m.get("totalTrades", 0)) >= 1, "expected at least one trade across the two symbols"
        assert len(eq) >= 2, "expected a non-trivial portfolio equity curve"
        # Portfolio curve should start at (near) the full shared capital, not a split.
        first_bal = float(eq[0]["balance"])
        assert abs(first_bal - capital) < capital * 0.5, \
            f"first equity point {first_bal} not near full capital {capital}"
        print("[portfolio] OK — shared-wallet multi-symbol path verified")
    finally:
        await close_pool()
        close_mongo()


if __name__ == "__main__":
    asyncio.run(main())
