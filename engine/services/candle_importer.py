import asyncio
import os
from datetime import datetime, timezone

import httpx

from config.timescale import get_pool
from core.constants import DEFAULT_BATCH_SIZE
from services.progress import publish_progress
from utils.timeframes import to_ms

_KLINES_URLS = {
    "Binance Futures": "https://fapi.binance.com/fapi/v1/klines",
    "Binance Spot": "https://api.binance.com/api/v3/klines",
}


async def import_candles(
    job_id: str,
    exchange: str,
    symbol: str,
    timeframe: str,
    start_date: str,
    end_date: str,
) -> dict:
    klines_url = _KLINES_URLS.get(exchange)
    if not klines_url:
        raise ValueError(f"Unsupported exchange: {exchange}")

    start_dt = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
    end_dt = datetime.fromisoformat(end_date).replace(tzinfo=timezone.utc)
    start_ms = int(start_dt.timestamp() * 1000)
    end_ms = int(end_dt.timestamp() * 1000)

    tf_ms = to_ms(timeframe)
    total_estimate = max(1, (end_ms - start_ms) // tf_ms)

    instrument_type = "futures" if exchange == "Binance Futures" else "spot"
    fetch_delay = int(os.getenv("BINANCE_FETCH_DELAY_MS", "200")) / 1000

    current_ms = start_ms
    total_inserted = 0
    pool = get_pool()

    async with httpx.AsyncClient(timeout=20.0) as client:
        while current_ms < end_ms:
            resp = await client.get(klines_url, params={
                "symbol": symbol,
                "interval": timeframe,
                "startTime": current_ms,
                "limit": DEFAULT_BATCH_SIZE,
            })
            resp.raise_for_status()
            raw = resp.json()

            if not raw:
                break

            # Filter out candles at or beyond end date
            raw = [c for c in raw if c[0] < end_ms]
            if not raw:
                break

            # Binance kline array: [openTime, open, high, low, close, volume, closeTime, quoteVolume, ...]
            rows = [
                (
                    datetime.fromtimestamp(c[0] / 1000, tz=timezone.utc),
                    exchange,
                    symbol,
                    timeframe,
                    instrument_type,
                    None,       # expiry — NULL for spot and perpetual futures
                    float(c[1]),  # open
                    float(c[2]),  # high
                    float(c[3]),  # low
                    float(c[4]),  # close
                    float(c[5]),  # volume
                    float(c[7]),  # quoteVolume
                )
                for c in raw
            ]

            async with pool.acquire() as conn:
                await conn.executemany(
                    """
                    INSERT INTO candles
                      (time, exchange, symbol, timeframe, instrument_type, expiry, open, high, low, close, volume, quote_volume)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
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
                message=f"Auto-fetching candles for {symbol} {timeframe} — {pct}%",
                candles_fetched=total_inserted,
                total_estimate=total_estimate,
            )

            await asyncio.sleep(fetch_delay)

    return {
        "candlesImported": total_inserted,
        "exchange": exchange,
        "symbol": symbol,
        "timeframe": timeframe,
        "startDate": start_date,
        "endDate": end_date,
    }
