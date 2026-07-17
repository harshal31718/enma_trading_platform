"""Plan 9 Step 9.7 (QNT-5): historical funding-rate importer.

Mirrors candle_importer.py's idempotent-upsert pattern exactly, applied to
Binance Futures' historical funding-rate endpoint instead of klines.

REST reference (verified against official Binance docs, root CLAUDE.md Rule A):
  GET https://fapi.binance.com/fapi/v1/fundingRate
  No signing required (public market data). Params: symbol, startTime,
  endTime (both ms, inclusive), limit (max 1000, default 100). Ascending
  order. Response rows: {symbol, fundingRate, fundingTime, markPrice}.

Only Binance Futures has funding (perpetual futures mechanic) — spot never
calls this. Same §2 guardrail as candle_importer.py: mainnet only, funding
history is a market-wide fact, not exchange-account-specific, so testnet's
fragmented/wiped data pool is never the source.
"""
import asyncio
import os
from datetime import datetime, timezone

import httpx

from config.timescale import get_pool
from services.progress import publish_progress

_FUNDING_RATE_URL = "https://fapi.binance.com/fapi/v1/fundingRate"
_MAX_LIMIT = 1000


async def import_funding_rates(
    job_id: str,
    exchange: str,
    symbol: str,
    start_date: str,
    end_date: str,
) -> dict:
    if exchange != "Binance Futures":
        raise ValueError(f"Funding rates only exist for Binance Futures perpetuals, got: {exchange}")

    start_dt = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
    end_dt = datetime.fromisoformat(end_date).replace(tzinfo=timezone.utc)
    start_ms = int(start_dt.timestamp() * 1000)
    end_ms = int(end_dt.timestamp() * 1000)

    fetch_delay = int(os.getenv("BINANCE_FETCH_DELAY_MS") or "200") / 1000

    current_ms = start_ms
    total_inserted = 0
    pool = get_pool()

    async with httpx.AsyncClient(timeout=20.0) as client:
        while current_ms < end_ms:
            resp = await client.get(_FUNDING_RATE_URL, params={
                "symbol": symbol,
                "startTime": current_ms,
                "endTime": end_ms,
                "limit": _MAX_LIMIT,
            })
            resp.raise_for_status()
            raw = resp.json()

            if not raw:
                break

            rows = [
                (
                    datetime.fromtimestamp(r["fundingTime"] / 1000, tz=timezone.utc),
                    exchange,
                    symbol,
                    float(r["fundingRate"]),
                    float(r["markPrice"]) if r.get("markPrice") not in (None, "") else None,
                )
                for r in raw
            ]

            async with pool.acquire() as conn:
                await conn.executemany(
                    """
                    INSERT INTO funding_rates (time, exchange, symbol, funding_rate, mark_price)
                    VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT DO NOTHING
                    """,
                    rows,
                )

            total_inserted += len(rows)

            # Binance funding-rate history has no fixed interval to derive
            # "next" from (rows[-1]'s own fundingTime + 1ms is the correct
            # cursor — matches the API's own "startTime + limit" pagination
            # note; unlike klines there's no tf_ms to add).
            last_funding_ms = raw[-1]["fundingTime"]
            if last_funding_ms <= current_ms:
                break  # no forward progress — avoid an infinite loop on a malformed response
            current_ms = last_funding_ms + 1

            await publish_progress(
                job_id=job_id,
                pct=min(99, int(((current_ms - start_ms) / max(1, end_ms - start_ms)) * 100)),
                message=f"Auto-fetching funding rates for {symbol} — {total_inserted} records",
                candles_fetched=total_inserted,
                total_estimate=total_inserted,
            )

            if len(raw) < _MAX_LIMIT:
                break  # last page

            await asyncio.sleep(fetch_delay)

    return {
        "fundingRatesImported": total_inserted,
        "exchange": exchange,
        "symbol": symbol,
        "startDate": start_date,
        "endDate": end_date,
    }
