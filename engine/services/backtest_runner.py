import os
import importlib
import asyncio
import numpy as np
from datetime import datetime, timezone, timedelta
import json
import logging
import redis.asyncio as aioredis

from config.timescale import get_pool
from config.mongo import get_database
from core.position import Position
from core.models import BacktestExecution
from core.pipeline import evaluate
from services.candle_manager import ensure_candles_available
from utils.timeframes import annual_factor
from decimal import ROUND_DOWN, ROUND_UP
from utils.symbols import _MAX_LEVERAGE_OFFLINE_MAP, clamp_and_round_qty, round_price
# Phase 2 — pluggable metric registry (A-012) + new metrics (A-007) + breakdown tables (A-008)
from services.metrics import MetricContext, default_registry
# Phase 2 — backtest curves: underwater (A-009), returns/MFE-MAE (A-010), rolling (A-011)
from services.curves import (
    underwater_curve_with_timestamps,
    returns_histogram,
    mfe_mae_scatter,
    rolling_curve,
    timeframe_to_seconds,
)
# Phase 2 — fill realism: gap-through stops (F-011), candle-bounded fills (F-012)
from services.fill_model import gap_through_stop_price, bounded_exit_price, bounded_entry_price

logger = logging.getLogger(__name__)

# Maximum equity-curve points stored in MongoDB.
# Downsampling keeps the document well under 1 MB even for 1-minute 3-year runs
# (~1.57 M candles → 1.57 M raw points → 1 000 stored points).
EQUITY_CURVE_MAX_POINTS = 1_000

# Batch size for bulk-inserting trades into backtestTrades collection
TRADE_INSERT_BATCH = 500

# ── Futures execution-realism defaults (see DECISIONS.md #10) ───────────────
# The `fee_rate` passed into run_backtest_simulation is treated as the TAKER
# rate (market fills: entry, SL/TP, liquidation, force-close). Resting limit
# fills would use MAKER_FEE, but the current engine only models market fills.
MAKER_FEE = 0.0002          # 0.02% — Binance USDⓈ-M maker
SLIPPAGE_PCT = 0.0005       # 0.05% adverse slippage applied to every market fill
FUNDING_RATE = 0.0          # per-8h funding rate; 0.0 disables funding entirely
FUNDING_HOURS = (0, 8, 16)  # UTC hours at which perpetual funding is charged


def _next_funding_boundary(dt: datetime) -> datetime:
    """Next funding timestamp strictly after ``dt`` (00:00/08:00/16:00 UTC)."""
    base = dt.replace(minute=0, second=0, microsecond=0)
    for add in range(0, 25):
        cand = base + timedelta(hours=add)
        if cand > dt and cand.hour in FUNDING_HOURS:
            return cand
    return dt + timedelta(hours=8)


def _finalize_trade(
    active_trade: dict,
    exit_idx: int,
    exit_price: float,
    exit_at: datetime,
    exit_reason: str,
    realized_pnl: float,
    pnl_pct: float,
    high_t: float,
    low_t: float,
) -> dict:
    entry = float(active_trade["entryPrice"])
    is_long = active_trade["type"] == "long"
    
    # Excursion update for exit candle
    if is_long:
        active_trade["_mfe"] = max(active_trade["_mfe"], high_t - entry)
        active_trade["_mae"] = min(active_trade["_mae"], low_t - entry)
    else:
        active_trade["_mfe"] = max(active_trade["_mfe"], entry - low_t)
        active_trade["_mae"] = min(active_trade["_mae"], entry - high_t)
        
    active_trade["runUpPct"] = f"{(active_trade['_mfe'] / entry) * 100:.2f}"
    active_trade["drawdownPct"] = f"{abs(active_trade['_mae'] / entry) * 100:.2f}"
    active_trade["barsHeld"] = int(exit_idx - active_trade["_entry_index"])
    
    active_trade.update({
        "exitPrice": str(exit_price),
        "exitAt": exit_at.isoformat(),
        "_exit_dt": exit_at,
        "exitReason": exit_reason,
        "pnl": f"{realized_pnl:.2f}",
        "pnlPct": f"{pnl_pct:.2f}",
    })
    return active_trade


def _compute_side_metrics(side_trades: list[dict], starting_capital: float) -> dict:
    n = len(side_trades)
    if n == 0:
        return {
            "totalTrades": 0,
            "winningTrades": 0,
            "losingTrades": 0,
            "winRate": "0.00",
            "netProfit": "0.00",
            "netProfitPct": "0.00",
            "grossProfit": "0.00",
            "grossLoss": "0.00",
            "profitFactor": "0.00",
            "averageWin": "0.00",
            "averageLoss": "0.00",
            "payoffRatio": "0.00",
            "averageHoldingPeriod": "0",
            "maxConsecutiveWins": 0,
            "maxConsecutiveLosses": 0,
        }
        
    pnls = np.array([float(t["pnl"]) for t in side_trades], dtype=np.float64)
    win_pnl = pnls[pnls > 0]
    loss_pnl = pnls[pnls <= 0]
    
    winning_trades = int(win_pnl.size)
    losing_trades = n - winning_trades
    win_rate = winning_trades / n
    
    net_profit = float(np.sum(pnls))
    net_profit_pct = (net_profit / starting_capital) * 100.0
    
    gross_profit = float(np.sum(win_pnl)) if win_pnl.size else 0.0
    gross_loss = float(np.sum(loss_pnl)) if loss_pnl.size else 0.0
    
    profit_factor = gross_profit / abs(gross_loss) if gross_loss != 0.0 else 0.0
    
    avg_win = float(np.mean(win_pnl)) if win_pnl.size else 0.0
    avg_loss = float(np.mean(loss_pnl)) if loss_pnl.size else 0.0
    payoff_ratio = avg_win / abs(avg_loss) if avg_loss != 0.0 else 0.0
    
    # Average holding period
    durations = [
        (tr["_exit_dt"] - tr["_entry_dt"]).total_seconds()
        for tr in side_trades
        if "_exit_dt" in tr and "_entry_dt" in tr
    ]
    avg_holding = float(np.mean(durations)) if durations else 0.0
    
    # Consecutive streaks
    max_wins = cur_wins = 0
    max_losses = cur_losses = 0
    for p in pnls:
        if p > 0:
            cur_wins += 1
            cur_losses = 0
            max_wins = max(max_wins, cur_wins)
        else:
            cur_losses += 1
            cur_wins = 0
            max_losses = max(max_losses, cur_losses)
            
    return {
        "totalTrades": n,
        "winningTrades": winning_trades,
        "losingTrades": losing_trades,
        "winRate": f"{win_rate:.2f}",
        "netProfit": f"{net_profit:.2f}",
        "netProfitPct": f"{net_profit_pct:.2f}",
        "grossProfit": f"{gross_profit:.2f}",
        "grossLoss": f"{gross_loss:.2f}",
        "profitFactor": f"{profit_factor:.2f}",
        "averageWin": f"{avg_win:.2f}",
        "averageLoss": f"{avg_loss:.2f}",
        "payoffRatio": f"{payoff_ratio:.2f}",
        "averageHoldingPeriod": f"{int(avg_holding)}",
        "maxConsecutiveWins": max_wins,
        "maxConsecutiveLosses": max_losses,
    }


def _safe_float(val, default):
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


async def run_backtest_simulation(
    job_id: str,
    strategy_file: str,
    exchange: str,
    symbol: str,
    timeframe: str,
    start_date: str,
    end_date: str,
    capital: float,
    leverage: int,
    fee_rate: float,
    slippage_pct: float | None = None,
    funding_enabled: bool = False,
    funding_rate: float | None = None,
    alpha_params: dict | None = None,
    risk_params: dict | None = None,
) -> dict:
    # ── 1. Parse strategy name ──────────────────────────────────────────────
    parts = strategy_file.split("/")
    if len(parts) >= 2 and parts[0] == "strategies":
        strategy_name = parts[1]
    else:
        strategy_name = strategy_file.replace("strategies/", "").split("/")[0]

    logger.info(f"[{job_id}] Initializing backtest for strategy: {strategy_name}")

    # ── 2. Dynamic import ───────────────────────────────────────────────────
    try:
        module = importlib.import_module(f"strategies.{strategy_name}")
        strategy_class = getattr(module, strategy_name)
    except Exception as e:
        raise RuntimeError(f"STRATEGY_ERROR: Failed to load strategy {strategy_name}: {e}")

    # ── 3. Ensure candles are available ─────────────────────────────────────
    start_dt = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
    end_dt   = datetime.fromisoformat(end_date).replace(tzinfo=timezone.utc)

    candles_available = await ensure_candles_available(
        job_id=job_id,
        exchange=exchange,
        symbol=symbol,
        timeframe=timeframe,
        start_date=start_date,
        end_date=end_date,
    )
    if not candles_available:
        raise ValueError(
            f"INSUFFICIENT_CANDLES: Failed to fetch required candles for {symbol} "
            f"on {exchange}. Please check your date range and try again."
        )

    logger.info(f"[{job_id}] Candles verified. Loading for simulation...")

    # ── 4. Load candles from TimescaleDB ────────────────────────────────────
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT time, open, close, high, low, volume
            FROM candles
            WHERE exchange = $1 AND symbol = $2 AND timeframe = $3 AND time >= $4 AND time < $5
            ORDER BY time ASC
            """,
            exchange, symbol, timeframe, start_dt, end_dt,
        )

    if len(rows) < 50:
        raise ValueError(
            f"INSUFFICIENT_CANDLES: Only {len(rows)} candles found. "
            "Minimum 50 candles required for backtesting warm-up."
        )

    # ── 5. Build candle numpy array ─────────────────────────────────────────
    # Column order: [timestamp_ms, open, close, high, low, volume]
    candles_np = np.column_stack([
        [r["time"].timestamp() * 1000 for r in rows],
        [r["open"]   for r in rows],
        [r["close"]  for r in rows],
        [r["high"]   for r in rows],
        [r["low"]    for r in rows],
        [r["volume"] for r in rows],
    ]).astype(np.float64)

    # ── 6. Initialise strategy ──────────────────────────────────────────────
    strategy = strategy_class()
    strategy.exchange       = exchange
    strategy.symbol         = symbol
    strategy.timeframe      = timeframe
    strategy.balance        = capital
    strategy.available_margin = capital
    strategy.leverage       = leverage
    strategy.fee_rate       = fee_rate
    strategy.exchange_type  = "futures" if "Futures" in exchange else "spot"
    strategy.is_backtesting = True

    # Resolve per-run simulation parameters first — needed for risk injection below.
    # fee_rate (taker) and _slippage are mirrored onto the strategy at 6b and are
    # the single source the Cost Model reads for every fee/slippage fill (Phase 2).
    _slippage   = slippage_pct   if slippage_pct   is not None else SLIPPAGE_PCT
    _fund_rate  = funding_rate   if funding_rate   is not None else FUNDING_RATE
    _funding_on = funding_enabled
    leverage    = max(int(leverage), 1)
    # Clamp leverage defensively to absolute schema limit (125) (F-014)
    leverage    = min(leverage, 125)
    # Clamp leverage to symbol max using offline map (no creds in worker).
    _sym_max_lev = _MAX_LEVERAGE_OFFLINE_MAP.get(symbol, 20)
    leverage     = min(leverage, _sym_max_lev)

    # ── 6a. Inject and validate alpha params (BUG-02 fix) ────────────────
    # Previously strategy_class() was called with no params — every UI config
    # was ignored and all runs used the strategy's hardcoded defaults.
    for key, val in (alpha_params or {}).items():
        if hasattr(strategy, "PARAMS") and key in strategy.PARAMS:
            bounds = strategy.PARAMS[key]
            try:
                typed_val = type(bounds["default"])(val)
            except (TypeError, ValueError):
                typed_val = val
            typed_val = max(bounds["min"], min(bounds["max"], typed_val))
            setattr(strategy, key, typed_val)
        elif hasattr(strategy, key):
            setattr(strategy, key, val)

    try:
        strategy.validate_params()
    except ValueError as e:
        raise RuntimeError(f"PARAM_ERROR: {e}")

    # ── 6a'. One-time vectorized indicator pre-computation ───────────────
    # Two-phase strategy contract: prepare() computes all indicators once over
    # the full candle array (C-speed), and before() indexes into those arrays at
    # strategy.index (set to the absolute index `t` in step B). Default prepare()
    # is a no-op, so unmigrated strategies are unaffected. Eliminates the O(N²)
    # recompute-on-growing-slice pattern (see workspace/plan strategy refactor).
    try:
        strategy.prepare(candles_np)
    except Exception as e:
        raise RuntimeError(f"STRATEGY_ERROR: prepare() failed: {e}")

    # ── 6b. Inject risk model params ──────────────────────────────────
    _risk_all = risk_params or {}
    _risk = _risk_all.get(symbol) or _risk_all.get("default") or _risk_all
    
    # Enforce global risk hard-limits as a defensive floor (F-014)
    strategy.risk_pct          = min(_safe_float(_risk.get("risk_pct"),       0.01), 0.20)
    strategy.rrr               = _safe_float(_risk.get("rrr"),            2.0)
    strategy.liq_buffer_pct    = _safe_float(_risk.get("liq_buffer_pct"), 0.005)
    strategy.max_session_dd    = min(_safe_float(_risk.get("max_session_dd"), 0.20), 0.90)
    strategy.cost_model.min_edge_mult = _safe_float(_risk.get("min_edge_mult"),     0.05)
    strategy.max_portfolio_risk       = _safe_float(_risk.get("max_portfolio_risk"), 0.06)
    
    strategy.volatility_multiplier = _safe_float(_risk.get("volatility_multiplier"), 1.0)
    strategy.max_exposure_notional = _safe_float(_risk.get("max_exposure_notional"), float('inf'))
    
    custom_atr_mult = _risk.get("custom_atr_mult")
    if custom_atr_mult is not None:
        strategy.custom_atr_mult = _safe_float(custom_atr_mult, None)
    else:
        strategy.custom_atr_mult = None
    strategy.slippage_pct      = _slippage
    strategy.fee_rate          = fee_rate
    strategy.available_capital = float(capital)
    strategy.peak_equity       = float(capital)

    # Execution Model for this run — backtest env (next-open market fills).
    # The single owner of fill assembly (price+notional+margin+fee); it composes
    # the strategy's Cost Model, so a custom cost_model still flows through.
    execution = BacktestExecution()

    # ── 6c. Enforce minimum warm-up (D-02 fix) ─────────────────────────
    warmup_period = max(strategy.MIN_WARMUP_CANDLES, min(50, len(rows) - 2))

    # equity_curve stores raw (iso_str, float) tuples — converted to dicts only
    # after downsampling, avoiding millions of dict allocations in the hot path.
    equity_timestamps: list[str]   = []
    equity_balances:   list[float] = []
    trades: list[dict] = []
    active_trade: dict | None = None
    total_fees = 0.0
    total_funding = 0.0
    liquidations = 0
    last_funding_dt = None  # last UTC funding boundary already charged for the open position

    # ── 7. Redis connection ─────────────────────────────────────────────────
    redis_url = os.getenv("REDIS_URL", "redis://redis:6379")
    # socket_timeout=None: disables the per-read socket timeout on the publish
    # client. Heavy strategies (MultiDivergence, BestSupertrend) block the
    # asyncio event loop for several seconds between publish calls (100 candles
    # × 50-100ms each). redis-py 8.x defaults to socket_timeout=5s which causes
    # "Timeout reading from redis:6379" before the simulation completes.
    r_client = aioredis.from_url(redis_url, socket_timeout=None, socket_connect_timeout=10)

    # ── 8. Async cancel-listener task ───────────────────────────────────────
    # Subscribes to backtest:cancel:{job_id} channel on a separate connection so
    # the hot-loop never makes a network round-trip.  It just flips a flag.
    is_cancelled = False

    async def _watch_cancel():
        nonlocal is_cancelled
        cancel_sub = aioredis.from_url(redis_url, socket_timeout=None, socket_connect_timeout=10)
        pubsub = cancel_sub.pubsub()
        await pubsub.subscribe(f"backtest:cancel:{job_id}")
        try:
            async for msg in pubsub.listen():
                if msg["type"] == "message":
                    is_cancelled = True
                    break
        except asyncio.CancelledError:
            pass
        finally:
            await pubsub.unsubscribe(f"backtest:cancel:{job_id}")
            await cancel_sub.aclose()

    cancel_task = asyncio.create_task(_watch_cancel())

    logger.info(f"[{job_id}] Running simulation loop on {len(rows)} candles...")
    total_candles = len(rows)

    try:
        for t in range(warmup_period, total_candles):
            # ── 8a. Progress publish + cancel check every 100 steps ─────────
            if t % 100 == 0:
                if is_cancelled:
                    logger.info(f"[{job_id}] Cancelled by user.")
                    raise RuntimeError("JOB_CANCELLED")

                pct = int((t / total_candles) * 100)
                await r_client.publish(
                    f"progress:{job_id}",
                    json.dumps({
                        "pct": pct,
                        "message": f"Simulating {symbol} {timeframe} — {pct}% ({t}/{total_candles} candles)",
                    }),
                )

            # ── 8b. Candle values ────────────────────────────────────────────
            time_t  = rows[t]["time"]
            open_t  = candles_np[t, 1]
            close_t = candles_np[t, 2]
            high_t  = candles_np[t, 3]
            low_t   = candles_np[t, 4]

            # ── A0. Atomic flip (close-and-reverse) at this candle's open ───
            # Signaled by flip_position() inside update_position() on the
            # previous candle. Both legs fill at this candle's OPEN as one
            # unit, so the reversed position enters this candle's
            # liquidation/SL/TP checks below with its protective orders armed.
            if strategy.position is not None and strategy._pending_flip is not None:
                flip = strategy._pending_flip
                strategy._pending_flip = None
                was_long = strategy.is_long

                # Leg 1 — close the old position (market fill: slippage + taker fee)
                exit_qty  = strategy.position.qty
                _fill = execution.exit_fill(strategy, open_t, exit_qty, "sell" if was_long else "buy")
                exit_fill = _fill.fill_price
                fee = _fill.fee
                total_fees += fee
                strategy.position.close(exit_fill)
                realized_pnl      = strategy.position.pnl - fee
                strategy.balance += realized_pnl
                strategy.available_margin = strategy.balance
                last_funding_dt = None

                if active_trade:
                    active_trade["id"] = f"t_{len(trades) + 1}"
                    active_trade = _finalize_trade(
                        active_trade,
                        t,
                        exit_fill,
                        time_t,
                        "flip",
                        realized_pnl,
                        strategy.position.pnl_pct,
                        high_t,
                        low_t,
                    )
                    trades.append(active_trade)
                    active_trade = None

                try:
                    strategy.on_close_position((exit_qty, exit_fill))
                except Exception as e:
                    logger.error(f"on_close_position error: {e}")

                strategy.position    = None
                strategy.stop_loss   = None
                strategy.take_profit = None

                # Leg 2 — open the opposite side at the same open (margin permitting)
                new_dir    = flip["direction"]
                new_qty    = flip["qty"]
                exchange_name = strategy.exchange or "Binance Futures"
                
                # Derive stoploss percent for reserve-calculating quantity clamps (F-008)
                sl_pct = abs(open_t - flip["stop_loss"]) / open_t if flip["stop_loss"] is not None else None
                new_qty = clamp_and_round_qty(symbol, exchange_name, new_qty, open_t, stop_loss_pct=sl_pct)

                if new_qty <= 0:
                    logger.warning(f"[{job_id}] Flip degraded to close-only: quantity rounded to 0")
                    strategy.position    = None
                    strategy.stop_loss   = None
                    strategy.take_profit = None
                else:
                    _entry = execution.entry_fill(strategy, open_t, new_qty, leverage,
                                                  "buy" if new_dir == "long" else "sell")
                    fill_price = _entry.fill_price
                    notional   = _entry.notional
                    req_margin = _entry.req_margin
                    fee        = _entry.fee
                    if not _entry.affordable(strategy.balance):
                        logger.warning(
                            f"[{job_id}] Flip degraded to close-only: qty {new_qty} margin "
                            f"${req_margin:.2f} + fee ${fee:.2f} vs balance ${strategy.balance:.2f}"
                        )
                        strategy.position    = None
                        strategy.stop_loss   = None
                        strategy.take_profit = None
                    else:
                        total_fees       += fee
                        strategy.balance -= fee
                        strategy.position = Position(
                            new_dir, new_qty, fill_price, leverage,
                            isolated_wallet=req_margin,
                        )
                        strategy.available_margin = strategy.balance - req_margin
                        last_funding_dt = time_t
                        
                        # SL/TP supplied with the flip are armed before exit checks; round to tickSize direction-awarely (F-006 / F-007)
                        rounding_mode = ROUND_DOWN if new_dir == "long" else ROUND_UP
                        strategy.stop_loss   = (new_qty, round_price(symbol, exchange_name, flip["stop_loss"], rounding=rounding_mode)) if flip["stop_loss"] is not None else None
                        strategy.take_profit = (new_qty, round_price(symbol, exchange_name, flip["take_profit"], rounding=rounding_mode)) if flip["take_profit"] is not None else None

                        # active_trade is built ONLY when the new leg actually
                        # opened. When the flip degrades to close-only above,
                        # strategy.position is None and active_trade stays None
                        # (set in leg 1) — building it here would deref None.
                        active_trade = {
                            "type":       new_dir,
                            "qty":        str(new_qty),
                            "entryPrice": str(fill_price),
                            "entryAt":    time_t.isoformat(),
                            "_entry_dt":  time_t,
                            "_entry_index": t,
                            "_mfe":       0.0,
                            "_mae":       0.0,
                            "leverage":   leverage,
                            "liqPrice":   f"{strategy.position.liquidation_price:.4f}",
                        }
                        try:
                            strategy.on_open_position((new_qty, fill_price))
                        except Exception as e:
                            logger.error(f"on_open_position error: {e}")

            # ── A1. Strategy-requested close (close_position() flag) ─────────
            # Checked after atomic flip (A0) but before new entry (A2).
            # Guaranteed market exit at this candle's open — cannot be
            # pre-empted by SL/TP legs (BUG-03 fix).
            if strategy.position is not None and strategy._close_at_open:
                strategy._close_at_open = False
                was_long_close = strategy.is_long
                exit_qty_close  = strategy.position.qty
                _fill = execution.exit_fill(strategy, open_t, exit_qty_close, "sell" if was_long_close else "buy")
                exit_fill_close = _fill.fill_price
                fee = _fill.fee
                total_fees += fee
                strategy.position.close(exit_fill_close)
                realized_pnl = strategy.position.pnl - fee
                strategy.balance += realized_pnl
                strategy.available_capital += strategy.position.margin + realized_pnl
                strategy.available_margin = strategy.balance
                last_funding_dt = None

                if active_trade:
                    active_trade["id"] = f"t_{len(trades) + 1}"
                    active_trade = _finalize_trade(
                        active_trade,
                        t,
                        exit_fill_close,
                        time_t,
                        "strategy_exit",
                        realized_pnl,
                        strategy.position.pnl_pct,
                        high_t,
                        low_t,
                    )
                    trades.append(active_trade)
                    active_trade = None

                try:
                    strategy.on_close_position((exit_qty_close, exit_fill_close))
                except Exception as e:
                    logger.error(f"on_close_position error (strategy_exit): {e}")

                strategy.position      = None
                strategy.stop_loss     = None
                strategy.take_profit   = None
                strategy._pending_flip = None

            # ── A2. Execute pending entry orders ────────────────────────────
            if strategy.position is None:
                # Let strategy cancel a pending entry before it fills
                if strategy.buy is not None or strategy.sell is not None:
                    try:
                        if strategy.should_cancel_entry():
                            strategy.buy  = None
                            strategy.sell = None
                    except Exception as e:
                        logger.error(f"Strategy should_cancel_entry error: {e}")

                # Buy (long entry) — market order: fills at open of next candle (F-005)
                if strategy.buy is not None:
                    buy_qty, _ = strategy.buy
                    exchange_name = strategy.exchange or "Binance Futures"
                    
                    sl_pct = None
                    if strategy.stop_loss is not None:
                        _, sl_price = strategy.stop_loss
                        sl_pct = abs(open_t - sl_price) / open_t
                        
                    buy_qty = clamp_and_round_qty(symbol, exchange_name, buy_qty, open_t, stop_loss_pct=sl_pct)
                    
                    if buy_qty <= 0:
                        strategy.buy         = None
                        strategy.stop_loss   = None
                        strategy.take_profit = None
                    else:
                        _entry = execution.entry_fill(strategy, open_t, buy_qty, leverage, "buy")
                        fill_price = _entry.fill_price          # adverse slippage
                        notional   = _entry.notional
                        req_margin = _entry.req_margin
                        fee        = _entry.fee
                        if not _entry.affordable(strategy.balance):
                            logger.warning(
                                f"[{job_id}] Long entry rejected: margin ${req_margin:.2f} + fee "
                                f"${fee:.2f} exceeds balance ${strategy.balance:.2f}"
                            )
                            strategy.buy         = None
                            strategy.stop_loss   = None
                            strategy.take_profit = None
                        else:
                            total_fees       += fee
                            strategy.balance -= fee
                            strategy.position = Position(
                                "long", buy_qty, fill_price, leverage,
                                isolated_wallet=req_margin,
                            )
                            strategy.available_capital -= req_margin
                            strategy.available_margin = strategy.balance - req_margin
                            last_funding_dt = time_t
                            active_trade = {
                                "type":       "long",
                                "qty":        str(buy_qty),
                                "entryPrice": str(fill_price),
                                "entryAt":    time_t.isoformat(),
                                "_entry_dt":  time_t,
                                "_entry_index": t,
                                "_mfe":       0.0,
                                "_mae":       0.0,
                                "leverage":   leverage,
                                "liqPrice":   f"{strategy.position.liquidation_price:.4f}",
                            }
                            try:
                                strategy.on_open_position((buy_qty, fill_price))
                            except Exception as e:
                                logger.error(f"on_open_position error: {e}")
                            strategy.buy = None

                # Sell (short entry) — market order: fills at open of next candle (F-005)
                elif strategy.sell is not None:
                    sell_qty, _ = strategy.sell
                    exchange_name = strategy.exchange or "Binance Futures"
                    
                    sl_pct = None
                    if strategy.stop_loss is not None:
                        _, sl_price = strategy.stop_loss
                        sl_pct = abs(open_t - sl_price) / open_t
                        
                    sell_qty = clamp_and_round_qty(symbol, exchange_name, sell_qty, open_t, stop_loss_pct=sl_pct)
                    
                    if sell_qty <= 0:
                        strategy.sell        = None
                        strategy.stop_loss   = None
                        strategy.take_profit = None
                    else:
                        _entry = execution.entry_fill(strategy, open_t, sell_qty, leverage, "sell")
                        fill_price = _entry.fill_price          # adverse slippage
                        notional   = _entry.notional
                        req_margin = _entry.req_margin
                        fee        = _entry.fee
                        if not _entry.affordable(strategy.balance):
                            logger.warning(
                                f"[{job_id}] Short entry rejected: margin ${req_margin:.2f} + fee "
                                f"${fee:.2f} exceeds balance ${strategy.balance:.2f}"
                            )
                            strategy.sell        = None
                            strategy.stop_loss   = None
                            strategy.take_profit = None
                        else:
                            total_fees       += fee
                            strategy.balance -= fee
                            strategy.position = Position(
                                "short", sell_qty, fill_price, leverage,
                                isolated_wallet=req_margin,
                            )
                            strategy.available_capital -= req_margin
                            strategy.available_margin = strategy.balance - req_margin
                            last_funding_dt = time_t
                            active_trade = {
                                "type":       "short",
                                "qty":        str(sell_qty),
                                "entryPrice": str(fill_price),
                                "entryAt":    time_t.isoformat(),
                                "_entry_dt":  time_t,
                                "_entry_index": t,
                                "_mfe":       0.0,
                                "_mae":       0.0,
                                "leverage":   leverage,
                                "liqPrice":   f"{strategy.position.liquidation_price:.4f}",
                            }
                            try:
                                strategy.on_open_position((sell_qty, fill_price))
                            except Exception as e:
                                logger.error(f"on_open_position error: {e}")
                            strategy.sell = None

            else:
                # ── Position open: update unrealized P&L ──────────────────
                strategy.position.update_pnl(close_t)

                # Update MFE/MAE excursions
                if active_trade is not None:
                    entry = float(active_trade["entryPrice"])
                    if strategy.is_long:
                        active_trade["_mfe"] = max(active_trade["_mfe"], high_t - entry)
                        active_trade["_mae"] = min(active_trade["_mae"], low_t - entry)
                    else:
                        active_trade["_mfe"] = max(active_trade["_mfe"], entry - low_t)
                        active_trade["_mae"] = min(active_trade["_mae"], entry - high_t)

                # ── Funding: notional × rate at each 8h UTC boundary ────────
                # A positive rate means longs pay shorts — shorts RECEIVE it.
                # total_funding is net funding paid (negative = received).
                if _funding_on and _fund_rate and last_funding_dt is not None:
                    side_sign = 1.0 if strategy.position.type == "long" else -1.0
                    boundary = _next_funding_boundary(last_funding_dt)
                    while boundary <= time_t:
                        funding = side_sign * strategy.position.qty * close_t * _fund_rate
                        total_funding    += funding
                        strategy.balance -= funding
                        last_funding_dt   = boundary
                        boundary = _next_funding_boundary(boundary)

                closed      = False
                exit_price  = 0.0
                exit_reason = ""
                was_long    = strategy.is_long  # captured before close() flips is_open

                # ── Liquidation is checked BEFORE stop-loss / take-profit ──
                if strategy.position.is_liquidated(high_t, low_t):
                    exit_price   = strategy.position.liquidation_price
                    exit_reason  = "liquidation"
                    closed       = True
                    liquidations += 1

                if not closed and strategy.is_long:
                    sl = strategy.stop_loss
                    tp = strategy.take_profit
                    if sl is not None:
                        _, sl_price = sl
                        if low_t <= sl_price:
                            exit_reason = "stop_loss"
                            closed      = True
                            # F-011: if the candle gapped THROUGH the stop, the
                            # stop never traded — fill at the candle OPEN
                            # (worst case) instead of the optimistic stop price.
                            gap_price = gap_through_stop_price(
                                is_long=True,
                                stop_price=sl_price,
                                candle_open=open_t,
                                candle_low=low_t,
                                candle_high=high_t,
                            )
                            exit_price = gap_price if gap_price is not None else sl_price
                    if not closed and tp is not None:
                        _, tp_price = tp
                        if high_t >= tp_price:
                            exit_price  = tp_price
                            exit_reason = "take_profit"
                            closed      = True

                elif not closed and strategy.is_short:
                    sl = strategy.stop_loss
                    tp = strategy.take_profit
                    if sl is not None:
                        _, sl_price = sl
                        if high_t >= sl_price:
                            exit_reason = "stop_loss"
                            closed      = True
                            # F-011: see long branch
                            gap_price = gap_through_stop_price(
                                is_long=False,
                                stop_price=sl_price,
                                candle_open=open_t,
                                candle_low=low_t,
                                candle_high=high_t,
                            )
                            exit_price = gap_price if gap_price is not None else sl_price
                    if not closed and tp is not None:
                        _, tp_price = tp
                        if low_t <= tp_price:
                            exit_price  = tp_price
                            exit_reason = "take_profit"
                            closed      = True

                if closed:
                    exit_qty = strategy.position.qty
                    locked_margin = strategy.position.margin
                    if exit_reason == "liquidation":
                        # Isolated margin: the entire isolated wallet is
                        # forfeited — loss is capped at the margin locked for
                        # this position. No extra slippage or exit fee is
                        # modeled; Binance's liquidation clearance fee comes
                        # out of the forfeited margin.
                        exit_fill = exit_price
                        strategy.position.close(exit_fill)
                        realized_pnl  = -strategy.position.margin
                        trade_pnl_pct = -100.0
                    else:
                        # F-012: bound the exit fill to the candle's realised
                        # trading range before applying slippage. The proposed
                        # exit_price (stop / TP / F-011 gap-open) is clamped
                        # to [low, high] and slippage is then added
                        # adversarially by execution.exit_fill (cost model).
                        # This mirrors freqtrade's ``_get_order_filled``
                        # semantics and replaces the prior "fill at exact
                        # exit_price" which was symbol/size-agnostic.
                        bounded_exit = bounded_exit_price(
                            is_long=was_long,
                            proposed_price=exit_price,
                            candle_open=open_t,
                            candle_low=low_t,
                            candle_high=high_t,
                        )
                        _fill = execution.exit_fill(strategy, bounded_exit, exit_qty, "sell" if was_long else "buy")
                        exit_fill = _fill.fill_price
                        fee = _fill.fee
                        total_fees += fee
                        strategy.position.close(exit_fill)
                        realized_pnl  = strategy.position.pnl - fee
                        trade_pnl_pct = strategy.position.pnl_pct
                    strategy.balance += realized_pnl
                    strategy.available_capital += locked_margin + realized_pnl
                    strategy.available_margin = strategy.balance
                    last_funding_dt = None

                    if active_trade:
                        active_trade["id"] = f"t_{len(trades) + 1}"
                        active_trade = _finalize_trade(
                            active_trade,
                            t,
                            exit_fill,
                            time_t,
                            exit_reason,
                            realized_pnl,
                            trade_pnl_pct,
                            high_t,
                            low_t,
                        )
                        trades.append(active_trade)
                        active_trade = None

                    try:
                        strategy.on_close_position((exit_qty, exit_fill))
                    except Exception as e:
                        logger.error(f"on_close_position error: {e}")

                    strategy.position      = None
                    strategy.stop_loss     = None
                    strategy.take_profit   = None
                    strategy._pending_flip = None  # a flip cannot survive its position

            # ── B. Update strategy candle window + equity tracking ───────────
            strategy.candles = candles_np[:t + 1]
            strategy.index   = t

            # Track session peak equity and drawdown for the can_trade() gate.
            # Owned by the Risk Model (Phase 1) so backtest and live share one
            # drawdown-tracking implementation; math is identical to the former
            # inline block (no behavior change).
            strategy.risk_model.update_session_risk(strategy)

            # ── C. Strategy decision hooks ───────────────────────────────
            try:
                strategy.before()            # C1: cache indicators
                current_holding = (          # C2: compute signed holding
                    strategy.position.qty * (1 if strategy.is_long else -1)
                ) if strategy.position else 0.0
                evaluate(strategy, current_holding)  # C3-C7: full five-model pipeline
                strategy.after()             # C8: post-candle cleanup

                # Round stop_loss and take_profit prices to tickSize direction-awarely (F-006 / F-007)
                direction_name = None
                if strategy.position is not None:
                    direction_name = strategy.position.type
                elif strategy.buy is not None:
                    direction_name = "long"
                elif strategy.sell is not None:
                    direction_name = "short"

                if direction_name is not None:
                    rounding_mode = ROUND_DOWN if direction_name == "long" else ROUND_UP
                    exchange_name = strategy.exchange or "Binance Futures"
                    if strategy.stop_loss is not None:
                        sl_qty, sl_price = strategy.stop_loss
                        strategy.stop_loss = (sl_qty, round_price(symbol, exchange_name, sl_price, rounding=rounding_mode))
                    if strategy.take_profit is not None:
                        tp_qty, tp_price = strategy.take_profit
                        strategy.take_profit = (tp_qty, round_price(symbol, exchange_name, tp_price, rounding=rounding_mode))
            except Exception as e:
                raise RuntimeError(f"STRATEGY_ERROR: Python strategy error at step {t}: {e}")

            # ── D. Record equity snapshot (raw lists — no dict allocation) ──
            unrealized = strategy.position.pnl if strategy.position is not None else 0.0
            equity_timestamps.append(time_t.isoformat())
            equity_balances.append(strategy.balance + unrealized)

    finally:
        cancel_task.cancel()
        try:
            await cancel_task
        except asyncio.CancelledError:
            pass

    # ── 9. Termination hooks + force-close open position ────────────────────
    # BUG-04 fix: before_terminate() and terminate() were never called.
    try:
        strategy.before_terminate()
    except Exception as e:
        logger.error(f"[{job_id}] before_terminate error: {e}")

    if strategy.position is not None:
        last_close = candles_np[-1, 2]
        was_long   = strategy.is_long
        _fill = execution.exit_fill(strategy, last_close, strategy.position.qty, "sell" if was_long else "buy")
        exit_fill  = _fill.fill_price
        fee = _fill.fee
        locked_margin = strategy.position.margin
        total_fees += fee
        strategy.position.close(exit_fill)
        realized_pnl      = strategy.position.pnl - fee
        strategy.balance += realized_pnl
        strategy.available_capital += locked_margin + realized_pnl
        strategy.available_margin = strategy.balance

        if active_trade:
            active_trade["id"] = f"t_{len(trades) + 1}"
            active_trade = _finalize_trade(
                active_trade,
                total_candles - 1,
                exit_fill,
                rows[-1]["time"],
                "force_close",
                realized_pnl,
                strategy.position.pnl_pct,
                candles_np[-1, 3],
                candles_np[-1, 4],
            )
            trades.append(active_trade)

    # Phase 2 (A-012): after the force-close, the final equity snapshot is
    # missing from equity_balances (it was appended inside the loop BEFORE the
    # close). Append the post-close balance so registry stats (NetProfitStat,
    # CAGRStat, etc.) see the realised final equity, not a stale in-loop
    # value. Legacy metric fields are unchanged — they read strategy.balance
    # directly.
    equity_balances.append(strategy.balance)
    equity_timestamps.append(rows[-1]["time"].isoformat())

    try:
        strategy.terminate()
    except Exception as e:
        logger.error(f"[{job_id}] terminate error: {e}")

    # ── 10. Calculate metrics using NumPy (no Python loops) ─────────────────
    logger.info(f"[{job_id}] Simulation complete. Calculating metrics...")

    balances_arr = np.array(equity_balances, dtype=np.float64)

    total_trades   = len(trades)
    pnl_values     = np.array([float(tr["pnl"]) for tr in trades], dtype=np.float64) if trades else np.array([])
    winning_trades = int(np.sum(pnl_values > 0)) if pnl_values.size else 0
    losing_trades  = total_trades - winning_trades
    win_rate       = winning_trades / total_trades if total_trades > 0 else 0.0

    net_profit     = strategy.balance - capital
    net_profit_pct = (net_profit / capital) * 100.0

    # Max drawdown — vectorised peak calculation
    running_max = np.maximum.accumulate(balances_arr)
    drawdown_arr = np.where(running_max > 0, (balances_arr - running_max) / running_max, 0.0)
    max_dd_pct   = float(np.min(drawdown_arr)) * 100.0

    # Sharpe / Sortino — vectorised returns
    sharpe = sortino = 0.0
    if balances_arr.size > 1:
        prev   = balances_arr[:-1]
        curr   = balances_arr[1:]
        # avoid division by zero on zero-balance rows
        mask   = prev > 0
        rets   = np.where(mask, (curr - prev) / prev, 0.0)
        std_r  = np.std(rets)
        if std_r > 0:
            annual  = annual_factor(timeframe)
            mean_r  = np.mean(rets)
            sharpe  = float((mean_r / std_r) * np.sqrt(annual))
            neg     = rets[rets < 0]
            down_std = np.std(neg) if neg.size > 0 else 0.0
            sortino = float((mean_r / down_std) * np.sqrt(annual)) if down_std > 0 else sharpe

    calmar = net_profit_pct / abs(max_dd_pct) if max_dd_pct != 0 else 0.0

    win_pnl  = pnl_values[pnl_values > 0]  if pnl_values.size else np.array([])
    loss_pnl = pnl_values[pnl_values <= 0] if pnl_values.size else np.array([])
    avg_win      = float(np.mean(win_pnl))  if win_pnl.size  else 0.0
    avg_loss     = float(np.mean(loss_pnl)) if loss_pnl.size else 0.0
    largest_win  = float(np.max(win_pnl))   if win_pnl.size  else 0.0
    largest_loss = float(np.min(loss_pnl))  if loss_pnl.size else 0.0

    # Advanced aggregate metrics
    gross_profit = float(np.sum(win_pnl)) if win_pnl.size else 0.0
    gross_loss = float(np.sum(loss_pnl)) if loss_pnl.size else 0.0
    profit_factor = gross_profit / abs(gross_loss) if gross_loss != 0.0 else 0.0
    expectancy = float(np.mean(pnl_values)) if pnl_values.size else 0.0
    payoff_ratio = avg_win / abs(avg_loss) if avg_loss != 0.0 else 0.0

    running_min = np.minimum.accumulate(balances_arr)
    runup_arr = np.where(running_min > 0, (balances_arr - running_min) / running_min, 0.0)
    max_runup_pct = float(np.max(runup_arr)) * 100.0 if runup_arr.size else 0.0

    buy_hold_pct = 0.0
    if candles_np.shape[0] > warmup_period:
        first_close = candles_np[warmup_period, 2]
        last_close = candles_np[-1, 2]
        buy_hold_pct = ((last_close - first_close) / first_close) * 100.0 if first_close > 0 else 0.0

    max_wins = cur_wins = 0
    max_losses = cur_losses = 0
    for p in pnl_values:
        if p > 0:
            cur_wins += 1
            cur_losses = 0
            max_wins = max(max_wins, cur_wins)
        else:
            cur_losses += 1
            cur_wins = 0
            max_losses = max(max_losses, cur_losses)

    # Average holding period in seconds
    avg_holding = 0.0
    if trades:
        durations = [
            (tr["_exit_dt"] - tr["_entry_dt"]).total_seconds()
            for tr in trades
            if "_exit_dt" in tr and "_entry_dt" in tr
        ]
        avg_holding = float(np.mean(durations)) if durations else 0.0

    long_trades = [t for t in trades if t["type"] == "long"]
    short_trades = [t for t in trades if t["type"] == "short"]

    metrics = {
        "totalTrades":          total_trades,
        "winRate":              f"{win_rate:.2f}",
        "netProfit":            f"{net_profit:.2f}",
        "netProfitPct":         f"{net_profit_pct:.2f}",
        "maxDrawdown":          f"{max_dd_pct:.2f}",
        "sharpeRatio":          f"{sharpe:.2f}",
        "sortinoRatio":         f"{sortino:.2f}",
        "calmarRatio":          f"{calmar:.2f}",
        "startingBalance":      f"{capital:.2f}",
        "finishingBalance":     f"{strategy.balance:.2f}",
        "totalFees":            f"{total_fees:.2f}",
        "totalFunding":         f"{total_funding:.2f}",
        "liquidations":         liquidations,
        "leverage":             leverage,
        "winningTrades":        winning_trades,
        "losingTrades":         losing_trades,
        "averageWin":           f"{avg_win:.2f}",
        "averageLoss":          f"{avg_loss:.2f}",
        "largestWin":           f"{largest_win:.2f}",
        "largestLoss":          f"{largest_loss:.2f}",
        "averageHoldingPeriod": f"{int(avg_holding)}",
        "grossProfit":          f"{gross_profit:.2f}",
        "grossLoss":            f"{gross_loss:.2f}",
        "profitFactor":         f"{profit_factor:.2f}",
        "expectancy":           f"{expectancy:.2f}",
        "payoffRatio":          f"{payoff_ratio:.2f}",
        "maxRunup":             f"{max_runup_pct:.2f}",
        "buyHoldReturnPct":     f"{buy_hold_pct:.2f}",
        "maxConsecutiveWins":   max_wins,
        "maxConsecutiveLosses": max_losses,
        "bySide": {
            "all":   _compute_side_metrics(trades, capital),
            "long":  _compute_side_metrics(long_trades, capital),
            "short": _compute_side_metrics(short_trades, capital),
        }
    }

    # ── 10b. Phase 2 — registry-driven metric additions (A-007 / A-008 / A-012) ─
    # The legacy block above is byte-identical to its pre-Phase-2 form. New
    # metrics (CAGR, SQN, expectancy ratio, drawdown duration, per-exit-reason
    # breakdown) come from the pluggable registry, so adding more is a
    # one-class edit. Existing metric KEYS are unchanged so the UI / golden
    # master keep matching for legacy fields; new keys are additive.
    _annual = annual_factor(timeframe)
    _metric_ctx = MetricContext(
        trades=trades,
        balances=balances_arr,
        equity_timestamps=equity_timestamps,
        candles_np=candles_np,
        capital=capital,
        timeframe=timeframe,
        annual_factor=_annual,
        warmup_period=warmup_period,
        total_fees=total_fees,
        total_funding=total_funding,
        liquidations=liquidations,
        leverage=leverage,
    )
    _registry = default_registry()
    _registry_metrics = _registry.compute_all(_metric_ctx)
    # Merge — registry wins for keys it provides (so byExitReason, cagr, sqn,
    # expectancyRatio, maxDrawdownDurationCandles are sourced from the registry).
    for k, v in _registry_metrics.items():
        metrics.setdefault(k, v)

    # ── 11. Downsample equity curve ─────────────────────────────────────────
    raw_n = len(equity_timestamps)
    if raw_n <= EQUITY_CURVE_MAX_POINTS:
        sampled_ts  = equity_timestamps
        sampled_bal = equity_balances
    else:
        indices     = np.round(np.linspace(0, raw_n - 1, EQUITY_CURVE_MAX_POINTS)).astype(int)
        sampled_ts  = [equity_timestamps[i] for i in indices]
        sampled_bal = [equity_balances[i]   for i in indices]

    equity_curve_docs = [
        {"timestamp": ts, "balance": f"{bal:.2f}"}
        for ts, bal in zip(sampled_ts, sampled_bal)
    ]

    # ── 11b. Phase 2 — extra curves (A-009 / A-010 / A-011) ─────────────────
    underwater_docs = underwater_curve_with_timestamps(
        equity_timestamps, balances_arr, max_points=EQUITY_CURVE_MAX_POINTS,
    )
    rolling_docs = rolling_curve(
        balances_arr,
        timeframe_seconds=timeframe_to_seconds(timeframe),
        annual_factor=_annual,
        window_candles=50,
        max_points=EQUITY_CURVE_MAX_POINTS,
    )
    returns_hist = returns_histogram(trades, capital)
    mfe_mae_pts  = mfe_mae_scatter(trades, capital)

    # ── 12. Write main result document to MongoDB (no trades / no raw curve) ─
    db = get_database()

    strategy_doc = await db.strategies.find_one({"name": strategy_name})
    strategy_id  = str(strategy_doc["_id"]) if strategy_doc else None

    actual_start = rows[0]["time"].isoformat()
    actual_end   = rows[-1]["time"].isoformat()

    await db.backtestResults.update_one(
        {"jobId": job_id},
        {
            "$set": {
                "jobId":        job_id,
                "strategyId":   strategy_id,
                "strategyName": strategy_name,
                "exchange":     exchange,
                "symbol":       symbol,
                "timeframe":    timeframe,
                "startDate":    actual_start,
                "endDate":      actual_end,
                "capital":      capital,
                "leverage":     leverage,
                "feeRate":      fee_rate,
                "status":       "completed",
                "metrics":      metrics,
                "equityCurve":  equity_curve_docs,   # ≤1 000 points
                # Phase 2 — extra curves (A-009 / A-010 / A-011)
                "underwaterCurve":       underwater_docs,
                "rollingMetricsCurve":   rolling_docs,
                "returnsHistogram":      returns_hist,
                "mfeMaeScatter":         mfe_mae_pts,
                "tradeCount":   total_trades,
                "updatedAt":    datetime.now(timezone.utc),
            },
            "$setOnInsert": {"createdAt": datetime.now(timezone.utc)},
        },
        upsert=True,
    )

    # ── 13. Bulk-insert trades into separate backtestTrades collection ───────
    if trades:
        trade_docs = [
            {
                "jobId":       job_id,
                "tradeIndex":  i + 1,
                "type":        tr["type"],
                "qty":         tr["qty"],
                "entryPrice":  tr["entryPrice"],
                "exitPrice":   tr.get("exitPrice", ""),
                "entryAt":     tr["entryAt"],
                "exitAt":      tr.get("exitAt", ""),
                "exitReason":  tr.get("exitReason", ""),
                "pnl":         tr["pnl"],
                "pnlPct":      tr.get("pnlPct", "0.00"),
                "leverage":    tr.get("leverage", 1),
                "liqPrice":    tr.get("liqPrice", ""),
                "runUpPct":    tr.get("runUpPct", "0.00"),
                "drawdownPct": tr.get("drawdownPct", "0.00"),
                "barsHeld":    tr.get("barsHeld", 0),
                # _entry_dt / _exit_dt are internal datetime objects — never persisted
            }
            for i, tr in enumerate(trades)
        ]
        # Batch inserts to stay well under the 16 MB BSON limit per command
        for start in range(0, len(trade_docs), TRADE_INSERT_BATCH):
            batch = trade_docs[start : start + TRADE_INSERT_BATCH]
            await db.backtestTrades.insert_many(batch, ordered=False)

    logger.info(
        f"[{job_id}] Persisted {total_trades} trades and "
        f"{len(equity_curve_docs)} equity-curve points to MongoDB."
    )

    # ── 14. Cleanup ─────────────────────────────────────────────────────────
    await r_client.aclose()

    return {
        "jobId":      job_id,
        "status":     "completed",
        "metrics":    metrics,
        "tradeCount": total_trades,
    }
