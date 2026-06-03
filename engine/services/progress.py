import json
import os

import redis.asyncio as aioredis

# Module-level client — created once, reused across all publish calls.
# Using a pool avoids the per-call connect/disconnect overhead that causes
# Redis connection exhaustion on long simulations (thousands of candles).
_redis_client: aioredis.Redis | None = None


def _get_client() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            os.getenv("REDIS_URL", "redis://redis:6379"),
            decode_responses=True,
        )
    return _redis_client


async def publish_progress(
    job_id: str,
    pct: int,
    message: str,
    candles_fetched: int,
    total_estimate: int,
) -> None:
    r = _get_client()
    payload = json.dumps({
        "pct": pct,
        "message": message,
        "candlesFetched": candles_fetched,
        "totalEstimate": total_estimate,
    })
    await r.publish(f"progress:{job_id}", payload)
