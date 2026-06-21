import logging
import os
from datetime import datetime, timezone

from config.mongo import get_database

logger = logging.getLogger(__name__)

STRATEGIES_DIR = os.path.join(os.path.dirname(__file__), "..", "strategies")

# NOTE: PnlFixer is intentionally NOT in this list — it was removed in a prior
# session and does not exist in the codebase.  The chaos runner's allow-list
# explicitly excludes it so it can never accidentally be re-introduced.
DEFAULT_STRATEGIES = [
    {
        "name": "MicroScalper",
        "description": "High-frequency stop-and-reverse scalper built for pipeline stress testing. Logic: 3/9 EMA crossover on 1m candles with an optional ATR volatility filter. Always in a position.",
    },
    {
        "name": "AdaptiveTrend",
        "description": "Regime-aware trend follower. Four layers must agree: trend-EMA regime, fast/slow EMA momentum cross, an ATR volatility gate, and volatility-targeted risk sizing. Exits via a chandelier ATR trailing stop with breakeven ratchet. Best on 1h/4h deep-liquidity pairs.",
    },
    {
        "name": "BestSupertrend",
        "description": "Multi-timeframe Supertrend trend follower combined with SMA crossovers. Filters entries by higher-timeframe Supertrend and exits on SMA crosses.",
    },
    {
        "name": "MicroMacroRSIDivergence",
        "description": "Regular RSI-divergence reversal with micro+macro pivot confluence. A macro swing-pivot divergence triggers only when a same-side micro divergence sits within the confluence window; filtered by RSI 50-level, RSI direction, smoothed-RSI, and pivot-distance/min-RSI-diff gates. Exits on ATR stop + R:R target plus optional opposite-divergence early exit. Best on 1h/4h.",
    },
    {
        "name": "MultiDivergence",
        "description": "Multi-oscillator divergence confluence (ported from the GainzAlgo Multi-Divergence Pine screener). Detects regular divergence between price swing pivots and nine sources (RSI, MFI, Stochastic, Z-Score, ADX, MACD, OBV, price-action, swing-volume); enters when at least N sources agree on a new pivot. ATR-based SL/TP with risk-per-trade sizing. Long & short.",
    },
]


async def seed_strategies():
    """
    Idempotent seeder — runs on engine startup.
    Creates strategy folders/files on disk if missing.
    Upserts metadata into MongoDB strategies collection.
    """
    db = get_database()

    for strategy in DEFAULT_STRATEGIES:
        name = strategy["name"]
        strategy_dir = os.path.join(STRATEGIES_DIR, name)
        file_path = os.path.join(strategy_dir, "__init__.py")
        relative_path = f"strategies/{name}/__init__.py"

        os.makedirs(strategy_dir, exist_ok=True)

        if not os.path.exists(file_path):
            logger.warning("Strategy file not found on disk: %s", file_path)
            continue

        await db.strategies.update_one(
            {"name": name},
            {
                "$set": {
                    "name": name,
                    "description": strategy["description"],
                    "filePath": relative_path,
                    "updatedAt": datetime.now(timezone.utc),
                },
                "$setOnInsert": {
                    "createdAt": datetime.now(timezone.utc),
                },
            },
            upsert=True,
        )
        logger.info("Strategy ready: %s", name)
