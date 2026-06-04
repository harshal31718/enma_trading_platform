import os
import importlib
import asyncio
import numpy as np
from datetime import datetime, timezone
import json
import logging
import redis.asyncio as aioredis

from config.timescale import get_pool
from config.mongo import get_database
from core.position import Position
from services.candle_manager import ensure_candles_available
from utils.timeframes import annual_factor

logger = logging.getLogger(__name__)

# Maximum equity-curve points stored in MongoDB.
# Downsampling keeps the document well under 1 MB even for 1-minute 3-year runs
# (~1.57 M candles → 1.57 M raw points → 1 000 stored points).
EQUITY_CURVE_MAX_POINTS = 1_000

# Batch size for bulk-inserting trades into backtestTrades collection
TRADE_INSERT_BATCH = 500



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
    candles_np = np.empty((len(rows), 6), dtype=np.float64)
    for idx, r in enumerate(rows):
        candles_np[idx, 0] = r["time"].timestamp() * 1000
        candles_np[idx, 1] = r["open"]
        candles_np[idx, 2] = r["close"]
        candles_np[idx, 3] = r["high"]
        candles_np[idx, 4] = r["low"]
        candles_np[idx, 5] = r["volume"]

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
            close_t = candles_np[t, 2]
            high_t  = candles_np[t, 3]
            low_t   = candles_np[t, 4]

            # ── A. Execute pending orders ────────────────────────────────────
            if strategy.position is None:
                # Let strategy cancel a pending entry
                if strategy.buy is not None or strategy.sell is not None:
                    try:
                        if strategy.should_cancel_entry():
                            strategy.buy  = None
                            strategy.sell = None
                    except Exception as e:
                        logger.error(f"Strategy should_cancel_entry error: {e}")

                # Buy (long entry)
                if strategy.buy is not None:
                    buy_qty, buy_price = strategy.buy
                    if low_t <= buy_price <= high_t:
                        fee = buy_qty * buy_price * fee_rate
                        total_fees      += fee
                        strategy.balance -= fee
                        strategy.position = Position("long", buy_qty, buy_price)
                        active_trade = {
                            "type":       "long",
                            "qty":        str(buy_qty),
                            "entryPrice": str(buy_price),
                            "entryAt":    time_t.isoformat(),
                            "_entry_dt":  time_t,
                        }
                        try:
                            strategy.on_open_position(strategy.buy)
                        except Exception as e:
                            logger.error(f"on_open_position error: {e}")
                        strategy.buy = None

                # Sell (short entry)
                elif strategy.sell is not None:
                    sell_qty, sell_price = strategy.sell
                    if low_t <= sell_price <= high_t:
                        fee = sell_qty * sell_price * fee_rate
                        total_fees      += fee
                        strategy.balance -= fee
                        strategy.position = Position("short", sell_qty, sell_price)
                        active_trade = {
                            "type":       "short",
                            "qty":        str(sell_qty),
                            "entryPrice": str(sell_price),
                            "entryAt":    time_t.isoformat(),
                            "_entry_dt":  time_t,
                        }
                        try:
                            strategy.on_open_position(strategy.sell)
                        except Exception as e:
                            logger.error(f"on_open_position error: {e}")
                        strategy.sell = None

            else:
                # ── Position open: update unrealized P&L ──────────────────
                strategy.position.update_pnl(close_t)

                closed      = False
                exit_price  = 0.0
                exit_reason = ""

                if strategy.is_long:
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

                elif strategy.is_short:
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
                    fee = strategy.position.qty * exit_price * fee_rate
                    total_fees += fee
                    strategy.position.close(exit_price)
                    realized_pnl     = strategy.position.pnl - fee
                    strategy.balance += realized_pnl

                    if active_trade:
                        active_trade.update({
                            "id":         f"t_{len(trades) + 1}",
                            "exitPrice":  str(exit_price),
                            "exitAt":     time_t.isoformat(),
                            "_exit_dt":   time_t,
                            "exitReason": exit_reason,
                            "pnl":        f"{realized_pnl:.2f}",
                            "pnlPct":     f"{strategy.position.pnl_pct:.2f}",
                        })
                        trades.append(active_trade)
                        active_trade = None

                    try:
                        strategy.on_close_position((strategy.position.qty, exit_price))
                    except Exception as e:
                        logger.error(f"on_close_position error: {e}")

                    strategy.position   = None
                    strategy.stop_loss  = None
                    strategy.take_profit = None

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
        fee = strategy.position.qty * last_close * fee_rate
        total_fees += fee
        strategy.position.close(last_close)
        realized_pnl     = strategy.position.pnl - fee
        strategy.balance += realized_pnl

        if active_trade:
            active_trade.update({
                "id":         f"t_{len(trades) + 1}",
                "exitPrice":  str(last_close),
                "exitAt":     rows[-1]["time"].isoformat(),
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
