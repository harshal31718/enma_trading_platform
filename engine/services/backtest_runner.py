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

logger = logging.getLogger(__name__)


def _get_annual_factor(timeframe: str) -> int:
    """Returns the number of candles in a year for the given timeframe to annualize Sharpe/Sortino."""
    try:
        val = int(timeframe[:-1])
        unit = timeframe[-1]
    except Exception:
        return 8760  # Default to hourly

    minutes_per_year = 525600
    if unit == "m":
        return minutes_per_year // val
    elif unit == "h":
        return (minutes_per_year // 60) // val
    elif unit == "d":
        return 365 // val
    elif unit == "w":
        return 52 // val
    return 8760


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
    # 1. Parse strategy name from file path (e.g. strategies/SimpleEMACross/__init__.py -> SimpleEMACross)
    # filePath format is: strategies/Name/__init__.py or similar
    parts = strategy_file.split("/")
    if len(parts) >= 2 and parts[0] == "strategies":
        strategy_name = parts[1]
    else:
        # Fallback
        strategy_name = strategy_file.replace("strategies/", "").split("/")[0]

    logger.info(f"[{job_id}] Initializing backtest for strategy: {strategy_name}")

    # 2. Dynamic import
    try:
        module = importlib.import_module(f"strategies.{strategy_name}")
        strategy_class = getattr(module, strategy_name)
    except Exception as e:
        logger.error(f"Failed to load strategy {strategy_name}: {e}")
        raise RuntimeError(f"STRATEGY_ERROR: Failed to load strategy {strategy_name}: {e}")

    # 3. Load candles from TimescaleDB
    start_dt = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
    end_dt = datetime.fromisoformat(end_date).replace(tzinfo=timezone.utc)

    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT time, open, close, high, low, volume
            FROM candles
            WHERE exchange = $1 AND symbol = $2 AND timeframe = $3 AND time >= $4 AND time < $5
            ORDER BY time ASC
            """,
            exchange,
            symbol,
            timeframe,
            start_dt,
            end_dt,
        )

    if len(rows) < 50:
        raise ValueError(
            f"INSUFFICIENT_CANDLES: Only {len(rows)} candles found. Minimum 50 candles required for backtesting warm-up."
        )

    # 4. Prepare candle numpy array
    # Shape: [[timestamp, open, close, high, low, volume], ...]
    candles_np = np.zeros((len(rows), 6))
    for idx, r in enumerate(rows):
        candles_np[idx] = [
            int(r["time"].timestamp() * 1000),
            float(r["open"]),
            float(r["close"]),
            float(r["high"]),
            float(r["low"]),
            float(r["volume"]),
        ]

    # 5. Initialize strategy and environment
    strategy = strategy_class()
    strategy.exchange = exchange
    strategy.symbol = symbol
    strategy.timeframe = timeframe
    strategy.balance = capital
    strategy.available_margin = capital
    strategy.leverage = leverage
    strategy.fee_rate = fee_rate
    strategy.exchange_type = "futures" if "Futures" in exchange else "spot"
    strategy.is_backtesting = True

    # Simulation variables
    warmup_period = min(50, len(rows) - 2)
    equity_curve = []
    trades = []
    
    # Track the currently open trade
    active_trade = None
    total_fees = 0.0

    # Redis connection for progress & cancel check
    redis_url = os.getenv("REDIS_URL", "redis://redis:6379")
    r_client = aioredis.from_url(redis_url)

    logger.info(f"[{job_id}] Running simulation loop on {len(rows)} candles...")

    for t in range(warmup_period, len(rows)):
        # Periodically check for cancellation (every 100 steps)
        if t % 100 == 0:
            cancel_flag = await r_client.get(f"backtest:cancel:{job_id}")
            if cancel_flag:
                logger.info(f"[{job_id}] Backtest job cancelled by user request.")
                await r_client.aclose()
                raise RuntimeError("JOB_CANCELLED")

            # Publish progress
            pct = int((t / len(rows)) * 100)
            progress_payload = json.dumps({
                "pct": pct,
                "message": f"Simulating {r_client}... {pct}% done",
            })
            await r_client.publish(f"progress:{job_id}", progress_payload)

        # Current candle details
        time_t = rows[t]["time"]
        open_t = candles_np[t, 1]
        close_t = candles_np[t, 2]
        high_t = candles_np[t, 3]
        low_t = candles_np[t, 4]

        # A. Execute Pending Orders from previous step on this candle's range
        if strategy.position is None:
            # Check Buy (Long Entry)
            if strategy.buy is not None:
                buy_qty, buy_price = strategy.buy
                # Limit order execution: low <= buy_price <= high
                if low_t <= buy_price <= high_t:
                    # Fee
                    fee = buy_qty * buy_price * fee_rate
                    total_fees += fee
                    strategy.balance -= fee
                    
                    pos = Position("long", buy_qty, buy_price)
                    strategy.position = pos
                    
                    # Track trade record
                    active_trade = {
                        "type": "long",
                        "qty": str(buy_qty),
                        "entryPrice": str(buy_price),
                        "entryAt": time_t.isoformat(),
                    }
                    
                    # Event hook
                    try:
                        strategy.on_open_position(strategy.buy)
                    except Exception as e:
                        logger.error(f"Strategy on_open_position error: {e}")
                    
                    strategy.buy = None

            # Check Sell (Short Entry)
            elif strategy.sell is not None:
                sell_qty, sell_price = strategy.sell
                if low_t <= sell_price <= high_t:
                    # Fee
                    fee = sell_qty * sell_price * fee_rate
                    total_fees += fee
                    strategy.balance -= fee
                    
                    pos = Position("short", sell_qty, sell_price)
                    strategy.position = pos
                    
                    # Track trade record
                    active_trade = {
                        "type": "short",
                        "qty": str(sell_qty),
                        "entryPrice": str(sell_price),
                        "entryAt": time_t.isoformat(),
                    }
                    
                    try:
                        strategy.on_open_position(strategy.sell)
                    except Exception as e:
                        logger.error(f"Strategy on_open_position error: {e}")
                        
                    strategy.sell = None

        else:
            # Position is open. Update unrealized P&L
            strategy.position.update_pnl(close_t)
            
            # Check Stop Loss & Take Profit Exits
            closed = False
            exit_price = 0.0
            exit_reason = ""

            # Standard exit rules
            if strategy.is_long:
                sl = strategy.stop_loss
                tp = strategy.take_profit
                
                # Check Stop Loss first (conservative)
                if sl is not None:
                    sl_qty, sl_price = sl
                    if low_t <= sl_price:
                        # Exited by SL
                        exit_price = sl_price
                        exit_reason = "stop_loss"
                        closed = True
                
                # Check Take Profit
                if not closed and tp is not None:
                    tp_qty, tp_price = tp
                    if high_t >= tp_price:
                        # Exited by TP
                        exit_price = tp_price
                        exit_reason = "take_profit"
                        closed = True
            
            elif strategy.is_short:
                sl = strategy.stop_loss
                tp = strategy.take_profit
                
                if sl is not None:
                    sl_qty, sl_price = sl
                    if high_t >= sl_price:
                        exit_price = sl_price
                        exit_reason = "stop_loss"
                        closed = True
                
                if not closed and tp is not None:
                    tp_qty, tp_price = tp
                    if low_t <= tp_price:
                        exit_price = tp_price
                        exit_reason = "take_profit"
                        closed = True

            if closed:
                # Deduct exit fee
                fee = strategy.position.qty * exit_price * fee_rate
                total_fees += fee
                
                # Close position
                strategy.position.close(exit_price)
                realized_pnl = strategy.position.pnl - fee
                strategy.balance += realized_pnl
                
                # Record trade
                if active_trade:
                    active_trade.update({
                        "id": f"t_{len(trades) + 1}",
                        "exitPrice": str(exit_price),
                        "exitAt": time_t.isoformat(),
                        "exitReason": exit_reason,
                        "pnl": f"{realized_pnl:.2f}",
                        "pnlPct": f"{strategy.position.pnl_pct:.2f}",
                    })
                    trades.append(active_trade)
                    active_trade = None
                
                try:
                    strategy.on_close_position((strategy.position.qty, exit_price))
                except Exception as e:
                    logger.error(f"Strategy on_close_position error: {e}")
                    
                strategy.position = None
                strategy.stop_loss = None
                strategy.take_profit = None

        # B. Set up candles state & update position state pointers
        strategy.candles = candles_np[:t+1]
        strategy.index = t

        # C. Call strategy decision hooks for the next step
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
            logger.error(f"Error executing strategy lifecycle hooks at step {t}: {e}")
            await r_client.aclose()
            raise RuntimeError(f"STRATEGY_ERROR: Python strategy error at step {t}: {e}")

        # D. Record equity curve snapshot
        unrealized_pnl = strategy.position.pnl if strategy.position is not None else 0.0
        current_equity = strategy.balance + unrealized_pnl
        equity_curve.append({
            "timestamp": time_t.isoformat(),
            "balance": f"{current_equity:.2f}"
        })

    # Close any remaining active trade at the end of the simulation
    if strategy.position is not None:
        last_candle_close = candles_np[-1, 2]
        fee = strategy.position.qty * last_candle_close * fee_rate
        total_fees += fee
        strategy.position.close(last_candle_close)
        realized_pnl = strategy.position.pnl - fee
        strategy.balance += realized_pnl
        
        if active_trade:
            active_trade.update({
                "id": f"t_{len(trades) + 1}",
                "exitPrice": str(last_candle_close),
                "exitAt": rows[-1]["time"].isoformat(),
                "exitReason": "force_close",
                "pnl": f"{realized_pnl:.2f}",
                "pnlPct": f"{strategy.position.pnl_pct:.2f}",
            })
            trades.append(active_trade)

    # 6. Calculate Final Statistics / Metrics
    logger.info(f"[{job_id}] Simulation complete. Calculating metrics...")
    total_trades = len(trades)
    winning_trades = sum(1 for tr in trades if float(tr["pnl"]) > 0)
    losing_trades = total_trades - winning_trades
    win_rate = winning_trades / total_trades if total_trades > 0 else 0.0

    net_profit = strategy.balance - capital
    net_profit_pct = (net_profit / capital) * 100.0

    # Max Drawdown
    peak = -1e9
    max_dd = 0.0
    for snapshot in equity_curve:
        bal = float(snapshot["balance"])
        if bal > peak:
            peak = bal
        dd = (bal - peak) / peak if peak > 0 else 0.0
        if dd < max_dd:
            max_dd = dd
    max_dd_pct = max_dd * 100.0

    # Sharpe and Sortino computation from equity returns
    returns = []
    for i in range(1, len(equity_curve)):
        prev = float(equity_curve[i-1]["balance"])
        curr = float(equity_curve[i]["balance"])
        ret = (curr - prev) / prev if prev > 0 else 0.0
        returns.append(ret)

    sharpe = 0.0
    sortino = 0.0
    if len(returns) > 0 and np.std(returns) > 0:
        annual_factor = _get_annual_factor(timeframe)
        mean_ret = np.mean(returns)
        std_ret = np.std(returns)
        sharpe = (mean_ret / std_ret) * np.sqrt(annual_factor)

        downside_returns = [r for r in returns if r < 0]
        if len(downside_returns) > 0 and np.std(downside_returns) > 0:
            downside_std = np.std(downside_returns)
            sortino = (mean_ret / downside_std) * np.sqrt(annual_factor)
        else:
            sortino = sharpe

    # Calmar
    calmar = net_profit_pct / abs(max_dd_pct) if max_dd_pct != 0 else 0.0

    # Winning / losing statistics
    win_pnl = [float(tr["pnl"]) for tr in trades if float(tr["pnl"]) > 0]
    loss_pnl = [float(tr["pnl"]) for tr in trades if float(tr["pnl"]) <= 0]
    
    avg_win = np.mean(win_pnl) if win_pnl else 0.0
    avg_loss = np.mean(loss_pnl) if loss_pnl else 0.0
    largest_win = max(win_pnl) if win_pnl else 0.0
    largest_loss = min(loss_pnl) if loss_pnl else 0.0

    # Average Holding Period in seconds
    durations = []
    for tr in trades:
        try:
            entry_dt = datetime.fromisoformat(tr["entryAt"])
            exit_dt = datetime.fromisoformat(tr["exitAt"])
            durations.append((exit_dt - entry_dt).total_seconds())
        except Exception:
            pass
    avg_holding = np.mean(durations) if durations else 0.0

    metrics = {
        "totalTrades": total_trades,
        "winRate": f"{win_rate:.2f}",
        "netProfit": f"{net_profit:.2f}",
        "netProfitPct": f"{net_profit_pct:.2f}",
        "maxDrawdown": f"{max_dd_pct:.2f}",
        "sharpeRatio": f"{sharpe:.2f}",
        "sortinoRatio": f"{sortino:.2f}",
        "calmarRatio": f"{calmar:.2f}",
        "startingBalance": f"{capital:.2f}",
        "finishingBalance": f"{strategy.balance:.2f}",
        "totalFees": f"{total_fees:.2f}",
        "winningTrades": winning_trades,
        "losingTrades": losing_trades,
        "averageWin": f"{avg_win:.2f}",
        "averageLoss": f"{avg_loss:.2f}",
        "largestWin": f"{largest_win:.2f}",
        "largestLoss": f"{largest_loss:.2f}",
        "averageHoldingPeriod": f"{int(avg_holding)}",
    }

    # 7. Write Backtest Results directly to MongoDB
    db = get_database()
    
    # Find strategyId for reference
    strategy_doc = await db.strategies.find_one({"name": strategy_name})
    strategy_id = str(strategy_doc["_id"]) if strategy_doc else None

    result_doc = {
        "jobId": job_id,
        "strategyId": strategy_id,
        "strategyName": strategy_name,
        "exchange": exchange,
        "symbol": symbol,
        "timeframe": timeframe,
        "startDate": start_date,
        "endDate": end_date,
        "capital": capital,
        "leverage": leverage,
        "feeRate": fee_rate,
        "status": "completed",
        "metrics": metrics,
        "trades": trades,
        "equityCurve": equity_curve,
        "createdAt": datetime.utcnow(),
    }
    
    await db.backtestResults.insert_one(result_doc)
    logger.info(f"[{job_id}] Backtest results persisted to MongoDB.")

    # Cleanup cancellation key
    await r_client.delete(f"backtest:cancel:{job_id}")
    await r_client.aclose()

    return {
        "id": job_id,
        "status": "completed",
        "metrics": metrics,
    }
