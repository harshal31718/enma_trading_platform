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
from core.params import param_coerce, param_validate
from services.candle_manager import ensure_candles_available
from utils.timeframes import annual_factor, required_base_candles_for_htf
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
from services.fill_model import gap_through_stop_price, bounded_exit_price

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
        "exitTag": active_trade.get("exitTag", ""),
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

try:
    from engine.core.kernel import ExecutionAdapter, ExecutionKernel
    from engine.core.models import DefaultPortfolioModel, InverseVolatilityPortfolio, compute_realized_volatility
except ImportError:
    from core.kernel import ExecutionAdapter, ExecutionKernel
    from core.models import DefaultPortfolioModel, InverseVolatilityPortfolio, compute_realized_volatility


class BacktestAdapter(ExecutionAdapter):
    def __init__(self, execution_model, fee_rate: float, slippage_pct: float, funding_enabled: bool, funding_rate: float, symbol: str):
        self.execution = execution_model
        self.fee_rate = fee_rate
        self.slippage_pct = slippage_pct
        self.funding_enabled = funding_enabled
        self.funding_rate = funding_rate
        self.symbol = symbol

        self.trades = []
        self.active_trade = None
        self.total_fees = 0.0
        self.total_funding = 0.0
        self.liquidations = 0
        self.last_funding_dt = None
        self.equity_timestamps = []
        self.equity_balances = []

    async def verify_position(self, strategy, symbol: str) -> None:
        pass

    async def execute_reduce(self, strategy, symbol: str, qty: float, exit_price: float,
                             time_t: datetime, index_t: int, adjust_tag: str = "") -> None:
        if strategy.position is None or not strategy.position.is_open:
            return
        if qty <= 0 or qty >= strategy.position.qty:
            return

        # Plan 5 Step 5.3 / Plan 20 (ENG-10): floor to stepSize for
        # backtest/live parity with the live adapter's execute_reduce (which
        # now clamps too) — a backtest must never report a scale-out fill at
        # a precision live Binance would reject.
        qty = clamp_and_round_qty(symbol, "Binance Futures", qty, exit_price, reduce_only=True)
        if qty <= 0 or qty >= strategy.position.qty:
            return

        open_t = strategy.candles[index_t, 1]
        was_long = strategy.position.type == "long"
        bounded_exit = bounded_exit_price(
            is_long=was_long,
            proposed_price=exit_price,
            candle_open=open_t,
            candle_low=strategy.candles[index_t, 4],
            candle_high=strategy.candles[index_t, 3],
        )
        _fill = self.execution.exit_fill(strategy, bounded_exit, qty, "sell" if was_long else "buy")
        fill_price = _fill.fill_price
        fee = _fill.fee
        self.total_fees += fee

        realized_pnl = strategy.position.reduce_qty(qty, fill_price) - fee
        strategy.balance += realized_pnl
        strategy.available_margin = strategy.balance

        if self.active_trade is not None:
            entry = float(self.active_trade["entryPrice"])
            _mfe = max(self.active_trade["_mfe"],
                       (strategy.candles[index_t, 3] - entry) if was_long else (entry - strategy.candles[index_t, 4]))
            _mae = min(self.active_trade["_mae"],
                       (strategy.candles[index_t, 4] - entry) if was_long else (entry - strategy.candles[index_t, 3]))

            # Record the partial exit as a synthetic trade for analytics
            partial_trade = {
                "type":       strategy.position.type,
                "symbol":     self.symbol,
                "qty":        str(qty),
                "entryPrice": str(self.active_trade["entryPrice"]),
                "exitPrice":  str(fill_price),
                "entryAt":    self.active_trade["entryAt"],
                "exitAt":     time_t.isoformat(),
                "_entry_dt":  self.active_trade["_entry_dt"],
                "_exit_dt":   time_t,
                "exitReason": "scale_out",
                "pnl":        f"{realized_pnl:.2f}",
                "pnlPct":     f"{(realized_pnl / (qty * fill_price / strategy.leverage)) * 100:.2f}",
                "leverage":   strategy.leverage,
                "liqPrice":   self.active_trade.get("liqPrice", ""),
                "_mfe":       _mfe,
                "_mae":       _mae,
                "runUpPct":   f"{(_mfe / float(self.active_trade['entryPrice'])) * 100:.2f}",
                "drawdownPct": f"{abs(_mae / float(self.active_trade['entryPrice'])) * 100:.2f}",
                "barsHeld":   int(index_t - self.active_trade["_entry_index"]),
                "entryTag":   adjust_tag or self.active_trade.get("entryTag", ""),
                "exitTag":    self.active_trade.get("exitTag", ""),
            }
            self.active_trade["qty"] = str(strategy.position.qty)
            self.trades.append(partial_trade)

        try:
            strategy.on_reduced_position((qty, fill_price))
        except Exception as e:
            logger.error(f"on_reduced_position error: {e}")

    async def charge_funding(self, strategy, close_t: float, time_t: datetime) -> None:
        if self.funding_enabled and self.funding_rate and self.last_funding_dt is not None:
            side_sign = 1.0 if strategy.position.type == "long" else -1.0
            boundary = _next_funding_boundary(self.last_funding_dt)
            while boundary <= time_t:
                funding = side_sign * strategy.position.qty * close_t * self.funding_rate
                self.total_funding += funding
                strategy.balance -= funding
                self.last_funding_dt = boundary
                boundary = _next_funding_boundary(boundary)

    async def execute_entry(self, strategy, symbol: str, direction: str, qty: float,
                            ref_price: float, time_t: datetime, index_t: int,
                            intent: str = "enter", adjust_tag: str = "") -> bool:
        exchange_name = strategy.exchange or "Binance Futures"
        sl_pct = None
        if strategy.stop_loss is not None:
            _, sl_price = strategy.stop_loss
            sl_pct = abs(ref_price - sl_price) / ref_price

        qty = clamp_and_round_qty(symbol, exchange_name, qty, ref_price, stop_loss_pct=sl_pct)
        if qty <= 0:
            return False

        _entry = self.execution.entry_fill(strategy, ref_price, qty, strategy.leverage, "buy" if direction == "long" else "sell")
        fill_price = _entry.fill_price
        notional = _entry.notional
        req_margin = _entry.req_margin
        fee = _entry.fee

        # F-017: affordability checks FREE capital (balance minus margin already
        # reserved by other symbols' open positions in a shared-wallet portfolio
        # run). _external_reserved_margin is 0.0 for single-symbol → unchanged.
        free_balance = strategy.balance - getattr(strategy, "_external_reserved_margin", 0.0)
        if not _entry.affordable(free_balance):
            logger.warning(
                f"[{strategy.symbol}] Entry rejected: margin ${req_margin:.2f} + fee "
                f"${fee:.2f} exceeds free capital ${free_balance:.2f}"
            )
            return False

        self.total_fees += fee
        strategy.balance -= fee

        if intent == "add" and strategy.position is not None and strategy.position.is_open:
            # Scale in — add to existing position (A-014)
            strategy.position.add_qty(qty, fill_price)
            # Update active trade stats for the add leg
            if self.active_trade is not None:
                old_qty = float(self.active_trade["qty"])
                old_entry = float(self.active_trade["entryPrice"])
                new_qty = old_qty + qty
                new_entry = (old_qty * old_entry + qty * fill_price) / new_qty
                self.active_trade["qty"] = str(new_qty)
                self.active_trade["entryPrice"] = str(new_entry)
                self.active_trade["liqPrice"] = f"{strategy.position.liquidation_price:.4f}"
            try:
                strategy.on_increased_position((qty, fill_price))
            except Exception as e:
                logger.error(f"on_increased_position error: {e}")
        else:
            strategy.position = Position(
                direction, qty, fill_price, strategy.leverage,
                isolated_wallet=req_margin,
            )
            strategy.available_capital -= req_margin
            self.last_funding_dt = time_t

            self.active_trade = {
                "type":       direction,
                "symbol":     self.symbol,
                "qty":        str(qty),
                "entryPrice": str(fill_price),
                "entryAt":    time_t.isoformat(),
                "_entry_dt":  time_t,
                "_entry_index": index_t,
                "_mfe":       0.0,
                "_mae":       0.0,
                "leverage":   strategy.leverage,
                "liqPrice":   f"{strategy.position.liquidation_price:.4f}",
                "entryTag":   adjust_tag or strategy.entry_tag or "",
                "exitTag":    strategy.exit_tag or "",
            }
            try:
                strategy.on_open_position((qty, fill_price))
            except Exception as e:
                logger.error(f"on_open_position error: {e}")

        strategy.available_margin = strategy.balance - (
            strategy.position.margin if strategy.position else 0
        )
        strategy._entered_this_candle = True
        return True

    async def execute_exit(self, strategy, symbol: str, qty: float, exit_price: float, reason: str, time_t: datetime, index_t: int, high_t: float, low_t: float) -> None:
        if strategy.position is None:
            return

        locked_margin = strategy.position.margin
        was_long = strategy.position.type == "long"

        if reason == "liquidation":
            exit_fill = exit_price
            strategy.position.close(exit_fill)
            realized_pnl = -strategy.position.margin
            trade_pnl_pct = -100.0
            self.liquidations += 1
        else:
            open_t = strategy.candles[index_t, 1]
            bounded_exit = bounded_exit_price(
                is_long=was_long,
                proposed_price=exit_price,
                candle_open=open_t,
                candle_low=low_t,
                candle_high=high_t,
            )
            _fill = self.execution.exit_fill(strategy, bounded_exit, qty, "sell" if was_long else "buy")
            exit_fill = _fill.fill_price
            fee = _fill.fee
            self.total_fees += fee
            strategy.position.close(exit_fill)
            realized_pnl = strategy.position.pnl - fee
            trade_pnl_pct = strategy.position.pnl_pct

        strategy.balance += realized_pnl
        strategy.available_capital += locked_margin + realized_pnl
        strategy.available_margin = strategy.balance
        self.last_funding_dt = None

        if self.active_trade:
            self.active_trade["id"] = f"t_{len(self.trades) + 1}"
            self.active_trade = _finalize_trade(
                self.active_trade,
                index_t,
                exit_fill,
                time_t,
                reason,
                realized_pnl,
                trade_pnl_pct,
                high_t,
                low_t,
            )
            self.trades.append(self.active_trade)
            self.active_trade = None

        try:
            strategy.on_close_position((qty, exit_fill))
        except Exception as e:
            logger.error(f"on_close_position error: {e}")

        strategy.position = None
        strategy.stop_loss = None
        strategy.take_profit = None
        strategy._pending_flip = None

    async def execute_flip(self, strategy, symbol: str, new_direction: str, new_qty: float, ref_price: float, time_t: datetime, index_t: int, high_t: float, low_t: float, stop_loss: float | None = None, take_profit: float | None = None) -> bool:
        if strategy.position is None:
            return False

        old_qty = strategy.position.qty
        was_long = strategy.position.type == "long"
        _fill = self.execution.exit_fill(strategy, ref_price, old_qty, "sell" if was_long else "buy")
        exit_fill = _fill.fill_price
        fee = _fill.fee
        self.total_fees += fee
        strategy.position.close(exit_fill)
        realized_pnl = strategy.position.pnl - fee
        strategy.balance += realized_pnl
        strategy.available_margin = strategy.balance
        self.last_funding_dt = None

        if self.active_trade:
            self.active_trade["id"] = f"t_{len(self.trades) + 1}"
            self.active_trade = _finalize_trade(
                self.active_trade,
                index_t,
                exit_fill,
                time_t,
                "flip",
                realized_pnl,
                strategy.position.pnl_pct,
                high_t,
                low_t,
            )
            self.trades.append(self.active_trade)
            self.active_trade = None

        try:
            strategy.on_close_position((old_qty, exit_fill))
        except Exception as e:
            logger.error(f"on_close_position error: {e}")

        strategy.position = None
        strategy.stop_loss = None
        strategy.take_profit = None

        # Leg 2
        exchange_name = strategy.exchange or "Binance Futures"
        sl_pct = None
        if stop_loss is not None:
            sl_pct = abs(ref_price - stop_loss) / ref_price

        new_qty = clamp_and_round_qty(symbol, exchange_name, new_qty, ref_price, stop_loss_pct=sl_pct)
        if new_qty <= 0:
            logger.warning(f"[{strategy.symbol}] Flip degraded to close-only: quantity rounded to 0")
            return False

        _entry = self.execution.entry_fill(strategy, ref_price, new_qty, strategy.leverage, "buy" if new_direction == "long" else "sell")
        fill_price = _entry.fill_price
        notional = _entry.notional
        req_margin = _entry.req_margin
        fee = _entry.fee

        free_balance = strategy.balance - getattr(strategy, "_external_reserved_margin", 0.0)
        if not _entry.affordable(free_balance):
            logger.warning(
                f"[{strategy.symbol}] Flip degraded to close-only: qty {new_qty} margin "
                f"${req_margin:.2f} + fee ${fee:.2f} vs free capital ${free_balance:.2f}"
            )
            return False

        self.total_fees += fee
        strategy.balance -= fee
        strategy.position = Position(
            new_direction, new_qty, fill_price, strategy.leverage,
            isolated_wallet=req_margin,
        )
        strategy.available_margin = strategy.balance - req_margin
        self.last_funding_dt = time_t

        # I-11: stop rounds away from entry; take-profit rounds away the other way.
        sl_rounding = ROUND_DOWN if new_direction == "long" else ROUND_UP
        tp_rounding = ROUND_UP if new_direction == "long" else ROUND_DOWN
        strategy.stop_loss = (new_qty, round_price(symbol, exchange_name, stop_loss, rounding=sl_rounding)) if stop_loss is not None else None
        strategy.take_profit = (new_qty, round_price(symbol, exchange_name, take_profit, rounding=tp_rounding)) if take_profit is not None else None

        self.active_trade = {
            "type":       new_direction,
            "symbol":     self.symbol,
            "qty":        str(new_qty),
            "entryPrice": str(fill_price),
            "entryAt":    time_t.isoformat(),
            "_entry_dt":  time_t,
            "_entry_index": index_t,
            "_mfe":       0.0,
            "_mae":       0.0,
            "leverage":   strategy.leverage,
            "liqPrice":   f"{strategy.position.liquidation_price:.4f}",
        }
        try:
            strategy.on_open_position((new_qty, fill_price))
        except Exception as e:
            logger.error(f"on_open_position error: {e}")

        strategy._entered_this_candle = False
        return True

    def record_equity(self, strategy, time_t: datetime) -> None:
        unrealized = strategy.position.pnl if strategy.position is not None else 0.0
        self.equity_timestamps.append(time_t.isoformat())
        self.equity_balances.append(strategy.balance + unrealized)

        # Update excursions for active trade
        if self.active_trade is not None:
            if getattr(strategy, "_entered_this_candle", False):
                strategy._entered_this_candle = False
                return
            entry = float(self.active_trade["entryPrice"])
            high_t = strategy.high
            low_t = strategy.low
            if self.active_trade["type"] == "long":
                self.active_trade["_mfe"] = max(self.active_trade["_mfe"], high_t - entry)
                self.active_trade["_mae"] = min(self.active_trade["_mae"], low_t - entry)
            else:
                self.active_trade["_mfe"] = max(self.active_trade["_mfe"], entry - low_t)
                self.active_trade["_mae"] = min(self.active_trade["_mae"], entry - high_t)


async def _run_shared_portfolio(
    job_id, symbols, strategies, adapters, kernels,
    rows_by_sym, candles_np_by_sym, warmup_periods,
    capital, timeframe, r_client, is_cancelled_fn,
):
    """F-017 shared-wallet multi-symbol portfolio simulation.

    All symbols advance together in timestamp order against ONE shared balance
    with shared isolated margin — mirroring multi-symbol live (where every
    position competes for the same wallet), instead of N independent
    single-symbol runs on pre-split capital.

    Returns ``(timestamps, balances)`` for the combined portfolio equity curve.
    """
    # Unified, timestamp-ordered event stream across all symbols.
    events = []  # (ts_ms, ts_dt, sym, local_t)
    for sym in symbols:
        rows = rows_by_sym[sym]
        cnp = candles_np_by_sym[sym]
        for t in range(warmup_periods[sym], len(rows)):
            events.append((cnp[t, 0], rows[t]["time"], sym, t))
    events.sort(key=lambda e: e[0])

    def _reserved_margin():
        total = 0.0
        for s in symbols:
            pos = strategies[s].position
            if pos is not None and pos.is_open:
                total += pos.margin
        return total

    def _portfolio_unrealized():
        total = 0.0
        for s in symbols:
            pos = strategies[s].position
            if pos is not None and pos.is_open:
                total += pos.pnl
        return total

    shared_balance = float(capital)
    portfolio_ts: list = []
    portfolio_bal: list = []
    total = len(events)

    for i, (ts_ms, time_t, sym, t) in enumerate(events):
        if i % 100 == 0:
            if is_cancelled_fn():
                logger.info(f"[{job_id}] Cancelled by user.")
                raise RuntimeError("JOB_CANCELLED")
            pct = int((i / total) * 100) if total else 0
            await r_client.publish(
                f"progress:{job_id}",
                json.dumps({
                    "pct": pct,
                    "message": f"Simulating portfolio ({len(symbols)} symbols) {timeframe} — {pct}% ({i}/{total} candles)",
                }),
            )

        strategy = strategies[sym]
        kernel = kernels[sym]
        cnp = candles_np_by_sym[sym]
        candle = cnp[t]
        strategy.candles = cnp[:t + 1]

        # Sync the shared wallet into this symbol before it acts. The affordability
        # check uses balance - _external_reserved_margin (all open positions), so a
        # new entry can only use capital not already locked by another symbol.
        strategy.balance = shared_balance
        strategy.available_margin = shared_balance
        strategy._external_reserved_margin = _reserved_margin()

        await kernel.execute_pending(strategy, sym, candle, t, time_t)
        await kernel.check_exits(strategy, sym, candle, is_live=False, index_t=t, time_t=time_t)
        await kernel.evaluate_and_route(strategy, sym, candle, is_live=False, index_t=t, time_t=time_t)

        # QNT-1: clears the per-candle `_entered_this_candle` flag (kernel.check_exits
        # early-returns while it's set) and updates trade excursions (_mfe/_mae) — this
        # path never called record_equity, so the flag stuck forever after a symbol's
        # first entry and every later SL/TP/liquidation/funding check was skipped.
        adapters[sym].record_equity(strategy, time_t)

        # Write realized cash changes (fees, realized PnL) back to the shared wallet.
        shared_balance = strategy.balance

        # Record one portfolio-equity point per unique timestamp (after the last
        # symbol at that timestamp has acted): cash + ALL open unrealized PnL.
        is_last_at_ts = (i == total - 1) or (events[i + 1][0] != ts_ms)
        if is_last_at_ts:
            portfolio_ts.append(time_t.isoformat())
            portfolio_bal.append(shared_balance + _portfolio_unrealized())

    # Termination: force-close any positions still open at each symbol's last candle.
    for sym in symbols:
        strategy = strategies[sym]
        adapter = adapters[sym]
        cnp = candles_np_by_sym[sym]
        rows = rows_by_sym[sym]
        try:
            strategy.before_terminate()
        except Exception as e:
            logger.error(f"[{job_id}] before_terminate error: {e}")
        if strategy.position is not None:
            strategy.balance = shared_balance
            strategy._external_reserved_margin = 0.0
            await adapter.execute_exit(
                strategy=strategy, symbol=sym, qty=strategy.position.qty,
                exit_price=cnp[-1, 2], reason="force_close",
                time_t=rows[-1]["time"], index_t=len(rows) - 1,
                high_t=cnp[-1, 3], low_t=cnp[-1, 4],
            )
            shared_balance = strategy.balance
        try:
            strategy.terminate()
        except Exception as e:
            logger.error(f"[{job_id}] terminate error: {e}")

    portfolio_ts.append(rows_by_sym[symbols[0]][-1]["time"].isoformat())
    portfolio_bal.append(shared_balance)
    return portfolio_ts, portfolio_bal


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
    user_id: str = "",
    entry_candle_exits: bool = False,
    _reprep_every_candle: bool = False,
) -> dict:
    # entry_candle_exits (QNT-3, Plan 9 Step 9.4): opt-in, default off. When
    # True, SL/TP/liquidation are evaluated against the same candle a
    # position was entered on, matching live (exchange-side SL/TP orders are
    # active immediately after the entry fill there) instead of the
    # optimistic default that waits until the following candle. Default
    # False is byte-identical to the pre-9.4 path. Flipping the platform
    # default needs a deliberate golden-master re-baseline + sign-off — see
    # workspace/plan/9_backtest-and-optimizer-correctness.md Step 9.4.
    # _reprep_every_candle (QNT-12, Plan 9 Step 9.5): test-only lookahead
    # sentinel hook. Default False is byte-identical to the pre-9.5 code path
    # (prepare() called once, upfront). When True (single-symbol runs only —
    # see tests/test_lookahead_sentinel.py), prepare() is re-invoked every
    # candle on a truncated candles_np[:t+1] array instead of the full
    # history, simulating what the strategy would see if it could only ever
    # look backward. A causal strategy produces an identical trade list
    # either way; one that leaks future data (indexes past self.index, or
    # normalizes over the whole series) diverges.
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

    # ── 3. Parse symbols & allocate capital ────────────────────────────────
    symbols = [s.strip() for s in symbol.split(",") if s.strip()]
    if not symbols:
        raise ValueError("No valid symbols specified.")

    capital_splits = DefaultPortfolioModel().allocate(capital, symbols)

    start_dt = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
    end_dt   = datetime.fromisoformat(end_date).replace(tzinfo=timezone.utc)

    # ── 4. Verify & load candles for all symbols ──────────────────────────
    candles_np_by_sym = {}
    rows_by_sym = {}
    warmup_periods = {}

    for sym in symbols:
        candles_available = await ensure_candles_available(
            job_id=job_id,
            exchange=exchange,
            symbol=sym,
            timeframe=timeframe,
            start_date=start_date,
            end_date=end_date,
        )
        if not candles_available:
            raise ValueError(
                f"INSUFFICIENT_CANDLES: Failed to fetch required candles for {sym} "
                f"on {exchange}. Please check your date range and try again."
            )

        pool = get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT time, open, close, high, low, volume
                FROM candles
                WHERE exchange = $1 AND symbol = $2 AND timeframe = $3 AND time >= $4 AND time < $5
                ORDER BY time ASC
                """,
                exchange, sym, timeframe, start_dt, end_dt,
            )

        if len(rows) < 50:
            raise ValueError(
                f"INSUFFICIENT_CANDLES: Only {len(rows)} candles found for {sym}. "
                "Minimum 50 candles required for backtesting warm-up."
            )

        rows_by_sym[sym] = rows

        candles_np = np.column_stack([
            [r["time"].timestamp() * 1000 for r in rows],
            [r["open"]   for r in rows],
            [r["close"]  for r in rows],
            [r["high"]   for r in rows],
            [r["low"]    for r in rows],
            [r["volume"] for r in rows],
        ]).astype(np.float64)
        candles_np_by_sym[sym] = candles_np

    # Plan 22 Step 22.6: opt-in inverse-volatility allocation, config-gated
    # via risk_params["allocation"] == "inverse_vol" (default "equal" — the
    # capital_splits computed above at step 3, BEFORE candles existed, is
    # left completely untouched in the default case, so the golden-master
    # path has zero diff). Only when opted in do we recompute capital_splits
    # here, now that warmup candle data is available, using each symbol's
    # first INVERSE_VOL_LOOKBACK closes (pure rule-based realized vol, no
    # fitted/GARCH models — fork #2's scope decision).
    _INVERSE_VOL_LOOKBACK = 30
    if (risk_params or {}).get("allocation") == "inverse_vol":
        _close_histories = {
            sym: candles_np_by_sym[sym][:_INVERSE_VOL_LOOKBACK, 2] for sym in symbols
        }
        _vols = compute_realized_volatility(_close_histories)
        capital_splits = InverseVolatilityPortfolio().allocate(capital, symbols, volatilities=_vols)
        logger.info(f"[{job_id}] inverse_vol allocation: {capital_splits}")

    # ── 5. Setup Redis connection ───────────────────────────────────────────
    redis_url = os.getenv("REDIS_URL", "redis://redis:6379")
    r_client = aioredis.from_url(redis_url, socket_timeout=None, socket_connect_timeout=10)

    # ── 6. Async cancel-listener task ───────────────────────────────────────
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

    # ── 7. Run simulation ──────────────────────────────────────────────────
    # Single-symbol: the symbol runs on its own balance (byte-identical to the
    # historical behaviour). Multi-symbol (F-017): all symbols advance together
    # in time against ONE shared balance with shared isolated margin via
    # _run_shared_portfolio(), representing multi-symbol live.
    strategies: dict = {}
    adapters = {}
    kernels: dict = {}
    total_candles_all = sum(len(rows_by_sym[sym]) for sym in symbols)
    _is_multi = len(symbols) > 1
    portfolio_curve = None

    try:
        # ── 7a. Per-symbol setup (strategy, params, adapter, kernel) ─────────
        for sym in symbols:
            rows = rows_by_sym[sym]
            candles_np = candles_np_by_sym[sym]
            # Shared-wallet portfolio runs start every symbol on the FULL capital
            # (the balance is synced from the shared wallet each step); single
            # symbol uses its allocated split (== capital), preserving behaviour.
            _init_cap = capital if _is_multi else capital_splits[sym]

            # Initialise strategy
            strategy = strategy_class()
            strategy.exchange       = exchange
            strategy.symbol         = sym
            strategy.timeframe      = timeframe
            strategy.balance        = _init_cap
            strategy.available_margin = _init_cap
            strategy.leverage       = leverage
            strategy.fee_rate       = fee_rate
            strategy.exchange_type  = "futures" if "Futures" in exchange else "spot"
            strategy.is_backtesting = True

            _slippage   = slippage_pct if slippage_pct is not None else SLIPPAGE_PCT
            _fund_rate  = funding_rate if funding_rate is not None else FUNDING_RATE
            _funding_on = funding_enabled
            sym_leverage = max(int(leverage), 1)
            sym_leverage = min(sym_leverage, 125)
            _sym_max_lev = _MAX_LEVERAGE_OFFLINE_MAP.get(sym, 20)
            sym_leverage = min(sym_leverage, _sym_max_lev)
            strategy.leverage = sym_leverage

            # Inject alpha params (F-015/F-016: reject out-of-range and unknown params)
            strategy_params = getattr(strategy, "PARAMS", {})
            for key, val in (alpha_params or {}).items():
                if key not in strategy_params:
                    raise ValueError(
                        f"Unknown parameter '{key}'. "
                        f"Valid parameters for {strategy.__class__.__name__}: {list(strategy_params.keys())}"
                    )
                bounds = strategy_params[key]
                try:
                    typed_val = param_coerce(bounds, val)
                except (TypeError, ValueError):
                    typed_val = val
                param_validate(bounds, typed_val)
                setattr(strategy, key, typed_val)

            try:
                strategy.validate_params()
            except ValueError as e:
                raise RuntimeError(f"PARAM_ERROR: {e}")

            # Plan 24 finding S-3(a): a strategy using a higher-timeframe
            # supertrend (duck-typed via `tf`/`pd` attrs — e.g. BestSupertrend)
            # can be structurally unable to ever form `pd+2` completed HTF
            # buckets within the chosen date range (e.g. tf="weekly" needs
            # ~12 weeks of history; a short backtest window silently produces
            # zero trades with no indication why). Log-only, not a hard
            # failure — a short warmup is a valid (if pointless) backtest
            # config, and the fix must never change simulation output.
            _strat_tf = getattr(strategy, "tf", None)
            _strat_pd = getattr(strategy, "pd", None)
            if isinstance(_strat_pd, int) and isinstance(_strat_tf, str):
                _required_candles = required_base_candles_for_htf(_strat_tf, _strat_pd, timeframe)
                if _required_candles is not None and len(candles_np) < _required_candles:
                    logger.error(
                        f"[{job_id}] {sym}: only {len(candles_np)} {timeframe} candles loaded, "
                        f"need ~{_required_candles} for tf={_strat_tf!r} (pd={_strat_pd}) to ever "
                        f"form a completed HTF supertrend bucket — this strategy will show zero "
                        f"trades for the whole run. Widen the date range or lower tf."
                    )

            # One-time vectorized indicator pre-computation
            try:
                strategy.prepare(candles_np)
            except Exception as e:
                raise RuntimeError(f"STRATEGY_ERROR: prepare() failed: {e}")

            # Inject risk params
            _risk_all = risk_params or {}
            _risk = _risk_all.get(sym) or _risk_all.get("default") or _risk_all
            strategy.risk_pct          = min(_safe_float(_risk.get("risk_pct"),       0.01), 0.20)
            strategy.rrr               = _safe_float(_risk.get("rrr"),            2.0)
            strategy.liq_buffer_pct    = _safe_float(_risk.get("liq_buffer_pct"), 0.005)
            strategy.max_session_dd    = min(_safe_float(_risk.get("max_session_dd"), 0.20), 0.90)
            strategy.portfolio_model.min_edge_mult = _safe_float(_risk.get("min_edge_mult"), 0.0)
            strategy.max_portfolio_risk       = _safe_float(_risk.get("max_portfolio_risk"), 0.06)
            strategy.volatility_multiplier = _safe_float(_risk.get("volatility_multiplier"), 1.0)
            strategy.max_exposure_notional = _safe_float(_risk.get("max_exposure_notional"), float('inf'))
            custom_atr_mult = _risk.get("custom_atr_mult")
            strategy.custom_atr_mult = _safe_float(custom_atr_mult, None) if custom_atr_mult is not None else None
            strategy.slippage_pct      = _slippage
            strategy.fee_rate          = fee_rate
            strategy.available_capital = float(_init_cap)
            strategy.peak_equity       = float(_init_cap)

            execution = BacktestExecution()
            strategy.execution_model = execution

            # Initialize adapter and kernel
            adapter = BacktestAdapter(execution, fee_rate, _slippage, _funding_on, _fund_rate, sym)
            adapters[sym] = adapter

            # Setup execution algorithm if configured
            exec_algo = None
            exec_algo_cfg = (alpha_params or {}).get("exec_algo")
            if exec_algo_cfg and isinstance(exec_algo_cfg, dict):
                algo_type = exec_algo_cfg.get("type")
                algo_params = exec_algo_cfg.get("params", {})
                try:
                    from core.models.exec_algo import TWAPAlgorithm, VWAPAlgorithm, IcebergAlgorithm
                except ImportError:
                    from engine.core.models.exec_algo import TWAPAlgorithm, VWAPAlgorithm, IcebergAlgorithm

                if algo_type == "twap":
                    exec_algo = TWAPAlgorithm(strategy, sym, algo_params)
                elif algo_type == "vwap":
                    exec_algo = VWAPAlgorithm(strategy, sym, algo_params)
                elif algo_type == "iceberg":
                    exec_algo = IcebergAlgorithm(strategy, sym, algo_params)

            kernel = ExecutionKernel(adapter, exec_algo, entry_candle_exits=entry_candle_exits)

            warmup_period = max(strategy.MIN_WARMUP_CANDLES, min(50, len(rows) - 2))
            warmup_periods[sym] = warmup_period
            strategies[sym] = strategy
            kernels[sym] = kernel

        # ── 7b. Simulation ──────────────────────────────────────────────────
        if _is_multi:
            portfolio_curve = await _run_shared_portfolio(
                job_id, symbols, strategies, adapters, kernels,
                rows_by_sym, candles_np_by_sym, warmup_periods,
                capital, timeframe, r_client, lambda: is_cancelled,
            )
        else:
            sym = symbols[0]
            strategy = strategies[sym]
            adapter = adapters[sym]
            kernel = kernels[sym]
            rows = rows_by_sym[sym]
            candles_np = candles_np_by_sym[sym]
            warmup_period = warmup_periods[sym]
            total_candles = len(rows)

            logger.info(f"[{job_id}] Running simulation loop on {sym} ({len(rows)} candles)...")

            for t in range(warmup_period, total_candles):
                if t % 100 == 0:
                    if is_cancelled:
                        logger.info(f"[{job_id}] Cancelled by user.")
                        raise RuntimeError("JOB_CANCELLED")
                    pct = int((t / total_candles_all) * 100)
                    await r_client.publish(
                        f"progress:{job_id}",
                        json.dumps({
                            "pct": pct,
                            "message": f"Simulating {sym} {timeframe} — {pct}% ({t}/{total_candles_all} candles)",
                        }),
                    )

                time_t = rows[t]["time"]
                candle = candles_np[t]

                # Set strategy.candles to include the current candle up front
                strategy.candles = candles_np[:t + 1]

                if _reprep_every_candle:
                    strategy.prepare(strategy.candles)

                # Step 1: Open of candle (execute pending buy/sell/flip/close)
                await kernel.execute_pending(strategy, sym, candle, t, time_t)

                # Step 2: Exit checking and unrealized P&L / funding update
                await kernel.check_exits(strategy, sym, candle, is_live=False, index_t=t, time_t=time_t)

                # Step 3: Candle close - indicators and evaluate
                await kernel.evaluate_and_route(strategy, sym, candle, is_live=False, index_t=t, time_t=time_t)

                # Record equity snapshot
                adapter.record_equity(strategy, time_t)

            # Termination
            try:
                strategy.before_terminate()
            except Exception as e:
                logger.error(f"[{job_id}] before_terminate error: {e}")

            if strategy.position is not None:
                last_close = candles_np[-1, 2]
                await adapter.execute_exit(
                    strategy=strategy,
                    symbol=sym,
                    qty=strategy.position.qty,
                    exit_price=last_close,
                    reason="force_close",
                    time_t=rows[-1]["time"],
                    index_t=total_candles - 1,
                    high_t=candles_np[-1, 3],
                    low_t=candles_np[-1, 4],
                )

            # Append post-close balance
            adapter.equity_balances.append(strategy.balance)
            adapter.equity_timestamps.append(rows[-1]["time"].isoformat())

            try:
                strategy.terminate()
            except Exception as e:
                logger.error(f"[{job_id}] terminate error: {e}")

    finally:
        cancel_task.cancel()
        try:
            await cancel_task
        except asyncio.CancelledError:
            pass

    # ── 8. Merge results across all symbols ────────────────────────────────
    logger.info(f"[{job_id}] Simulation complete. Merging results...")

    combined_trades = []
    for sym in symbols:
        combined_trades.extend(adapters[sym].trades)

    combined_trades.sort(key=lambda tr: tr["_entry_dt"])
    for idx, tr in enumerate(combined_trades):
        tr["id"] = f"t_{idx + 1}"

    # Equity curve. Multi-symbol (F-017): the single shared-wallet portfolio
    # curve built during the interleaved run. Single-symbol: the per-symbol
    # curve (summing one symbol → identical to the historical behaviour).
    if portfolio_curve is not None:
        combined_timestamps, combined_balances = portfolio_curve
    else:
        all_timestamps = set()
        for sym in symbols:
            all_timestamps.update(adapters[sym].equity_timestamps)

        combined_timestamps = sorted(list(all_timestamps))
        combined_balances = []

        last_balances = {sym: capital_splits[sym] for sym in symbols}
        for ts in combined_timestamps:
            ts_balance_sum = 0.0
            for sym in symbols:
                adapter = adapters[sym]
                if ts in adapter.equity_timestamps:
                    idx = adapter.equity_timestamps.index(ts)
                    last_balances[sym] = adapter.equity_balances[idx]
                ts_balance_sum += last_balances[sym]
            combined_balances.append(ts_balance_sum)

    # ── 9. Calculate metrics on combined portfolio ────────────────────────
    balances_arr = np.array(combined_balances, dtype=np.float64)
    total_trades = len(combined_trades)

    total_fees = sum(adapters[sym].total_fees for sym in symbols)
    total_funding = sum(adapters[sym].total_funding for sym in symbols)
    liquidations = sum(adapters[sym].liquidations for sym in symbols)

    buy_hold_pcts = []
    for sym in symbols:
        candles_np = candles_np_by_sym[sym]
        warmup_period = warmup_periods[sym]
        if candles_np.shape[0] > warmup_period:
            first_close = candles_np[warmup_period, 2]
            last_close = candles_np[-1, 2]
            buy_hold_pct = ((last_close - first_close) / first_close) * 100.0 if first_close > 0 else 0.0
        else:
            buy_hold_pct = 0.0
        buy_hold_pcts.append(buy_hold_pct)
    avg_buy_hold_pct = sum(buy_hold_pcts) / len(symbols) if symbols else 0.0

    # Use real candles from the first symbol to preserve exact timestamps and index alignment
    first_sym = symbols[0]
    base_candles = candles_np_by_sym[first_sym].copy()
    warmup_period_first = warmup_periods[first_sym]
    if base_candles.shape[0] > warmup_period_first:
        first_close = base_candles[warmup_period_first, 2]
        base_candles[-1, 2] = first_close * (1.0 + avg_buy_hold_pct / 100.0)

    _metric_ctx = MetricContext(
        trades=combined_trades,
        balances=balances_arr,
        equity_timestamps=combined_timestamps,
        candles_np=base_candles,
        capital=capital,
        timeframe=timeframe,
        annual_factor=annual_factor(timeframe),
        warmup_period=warmup_period_first,
        total_fees=total_fees,
        total_funding=total_funding,
        liquidations=liquidations,
        leverage=leverage,
    )

    _registry = default_registry()
    metrics = _registry.compute_all(_metric_ctx)

    long_trades = [t for t in combined_trades if t["type"] == "long"]
    short_trades = [t for t in combined_trades if t["type"] == "short"]
    metrics["bySide"] = {
        "all":   _compute_side_metrics(combined_trades, capital),
        "long":  _compute_side_metrics(long_trades, capital),
        "short": _compute_side_metrics(short_trades, capital),
    }

    # ── 10. Downsample combined equity curve ──────────────────────────────
    raw_n = len(combined_timestamps)
    if raw_n <= EQUITY_CURVE_MAX_POINTS:
        sampled_ts  = combined_timestamps
        sampled_bal = combined_balances
    else:
        indices     = np.round(np.linspace(0, raw_n - 1, EQUITY_CURVE_MAX_POINTS)).astype(int)
        sampled_ts  = [combined_timestamps[i] for i in indices]
        sampled_bal = [combined_balances[i]   for i in indices]

    equity_curve_docs = [
        {"timestamp": ts, "balance": f"{bal:.2f}"}
        for ts, bal in zip(sampled_ts, sampled_bal)
    ]

    underwater_docs = underwater_curve_with_timestamps(
        combined_timestamps, balances_arr, max_points=EQUITY_CURVE_MAX_POINTS,
    )
    rolling_docs = rolling_curve(
        balances_arr,
        timeframe_seconds=timeframe_to_seconds(timeframe),
        annual_factor=annual_factor(timeframe),
        window_candles=50,
        max_points=EQUITY_CURVE_MAX_POINTS,
    )
    returns_hist = returns_histogram(combined_trades, capital)
    mfe_mae_pts  = mfe_mae_scatter(combined_trades, capital)

    # ── 11. Write main result document to MongoDB ─────────────────────────
    db = get_database()
    strategy_doc = await db.strategies.find_one({"name": strategy_name})
    strategy_id  = str(strategy_doc["_id"]) if strategy_doc else None

    # Use actual candle boundaries from first symbol as time bounds
    first_sym = symbols[0]
    actual_start = rows_by_sym[first_sym][0]["time"].isoformat()
    actual_end   = rows_by_sym[first_sym][-1]["time"].isoformat()

    # QNT-17: persist the full run config so re-derived runs (leverage sensitivity,
    # Monte Carlo, any future re-simulation) reproduce THIS run's params instead of
    # silently falling back to defaults. leverage_sensitivity_runner.py already reads
    # these fields back via parent.get(...) — they were simply never being written.
    _effective_slippage_pct = slippage_pct if slippage_pct is not None else SLIPPAGE_PCT
    _effective_funding_rate = funding_rate if funding_rate is not None else FUNDING_RATE

    await db.backtestResults.update_one(
        {"jobId": job_id},
        {
            "$set": {
                "jobId":        job_id,
                "userId":       user_id,
                "strategyId":   strategy_id,
                "strategyName": strategy_name,
                "exchange":     exchange,
                "symbol":       symbol,  # comma-separated symbols string
                "timeframe":    timeframe,
                "startDate":    actual_start,
                "endDate":      actual_end,
                "capital":      capital,
                "leverage":     leverage,
                "feeRate":      fee_rate,
                "slippagePct":  _effective_slippage_pct,
                "fundingEnabled": funding_enabled,
                "fundingRate":  _effective_funding_rate,
                "alphaParams":  alpha_params or {},
                "riskParams":   risk_params or {},
                "status":       "completed",
                "metrics":      metrics,
                "equityCurve":  equity_curve_docs,
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

    # ── 12. Bulk-insert trades ─────────────────────────────────────────────
    if combined_trades:
        trade_docs = [
            {
                "jobId":       job_id,
                "userId":      user_id,
                "tradeIndex":  i + 1,
                "type":        tr["type"],
                "symbol":      tr.get("symbol", ""),
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
                "entryTag":    tr.get("entryTag", ""),
                "exitTag":     tr.get("exitTag", ""),
            }
            for i, tr in enumerate(combined_trades)
        ]
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
