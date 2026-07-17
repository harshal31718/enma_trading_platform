"""Plan 9 Step 9.7 (QNT-5): single entry point for historical funding-rate
data — mirrors candle_manager.py's ensure_candles_available() contract.
Never bypass this to query the funding_rates table directly from a router
or the simulation loop.
"""
import logging
from datetime import datetime, timezone

from config.timescale import get_pool
from services.funding_importer import import_funding_rates

logger = logging.getLogger(__name__)


async def get_available_funding_count(exchange: str, symbol: str, start_date: str, end_date: str) -> int:
    start_dt = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
    end_dt = datetime.fromisoformat(end_date).replace(tzinfo=timezone.utc)

    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            result = await conn.fetchval(
                """
                SELECT COUNT(*) FROM funding_rates
                WHERE exchange = $1 AND symbol = $2 AND time >= $3 AND time < $4
                """,
                exchange, symbol, start_dt, end_dt,
            )
        return result or 0
    except Exception as e:
        logger.warning(f"Error checking funding-rate count: {e}")
        return 0


async def ensure_funding_available(
    job_id: str, exchange: str, symbol: str, start_date: str, end_date: str,
) -> bool:
    """Ensure funding-rate history exists for [start_date, end_date). Unlike
    ensure_candles_available(), there's no fixed-interval "warmup" concept —
    perpetual funding events are sparse (~every 8h) and irregular per symbol,
    so any nonzero count for the exact requested range is "available".
    Fetches on a cache miss and re-checks once. Returns True even when zero
    funding events genuinely occurred in a short window (a fetch that
    legitimately returns nothing is not a failure) — callers that need to
    distinguish "no data fetched" from "no funding events occurred" should
    inspect the actual row count themselves.
    """
    available = await get_available_funding_count(exchange, symbol, start_date, end_date)
    if available > 0:
        return True

    logger.info(f"[{job_id}] No cached funding rates for {symbol} {start_date}..{end_date} — fetching")
    try:
        result = await import_funding_rates(
            job_id=job_id, exchange=exchange, symbol=symbol, start_date=start_date, end_date=end_date,
        )
        logger.info(f"[{job_id}] Funding rates fetched: {result['fundingRatesImported']} imported")
        return True
    except Exception as e:
        logger.error(f"[{job_id}] Failed to auto-fetch funding rates: {e}")
        return False
