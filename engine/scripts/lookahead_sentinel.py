"""Lookahead-bias sentinel (Plan 9 Step 9.5, QNT-12 / detector for QNT-9).

`prepare(candles_np)` receives the FULL candle array including future candles
and trusts every strategy to only read causally. This harness catches a
strategy that doesn't: it runs each seeded strategy TWICE over the same
single-symbol window — once with the real (fast) full-array `prepare()`
call, once with `_reprep_every_candle=True` (`services/backtest_runner.py`),
which re-invokes `prepare()` every candle on a candles_np[:t+1] truncation,
simulating a strategy that can only ever see the past. A causal strategy
produces an IDENTICAL trade list either way. A divergence means the strategy
leaked future information (or made an assumption that only holds for a
full-length array, e.g. indexing from the end instead of `self.index`).

REQUIRES TA-Lib + the engine databases — run INSIDE the engine container.
Reuses whatever candles the golden master already cached (same default
symbol/date-range) — only fetches fresh from Binance on a cold DB, same
external-network caveat as scripts/golden_master.py.

    docker compose exec engine python -m scripts.lookahead_sentinel

Exit 0 = no divergence found for any seeded strategy. Exit 1 = at least one
strategy's trade list changed between full-array and expanding-window prepare.
"""
from __future__ import annotations

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

STRATEGIES = [
    "MicroScalper",
    "AdaptiveTrend",
    "BestSupertrend",
    "MicroMacroRSIDivergence",
    "MultiDivergence",
]

CONFIG = {
    "exchange": "Binance Futures",
    "symbol": "BTCUSDT",
    "timeframe": "1h",
    "start_date": "2024-01-01",
    "end_date": "2024-04-01",  # 3 months — enough candles to exercise indicators, short enough for O(n) re-prep to be fast
    "capital": 10_000.0,
    "leverage": 3,
    "fee_rate": 0.0005,
    "slippage_pct": 0.0005,
    "funding_enabled": False,
    "funding_rate": 0.0,
    "risk_params": {
        "risk_pct": 0.01,
        "rrr": 2.0,
        "liq_buffer_pct": 0.005,
        "max_session_dd": 0.20,
    },
}


def _trade_signature(trades: list[dict]) -> list[tuple]:
    """Reduce a trade list to the fields that matter for a lookahead check —
    exact prices are already covered by golden_master.py; here it's whether
    THE SAME decisions get made at all."""
    return [
        (t.get("type"), t.get("entryAt"), t.get("exitAt"), t.get("exitReason"), t.get("qty"))
        for t in trades
    ]


async def _run_one(name: str, reprep: bool) -> list[dict]:
    from config.timescale import get_pool
    from services.backtest_runner import run_backtest_simulation

    job_id = f"sentinel_{'reprep' if reprep else 'full'}_{name}"
    out = await run_backtest_simulation(
        job_id=job_id,
        strategy_file=f"strategies/{name}/__init__.py",
        exchange=CONFIG["exchange"],
        symbol=CONFIG["symbol"],
        timeframe=CONFIG["timeframe"],
        start_date=CONFIG["start_date"],
        end_date=CONFIG["end_date"],
        capital=CONFIG["capital"],
        leverage=CONFIG["leverage"],
        fee_rate=CONFIG["fee_rate"],
        slippage_pct=CONFIG["slippage_pct"],
        funding_enabled=CONFIG["funding_enabled"],
        funding_rate=CONFIG["funding_rate"],
        alpha_params=None,
        risk_params=CONFIG["risk_params"],
        _reprep_every_candle=reprep,
    )
    return out


async def main() -> int:
    from config.timescale import init_pool, close_pool
    from config.mongo import close_mongo, get_database

    await init_pool()
    divergences = []
    try:
        for name in STRATEGIES:
            print(f"[sentinel] {name}: running full-array prepare()...", flush=True)
            await _run_one(name, reprep=False)
            print(f"[sentinel] {name}: running expanding-window prepare() (slow)...", flush=True)
            await _run_one(name, reprep=True)

            db = get_database()
            full_trades = await db.backtestTrades.find({"jobId": f"sentinel_full_{name}"}).sort("tradeIndex", 1).to_list(length=10_000)
            reprep_trades = await db.backtestTrades.find({"jobId": f"sentinel_reprep_{name}"}).sort("tradeIndex", 1).to_list(length=10_000)

            full_sig = _trade_signature(full_trades)
            reprep_sig = _trade_signature(reprep_trades)

            if full_sig == reprep_sig:
                print(f"[sentinel] {name}: OK — {len(full_sig)} trades, identical either way", flush=True)
            else:
                divergences.append(name)
                print(
                    f"[sentinel] {name}: DIVERGENCE — full-array={len(full_sig)} trades, "
                    f"expanding-window={len(reprep_sig)} trades — possible lookahead bias",
                    flush=True,
                )

            # Cleanup this strategy's sentinel job docs before the next one.
            await db.backtestResults.delete_many({"jobId": {"$in": [f"sentinel_full_{name}", f"sentinel_reprep_{name}"]}})
            await db.backtestTrades.delete_many({"jobId": {"$in": [f"sentinel_full_{name}", f"sentinel_reprep_{name}"]}})
    finally:
        await close_pool()
        close_mongo()

    if divergences:
        print(f"[sentinel] LOOKAHEAD SENTINEL FAILED for: {', '.join(divergences)}")
        return 1
    print("[sentinel] LOOKAHEAD SENTINEL OK — no divergence for any seeded strategy")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
