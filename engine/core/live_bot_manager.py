import asyncio
import logging
import os
from datetime import datetime, timezone

import httpx
import numpy as np

from config.timescale import get_pool
from core.position import Position
from utils.symbols import get_ccxt_exchange, to_ccxt_symbol
from utils.timeframes import to_ms

logger = logging.getLogger(__name__)

# How many historical candles to load for indicator warmup
WARMUP_CANDLES = 200

# Server URL for callbacks
SERVER_URL = os.getenv("SERVER_URL", "http://server:5000")


class LiveBotManager:
    def __init__(self):
        self.sessions: dict[str, dict] = {}
        self._stop_signals: dict[str, asyncio.Event] = {}
        self._tasks: dict[str, list[asyncio.Task]] = {}

    async def start_session(self, session_config: dict) -> None:
        """Start a new live bot session. session_config from Node."""
        session_id = session_config["session_id"]
        strategy_name = session_config["strategy_name"]
        symbols = session_config["symbols"]
        timeframe = session_config["timeframe"]
        params = session_config.get("params", {})
        capital_per_symbol = float(session_config["capital"]) / len(symbols)
        leverage = int(session_config.get("leverage", 1))

        # Dynamic import of strategy class
        import importlib
        module = importlib.import_module(f"strategies.{strategy_name}")
        strategy_class = getattr(module, strategy_name)

        stop_event = asyncio.Event()
        self._stop_signals[session_id] = stop_event
        self._tasks[session_id] = []

        self.sessions[session_id] = {
            "session_id": session_id,
            "strategy_name": strategy_name,
            "symbols": symbols,
            "timeframe": timeframe,
            "params": params,
            "capital": float(session_config["capital"]),
            "leverage": leverage,
            "status": "running",
            "pnl": 0.0,
            "open_positions": {},  # symbol -> dict with position info
            "strategy_instances": {},  # symbol -> strategy instance
        }

        # Spawn one task per symbol
        for symbol in symbols:
            task = asyncio.create_task(
                self._run_symbol_loop(
                    session_id, strategy_class, symbol, params,
                    timeframe, capital_per_symbol, leverage
                )
            )
            self._tasks[session_id].append(task)

        # Notify Node that session is now running
        await self._notify_node(session_id, {
            "pnl": "0",
            "openPositions": [],
            "status": "running",
        })

        logger.info(f"[AlgoBot] Session {session_id} started with {len(symbols)} symbols")

    async def stop_session(self, session_id: str) -> None:
        """Stop a running session. Called from the FastAPI route via BackgroundTasks."""
        session = self.sessions.get(session_id)
        if not session:
            return

        logger.info(f"[AlgoBot] Stopping session {session_id}")
        session["status"] = "stopping"

        # Signal all loops to stop
        stop_event = self._stop_signals.get(session_id)
        if stop_event:
            stop_event.set()

        # Cancel all tasks
        tasks = self._tasks.get(session_id, [])
        for task in tasks:
            task.cancel()

        # Wait for tasks to finish (with timeout)
        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=30.0
            )
        except asyncio.TimeoutError:
            logger.warning(f"[AlgoBot] Session {session_id} task cancellation timed out")

        # Close any remaining open positions sequentially.
        # Wrapped in a 120-second timeout so the stop sequence can never hang
        # indefinitely on a blocked Node callback or a stuck position close.
        open_positions = session.get("open_positions", {})
        if open_positions:
            async def _close_all():
                for symbol, pos_info in list(open_positions.items()):
                    if pos_info:
                        try:
                            await self._close_position_on_stop(session_id, symbol, pos_info, session)
                        except Exception as e:
                            logger.error(f"[AlgoBot] Error closing position {symbol}: {e}")

            try:
                await asyncio.wait_for(_close_all(), timeout=120.0)
            except asyncio.TimeoutError:
                logger.error(
                    f"[AlgoBot] Position close loop timed out for session {session_id} — forcing stop"
                )
                session["open_positions"].clear()

        # Mark session as stopped — always reached even after timeout
        session["status"] = "stopped"
        remaining_pnl = str(round(session["pnl"], 2))

        await self._notify_node(session_id, {
            "pnl": remaining_pnl,
            "openPositions": [],
            "status": "stopped",
            "event": "stopped",
        })

        # Cleanup
        self.sessions.pop(session_id, None)
        self._stop_signals.pop(session_id, None)
        self._tasks.pop(session_id, None)

        logger.info(f"[AlgoBot] Session {session_id} stopped")

    async def get_session_status(self, session_id: str) -> dict:
        session = self.sessions.get(session_id)
        if not session:
            return {"status": "not_found"}
        open_pos = list(session.get("open_positions", {}).keys())
        return {
            "status": session["status"],
            "pnl": str(round(session["pnl"], 2)),
            "openPositions": open_pos,
        }

    # ── Private helpers ──────────────────────────────────────────────────────

    async def _run_symbol_loop(
        self, session_id: str, strategy_class, symbol: str,
        params: dict, timeframe: str, capital: float, leverage: int
    ) -> None:
        """Main loop for one symbol. Runs until stop signal is set."""
        strategy = strategy_class()
        strategy.symbol = symbol
        strategy.timeframe = timeframe
        strategy.balance = capital
        strategy.leverage = leverage
        strategy.is_papertrading = True
        strategy.is_livetrading = False
        strategy.is_backtesting = False
        strategy.exchange = "Binance Futures"
        strategy.exchange_type = "futures"
        strategy.fee_rate = 0.001

        # Set user params on instance
        for key, meta in getattr(strategy_class, "PARAMS", {}).items():
            setattr(strategy, key, params.get(key, meta["default"]))

        # Store strategy instance for stats access
        session = self.sessions.get(session_id)
        if session:
            session["strategy_instances"][symbol] = strategy

        # Fetch initial warmup candles from TimescaleDB
        try:
            candles = await self._fetch_warmup_candles(symbol, timeframe, WARMUP_CANDLES)
            if candles is None or len(candles) < 20:
                logger.warning(f"[AlgoBot] Not enough warmup candles for {symbol}, fetching from CCXT")
                candles = await self._fetch_candles_from_ccxt(symbol, timeframe, WARMUP_CANDLES)
            strategy.candles = candles
        except Exception as e:
            logger.error(f"[AlgoBot] Failed to load warmup candles for {symbol}: {e}")
            strategy.candles = np.empty((0, 6), dtype=np.float64)

        stop_event = self._stop_signals.get(session_id)
        interval_seconds = to_ms(timeframe) / 1000

        try:
            while not (stop_event and stop_event.is_set()):
                # Fetch latest candle and append
                try:
                    latest = await self._fetch_latest_candle(symbol, timeframe)
                    if latest is not None:
                        strategy.candles = self._append_candle(strategy.candles, latest)
                except Exception as e:
                    logger.warning(f"[AlgoBot] Failed to fetch latest candle for {symbol}: {e}")

                if len(strategy.candles) < 2:
                    await asyncio.sleep(interval_seconds)
                    continue

                # Strategy execution
                try:
                    strategy.before()

                    if strategy.position is None:
                        if strategy.should_long():
                            strategy.go_long()
                            if strategy.buy is not None:
                                await self._execute_paper_entry(session_id, strategy, symbol, "long")
                        elif strategy.should_short():
                            strategy.go_short()
                            if strategy.sell is not None:
                                await self._execute_paper_entry(session_id, strategy, symbol, "short")
                    else:
                        strategy.position.update_pnl(strategy.price)
                        await self._check_exits(session_id, strategy, symbol)
                        if strategy.position is not None:
                            strategy.update_position()

                    strategy.after()
                except Exception as e:
                    logger.error(f"[AlgoBot] Strategy error [{symbol}]: {e}")

                # Push stats to Node
                await self._push_stats(session_id)

                # Sleep until next candle (use a wait_for so stop signal can interrupt)
                try:
                    await asyncio.wait_for(
                        asyncio.shield(stop_event.wait()),
                        timeout=interval_seconds
                    )
                    # If we reach here, stop was signaled during sleep
                    break
                except asyncio.TimeoutError:
                    pass  # Normal: interval elapsed, continue loop

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[AlgoBot] Unexpected error in symbol loop [{symbol}]: {e}")

    async def _execute_paper_entry(
        self, session_id: str, strategy, symbol: str, direction: str
    ) -> None:
        """Simulate a paper order fill at current price."""
        session = self.sessions.get(session_id)
        if not session:
            return

        if direction == "long":
            qty, price = strategy.buy
        else:
            qty, price = strategy.sell

        fill_price = strategy.price  # Market fill at current close

        strategy.position = Position(direction, qty, fill_price)
        if direction == "long":
            strategy.buy = None
        else:
            strategy.sell = None

        pos_info = {
            "symbol": symbol,
            "side": direction,
            "qty": str(qty),
            "price": str(fill_price),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        session["open_positions"][symbol] = pos_info

        await self._notify_node(session_id, {
            "pnl": str(round(session["pnl"], 2)),
            "openPositions": list(session["open_positions"].keys()),
            "status": "running",
            "event": "position:open",
            "eventData": pos_info,
        })

        logger.info(f"[AlgoBot] Paper {direction} filled: {symbol} qty={qty} @ {fill_price}")

    async def _check_exits(self, session_id: str, strategy, symbol: str) -> None:
        """Check stop-loss and take-profit for open position."""
        if strategy.position is None:
            return

        current = strategy.price
        # Get candle high/low for more accurate SL/TP simulation
        high_t = strategy.high
        low_t = strategy.low

        closed = False
        exit_price = current
        exit_reason = ""

        if strategy.is_long:
            sl = strategy.stop_loss
            tp = strategy.take_profit
            if sl is not None:
                _, sl_price = sl
                if low_t <= sl_price:
                    exit_price = sl_price
                    exit_reason = "stop_loss"
                    closed = True
            if not closed and tp is not None:
                _, tp_price = tp
                if high_t >= tp_price:
                    exit_price = tp_price
                    exit_reason = "take_profit"
                    closed = True
        elif strategy.is_short:
            sl = strategy.stop_loss
            tp = strategy.take_profit
            if sl is not None:
                _, sl_price = sl
                if high_t >= sl_price:
                    exit_price = sl_price
                    exit_reason = "stop_loss"
                    closed = True
            if not closed and tp is not None:
                _, tp_price = tp
                if low_t <= tp_price:
                    exit_price = tp_price
                    exit_reason = "take_profit"
                    closed = True

        if closed:
            await self._close_position(session_id, strategy, symbol, exit_price, exit_reason)

    async def _close_position(
        self, session_id: str, strategy, symbol: str, exit_price: float, reason: str
    ) -> None:
        """Close position and notify Node."""
        session = self.sessions.get(session_id)
        if not session or strategy.position is None:
            return

        fee = strategy.position.qty * exit_price * strategy.fee_rate
        strategy.position.close(exit_price)
        realized_pnl = strategy.position.pnl - fee
        strategy.balance += realized_pnl
        session["pnl"] += realized_pnl

        event_data = {
            "symbol": symbol,
            "pnl": str(round(realized_pnl, 2)),
            "exitPrice": str(exit_price),
            "exitReason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        strategy.position = None
        strategy.stop_loss = None
        strategy.take_profit = None
        session["open_positions"].pop(symbol, None)

        await self._notify_node(session_id, {
            "pnl": str(round(session["pnl"], 2)),
            "openPositions": list(session["open_positions"].keys()),
            "status": "running",
            "event": "position:close",
            "eventData": event_data,
        })

        logger.info(f"[AlgoBot] Position closed: {symbol} pnl={realized_pnl:.2f} reason={reason}")

    async def _close_position_on_stop(
        self, session_id: str, symbol: str, _pos_info: dict, session: dict
    ) -> None:
        """Force-close a position during session stop sequence."""
        strategy = session.get("strategy_instances", {}).get(symbol)
        if strategy and strategy.position:
            exit_price = strategy.price
            await self._close_position(session_id, strategy, symbol, exit_price, "session_stop")
        else:
            # No live strategy instance — release lock via Node notification
            session["open_positions"].pop(symbol, None)
            await self._notify_node(session_id, {
                "pnl": str(round(session["pnl"], 2)),
                "openPositions": list(session["open_positions"].keys()),
                "status": "stopping",
                "event": "position:close",
                "eventData": {
                    "symbol": symbol,
                    "pnl": "0",
                    "exitPrice": "0",
                    "exitReason": "session_stop",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            })

    async def _push_stats(self, session_id: str) -> None:
        """Push periodic stats update to Node (no position event)."""
        session = self.sessions.get(session_id)
        if not session:
            return
        total_pnl = sum(
            strat.position.pnl if strat.position else 0.0
            for strat in session.get("strategy_instances", {}).values()
        ) + session["pnl"]
        await self._notify_node(session_id, {
            "pnl": str(round(total_pnl, 2)),
            "openPositions": list(session.get("open_positions", {}).keys()),
            "status": "running",
        })

    async def _notify_node(self, session_id: str, data: dict) -> None:
        """Send stats/event update to Node server via HTTP PATCH."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.patch(
                    f"{SERVER_URL}/internal/algo/sessions/{session_id}/stats",
                    json=data,
                )
        except Exception as e:
            logger.warning(f"[AlgoBot] Failed to notify Node for session {session_id}: {e}")

    async def _fetch_warmup_candles(
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
                    to_ccxt_symbol(symbol),
                    timeframe,
                    limit,
                )
            if not rows:
                return None
            # Reverse so oldest first, build numpy array
            rows = list(reversed(rows))
            candles = np.empty((len(rows), 6), dtype=np.float64)
            for i, r in enumerate(rows):
                candles[i, 0] = r["time"].timestamp() * 1000
                candles[i, 1] = r["open"]
                candles[i, 2] = r["close"]
                candles[i, 3] = r["high"]
                candles[i, 4] = r["low"]
                candles[i, 5] = r["volume"]
            return candles
        except Exception as e:
            logger.error(f"[AlgoBot] TimescaleDB warmup fetch failed for {symbol}: {e}")
            return None

    async def _fetch_candles_from_ccxt(
        self, symbol: str, timeframe: str, limit: int
    ) -> np.ndarray:
        """Fetch candles from CCXT (Binance Futures) as fallback."""
        ex = get_ccxt_exchange("Binance Futures")
        ccxt_symbol = to_ccxt_symbol(symbol)
        try:
            raw = await asyncio.to_thread(
                ex.fetch_ohlcv, ccxt_symbol, timeframe, limit=limit
            )
            if not raw:
                return np.empty((0, 6), dtype=np.float64)
            candles = np.empty((len(raw), 6), dtype=np.float64)
            for i, c in enumerate(raw):
                candles[i, 0] = float(c[0])   # timestamp ms
                candles[i, 1] = float(c[1])   # open
                candles[i, 2] = float(c[4])   # close (ccxt index 4)
                candles[i, 3] = float(c[2])   # high (ccxt index 2)
                candles[i, 4] = float(c[3])   # low  (ccxt index 3)
                candles[i, 5] = float(c[5])   # volume
            return candles
        except Exception as e:
            logger.error(f"[AlgoBot] CCXT fetch failed for {symbol}: {e}")
            return np.empty((0, 6), dtype=np.float64)

    async def _fetch_latest_candle(
        self, symbol: str, timeframe: str
    ) -> np.ndarray | None:
        """Fetch the latest closed candle from CCXT."""
        ex = get_ccxt_exchange("Binance Futures")
        ccxt_symbol = to_ccxt_symbol(symbol)
        try:
            # Fetch 2 candles — the second-to-last is the most recently closed
            raw = await asyncio.to_thread(
                ex.fetch_ohlcv, ccxt_symbol, timeframe, limit=2
            )
            if not raw or len(raw) < 2:
                return None
            c = raw[-2]  # Most recently closed candle
            candle = np.array([
                float(c[0]),  # timestamp ms
                float(c[1]),  # open
                float(c[4]),  # close (ccxt index 4)
                float(c[2]),  # high  (ccxt index 2)
                float(c[3]),  # low   (ccxt index 3)
                float(c[5]),  # volume
            ], dtype=np.float64)
            return candle
        except Exception as e:
            logger.warning(f"[AlgoBot] Latest candle fetch failed for {symbol}: {e}")
            return None

    def _append_candle(self, candles: np.ndarray, new_candle: np.ndarray) -> np.ndarray:
        """Append a new candle to the array if it's not a duplicate. Keep last 500."""
        if len(candles) > 0:
            last_ts = candles[-1, 0]
            if new_candle[0] <= last_ts:
                # Update the last candle if same timestamp, else ignore older
                if new_candle[0] == last_ts:
                    candles[-1] = new_candle
                return candles
        candles = np.vstack([candles, new_candle]) if len(candles) > 0 else new_candle.reshape(1, 6)
        # Keep only last 500 candles
        if len(candles) > 500:
            candles = candles[-500:]
        return candles


# Singleton instance
live_bot_manager = LiveBotManager()
