"""Candle sourcing for live sessions — warmup (TimescaleDB), REST fallback/HTF
(Binance Futures mainnet), and in-memory candle-array maintenance.

Extracted from `LiveBotManager` (Plan 6 Step 6.1, ENG-1/ENG-4). Behavior-preserving
move only — no logic changed, see golden-master baseline `before_plan6.json`.
"""
from __future__ import annotations

import logging

import httpx
import numpy as np

from config.timescale import get_pool
from core.candle_columns import TIMESTAMP, OPEN, CLOSE, HIGH, LOW, VOLUME, NUM_COLUMNS

logger = logging.getLogger(__name__)

_HTF_REST_URL = "https://fapi.binance.com/fapi/v1/klines"

# Plan 8 Step 8.3 (ENG-8): named so live_bot_manager.py's readiness gate can
# assert a strategy's declared MIN_WARMUP_CANDLES never exceeds what the
# in-memory candle array actually retains.
MAX_CANDLES_RETAINED = 500


class MarketDataFeed:
    """Sources candles for live bot sessions from TimescaleDB and Binance REST."""

    async def fetch_warmup_candles(
        self, symbol: str, timeframe: str, limit: int
    ) -> np.ndarray | None:
        """Fetch recent candles from TimescaleDB for indicator warmup."""
        pool = get_pool()
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT time, open, close, high, low, volume
                    FROM candles
                    WHERE exchange = $1 AND symbol = $2 AND timeframe = $3
                    ORDER BY time DESC
                    LIMIT $4
                    """,
                    "Binance Futures",
                    symbol,
                    timeframe,
                    limit,
                )
            if not rows:
                return None
            # Reverse so oldest first, build numpy array
            rows = list(reversed(rows))
            candles = np.empty((len(rows), NUM_COLUMNS), dtype=np.float64)
            for i, r in enumerate(rows):
                candles[i, TIMESTAMP] = r["time"].timestamp() * 1000
                candles[i, OPEN] = r["open"]
                candles[i, CLOSE] = r["close"]
                candles[i, HIGH] = r["high"]
                candles[i, LOW] = r["low"]
                candles[i, VOLUME] = r["volume"]
            return candles
        except Exception as e:
            logger.error(f"[AlgoBot] TimescaleDB warmup fetch failed for {symbol}: {e}")
            return None

    async def fetch_candles_from_rest(
        self, symbol: str, timeframe: str, limit: int
    ) -> np.ndarray:
        """Fetch recent candles from Binance Futures mainnet REST as warmup fallback."""
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(_HTF_REST_URL, params={
                    "symbol": symbol,
                    "interval": timeframe,
                    "limit": limit,
                })
                resp.raise_for_status()
                raw = resp.json()
            if not raw:
                return np.empty((0, NUM_COLUMNS), dtype=np.float64)
            raw = raw[:-1]  # Exclude the currently open candle
            # Binance kline: [openTime, open, high, low, close, volume, ...] —
            # standard order, NOT the engine's own [ts, open, close, high, low, vol].
            candles = np.empty((len(raw), NUM_COLUMNS), dtype=np.float64)
            for i, c in enumerate(raw):
                candles[i, TIMESTAMP] = float(c[0])
                candles[i, OPEN] = float(c[1])
                candles[i, CLOSE] = float(c[4])
                candles[i, HIGH] = float(c[2])
                candles[i, LOW] = float(c[3])
                candles[i, VOLUME] = float(c[5])
            return candles
        except Exception as e:
            logger.error(f"[AlgoBot] Binance REST candle fetch failed for {symbol}: {e}")
            return np.empty((0, NUM_COLUMNS), dtype=np.float64)

    async def fetch_htf_candles(
        self, symbol: str, tf_interval: str, limit: int = 50
    ) -> np.ndarray:
        """Fetch HTF candles from Binance Futures REST for live multi-timeframe strategies.
        Returns the same [timestamp_ms, open, close, high, low, volume] layout as base candles.
        Excludes the currently open candle (same as fetch_candles_from_rest)."""
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(_HTF_REST_URL, params={
                    "symbol": symbol,
                    "interval": tf_interval,
                    "limit": limit,
                })
                resp.raise_for_status()
                raw = resp.json()
            if not raw:
                return np.empty((0, NUM_COLUMNS), dtype=np.float64)
            raw = raw[:-1]  # Exclude the currently open candle
            # Binance kline: [openTime, open, high, low, close, volume, ...] —
            # standard order, NOT the engine's own [ts, open, close, high, low, vol].
            candles = np.empty((len(raw), NUM_COLUMNS), dtype=np.float64)
            for i, c in enumerate(raw):
                candles[i, TIMESTAMP] = float(c[0])
                candles[i, OPEN] = float(c[1])
                candles[i, CLOSE] = float(c[4])
                candles[i, HIGH] = float(c[2])
                candles[i, LOW] = float(c[3])
                candles[i, VOLUME] = float(c[5])
            return candles
        except Exception as e:
            logger.error(f"[AlgoBot] HTF REST fetch failed for {symbol} {tf_interval}: {e}")
            return np.empty((0, NUM_COLUMNS), dtype=np.float64)

    def append_candle(self, candles: np.ndarray, new_candle: np.ndarray) -> np.ndarray:
        """Append a new candle to the array if it's not a duplicate. Keep last MAX_CANDLES_RETAINED."""
        if len(candles) > 0:
            last_ts = candles[-1, TIMESTAMP]
            if new_candle[TIMESTAMP] <= last_ts:
                # Update the last candle if same timestamp, else ignore older
                if new_candle[TIMESTAMP] == last_ts:
                    candles[-1] = new_candle
                return candles
        candles = np.vstack([candles, new_candle]) if len(candles) > 0 else new_candle.reshape(1, NUM_COLUMNS)
        # Keep only the last MAX_CANDLES_RETAINED candles
        if len(candles) > MAX_CANDLES_RETAINED:
            candles = candles[-MAX_CANDLES_RETAINED:]
        return candles
