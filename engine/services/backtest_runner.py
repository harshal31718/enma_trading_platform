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
from core.margin import initial_margin
from services.candle_manager import ensure_candles_available
from utils.timeframes import annual_factor

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

    warmup_period = min(50, len(rows) - 2)
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

    # Resolve per-run simulation parameters.  Module-level constants remain as
    # fallbacks for any caller that doesn't pass these arguments.
    taker_fee   = fee_rate
    _slippage   = slippage_pct   if slippage_pct   is not None else SLIPPAGE_PCT
    _fund_rate  = funding_rate   if funding_rate   is not None else FUNDING_RATE
    _funding_on = funding_enabled
    leverage    = max(int(leverage), 1)

    # ── 7. Redis connection ─────────────────────────────────────────────────
    redis_url = os.getenv("REDIS_URL", "redis://redis:6379")
    r_client = aioredis.from_url(redis_url)

    # ── 8. Async cancel-listener task ───────────────────────────────────────
    # Subscribes to backtest:cancel:{job_id} channel on a separate connection so
    # the hot-loop never makes a network round-trip.  It just flips a flag.
    is_cancelled = False

    async def _watch_cancel():
        nonlocal is_cancelled
        cancel_sub = aioredis.from_url(redis_url)
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
                exit_fill = open_t * (1.0 - _slippage) if was_long else open_t * (1.0 + _slippage)
                exit_qty  = strategy.position.qty
                fee = exit_qty * exit_fill * taker_fee
                total_fees += fee
                strategy.position.close(exit_fill)
                realized_pnl      = strategy.position.pnl - fee
                strategy.balance += realized_pnl
                strategy.available_margin = strategy.balance
                last_funding_dt = None

                if active_trade:
                    active_trade.update({
                        "id":         f"t_{len(trades) + 1}",
                        "exitPrice":  str(exit_fill),
                        "exitAt":     time_t.isoformat(),
                        "_exit_dt":   time_t,
                        "exitReason": "flip",
                        "pnl":        f"{realized_pnl:.2f}",
                        "pnlPct":     f"{strategy.position.pnl_pct:.2f}",
                    })
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
                fill_price = open_t * (1.0 + _slippage) if new_dir == "long" else open_t * (1.0 - _slippage)
                notional   = new_qty * fill_price
                req_margin = initial_margin(notional, leverage)
                fee        = notional * taker_fee
                if new_qty <= 0 or req_margin + fee > strategy.balance:
                    logger.warning(
                        f"[{job_id}] Flip degraded to close-only: qty {new_qty} margin "
                        f"${req_margin:.2f} + fee ${fee:.2f} vs balance ${strategy.balance:.2f}"
                    )
                else:
                    total_fees       += fee
                    strategy.balance -= fee
                    strategy.position = Position(
                        new_dir, new_qty, fill_price, leverage,
                        isolated_wallet=req_margin,
                    )
                    strategy.available_margin = strategy.balance - req_margin
                    last_funding_dt = time_t
                    # SL/TP supplied with the flip are armed before exit checks
                    strategy.stop_loss   = (new_qty, flip["stop_loss"])   if flip["stop_loss"]   is not None else None
                    strategy.take_profit = (new_qty, flip["take_profit"]) if flip["take_profit"] is not None else None
                    active_trade = {
                        "type":       new_dir,
                        "qty":        str(new_qty),
                        "entryPrice": str(fill_price),
                        "entryAt":    time_t.isoformat(),
                        "_entry_dt":  time_t,
                        "leverage":   leverage,
                        "liqPrice":   f"{strategy.position.liquidation_price:.4f}",
                    }
                    try:
                        strategy.on_open_position((new_qty, fill_price))
                    except Exception as e:
                        logger.error(f"on_open_position error: {e}")

            # ── A. Execute pending orders ────────────────────────────────────
            if strategy.position is None:
                # Let strategy cancel a pending entry before it fills
                if strategy.buy is not None or strategy.sell is not None:
                    try:
                        if strategy.should_cancel_entry():
                            strategy.buy  = None
                            strategy.sell = None
                    except Exception as e:
                        logger.error(f"Strategy should_cancel_entry error: {e}")

                # Buy (long entry) — market order: fills at open of next candle
                if strategy.buy is not None:
                    buy_qty, _ = strategy.buy
                    fill_price = open_t * (1.0 + _slippage)  # adverse slippage
                    notional   = buy_qty * fill_price
                    req_margin = initial_margin(notional, leverage)
                    fee        = notional * taker_fee
                    if req_margin + fee > strategy.balance:
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
                        strategy.available_margin = strategy.balance - req_margin
                        last_funding_dt = time_t
                        active_trade = {
                            "type":       "long",
                            "qty":        str(buy_qty),
                            "entryPrice": str(fill_price),
                            "entryAt":    time_t.isoformat(),
                            "_entry_dt":  time_t,
                            "leverage":   leverage,
                            "liqPrice":   f"{strategy.position.liquidation_price:.4f}",
                        }
                        try:
                            strategy.on_open_position((buy_qty, fill_price))
                        except Exception as e:
                            logger.error(f"on_open_position error: {e}")
                        strategy.buy = None

                # Sell (short entry) — market order: fills at open of next candle
                elif strategy.sell is not None:
                    sell_qty, _ = strategy.sell
                    fill_price = open_t * (1.0 - _slippage)  # adverse slippage
                    notional   = sell_qty * fill_price
                    req_margin = initial_margin(notional, leverage)
                    fee        = notional * taker_fee
                    if req_margin + fee > strategy.balance:
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
                        strategy.available_margin = strategy.balance - req_margin
                        last_funding_dt = time_t
                        active_trade = {
                            "type":       "short",
                            "qty":        str(sell_qty),
                            "entryPrice": str(fill_price),
                            "entryAt":    time_t.isoformat(),
                            "_entry_dt":  time_t,
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
                            exit_price  = sl_price
                            exit_reason = "stop_loss"
                            closed      = True
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
                            exit_price  = sl_price
                            exit_reason = "stop_loss"
                            closed      = True
                    if not closed and tp is not None:
                        _, tp_price = tp
                        if low_t <= tp_price:
                            exit_price  = tp_price
                            exit_reason = "take_profit"
                            closed      = True

                if closed:
                    exit_qty = strategy.position.qty
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
                        # Adverse slippage on the market exit fill
                        exit_fill = exit_price * (1.0 - _slippage) if was_long else exit_price * (1.0 + _slippage)
                        fee = exit_qty * exit_fill * taker_fee
                        total_fees += fee
                        strategy.position.close(exit_fill)
                        realized_pnl  = strategy.position.pnl - fee
                        trade_pnl_pct = strategy.position.pnl_pct
                    strategy.balance += realized_pnl
                    strategy.available_margin = strategy.balance
                    last_funding_dt = None

                    if active_trade:
                        active_trade.update({
                            "id":         f"t_{len(trades) + 1}",
                            "exitPrice":  str(exit_fill),
                            "exitAt":     time_t.isoformat(),
                            "_exit_dt":   time_t,
                            "exitReason": exit_reason,
                            "pnl":        f"{realized_pnl:.2f}",
                            "pnlPct":     f"{trade_pnl_pct:.2f}",
                        })
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

            # ── B. Update strategy candle window ────────────────────────────
            strategy.candles = candles_np[:t + 1]
            strategy.index   = t

            # ── C. Strategy decision hooks ───────────────────────────────────
            try:
                strategy.before()
                if strategy.position is None:
                    if strategy.should_long():
                        strategy.go_long()
                    elif strategy.should_short():
                        strategy.go_short()
                else:
                    strategy.update_position()
                strategy.after()
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

    # ── 9. Force-close any open position at simulation end ──────────────────
    if strategy.position is not None:
        last_close = candles_np[-1, 2]
        was_long   = strategy.is_long
        exit_fill  = last_close * (1.0 - _slippage) if was_long else last_close * (1.0 + _slippage)
        fee = strategy.position.qty * exit_fill * taker_fee
        total_fees += fee
        strategy.position.close(exit_fill)
        realized_pnl      = strategy.position.pnl - fee
        strategy.balance += realized_pnl
        strategy.available_margin = strategy.balance

        if active_trade:
            active_trade.update({
                "id":         f"t_{len(trades) + 1}",
                "exitPrice":  str(exit_fill),
                "exitAt":     rows[-1]["time"].isoformat(),
                "_exit_dt":   rows[-1]["time"],
                "exitReason": "force_close",
                "pnl":        f"{realized_pnl:.2f}",
                "pnlPct":     f"{strategy.position.pnl_pct:.2f}",
            })
            trades.append(active_trade)

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

    # Average holding period in seconds
    avg_holding = 0.0
    if trades:
        durations = [
            (tr["_exit_dt"] - tr["_entry_dt"]).total_seconds()
            for tr in trades
            if "_exit_dt" in tr and "_entry_dt" in tr
        ]
        avg_holding = float(np.mean(durations)) if durations else 0.0

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
    }

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
