import asyncio
import os
from datetime import datetime, timezone

from config.mongo import get_database
from config.timescale import get_pool
from core.constants import DEFAULT_BATCH_SIZE
from services.progress import publish_progress
from utils.symbols import get_ccxt_exchange, to_ccxt_symbol


def _timeframe_to_ms(timeframe: str) -> int:
    units = {"m": 60_000, "h": 3_600_000, "d": 86_400_000, "w": 604_800_000}
    return int(timeframe[:-1]) * units[timeframe[-1]]


async def import_candles(
    job_id: str,
    exchange: str,
    symbol: str,
    timeframe: str,
    start_date: str,
    end_date: str,
) -> dict:
    ex = get_ccxt_exchange(exchange)
    ccxt_symbol = to_ccxt_symbol(symbol)

    start_dt = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
    end_dt = datetime.fromisoformat(end_date).replace(tzinfo=timezone.utc)
    start_ms = int(start_dt.timestamp() * 1000)
    end_ms = int(end_dt.timestamp() * 1000)

    tf_ms = _timeframe_to_ms(timeframe)
    total_estimate = max(1, (end_ms - start_ms) // tf_ms)

    instrument_type = "perpetual" if exchange == "Binance Futures" else "spot"
    fetch_delay_ms = int(os.getenv("BINANCE_FETCH_DELAY_MS", "200")) / 1000

    current_ms = start_ms
    total_inserted = 0
    pool = get_pool()

    while current_ms < end_ms:
        raw = await asyncio.to_thread(
            ex.fetch_ohlcv,
            ccxt_symbol,
            timeframe,
            since=current_ms,
            limit=DEFAULT_BATCH_SIZE,
        )
        if not raw:
            break

        # Filter out candles beyond end date
        raw = [c for c in raw if c[0] < end_ms]
        if not raw:
            break

        # Build rows: (time, exchange, symbol, timeframe, instrument_type, open, high, low, close, volume, quote_volume)
        # quote_volume is not returned by ccxt fetch_ohlcv default klines — set to 0 for now
        rows = [
            (
                datetime.fromtimestamp(c[0] / 1000, tz=timezone.utc),
                exchange,
                symbol,
                timeframe,
                instrument_type,
                c[1],  # open
                c[2],  # high
                c[3],  # low
                c[4],  # close
                c[5],  # volume
                0,     # quote_volume — not available in standard OHLCV; future pass will use full kline endpoint
            )
            for c in raw
        ]

        async with pool.acquire() as conn:
            await conn.executemany(
                """
                INSERT INTO candles
                    (time, exchange, symbol, timeframe, instrument_type, open, high, low, close, volume, quote_volume)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                ON CONFLICT DO NOTHING
                """,
                rows,
            )

        total_inserted += len(rows)
        current_ms = raw[-1][0] + tf_ms

        pct = min(99, int((total_inserted / total_estimate) * 100))
        await publish_progress(
            job_id=job_id,
            pct=pct,
            message=f"Fetched {total_inserted} / ~{total_estimate} candles",
            candles_fetched=total_inserted,
            total_estimate=total_estimate,
        )

        await asyncio.sleep(fetch_delay_ms)

    # Write import record to MongoDB
    db = get_database()
    await db.candleImports.insert_one({
        "jobId": job_id,
        "exchange": exchange,
        "symbol": symbol,
        "timeframe": timeframe,
        "startDate": start_date,
        "endDate": end_date,
        "candleCount": total_inserted,
        "status": "completed",
        "importedAt": datetime.utcnow(),
    })

    return {
        "candlesImported": total_inserted,
        "exchange": exchange,
        "symbol": symbol,
        "timeframe": timeframe,
        "startDate": start_date,
        "endDate": end_date,
    }
