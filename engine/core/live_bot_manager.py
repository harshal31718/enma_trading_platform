import asyncio
import json
import logging
import os
from datetime import datetime, timezone

import httpx
import numpy as np
import websockets

from config.timescale import get_pool
from core.position import Position
from core.models import DefaultPortfolioModel, LiveExecution, OrderPlan
from core.pipeline import evaluate
from services.trade_recorder import record_trade, build_trade_record
from utils.symbols import round_price, round_qty, clamp_and_round_qty, clamp_leverage

logger = logging.getLogger(__name__)

# How many historical candles to load for indicator warmup
WARMUP_CANDLES = 200

# Maps strategy tf param values to Binance interval strings (case-sensitive: "1M" = monthly)
_TF_TO_BINANCE = {
    "1h": "1h",
    "4h": "4h",
    "daily": "1d",
    "weekly": "1w",
    "monthly": "1M",
}

# Server URL for callbacks
SERVER_URL = os.getenv("SERVER_URL", "http://server:5000")


def _get_min_candles_required(strategy) -> int:
    """
    Finds the largest numeric param on the strategy and applies a 2x buffer
    to ensure all indicator lookback windows (including derived ones like
    atr_sma = atr_period * 2) have enough candles.
    Falls back to 100 if no params exist.
    """
    params_schema = getattr(strategy.__class__, "PARAMS", {})
    numeric_values = [
        getattr(strategy, key, meta.get("default", 0))
        for key, meta in params_schema.items()
        if meta.get("type") in ("int", "float")
    ]
    largest = max((v for v in numeric_values if isinstance(v, (int, float)) and v > 0), default=50)
    return int(largest) * 3  # 3x buffer: covers derived indicators (e.g. atr_sma = atr_period * 2)

def _safe_float(val, default):
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


class LiveBotManager:
    def __init__(self):
        self.sessions: dict[str, dict] = {}
        self._stop_signals: dict[str, asyncio.Event] = {}
        self._tasks: dict[str, list[asyncio.Task]] = {}
        # Limit concurrent Binance testnet calls per session to avoid overwhelming
        # the testnet when many symbols fire signals on the same candle close.
        self._order_semaphores: dict[str, asyncio.Semaphore] = {}

    async def start_session(self, session_config: dict) -> None:
        """Start a new live bot session. session_config from Node."""
        session_id = session_config["session_id"]
        strategy_name = session_config["strategy_name"]
        symbols = session_config["symbols"]
        timeframe = session_config["timeframe"]
        params = session_config.get("params", {})
        # Cross-symbol capital split owned by the Portfolio Model (Phase 3).
        # Default is an equal split (byte-identical to the former
        # capital/len(symbols)); a custom PortfolioModel can re-weight here.
        allocation = DefaultPortfolioModel().allocate(
            float(session_config["capital"]), symbols
        )
        leverage = int(session_config.get("leverage", 1))
        fee_rate = float(session_config.get("fee_rate", 0.0005))
        risk_params = session_config.get("risk_params", {}) or {}

        # Dynamic import of strategy class
        import importlib
        module = importlib.import_module(f"strategies.{strategy_name}")
        strategy_class = getattr(module, strategy_name)

        stop_event = asyncio.Event()
        self._stop_signals[session_id] = stop_event
        self._tasks[session_id] = []
        # Allow at most 2 concurrent Binance order calls per session
        self._order_semaphores[session_id] = asyncio.Semaphore(2)

        self.sessions[session_id] = {
            "session_id": session_id,
            "strategy_name": strategy_name,
            "symbols": symbols,
            "timeframe": timeframe,
            "params": params,
            "capital": float(session_config["capital"]),
            "leverage": leverage,
            "risk_params": risk_params,
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
                    timeframe, allocation[symbol], leverage, fee_rate,
                    risk_params,
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

        # Close ALL session symbols on Binance — not just the ones the engine
        # thinks are open. This handles cases where Binance has a real position
        # but the engine's in-memory open_positions is stale (e.g. after a restart
        # or a missed SL/TP fill). Close requests for symbols with no open
        # position are safe — Node's close-position handler returns a no-op.
        # Wrapped in a 120-second timeout so the stop can never hang.
        all_symbols = session.get("symbols", [])
        if all_symbols:
            async def _close_all():
                for symbol in all_symbols:
                    pos_info = session.get("open_positions", {}).get(symbol)
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
        self._order_semaphores.pop(session_id, None)

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
        params: dict, timeframe: str, capital: float, leverage: int,
        fee_rate: float = 0.0005, risk_params: dict | None = None,
    ) -> None:
        """Main loop for one symbol. Connects to Binance kline WebSocket and fires
        strategy logic on every closed candle. Runs until stop signal is set."""
        consecutive_errors = 0

        strategy = strategy_class()
        strategy.symbol = symbol
        strategy.timeframe = timeframe
        strategy.balance = capital
        strategy.leverage = leverage
        strategy.is_papertrading = False
        strategy.is_livetrading = True
        strategy.is_backtesting = False
        strategy.exchange = "Binance Futures"
        strategy.exchange_type = "futures"
        strategy.fee_rate = fee_rate

        # Set user params on instance
        for key, meta in getattr(strategy_class, "PARAMS", {}).items():
            setattr(strategy, key, params.get(key, meta["default"]))

        # Inject risk model params (mirrors backtest_runner step 6b). Live
        # trading executes against real fills, so slippage_pct is left at the
        # BaseStrategy default — it only models simulated market-fill slippage.
        # Each per-symbol strategy gets its own slice of the session capital.
        _risk_all = risk_params or {}
        _risk = _risk_all.get(symbol) or _risk_all.get("default") or _risk_all
        
        strategy.risk_pct          = _safe_float(_risk.get("risk_pct"),       strategy.risk_pct)
        strategy.rrr               = _safe_float(_risk.get("rrr"),            strategy.rrr)
        strategy.liq_buffer_pct    = _safe_float(_risk.get("liq_buffer_pct"), strategy.liq_buffer_pct)
        strategy.max_session_dd    = _safe_float(_risk.get("max_session_dd"), strategy.max_session_dd)
        strategy.cost_model.min_edge_mult = _safe_float(_risk.get("min_edge_mult"),     0.05)
        strategy.max_portfolio_risk       = _safe_float(_risk.get("max_portfolio_risk"), 0.06)
        
        strategy.volatility_multiplier = _safe_float(_risk.get("volatility_multiplier"), 1.0)
        strategy.max_exposure_notional = _safe_float(_risk.get("max_exposure_notional"), float('inf'))
        
        custom_atr_mult = _risk.get("custom_atr_mult")
        if custom_atr_mult is not None:
            strategy.custom_atr_mult = _safe_float(custom_atr_mult, None)
        else:
            strategy.custom_atr_mult = None
        strategy.available_capital = float(capital)
        strategy.peak_equity       = float(capital)

        # Execution Model for the live env (real Binance market fills). Owns the
        # realized exit-fee accounting; composes the strategy's Cost Model.
        strategy.execution_model = LiveExecution()

        # Store strategy instance for stats access
        session = self.sessions.get(session_id)
        if session:
            session["strategy_instances"][symbol] = strategy

        # Clamp requested leverage to what Binance actually allows for this symbol.
        # Uses the signed /fapi/v1/leverageBracket endpoint if credentials are
        # available via env (the live path always has them set in server/.env).
        api_key = os.getenv("BINANCE_TESTNET_API_KEY")
        api_secret = os.getenv("BINANCE_TESTNET_SECRET")
        effective_leverage = await clamp_leverage(
            leverage, "Binance Futures", symbol,
            api_key=api_key, api_secret=api_secret, mode="testnet",
        )
        if effective_leverage != leverage:
            logger.info(
                f"[AlgoBot] {symbol}: leverage clamped {leverage}→{effective_leverage} "
                f"(symbol max exceeded)"
            )
            await self._notify_node(session_id, {
                "event": "log",
                "eventData": {
                    "type": "info",
                    "message": f"{symbol}: leverage clamped {leverage}x→{effective_leverage}x (symbol max)"
                }
            })
        leverage = effective_leverage
        strategy.leverage = effective_leverage

        # Set leverage on Binance Testnet before entering
        try:
            await self._call_node_internal(
                session_id, f"/internal/algo/sessions/{session_id}/set-leverage",
                {"symbol": symbol, "leverage": leverage}
            )
            logger.info(f"[AlgoBot] Set leverage {leverage}x for {symbol}")
        except Exception as e:
            logger.warning(f"[AlgoBot] Failed to set leverage for {symbol}: {e}")

        # Fetch initial warmup candles from TimescaleDB
        try:
            candles = await self._fetch_warmup_candles(symbol, timeframe, WARMUP_CANDLES)
            if candles is None or len(candles) < 20:
                logger.warning(f"[AlgoBot] Not enough warmup candles for {symbol}, fetching from Binance REST")
                candles = await self._fetch_candles_from_rest(symbol, timeframe, WARMUP_CANDLES)
            strategy.candles = candles
            # Warmup: replay last 3 historical candles to prime indicator state only.
            # No orders are placed — warmup is read-only so all symbols can initialise
            # in parallel without flooding the testnet or hitting the Node timeout.
            if candles is not None and len(candles) >= 3:
                logger.info(f"[AlgoBot] {symbol}: Warming up indicator state on last 3 historical candles")
                for t in range(len(candles) - 3, len(candles)):
                    strategy.candles = candles[:t+1]
                    strategy.index = t
                    try:
                        # Two-phase contract: prepare() batch-computes indicators
                        # over the current window, before() then indexes at i.
                        strategy.prepare(strategy.candles)
                        strategy.before()
                        strategy.after()
                    except Exception as e:
                        logger.error(f"[AlgoBot] Warmup error on {symbol} at index {t}: {e}")
                # Reset strategy.candles to the full set
                strategy.candles = candles
        except Exception as e:
            logger.error(f"[AlgoBot] Failed to load warmup candles for {symbol}: {e}")
            strategy.candles = np.empty((0, 6), dtype=np.float64)

        # Fetch HTF candles if strategy uses a higher timeframe (e.g. BestSupertrend tf param)
        htf_tf = getattr(strategy, 'tf', None)
        if htf_tf is not None:
            htf_interval = _TF_TO_BINANCE.get(htf_tf.lower())
            if htf_interval and htf_interval != timeframe:
                try:
                    htf_candles = await self._fetch_htf_candles(symbol, htf_interval, 50)
                    strategy._htf_candles = htf_candles
                    logger.info(f"[AlgoBot] {symbol}: HTF ({htf_interval}) candles loaded: {len(htf_candles)}")
                except Exception as e:
                    logger.warning(f"[AlgoBot] {symbol}: HTF candle fetch failed — {e}")

        # Sync any pre-existing Binance position into local state.
        # This recovers positions that were opened before the engine tracked them
        # (e.g. SL/TP placement failed on a prior run, leaving an untracked fill).
        await self._sync_open_position(session_id, strategy, symbol)

        stop_event = self._stop_signals.get(session_id)
        # btcusdt@kline_1h  — Binance stream name format
        ws_symbol = symbol.lower()
        ws_url = f"wss://fstream.binancefuture.com/ws/{ws_symbol}@kline_{timeframe}"

        try:
            while not (stop_event and stop_event.is_set()):
                try:
                    async with websockets.connect(
                        ws_url,
                        ping_interval=20,
                        ping_timeout=20,
                        close_timeout=5,
                    ) as ws:
                        logger.info(f"[AlgoBot] {symbol}: WS connected → {ws_url}")
                        await self._notify_node(session_id, {
                            "event": "log",
                            "eventData": {"type": "info", "message": f"{symbol}: WS connected · waiting for {timeframe} candle closes"}
                        })

                        warmed_up = len(strategy.candles) >= _get_min_candles_required(strategy)

                        async for raw in ws:
                            if stop_event and stop_event.is_set():
                                return

                            # Parse kline message
                            try:
                                msg = json.loads(raw)
                            except Exception:
                                continue

                            kline = msg.get("k", {})
                            if not kline.get("x", False):
                                # Candle still open — skip until it closes
                                continue

                            close_price = float(kline["c"])

                            # Build candle [timestamp_ms, open, close, high, low, volume]
                            candle = np.array([
                                float(kline["t"]),  # open time ms
                                float(kline["o"]),  # open
                                close_price,        # close
                                float(kline["h"]),  # high
                                float(kline["l"]),  # low
                                float(kline["v"]),  # volume
                            ], dtype=np.float64)
                            strategy.candles = self._append_candle(strategy.candles, candle)

                            min_required = _get_min_candles_required(strategy)
                            if len(strategy.candles) < min_required:
                                warmed_up = False
                                logger.info(f"[AlgoBot] {symbol}: warming up ({len(strategy.candles)}/{min_required})")
                                continue

                            # Emit "ready" once when warmup completes
                            if not warmed_up:
                                warmed_up = True
                                await self._notify_node(session_id, {
                                    "event": "log",
                                    "eventData": {"type": "info", "message": f"{symbol}: Ready · {len(strategy.candles)} candles loaded"}
                                })

                            # Update HTF candles on each closed base candle (live multi-timeframe)
                            _htf_tf = getattr(strategy, 'tf', None)
                            if _htf_tf is not None and getattr(strategy, '_htf_candles', None) is not None:
                                _htf_interval = _TF_TO_BINANCE.get(_htf_tf.lower())
                                if _htf_interval and _htf_interval != timeframe:
                                    try:
                                        _new_htf = await self._fetch_htf_candles(symbol, _htf_interval, 2)
                                        if len(_new_htf) > 0:
                                            _last_ts = strategy._htf_candles[-1, 0] if len(strategy._htf_candles) > 0 else 0
                                            if _new_htf[-1, 0] > _last_ts:
                                                strategy._htf_candles = self._append_candle(strategy._htf_candles, _new_htf[-1])
                                                if len(strategy._htf_candles) > 100:
                                                    strategy._htf_candles = strategy._htf_candles[-100:]
                                    except Exception as _e:
                                        logger.warning(f"[AlgoBot] {symbol}: HTF candle update failed — {_e}")

                            # Strategy execution
                            try:
                                # Two-phase contract (live): re-run the one-time
                                # vectorized prepare() on the rolling ≤500-candle
                                # window each closed candle, set index to the last
                                # row, then before() is a pure index lookup —
                                # identical indicator math to the backtest path,
                                # O(≤500) per candle (~once/hr), no drift.
                                strategy.index = len(strategy.candles) - 1
                                strategy.prepare(strategy.candles)
                                strategy.before()

                                if strategy.position is not None:
                                    strategy.position.update_pnl(strategy.price)
                                    await self._verify_exchange_position_still_open(session_id, strategy, symbol)
                                if strategy.position is not None:
                                    await self._check_exits(session_id, strategy, symbol)
                                current_holding = (
                                    strategy.position.qty * (1 if strategy.is_long else -1)
                                ) if strategy.position else 0.0
                                plan = evaluate(strategy, current_holding)
                                if strategy.position is None and plan is not None:
                                    await self._execute_entry(session_id, strategy, symbol, plan)
                                elif strategy.has_pending_flip:
                                    await self._execute_flip(session_id, strategy, symbol)
                                elif strategy._close_at_open:
                                    strategy._close_at_open = False
                                    await self._close_position(
                                        session_id, strategy, symbol, strategy.price, "strategy_exit"
                                    )

                                strategy.after()
                            except Exception as e:
                                consecutive_errors += 1
                                logger.error(
                                    f"[AlgoBot] Strategy error [{symbol}] "
                                    f"(#{consecutive_errors}): {e}"
                                )
                                if consecutive_errors >= 5:
                                    logger.error(
                                        f"[AlgoBot] {symbol} exceeded max errors, stopping."
                                    )
                                    await self._notify_node(session_id, {
                                        "status": "error",
                                        "errorMessage": f"Strategy loop failed on {symbol}: {e}"
                                    })
                                    return
                                continue
                            else:
                                consecutive_errors = 0

                            await self._push_stats(session_id)

                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    if stop_event and stop_event.is_set():
                        return
                    logger.warning(
                        f"[AlgoBot] {symbol}: WS disconnected ({e}), reconnecting in 5s"
                    )
                    await self._notify_node(session_id, {
                        "event": "log",
                        "eventData": {"type": "error", "message": f"{symbol}: WS disconnected — reconnecting in 5s"}
                    })
                    await asyncio.sleep(5)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[AlgoBot] Unexpected error in symbol loop [{symbol}]: {e}")

    async def _execute_entry(
        self, session_id: str, strategy, symbol: str, plan: OrderPlan
    ) -> None:
        """Place a MARKET entry order on Binance Testnet and track position locally."""
        session = self.sessions.get(session_id)
        if not session:
            return

        direction = "long" if plan.direction > 0 else "short"
        qty = plan.qty

        fill_price = strategy.price  # local fill price for PnL tracking

        # Snap quantity and prices to Binance's LOT_SIZE/PRICE_FILTER precision.
        exchange_name = "Binance Futures"
        qty = clamp_and_round_qty(symbol, exchange_name, qty, fill_price)
        sl_raw = plan.stop_loss
        tp_raw = plan.take_profit
        sl_price = round_price(symbol, exchange_name, sl_raw) if sl_raw else None
        tp_price = round_price(symbol, exchange_name, tp_raw) if tp_raw else None

        if qty <= 0:
            logger.warning(f"[AlgoBot] Quantity rounded to 0 for {symbol} (below min lot size), skipping")
            strategy.buy = None
            strategy.sell = None
            return

        # Skip if the bumped notional exceeds the leveraged buying power allocated to this symbol.
        # This prevents BTCUSDT (minNotional=$50) from placing a $50 order when the
        # risk-sized qty was only worth ~$6 — that would risk far more than intended.
        notional = qty * fill_price
        max_allowed_notional = strategy.balance * strategy.leverage * 1.05
        if notional > max_allowed_notional:
            logger.warning(
                f"[AlgoBot] {symbol}: notional ${notional:.2f} exceeds leveraged buying power "
                f"${strategy.balance * strategy.leverage:.2f} (leverage {strategy.leverage}x) after min-notional bump, skipping"
            )
            await self._notify_node(session_id, {
                "event": "log",
                "eventData": {
                    "type": "error",
                    "message": f"Skipped {symbol}: notional ${notional:.2f} exceeds leveraged buying power ${strategy.balance * strategy.leverage:.2f}"
                }
            })
            strategy.buy = None
            strategy.sell = None
            return

        # Validate SL/TP won't immediately trigger at the current candle price.
        # Price can move between candle close and actual fill, causing Binance to
        # reject the conditional order with "would immediately trigger".
        # Drop invalid SL/TP rather than let them blow up the whole order.
        if sl_price is not None:
            if direction == "long" and sl_price >= fill_price:
                logger.warning(f"[AlgoBot] {symbol}: SL {sl_price} >= entry {fill_price}, dropping SL")
                sl_price = None
            elif direction == "short" and sl_price <= fill_price:
                logger.warning(f"[AlgoBot] {symbol}: SL {sl_price} <= entry {fill_price}, dropping SL")
                sl_price = None
        if tp_price is not None:
            if direction == "long" and tp_price <= fill_price:
                logger.warning(f"[AlgoBot] {symbol}: TP {tp_price} <= entry {fill_price}, dropping TP")
                tp_price = None
            elif direction == "short" and tp_price >= fill_price:
                logger.warning(f"[AlgoBot] {symbol}: TP {tp_price} >= entry {fill_price}, dropping TP")
                tp_price = None

        binance_side = "BUY" if direction == "long" else "SELL"
        sem = self._order_semaphores.get(session_id)
        try:
            async with (sem if sem else asyncio.nullcontext()):
                resp = await self._call_node_internal(
                    session_id,
                    f"/internal/algo/sessions/{session_id}/place-order",
                    {
                        "symbol": symbol,
                        "side": binance_side,
                        "type": "MARKET",
                        "quantity": qty,
                        "stopLoss": sl_price,
                        "takeProfit": tp_price,
                    }
                )
            # Verify order response contains success flag and order identifier
            if not resp.get("success"):
                logger.error(f"[AlgoBot] Order placement failed for {symbol}: {resp.get('error', 'Unknown error')}")
                await self._notify_node(session_id, {
                    "event": "log",
                    "eventData": {"type": "error", "message": f"Order failed {symbol}: {resp.get('error', 'Unknown error')}"}
                })
                strategy.buy = None
                strategy.sell = None
                return
            if not resp.get("orderId"):
                logger.warning(f"[AlgoBot] Order placed but no orderId returned for {symbol}, assuming fill succeeded.")
            logger.info(f"[AlgoBot] Testnet {direction} order placed: {symbol} qty={qty}, orderId={resp.get('orderId')}")
        except Exception as e:
            logger.error(f"[AlgoBot] Testnet order failed for {symbol}: {e}")
            await self._notify_node(session_id, {
                "event": "log",
                "eventData": {"type": "error", "message": f"Order failed {symbol}: {e}"}
            })
            strategy.buy = None
            strategy.sell = None
            return

        # Track position locally for SL/TP monitoring and PnL
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
            "leverage": strategy.leverage,
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

        logger.info(f"[AlgoBot] Testnet {direction} filled: {symbol} qty={qty} @ {fill_price}")

    async def _execute_flip(self, session_id: str, strategy, symbol: str) -> None:
        """Execute an atomic close-and-reverse signaled by strategy.flip_position().

        Runs inside the single per-symbol task and is awaited sequentially, so
        the two legs can never interleave with exit checks or another entry for
        this symbol. The pending-flip flag is consumed BEFORE any network call:
        a failed leg is never retried on a later candle, so a Binance error or
        latency desync degrades the flip to close-only (flat) — never to a
        doubled or unprotected position.
        """
        flip = strategy._pending_flip
        strategy._pending_flip = None
        if flip is None or strategy.position is None:
            return

        await self._notify_node(session_id, {
            "event": "log",
            "eventData": {"type": "info", "message": f"{symbol}: flip signal — reversing to {flip['direction']}"}
        })

        # Leg 1 — close the existing position (market, via Node internal route).
        await self._close_position(session_id, strategy, symbol, strategy.price, "flip")
        if strategy.position is not None:
            return  # local close did not complete — never open the opposite leg

        # Leg 2 — open the opposite side with the flip's SL/TP armed.
        # _execute_entry re-validates qty/min-notional and drops an SL/TP that
        # would immediately trigger, exactly like a normal entry.
        qty = flip["qty"]
        if qty <= 0:
            return
        plan = OrderPlan(
            direction=1 if flip["direction"] == "long" else -1,
            qty=qty,
            entry_price=strategy.price,
            stop_loss=flip["stop_loss"],
            take_profit=flip["take_profit"],
            order_type=getattr(strategy, "order_type", "market"),
        )
        await self._execute_entry(session_id, strategy, symbol, plan)

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
        """Close position on Binance Testnet and update local tracking."""
        session = self.sessions.get(session_id)
        if not session or strategy.position is None:
            return

        pos = strategy.position
        sl_price = strategy.stop_loss[1] if strategy.stop_loss else None
        tp_price = strategy.take_profit[1] if strategy.take_profit else None
        entry_time_str = session["open_positions"].get(symbol, {}).get("timestamp")
        entry_time = datetime.fromisoformat(entry_time_str.replace("Z", "+00:00")) if entry_time_str else datetime.now(timezone.utc)
        executed_by = session.get("strategy_name", "unknown")
        exit_time = datetime.now(timezone.utc)

        sem = self._order_semaphores.get(session_id)
        try:
            async with (sem if sem else asyncio.nullcontext()):
                resp = await self._call_node_internal(
                    session_id,
                    f"/internal/algo/sessions/{session_id}/close-position",
                    {"symbol": symbol}
                )
            if not resp.get("success"):
                raise Exception(resp.get("error", "Unknown close error"))
            logger.info(f"[AlgoBot] Testnet close-position sent for {symbol} reason={reason}")
        except Exception as e:
            logger.error(f"[AlgoBot] Testnet close-position failed for {symbol}: {e}")

        fee = strategy.execution_model.exit_fee(strategy, pos.qty, exit_price)
        pos.close(exit_price)
        realized_pnl = pos.pnl - fee
        strategy.balance += realized_pnl
        session["pnl"] += realized_pnl

        event_data = {
            "symbol": symbol,
            "pnl": str(round(realized_pnl, 2)),
            "exitPrice": str(exit_price),
            "exitReason": reason,
            "timestamp": exit_time.isoformat(),
        }

        trade_record = build_trade_record(
            source="bot",
            executed_by=executed_by,
            symbol=symbol,
            side=pos.type,
            qty=str(pos.qty),
            entry_price=str(pos.entry_price),
            exit_price=str(exit_price),
            sl_order_price=str(sl_price) if sl_price is not None else None,
            tp_order_price=str(tp_price) if tp_price is not None else None,
            margin=str(pos.margin) if pos.margin else None,
            liquidation_price=str(pos.liquidation_price) if pos.liquidation_price else None,
            leverage=pos.leverage if pos.leverage else None,
            net_pnl=str(round(realized_pnl, 2)),
            pnl_pct=str(round(pos.pnl_pct, 2)) if pos.pnl_pct else None,
            fee=str(round(fee, 2)) if fee else None,
            exit_reason=reason,
            session_id=session_id,
            strategy_name=session.get("strategy_name"),
            entry_time=entry_time,
            exit_time=exit_time,
        )

        strategy.position = None
        strategy.stop_loss = None
        strategy.take_profit = None
        strategy._pending_flip = None
        session["open_positions"].pop(symbol, None)

        # Persist the trade record BEFORE notifying Node so the server's
        # per-symbol aggregation (computeSymbolStats) sees this closed trade.
        await record_trade(trade_record)

        await self._notify_node(session_id, {
            "pnl": str(round(session["pnl"], 2)),
            "openPositions": list(session["open_positions"].keys()),
            "status": "running",
            "event": "position:close",
            "eventData": event_data,
        })

        logger.info(f"[AlgoBot] Position closed: {symbol} pnl={realized_pnl:.2f} reason={reason}")

    async def _close_position_on_stop(
        self, session_id: str, symbol: str, _pos_info: dict | None, session: dict
    ) -> None:
        """Force-close a position on Binance during session stop.

        Called for every session symbol, not just those in open_positions, so
        that real Binance positions that the engine lost track of are still
        closed. Node's close-position handler is a no-op when positionAmt == 0.
        """
        strategy = session.get("strategy_instances", {}).get(symbol)

        try:
            resp = await self._call_node_internal(
                session_id,
                f"/internal/algo/sessions/{session_id}/close-position",
                {"symbol": symbol}
            )
            if not resp.get("success"):
                raise Exception(resp.get("error", "Unknown close error"))
            logger.info(f"[AlgoBot] Close-position sent for {symbol} on stop")
        except Exception as e:
            logger.error(f"[AlgoBot] Close-position failed for {symbol} on stop: {e}")

        # Update local PnL tracking if the engine knew about this position
        if strategy and strategy.position:
            pos = strategy.position
            sl_price = strategy.stop_loss[1] if strategy.stop_loss else None
            tp_price = strategy.take_profit[1] if strategy.take_profit else None
            entry_time_str = session["open_positions"].get(symbol, {}).get("timestamp")
            entry_time = datetime.fromisoformat(entry_time_str.replace("Z", "+00:00")) if entry_time_str else datetime.now(timezone.utc)
            executed_by = session.get("strategy_name", "unknown")
            exit_time = datetime.now(timezone.utc)
            exit_price = strategy.price

            fee = strategy.execution_model.exit_fee(strategy, pos.qty, exit_price)
            pos.close(exit_price)
            realized_pnl = pos.pnl - fee
            strategy.balance += realized_pnl
            session["pnl"] += realized_pnl

            trade_record = build_trade_record(
                source="bot",
                executed_by=executed_by,
                symbol=symbol,
                side=pos.type,
                qty=str(pos.qty),
                entry_price=str(pos.entry_price),
                exit_price=str(exit_price),
                sl_order_price=str(sl_price) if sl_price is not None else None,
                tp_order_price=str(tp_price) if tp_price is not None else None,
                margin=str(pos.margin) if pos.margin else None,
                liquidation_price=str(pos.liquidation_price) if pos.liquidation_price else None,
                leverage=pos.leverage if pos.leverage else None,
                net_pnl=str(round(realized_pnl, 2)),
                pnl_pct=str(round(pos.pnl_pct, 2)) if pos.pnl_pct else None,
                fee=str(round(fee, 2)) if fee else None,
                exit_reason="session_stop",
                session_id=session_id,
                strategy_name=session.get("strategy_name"),
                entry_time=entry_time,
                exit_time=exit_time,
            )

            strategy.position = None
            strategy.stop_loss = None
            strategy.take_profit = None

            await record_trade(trade_record)

        session["open_positions"].pop(symbol, None)

    async def _verify_exchange_position_still_open(self, session_id: str, strategy, symbol: str) -> None:
        """Verify that the local open position is still open on the exchange.
        If it has been closed (e.g. via Binance SL/TP or manual close), clean up local state."""
        session = self.sessions.get(session_id)
        if not session or strategy.position is None:
            return
        
        try:
            resp = await self._call_node_internal(
                session_id,
                f"/internal/algo/sessions/{session_id}/get-position",
                {"symbol": symbol}
            )
            if not resp.get("success"):
                return
            pos = resp.get("data")
            is_closed = False
            if not pos:
                is_closed = True
            else:
                amt = float(pos.get("positionAmt", 0))
                if amt == 0:
                    is_closed = True
                else:
                    exchange_dir = "long" if amt > 0 else "short"
                    local_dir = strategy.position.type
                    if exchange_dir != local_dir:
                        is_closed = True
            
            if is_closed:
                logger.warning(f"[AlgoBot] {symbol}: detected position closed on exchange. Syncing local state to flat.")
                pos = strategy.position
                fee = strategy.execution_model.exit_fee(strategy, pos.qty, strategy.price)
                pos.close(strategy.price)
                realized_pnl = pos.pnl - fee
                strategy.balance += realized_pnl
                session["pnl"] += realized_pnl
                
                exit_time = datetime.now(timezone.utc)
                entry_time_str = session["open_positions"].get(symbol, {}).get("timestamp")
                entry_time = datetime.fromisoformat(entry_time_str.replace("Z", "+00:00")) if entry_time_str else exit_time
                
                event_data = {
                    "symbol": symbol,
                    "pnl": str(round(realized_pnl, 2)),
                    "exitPrice": str(strategy.price),
                    "exitReason": "exchange_sync",
                    "timestamp": exit_time.isoformat(),
                }
                
                trade_record = build_trade_record(
                    source="bot",
                    executed_by=session.get("strategy_name", "unknown"),
                    symbol=symbol,
                    side=pos.type,
                    qty=str(pos.qty),
                    entry_price=str(pos.entry_price),
                    exit_price=str(strategy.price),
                    sl_order_price=str(strategy.stop_loss[1]) if strategy.stop_loss else None,
                    tp_order_price=str(strategy.take_profit[1]) if strategy.take_profit else None,
                    margin=str(pos.margin) if pos.margin else None,
                    liquidation_price=str(pos.liquidation_price) if pos.liquidation_price else None,
                    leverage=pos.leverage if pos.leverage else None,
                    net_pnl=str(round(realized_pnl, 2)),
                    pnl_pct=str(round(pos.pnl_pct, 2)) if pos.pnl_pct else None,
                    fee=str(round(fee, 2)) if fee else None,
                    exit_reason="exchange_sync",
                    session_id=session_id,
                    strategy_name=session.get("strategy_name"),
                    entry_time=entry_time,
                    exit_time=exit_time,
                )
                
                strategy.position = None
                strategy.stop_loss = None
                strategy.take_profit = None
                strategy._pending_flip = None
                session["open_positions"].pop(symbol, None)
                
                await record_trade(trade_record)
                
                await self._notify_node(session_id, {
                    "pnl": str(round(session["pnl"], 2)),
                    "openPositions": list(session["open_positions"].keys()),
                    "status": "running",
                    "event": "position:close",
                    "eventData": event_data,
                })
        except Exception as e:
            logger.warning(f"[AlgoBot] {symbol}: position verification failed — {e}")

    async def _sync_open_position(self, session_id: str, strategy, symbol: str) -> None:
        """Query Binance for an existing position on this symbol and restore it into
        the engine's local state. Called once per symbol at loop startup so that
        positions opened before the engine tracked them (e.g. from a previous run
        where SL/TP placement failed and caused an early return) are not ignored."""
        session = self.sessions.get(session_id)
        if not session:
            return
        try:
            resp = await self._call_node_internal(
                session_id,
                f"/internal/algo/sessions/{session_id}/get-position",
                {"symbol": symbol}
            )
            if not resp.get("success"):
                return
            pos = resp.get("data")
            if not pos:
                return
            amt = float(pos.get("positionAmt", 0))
            if amt == 0:
                return

            direction = "long" if amt > 0 else "short"
            qty = abs(amt)
            entry_price = float(pos.get("entryPrice", 0))
            if entry_price == 0:
                return

            logger.info(f"[AlgoBot] {symbol}: found existing {direction} position qty={qty} @ {entry_price}, restoring")
            strategy.position = Position(direction, qty, entry_price)
            pos_info = {
                "symbol": symbol,
                "side": direction,
                "qty": str(qty),
                "price": str(entry_price),
                "leverage": strategy.leverage,
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
        except Exception as e:
            logger.warning(f"[AlgoBot] {symbol}: position sync failed — {e}")

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

    async def _call_node_internal(self, session_id: str, path: str, body: dict) -> dict:
        """Call a Node internal endpoint and return parsed JSON response."""
        try:
            async with httpx.AsyncClient(timeout=45.0) as client:
                resp = await client.post(f"{SERVER_URL}{path}", json=body)
                return resp.json()
        except Exception as e:
            logger.error(f"[AlgoBot] Node internal call failed ({path}): {e}")
            return {"success": False, "error": str(e)}

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
                    symbol,
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

    async def _fetch_candles_from_rest(
        self, symbol: str, timeframe: str, limit: int
    ) -> np.ndarray:
        """Fetch recent candles from Binance Futures mainnet REST as warmup fallback."""
        url = "https://fapi.binance.com/fapi/v1/klines"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(url, params={
                    "symbol": symbol,
                    "interval": timeframe,
                    "limit": limit,
                })
                resp.raise_for_status()
                raw = resp.json()
            if not raw:
                return np.empty((0, 6), dtype=np.float64)
            raw = raw[:-1]  # Exclude the currently open candle
            # Binance kline: [openTime, open, high, low, close, volume, ...]
            candles = np.empty((len(raw), 6), dtype=np.float64)
            for i, c in enumerate(raw):
                candles[i, 0] = float(c[0])  # timestamp ms
                candles[i, 1] = float(c[1])  # open
                candles[i, 2] = float(c[4])  # close
                candles[i, 3] = float(c[2])  # high
                candles[i, 4] = float(c[3])  # low
                candles[i, 5] = float(c[5])  # volume
            return candles
        except Exception as e:
            logger.error(f"[AlgoBot] Binance REST candle fetch failed for {symbol}: {e}")
            return np.empty((0, 6), dtype=np.float64)

    async def _fetch_htf_candles(
        self, symbol: str, tf_interval: str, limit: int = 50
    ) -> np.ndarray:
        """Fetch HTF candles from Binance Futures REST for live multi-timeframe strategies.
        Returns the same [timestamp_ms, open, close, high, low, volume] layout as base candles.
        Excludes the currently open candle (same as _fetch_candles_from_rest)."""
        url = "https://fapi.binance.com/fapi/v1/klines"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(url, params={
                    "symbol": symbol,
                    "interval": tf_interval,
                    "limit": limit,
                })
                resp.raise_for_status()
                raw = resp.json()
            if not raw:
                return np.empty((0, 6), dtype=np.float64)
            raw = raw[:-1]  # Exclude the currently open candle
            candles = np.empty((len(raw), 6), dtype=np.float64)
            for i, c in enumerate(raw):
                candles[i, 0] = float(c[0])  # timestamp ms
                candles[i, 1] = float(c[1])  # open
                candles[i, 2] = float(c[4])  # close
                candles[i, 3] = float(c[2])  # high
                candles[i, 4] = float(c[3])  # low
                candles[i, 5] = float(c[5])  # volume
            return candles
        except Exception as e:
            logger.error(f"[AlgoBot] HTF REST fetch failed for {symbol} {tf_interval}: {e}")
            return np.empty((0, 6), dtype=np.float64)

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
