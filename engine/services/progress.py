import json
import os

import redis.asyncio as aioredis


async def publish_progress(
    job_id: str,
    pct: int,
    message: str,
    candles_fetched: int,
    total_estimate: int,
) -> None:
    r = aioredis.from_url(os.getenv("REDIS_URL", "redis://redis:6379"))
    payload = json.dumps({
        "pct": pct,
        "message": message,
        "candlesFetched": candles_fetched,
        "totalEstimate": total_estimate,
    })
    await r.publish(f"progress:{job_id}", payload)
    await r.aclose()
