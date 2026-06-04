import logging
import os
from datetime import datetime, timezone

from config.mongo import get_database

logger = logging.getLogger(__name__)

STRATEGIES_DIR = os.path.join(os.path.dirname(__file__), "..", "strategies")

DEFAULT_STRATEGIES = [
    {
        "name": "SimpleEMACross",
        "description": "Fast/slow EMA crossover. Goes long on golden cross, short on death cross. Uses ATR for dynamic stop-loss sizing.",
    },
    {
        "name": "RSIReversion",
        "description": "RSI mean reversion. Goes long when RSI < 30 (oversold), short when RSI > 70 (overbought). Exits when RSI reverts to 50.",
    },
    {
        "name": "DonchianBreakout",
        "description": "Donchian channel breakout. Goes long on upper channel break, short on lower channel break. Exits at middle band.",
    },
    {
        "name": "MicroScalper",
        "description": "High-frequency stop-and-reverse scalper built for pipeline stress testing. Logic: 3/9 EMA crossover on 1m candles with an optional ATR volatility filter. Always in a position.",
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
