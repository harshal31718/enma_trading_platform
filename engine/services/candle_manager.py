import asyncio
import logging
from datetime import datetime, timezone, timedelta
from config.timescale import get_pool
from services.candle_importer import import_candles
from services.progress import publish_progress

logger = logging.getLogger(__name__)

WARMUP_CANDLES = 50  # Minimum candles needed for indicator warm-up
EXTRA_FETCH_CANDLES = 200  # Extra candles to fetch before start date for safety


def _timeframe_to_timedelta(timeframe: str) -> timedelta:
    """Convert timeframe string to timedelta (e.g., '1h' -> timedelta(hours=1))."""
    try:
        val = int(timeframe[:-1])
        unit = timeframe[-1]
    except Exception:
        return timedelta(hours=1)

    if unit == "m":
        return timedelta(minutes=val)
    elif unit == "h":
        return timedelta(hours=val)
    elif unit == "d":
        return timedelta(days=val)
    elif unit == "w":
        return timedelta(weeks=val)
    return timedelta(hours=1)


async def get_available_candles_count(
    exchange: str,
    symbol: str,
    timeframe: str,
    start_date: str,
    end_date: str,
) -> int:
    """Check how many candles exist in TimescaleDB for the given parameters."""
    start_dt = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
    end_dt = datetime.fromisoformat(end_date).replace(tzinfo=timezone.utc)

    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            result = await conn.fetchval(
                """
                SELECT COUNT(*) FROM candles
                WHERE exchange = $1 AND symbol = $2 AND timeframe = $3
                AND time >= $4 AND time < $5
                """,
                exchange,
                symbol,
                timeframe,
                start_dt,
                end_dt,
            )
        return result or 0
    except Exception as e:
        logger.warning(f"Error checking candle count: {e}")
        return 0


async def ensure_candles_available(
    job_id: str,
    exchange: str,
    symbol: str,
    timeframe: str,
    start_date: str,
    end_date: str,
) -> bool:
    """
    Ensure sufficient candles exist for backtesting.
    If not, automatically fetch them with extended date range.
    Returns True if candles are now available, False otherwise.
    """
    start_dt = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
    end_dt = datetime.fromisoformat(end_date).replace(tzinfo=timezone.utc)

    # Check existing candles
    available = await get_available_candles_count(
        exchange, symbol, timeframe, start_date, end_date
    )

    logger.info(
        f"[{job_id}] Checking candles: {available} available for {symbol} {timeframe} "
        f"({start_date} to {end_date})"
    )

    if available >= WARMUP_CANDLES:
        logger.info(f"[{job_id}] Sufficient candles available. Proceeding with backtest.")
        return True

    # Need to fetch candles
    # Extend start date to include warm-up period
    tf_delta = _timeframe_to_timedelta(timeframe)
    extended_start_dt = start_dt - (tf_delta * EXTRA_FETCH_CANDLES)
    extended_end_dt = end_dt

    extended_start = extended_start_dt.isoformat()
    extended_end = extended_end_dt.isoformat()

    logger.info(
        f"[{job_id}] Insufficient candles ({available}/{WARMUP_CANDLES}). "
        f"Auto-fetching from {extended_start} to {extended_end}"
    )

    # Publish progress: starting fetch
    estimated_total = int((extended_end_dt - extended_start_dt) / tf_delta)
    await publish_progress(
        job_id=job_id,
        pct=0,
        message=f"Auto-fetching candles for {symbol} {timeframe} — 0%",
        candles_fetched=0,
        total_estimate=estimated_total,
    )

    try:
        result = await import_candles(
            job_id=job_id,
            exchange=exchange,
            symbol=symbol,
            timeframe=timeframe,
            start_date=extended_start,
            end_date=extended_end,
        )

        logger.info(
            f"[{job_id}] Candles fetched: {result['candlesImported']} total imported"
        )

        # Verify candles are now available
        available_after = await get_available_candles_count(
            exchange, symbol, timeframe, start_date, end_date
        )

        logger.info(
            f"[{job_id}] After import: {available_after} candles available for backtest period"
        )

        if available_after < WARMUP_CANDLES:
            logger.error(
                f"[{job_id}] Still insufficient candles after import: {available_after}/{WARMUP_CANDLES}"
            )
            return False

        return True

    except Exception as e:
        logger.error(f"[{job_id}] Failed to auto-fetch candles: {e}")
        return False


async def get_cached_candles_summary() -> list:
    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT symbol, timeframe, exchange, instrument_type,
                       MIN(time) AS start_date, MAX(time) AS end_date, COUNT(*) AS total_candles
                FROM candles
                GROUP BY symbol, timeframe, exchange, instrument_type
                ORDER BY symbol, timeframe
                """
            )
            return [
                {
                    "symbol": r["symbol"].replace("/", "-"),
                    "timeframe": r["timeframe"],
                    "exchange": r["exchange"],
                    "instrument_type": r["instrument_type"],
                    "start_date": r["start_date"].isoformat() if r["start_date"] else None,
                    "end_date": r["end_date"].isoformat() if r["end_date"] else None,
                    "total_candles": r["total_candles"],
                }
                for r in rows
            ]
    except Exception as e:
        logger.error(f"Error fetching cached candles summary: {e}")
        return []
