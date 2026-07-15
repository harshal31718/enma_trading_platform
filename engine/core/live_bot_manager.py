from __future__ import annotations
import asyncio
import contextlib
import json
import logging
import os
import random
from datetime import datetime, timezone
from decimal import ROUND_DOWN, ROUND_UP
from enum import Enum
from uuid import uuid4

import httpx
import numpy as np
import websockets

from config.timescale import get_pool
from core.position import Position
from core.models import (
    DefaultPortfolioModel, LiveExecution, OrderPlan,
    CooldownPeriod, StoplossGuard, ProtectionManager,
)
from core.params import param_coerce, param_default, param_validate
from core.pipeline import evaluate
from services.trade_recorder import record_trade, build_trade_record
from services.user_data_stream import UserDataStreamManager
from services.pairlist import pairlist_from_config
from utils.symbols import round_price, clamp_and_round_qty, clamp_leverage, get_ticker_data, is_symbol_invalid
from core.kernel import ExecutionAdapter, ExecutionKernel

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

# Plan 3 Step 3.1 (SEC-1): shared secret authenticating engine -> Node
# /internal/* calls (distinct from ENGINE_API_KEY, which authenticates the
# other direction, Node -> engine).
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "")


def _internal_headers() -> dict:
    return {"X-Internal-Key": INTERNAL_API_KEY}


TRADING_STATES = ("active", "reducing", "halted")


from utils.rate_limiter import OrderRateLimiter


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


class LiveAdapter(ExecutionAdapter):
    def __init__(self, manager: LiveBotManager, session_id: str):
        self.manager = manager
        self.session_id = session_id

    async def verify_position(self, strategy, symbol: str) -> None:
        # Reconciliation is now handled by _reconcile_exchange_state() called
        # unconditionally at the top of every candle loop (F-001/F-004).
        pass

    async def execute_entry(
        self, strategy, symbol: str, direction: str, qty: float, ref_price: float,
        time_t: datetime, index_t: int, intent: str = "enter", adjust_tag: str = "",
    ) -> bool:
        session = self.manager.sessions.get(self.session_id)
        if not session:
            return False

        # DCA scale-in (A-014): skip new-entry guards when adding to existing position
        is_dca = intent == "add" and strategy.position is not None and strategy.position.is_open

        if not is_dca:
            # TradingState check (A-002) — halt new entries when reducing or halted
            trading_state = session.get("trading_state", "active")
            if trading_state in ("halted", "reducing"):
                logger.warning(f"[AlgoBot] {symbol}: entry blocked, trading_state={trading_state}")
                await self.manager._notify_node(self.session_id, {
                    "event": "log",
                    "eventData": {"type": "warning", "message": f"{symbol}: entry blocked (trading_state={trading_state})"}
                })
                strategy.buy = None
                strategy.sell = None
                return False

            # Protections check (A-001)
            protection_manager = session.get("protection_manager")
            if protection_manager is not None:
                lock = protection_manager.check_entry(symbol, direction, session.get("capital", 0))
                if lock is not None:
                    logger.warning(f"[AlgoBot] {symbol}: entry blocked by protection: {lock.reason}")
                    await self.manager._notify_node(self.session_id, {
                        "event": "log",
                        "eventData": {"type": "warning", "message": f"{symbol}: entry blocked — {lock.reason}"}
                    })
                    strategy.buy = None
                    strategy.sell = None
                    return False

            # Rate limiter check (A-003)
            rate_limiter = session.get("rate_limiter")
            if rate_limiter is not None and not rate_limiter.allow():
                logger.warning(f"[AlgoBot] {symbol}: order rate limited, skipping")
                await self.manager._notify_node(self.session_id, {
                    "event": "log",
                    "eventData": {"type": "warning", "message": f"{symbol}: order rate limited, skipping"}
                })
                strategy.buy = None
                strategy.sell = None
                return False

        fill_price = ref_price

        # Retrieve SL/TP values from strategy (updated by evaluate pipeline or exec_algo)
        sl_raw = strategy.stop_loss[1] if strategy.stop_loss else None
        tp_raw = strategy.take_profit[1] if strategy.take_profit else None
        sl_pct = abs(fill_price - sl_raw) / fill_price if sl_raw else None

        exchange_name = "Binance Futures"
        qty = clamp_and_round_qty(symbol, exchange_name, qty, fill_price, stop_loss_pct=sl_pct)

        # I-11: stop rounds away from entry; take-profit rounds away the other way
        # (using the stop's mode for TP biased it toward entry — easier to hit).
        sl_rounding = ROUND_DOWN if direction == "long" else ROUND_UP
        tp_rounding = ROUND_UP if direction == "long" else ROUND_DOWN
        sl_price = round_price(symbol, exchange_name, sl_raw, rounding=sl_rounding) if sl_raw else None
        tp_price = round_price(symbol, exchange_name, tp_raw, rounding=tp_rounding) if tp_raw else None

        if qty <= 0:
            logger.warning(f"[AlgoBot] Quantity rounded to 0 for {symbol} (below min lot size), skipping")
            strategy.buy = None
            strategy.sell = None
            return False

        notional = qty * fill_price
        max_allowed_notional = strategy.balance * strategy.leverage * 1.05
        if notional > max_allowed_notional:
            logger.warning(
                f"[AlgoBot] {symbol}: notional ${notional:.2f} exceeds leveraged buying power "
                f"${strategy.balance * strategy.leverage:.2f} (leverage {strategy.leverage}x) after min-notional bump, skipping"
            )
            await self.manager._notify_node(self.session_id, {
                "event": "log",
                "eventData": {
                    "type": "error",
                    "message": f"Skipped {symbol}: notional ${notional:.2f} exceeds leveraged buying power ${strategy.balance * strategy.leverage:.2f}"
                }
            })
            strategy.buy = None
            strategy.sell = None
            return False

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
        sem = self.manager._order_semaphores.get(self.session_id)

        # ── F-019: Track placed algo order IDs for OUO peer-cancel ──
        _placed_algo_ids: dict[str, str | None] = {"sl": None, "tp": None}

        # DCA scale-in: skip SL/TP placement and use existing brackets
        if is_dca:
            try:
                from services.binance_testnet import send_signed_request as _signed
                _api_key = session.get("api_key", "")
                _api_secret = session.get("api_secret", "")
                if not _api_key or not _api_secret:
                    raise RuntimeError("Binance Testnet API credentials not configured")

                async with (sem if sem else contextlib.nullcontext()):
                    add_params = {
                        "symbol": symbol,
                        "side": binance_side,
                        "type": "MARKET",
                        "quantity": _fmt_num(qty),
                        "newOrderRespType": "RESULT",
                    }
                    result = await _signed(
                        "POST", "/fapi/v1/order",
                        _api_key, _api_secret,
                        params=add_params,
                        mode="testnet",
                    )
                    fill_price = float(result.get("avgPrice", ref_price))
                    logger.info(
                        f"[AlgoBot] DCA add {direction}: {symbol} +{qty} @ {fill_price} "
                        f"orderId={result.get('orderId')}"
                    )

                strategy.position.add_qty(qty, fill_price)
                pos_info = session["open_positions"].get(symbol, {})
                old_qty = float(pos_info.get("qty", 0))
                new_qty = old_qty + qty
                new_price = (old_qty * float(pos_info.get("price", 0)) + qty * fill_price) / new_qty if old_qty > 0 else fill_price
                pos_info["qty"] = str(new_qty)
                pos_info["price"] = str(new_price)
                session["open_positions"][symbol] = pos_info

                try:
                    strategy.on_increased_position((qty, fill_price))
                except Exception as e:
                    logger.error(f"on_increased_position error: {e}")

                await self.manager._notify_node(self.session_id, {
                    "pnl": str(round(session["pnl"], 2)),
                    "openPositions": list(session["open_positions"].keys()),
                    "status": "running",
                    "event": "position:adjust",
                    "eventData": {
                        "symbol": symbol,
                        "qty": str(new_qty),
                        "price": str(new_price),
                        "adjustQty": str(qty),
                        "adjustTag": adjust_tag,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                })
                return True
            except Exception as e:
                logger.error(f"[AlgoBot] DCA add failed for {symbol}: {e}")
                return False

        try:
            # F-003: Place orders directly on Binance instead of routing
            # through the engine→Node→engine→Binance hop chain.
            from services.binance_testnet import send_signed_request as _signed
            _api_key = session.get("api_key", "")
            _api_secret = session.get("api_secret", "")
            if not _api_key or not _api_secret:
                raise RuntimeError("Binance Testnet API credentials not configured")

            order_id = None
            async with (sem if sem else contextlib.nullcontext()):
                # Step 1: Place the entry MARKET order
                entry_params = {
                    "symbol": symbol,
                    "side": binance_side,
                    "type": "MARKET",
                    "quantity": _fmt_num(qty),
                    "newOrderRespType": "RESULT",
                }
                entry_result = await _signed(
                    "POST", "/fapi/v1/order",
                    _api_key, _api_secret,
                    params=entry_params,
                    mode="testnet",
                )
                order_id = entry_result.get("orderId")
                logger.info(
                    f"[AlgoBot] Testnet {direction} entry filled: {symbol} qty={qty} "
                    f"@ {entry_result.get('avgPrice', fill_price)} orderId={order_id}"
                )

                # Step 2: Best-effort SL/TP placement (orders placed directly,
                # no separate hop).  Failure here does not revert the entry.
                close_side = "SELL" if binance_side == "BUY" else "BUY"
                tpsl_prefix = f"tpsl_{uuid4_hex8()}_"

                if sl_price is not None:
                    try:
                        sl_params = {
                            "algoType": "CONDITIONAL",
                            "symbol": symbol,
                            "side": close_side,
                            "type": "STOP_MARKET",
                            "triggerPrice": _fmt_num(sl_price),
                            "workingType": "MARK_PRICE",
                            "closePosition": "true",
                            "clientAlgoId": f"{tpsl_prefix}sl",
                        }
                        sl_result = await _signed(
                            "POST", "/fapi/v1/algoOrder",
                            _api_key, _api_secret,
                            params=sl_params,
                            mode="testnet",
                        )
                        logger.info(f"[AlgoBot] SL placed for {symbol}: algoId={sl_result.get('algoId')}")
                        # Track algo order ID for OUO peer-cancel (F-019)
                        _placed_algo_ids["sl"] = sl_result.get("algoId")
                    except Exception as sl_e:
                        logger.warning(f"[AlgoBot] SL placement failed for {symbol}: {sl_e}")
                        # ── F-018: Emergency market exit ────────────────────
                        # Entry filled but SL placement failed → position is
                        # naked. Force-close at market immediately.
                        try:
                            _close_side = "SELL" if binance_side == "BUY" else "BUY"
                            _close_params = {
                                "symbol": symbol,
                                "side": _close_side,
                                "type": "MARKET",
                                "quantity": _fmt_num(qty),
                                "reduceOnly": "true",
                            }
                            await _signed(
                                "POST", "/fapi/v1/order",
                                _api_key, _api_secret,
                                params=_close_params,
                                mode="testnet",
                            )
                            logger.warning(f"[AlgoBot] {symbol}: emergency MARKET close sent (SL placement failed)")
                        except Exception as _close_e:
                            logger.error(f"[AlgoBot] {symbol}: emergency MARKET close FAILED: {_close_e}")

                        # Record the trade locally with emergency_exit reason
                        _pos_e = Position(direction, qty, fill_price)
                        _fee_e = strategy.execution_model.exit_fee(strategy, _pos_e.qty, fill_price)
                        _pos_e.close(fill_price)
                        _rpnl_e = _pos_e.pnl - _fee_e
                        strategy.balance += _rpnl_e
                        session["pnl"] += _rpnl_e
                        _tr = build_trade_record(
                            source="bot",
                            executed_by=session.get("strategy_name", "unknown"),
                            symbol=symbol,
                            side=direction,
                            qty=str(qty),
                            entry_price=str(fill_price),
                            exit_price=str(fill_price),
                            sl_order_price=str(sl_price),
                            tp_order_price=None,
                            margin=str(_pos_e.margin) if _pos_e.margin else None,
                            liquidation_price=str(_pos_e.liquidation_price) if _pos_e.liquidation_price else None,
                            leverage=_pos_e.leverage if _pos_e.leverage else None,
                            net_pnl=str(round(_rpnl_e, 2)),
                            pnl_pct=str(round(_pos_e.pnl_pct, 2)) if _pos_e.pnl_pct else None,
                            fee=str(round(_fee_e, 2)) if _fee_e else None,
                            exit_reason="emergency_exit",
                            user_id=session.get("user_id", ""),
                            session_id=self.session_id,
                            strategy_name=session.get("strategy_name"),
                            entry_time=datetime.now(timezone.utc),
                            exit_time=datetime.now(timezone.utc),
                        )
                        await record_trade(_tr)
                        await self.manager._notify_node(self.session_id, {
                            "pnl": str(round(session["pnl"], 2)),
                            "openPositions": list(session["open_positions"].keys()),
                            "status": "running",
                            "event": "position:close",
                            "eventData": {
                                "symbol": symbol,
                                "pnl": str(round(_rpnl_e, 2)),
                                "exitPrice": str(fill_price),
                                "exitReason": "emergency_exit",
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            },
                        })
                        logger.warning(f"[AlgoBot] {symbol}: emergency exit complete — PnL={_rpnl_e:.2f}")
                        strategy.buy = None
                        strategy.sell = None
                        return False

                if tp_price is not None:
                    try:
                        tp_params = {
                            "algoType": "CONDITIONAL",
                            "symbol": symbol,
                            "side": close_side,
                            "type": "TAKE_PROFIT_MARKET",
                            "triggerPrice": _fmt_num(tp_price),
                            "workingType": "MARK_PRICE",
                            "closePosition": "true",
                            "clientAlgoId": f"{tpsl_prefix}tp",
                        }
                        tp_result = await _signed(
                            "POST", "/fapi/v1/algoOrder",
                            _api_key, _api_secret,
                            params=tp_params,
                            mode="testnet",
                        )
                        logger.info(f"[AlgoBot] TP placed for {symbol}: algoId={tp_result.get('algoId')}")
                        _placed_algo_ids["tp"] = tp_result.get("algoId")
                    except Exception as tp_e:
                        logger.warning(f"[AlgoBot] TP placement failed for {symbol}: {tp_e}")
                        await self.manager._notify_node(self.session_id, {
                            "event": "log",
                            "eventData": {"type": "warning", "message": f"{symbol}: TP skipped — {tp_e}"},
                        })

        except Exception as e:
            logger.error(f"[AlgoBot] Testnet order failed for {symbol}: {e}")
            await self.manager._notify_node(self.session_id, {
                "event": "log",
                "eventData": {"type": "error", "message": f"Order failed {symbol}: {e}"}
            })
            strategy.buy = None
            strategy.sell = None
            return False

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
            "algo_ids": _placed_algo_ids,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        session["open_positions"][symbol] = pos_info

        await self.manager._notify_node(self.session_id, {
            "pnl": str(round(session["pnl"], 2)),
            "openPositions": list(session["open_positions"].keys()),
            "status": "running",
            "event": "position:open",
            "eventData": pos_info,
        })

        logger.info(f"[AlgoBot] Testnet {direction} filled: {symbol} qty={qty} @ {fill_price}")
        return True

    async def execute_reduce(
        self, strategy, symbol: str, qty: float, exit_price: float,
        time_t: datetime, index_t: int, adjust_tag: str = "",
    ) -> None:
        session = self.manager.sessions.get(self.session_id)
        if not session or strategy.position is None or not strategy.position.is_open:
            return
        if qty <= 0 or qty >= strategy.position.qty:
            return

        reduce_side = "SELL" if strategy.position.type == "long" else "BUY"
        try:
            from services.binance_testnet import send_signed_request as _signed
            _api_key = session.get("api_key", "")
            _api_secret = session.get("api_secret", "")

            sem = self.manager._order_semaphores.get(self.session_id)
            async with (sem if sem else contextlib.nullcontext()):
                reduce_params = {
                    "symbol": symbol,
                    "side": reduce_side,
                    "type": "MARKET",
                    "quantity": _fmt_num(qty),
                    "reduceOnly": "true",
                    "newOrderRespType": "RESULT",
                }
                result = await _signed(
                    "POST", "/fapi/v1/order",
                    _api_key, _api_secret,
                    params=reduce_params,
                    mode="testnet",
                )
                fill_price = float(result.get("avgPrice", exit_price))
                logger.info(
                    f"[AlgoBot] DCA reduce {strategy.position.type}: {symbol} -{qty} @ {fill_price} "
                    f"orderId={result.get('orderId')}"
                )

            realized_pnl = strategy.position.reduce_qty(qty, fill_price)
            fee = strategy.execution_model.exit_fee(strategy, qty, fill_price)
            realized_pnl -= fee

            pos_info = session["open_positions"].get(symbol, {})
            new_qty = strategy.position.qty
            pos_info["qty"] = str(new_qty)
            session["open_positions"][symbol] = pos_info

            _tr = build_trade_record(
                source="bot",
                executed_by=session.get("strategy_name", "unknown"),
                symbol=symbol,
                side=strategy.position.type,
                qty=str(qty),
                entry_price=str(pos_info.get("price", "0")),
                exit_price=str(fill_price),
                sl_order_price=None,
                tp_order_price=None,
                margin=None,
                liquidation_price=None,
                leverage=strategy.leverage,
                net_pnl=str(round(realized_pnl, 2)),
                pnl_pct=None,
                fee=str(round(fee, 2)) if fee else None,
                exit_reason="scale_out",
                user_id=session.get("user_id", ""),
                session_id=self.session_id,
                strategy_name=session.get("strategy_name"),
                entry_time=datetime.now(timezone.utc),
                exit_time=datetime.now(timezone.utc),
                entry_tag=adjust_tag or "",
                exit_tag="",
            )
            await record_trade(_tr)

            try:
                strategy.on_reduced_position((qty, fill_price))
            except Exception as e:
                logger.error(f"on_reduced_position error: {e}")

            await self.manager._notify_node(self.session_id, {
                "pnl": str(round(session["pnl"], 2)),
                "openPositions": list(session["open_positions"].keys()),
                "status": "running",
                "event": "position:adjust",
                "eventData": {
                    "symbol": symbol,
                    "qty": str(new_qty),
                    "reduceQty": str(qty),
                    "exitPrice": str(fill_price),
                    "adjustTag": adjust_tag,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            })
        except Exception as e:
            logger.error(f"[AlgoBot] DCA reduce failed for {symbol}: {e}")

    async def execute_exit(
        self, strategy, symbol: str, qty: float, exit_price: float, reason: str, time_t: datetime, index_t: int,
        high_t: float, low_t: float
    ) -> None:
        session = self.manager.sessions.get(self.session_id)
        if not session or strategy.position is None:
            return

        pos = strategy.position
        sl_price = strategy.stop_loss[1] if strategy.stop_loss else None
        tp_price = strategy.take_profit[1] if strategy.take_profit else None
        entry_time_str = session["open_positions"].get(symbol, {}).get("timestamp")
        entry_time = datetime.fromisoformat(entry_time_str.replace("Z", "+00:00")) if entry_time_str else datetime.now(timezone.utc)
        executed_by = session.get("strategy_name", "unknown")
        exit_time = datetime.now(timezone.utc)

        # Rate limiter check (A-003)
        rate_limiter = session.get("rate_limiter")
        if rate_limiter is not None and not rate_limiter.allow():
            logger.warning(f"[AlgoBot] {symbol}: exit rate limited, proceeding anyway")

        # F-003: Close position directly on Binance instead of routing
        # through Node.  Determines position side and sends a reduceOnly
        # MARKET order.
        #
        # Plan 5 Step 5.2 (ENG-2): the exchange is the source of truth for
        # whether this position actually closed and at what price.
        # - On any failure placing/confirming the close, we `return` before
        #   touching local position/PnL state — the position stays open and
        #   reconciliation is responsible for it, instead of silently
        #   fabricating a close event.
        # - On success, `exit_price` is overwritten with the REAL avgPrice
        #   from the fill (falling back to a direct order query if the
        #   immediate response didn't carry it) instead of the SL/TP
        #   trigger price / last candle close this function was called with.
        sem = self.manager._order_semaphores.get(self.session_id)
        client_order_id = f"enma_{self.session_id[:8]}_{symbol}_{uuid4_hex8()}"
        try:
            from services.binance_testnet import send_signed_request as _signed
            _api_key = session.get("api_key", "")
            _api_secret = session.get("api_secret", "")
            if not _api_key or not _api_secret:
                raise RuntimeError("Binance Testnet API credentials not configured")

            close_side = "SELL" if strategy.is_long else "BUY"
            async with (sem if sem else contextlib.nullcontext()):
                close_params = {
                    "symbol": symbol,
                    "side": close_side,
                    "type": "MARKET",
                    "quantity": _fmt_num(abs(pos.qty)),
                    "reduceOnly": "true",
                    "newOrderRespType": "RESULT",
                    "newClientOrderId": client_order_id,
                }
                order_result = await _signed(
                    "POST", "/fapi/v1/order",
                    _api_key, _api_secret,
                    params=close_params,
                    mode="testnet",
                )
            real_fill_price = _extract_fill_price(order_result)
            if real_fill_price is None:
                real_fill_price = await _query_real_fill_price(_api_key, _api_secret, symbol, client_order_id)
            if real_fill_price is None:
                # The order was accepted (no exception above) but no fill price
                # is discoverable — extremely unlikely for a MARKET order, but
                # fail loud rather than silently trusting the trigger estimate.
                logger.error(
                    f"[AlgoBot] {symbol}: close order {order_result.get('orderId')} accepted but no fill "
                    f"price found — booking with the trigger-price estimate ${exit_price}, flagged for reconciliation"
                )
            else:
                exit_price = real_fill_price
            logger.info(f"[AlgoBot] Testnet close-position filled for {symbol} reason={reason} @ {exit_price}")
        except Exception as e:
            logger.error(
                f"[AlgoBot] Testnet close-position FAILED for {symbol}: {e} — "
                f"position stays open locally, NOT booking a fabricated close"
            )
            await self.manager._notify_node(self.session_id, {
                "status": "running",
                "event": "close_failed",
                "eventData": {
                    "symbol": symbol,
                    "reason": reason,
                    "error": str(e),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            })
            return

        fee = strategy.execution_model.exit_fee(strategy, pos.qty, exit_price)
        pos.close(exit_price)
        realized_pnl = pos.pnl - fee
        strategy.balance += realized_pnl
        session["pnl"] += realized_pnl

        # Record trade close in protections (A-001)
        protection_manager = session.get("protection_manager")
        if protection_manager is not None:
            protection_manager.record_trade_close(
                pair=symbol,
                side=pos.type,
                exit_reason=reason,
                profit=realized_pnl,
                close_timestamp=exit_time.timestamp(),
            )

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
            user_id=session.get("user_id", ""),
            session_id=self.session_id,
            strategy_name=session.get("strategy_name"),
            entry_time=entry_time,
            exit_time=exit_time,
            entry_tag=strategy.entry_tag or "",
            exit_tag=strategy.exit_tag or "",
        )

        strategy.position = None
        strategy.stop_loss = None
        strategy.take_profit = None
        strategy._pending_flip = None
        session["open_positions"].pop(symbol, None)

        # Persist the trade record BEFORE notifying Node so the server's
        # per-symbol aggregation (computeSymbolStats) sees this closed trade.
        await record_trade(trade_record)

        await self.manager._notify_node(self.session_id, {
            "pnl": str(round(session["pnl"], 2)),
            "openPositions": list(session["open_positions"].keys()),
            "status": "running",
            "event": "position:close",
            "eventData": event_data,
        })

        logger.info(f"[AlgoBot] Position closed: {symbol} pnl={realized_pnl:.2f} reason={reason}")

    async def execute_flip(
        self, strategy, symbol: str, new_direction: str, new_qty: float, ref_price: float, time_t: datetime,
        index_t: int, high_t: float, low_t: float, stop_loss: float | None = None, take_profit: float | None = None
    ) -> bool:
        await self.execute_exit(
            strategy=strategy,
            symbol=symbol,
            qty=strategy.position.qty,
            exit_price=ref_price,
            reason="flip",
            time_t=time_t,
            index_t=index_t,
            high_t=high_t,
            low_t=low_t,
        )
        if strategy.position is not None:
            return False

        if new_qty <= 0:
            return False

        strategy.stop_loss = (new_qty, stop_loss) if stop_loss is not None else None
        strategy.take_profit = (new_qty, take_profit) if take_profit is not None else None

        success = await self.execute_entry(
            strategy=strategy,
            symbol=symbol,
            direction=new_direction,
            qty=new_qty,
            ref_price=ref_price,
            time_t=time_t,
            index_t=index_t,
        )
        return success


class LiveBotManager:
    def __init__(self):
        self.sessions: dict[str, dict] = {}
        self._stop_signals: dict[str, asyncio.Event] = {}
        self._tasks: dict[str, list[asyncio.Task]] = {}
        # Limit concurrent Binance testnet calls per session to avoid overwhelming
        # the testnet when many symbols fire signals on the same candle close.
        self._order_semaphores: dict[str, asyncio.Semaphore] = {}
        # Plan 5 Step 5.4 (ENG-3): the per-candle loop (reconcile -> check_exits
        # -> evaluate_and_route) and the user-data WS fill callback (_on_fill,
        # which also calls _reconcile_exchange_state) both mutate the same
        # strategy.position / session["pnl"] / session["open_positions"] state
        # and can interleave at any await point — a fill landing mid-candle-
        # loop is a real double-close/double-count race. One lock per
        # (session_id, symbol) serializes them.
        self._symbol_state_locks: dict[tuple[str, str], asyncio.Lock] = {}

    def _get_symbol_lock(self, session_id: str, symbol: str) -> asyncio.Lock:
        key = (session_id, symbol)
        lock = self._symbol_state_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._symbol_state_locks[key] = lock
        return lock

    async def start_session(self, session_config: dict) -> None:
        """Start a new live bot session. session_config from Node."""
        session_id = session_config["session_id"]
        strategy_name = session_config["strategy_name"]
        symbols = session_config.get("symbols", [])
        timeframe = session_config["timeframe"]
        params = session_config.get("params", {})
        risk_params = session_config.get("risk_params", {}) or {}
        user_id = session_config.get("user_id", "")
        api_key = session_config.get("api_key", "")
        api_secret = session_config.get("api_secret", "")

        # Resolve pairlist pipeline if symbols not explicitly provided (A-004)
        pairlist_config = risk_params.get("pairlist")
        if not symbols and pairlist_config:
            pairlist_pipeline = pairlist_from_config(pairlist_config)
            symbols = pairlist_pipeline.run(exchange="Binance Futures")
            logger.info(
                f"[AlgoBot] Session {session_id}: pairlist generated {len(symbols)} symbols "
                f"({pairlist_pipeline})"
            )

        if not symbols:
            logger.error(f"[AlgoBot] Session {session_id}: no symbols provided and pairlist yielded none")
            await self._notify_node(session_id, {
                "event": "log",
                "eventData": {"type": "error", "message": "No symbols available for session"},
            })
            return

        # Cross-symbol capital split owned by the Portfolio Model (Phase 3).
        # Default is an equal split (byte-identical to the former
        # capital/len(symbols)); a custom PortfolioModel can re-weight here.
        allocation = DefaultPortfolioModel().allocate(
            float(session_config["capital"]), symbols
        )
        leverage = int(session_config.get("leverage", 1))
        fee_rate = float(session_config.get("fee_rate", 0.0005))

        # Dynamic import of strategy class
        import importlib
        module = importlib.import_module(f"strategies.{strategy_name}")
        strategy_class = getattr(module, strategy_name)

        stop_event = asyncio.Event()
        self._stop_signals[session_id] = stop_event
        self._tasks[session_id] = []
        # Allow at most 2 concurrent Binance order calls per session
        self._order_semaphores[session_id] = asyncio.Semaphore(2)

        # Per-session user data stream with the user's own credentials
        uds = UserDataStreamManager(api_key=api_key, api_secret=api_secret)
        try:
            await uds.start()
            logger.info(f"[AlgoBot] Session {session_id}: user data stream started")
        except Exception as _uds_e:
            logger.warning(f"[AlgoBot] Session {session_id}: user data stream failed to start: {_uds_e}")

        # Setup protections stack (A-001) from risk_params config
        protection_manager = ProtectionManager()
        prot_cfg = risk_params.get("protections", {}) or {}
        cooldown_cfg = prot_cfg.get("cooldown_period", {})
        if cooldown_cfg.get("enabled", True):
            protection_manager.add(CooldownPeriod(cooldown_cfg))
        stoploss_cfg = prot_cfg.get("stoploss_guard", {})
        if stoploss_cfg.get("enabled", True):
            protection_manager.add(StoplossGuard(stoploss_cfg))

        # Order rate limiter (A-003): default 10 req/s per session
        rate_limit_cfg = risk_params.get("rate_limiting", {}) or {}
        rate_limiter = OrderRateLimiter(
            max_rate=int(rate_limit_cfg.get("max_rate", 10)),
            window_seconds=int(rate_limit_cfg.get("window_seconds", 1)),
        )

        self.sessions[session_id] = {
            "session_id": session_id,
            "user_id": user_id,
            "api_key": api_key,
            "api_secret": api_secret,
            "uds": uds,
            "strategy_name": strategy_name,
            "symbols": symbols,
            "timeframe": timeframe,
            "params": params,
            "capital": float(session_config["capital"]),
            "leverage": leverage,
            "risk_params": risk_params,
            "status": "running",
            "pnl": 0.0,
            "trading_state": "active",  # A-002: active/reducing/halted
            "protection_manager": protection_manager,  # A-001
            "rate_limiter": rate_limiter,  # A-003
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
        # Closes run with bounded concurrency (8 in flight) so a large Chaos
        # session (100+ symbols) can actually finish inside the timeout — a
        # fully serial loop (2 signed Binance calls per symbol) cannot. Wrapped
        # in a 120-second timeout so the stop can never hang indefinitely.
        all_symbols = session.get("symbols", [])
        unconfirmed_on_stop = []
        if all_symbols:
            close_semaphore = asyncio.Semaphore(8)

            async def _close_one(symbol):
                async with close_semaphore:
                    pos_info = session.get("open_positions", {}).get(symbol)
                    try:
                        confirmed = await self._close_position_on_stop(session_id, symbol, pos_info, session)
                        if not confirmed:
                            unconfirmed_on_stop.append(symbol)
                    except Exception as e:
                        logger.error(f"[AlgoBot] Error closing position {symbol}: {e}")
                        unconfirmed_on_stop.append(symbol)

            try:
                await asyncio.wait_for(
                    asyncio.gather(*(_close_one(s) for s in all_symbols)),
                    timeout=120.0,
                )
            except asyncio.TimeoutError:
                # Do NOT clear open_positions here — any symbol still present
                # may genuinely still be open on Binance. Reporting it as
                # closed when it isn't is what orphans real positions; the
                # periodic full-account reconciliation sweep is the backstop
                # for whatever this timeout leaves unconfirmed.
                logger.error(
                    f"[AlgoBot] Position close loop timed out for session {session_id} — "
                    f"{len(session.get('open_positions', {}))} symbol(s) still tracked as open"
                )

        if unconfirmed_on_stop:
            logger.error(
                f"[AlgoBot] Session {session_id}: {len(unconfirmed_on_stop)} symbol(s) "
                f"failed to confirm-close on stop, may still be open on Binance: {unconfirmed_on_stop}"
            )

        # Mark session as stopped — always reached even after timeout. Report
        # whatever open_positions actually still holds, never a blanket [] —
        # a wrong-but-confident empty list is worse than an honest non-empty one.
        session["status"] = "stopped"
        remaining_pnl = str(round(session["pnl"], 2))
        remaining_open = list(session.get("open_positions", {}).keys())

        await self._notify_node(session_id, {
            "pnl": remaining_pnl,
            "openPositions": remaining_open,
            "status": "stopped",
            "event": "stopped",
        })

        # Stop per-session user data stream
        _uds = session.get("uds")
        if _uds:
            try:
                await _uds.stop()
            except Exception as _e:
                logger.warning(f"[AlgoBot] Session {session_id}: UDS stop error: {_e}")

        # Cleanup
        self.sessions.pop(session_id, None)
        self._stop_signals.pop(session_id, None)
        self._tasks.pop(session_id, None)
        self._order_semaphores.pop(session_id, None)
        for _key in [k for k in self._symbol_state_locks if k[0] == session_id]:
            self._symbol_state_locks.pop(_key, None)

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
            "trading_state": session.get("trading_state", "active"),
        }

    async def set_trading_state(self, session_id: str, new_state: str) -> dict:
        """Set the trading state for a session (A-002)."""
        session = self.sessions.get(session_id)
        if not session:
            return {"success": False, "error": "Session not found"}
        if new_state not in TRADING_STATES:
            return {"success": False, "error": f"Invalid trading_state '{new_state}'. Must be one of: {', '.join(TRADING_STATES)}"}
        old_state = session.get("trading_state", "active")
        session["trading_state"] = new_state
        logger.info(f"[AlgoBot] Session {session_id}: trading_state {old_state} -> {new_state}")
        await self._notify_node(session_id, {
            "event": "log",
            "eventData": {"type": "info", "message": f"Trading state changed: {old_state} -> {new_state}"}
        })
        return {"success": True, "data": {"trading_state": new_state}}

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

        # Set user params on instance (F-015/F-016: reject out-of-range and unknown params)
        _strategy_params = getattr(strategy_class, "PARAMS", {})
        for key in params:
            if key not in _strategy_params:
                raise ValueError(
                    f"Unknown parameter '{key}'. "
                    f"Valid parameters for {strategy_class.__name__}: {list(_strategy_params.keys())}"
                )
        for key, meta in _strategy_params.items():
            raw_val = params.get(key, param_default(meta))
            try:
                typed_val = param_coerce(meta, raw_val)
            except (TypeError, ValueError):
                typed_val = raw_val
            param_validate(meta, typed_val)
            setattr(strategy, key, typed_val)

        # Inject risk model params (mirrors backtest_runner step 6b). Live
        # trading executes against real fills, so slippage_pct is left at the
        # BaseStrategy default — it only models simulated market-fill slippage.
        # Each per-symbol strategy gets its own slice of the session capital.
        _risk_all = risk_params or {}
        _risk = _risk_all.get(symbol) or _risk_all.get("default") or _risk_all
        
        # Enforce global risk hard-limits as a defensive floor (F-014)
        strategy.risk_pct          = min(_safe_float(_risk.get("risk_pct"),       strategy.risk_pct), 0.20)
        strategy.rrr               = _safe_float(_risk.get("rrr"),            strategy.rrr)
        strategy.liq_buffer_pct    = _safe_float(_risk.get("liq_buffer_pct"), strategy.liq_buffer_pct)
        strategy.max_session_dd    = min(_safe_float(_risk.get("max_session_dd"), strategy.max_session_dd), 0.90)
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

        # Clamp leverage defensively to absolute schema limit (125) (F-014)
        leverage = min(max(leverage, 1), 125)

        # Clamp requested leverage to what Binance actually allows for this symbol.
        # Uses the signed /fapi/v1/leverageBracket endpoint if credentials are
        # available via env (the live path always has them set in server/.env).
        api_key = session.get("api_key", "") if session else ""
        api_secret = session.get("api_secret", "") if session else ""
        effective_leverage = await clamp_leverage(
            leverage, "Binance Futures", symbol,
            api_key=api_key, api_secret=api_secret, mode="testnet",
        )

        # The leverageBracket probe above may have just confirmed this symbol is
        # rejected outright by demo-fapi (testnet exchangeInfo lists more symbols
        # than the testnet matching engine actually supports — see utils/symbols.py
        # _invalid_symbols). Abort now rather than opening a WS connection and
        # repeatedly hammering a doomed order every candle close.
        if is_symbol_invalid("Binance Futures", symbol):
            logger.warning(f"[AlgoBot] {symbol}: confirmed not tradable on this environment, skipping")
            await self._notify_node(session_id, {
                "event": "log",
                "eventData": {"type": "error", "message": f"{symbol}: not tradable on this environment — skipping"}
            })
            return

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

        # Register user data stream callback for event-driven fill detection
        # (F-020).  Triggers immediate reconciliation when an order fills
        # between candles — no need to wait for the next kline close.
        from services.binance_testnet import send_signed_request as _uds_signed
        _uds = session.get("uds") if session else None
        _fill_cb_registered = False
        if _uds and _uds._running:
            async def _on_fill(order_data: dict) -> None:
                symbol_s = order_data.get("s", "")
                if symbol_s != symbol:
                    return
                status = order_data.get("X", "")
                client_algo_id = order_data.get("clientOrderId", "") or order_data.get("i", "")
                logger.info(
                    f"[AlgoBot] {symbol}: user-data fill event — "
                    f"status={status} clientAlgoId={client_algo_id}"
                )

                # Plan 5 Step 5.4 (ENG-3): serialize against the per-candle
                # loop's reconcile/check_exits/evaluate_and_route block below —
                # both mutate strategy.position / session state and a fill
                # landing mid-candle-loop is a real double-close/double-count race.
                async with self._get_symbol_lock(session_id, symbol):
                    # ── F-019: OUO peer-cancel on partial/full fill ──────
                    # If a tracked algo order (tpsl_ prefix) is FILLED or
                    # PARTIALLY_FILLED, cancel the peer leg to prevent
                    # over-close on a reduced position.
                    if status in ("FILLED", "PARTIALLY_FILLED") and client_algo_id.startswith("tpsl_"):
                        _pos_info = session.get("open_positions", {}).get(symbol)
                        if _pos_info and "algo_ids" in _pos_info:
                            _aids = _pos_info["algo_ids"]
                            _peer_id = _aids.get("tp") if "sl" in client_algo_id else _aids.get("sl")
                            if _peer_id:
                                try:
                                    _api_key = session.get("api_key", "") if session else ""
                                    _api_secret = session.get("api_secret", "") if session else ""
                                    if _api_key and _api_secret:
                                        await _uds_signed(
                                            "DELETE", "/fapi/v1/algoOrder",
                                            _api_key, _api_secret,
                                            params={"symbol": symbol, "algoId": _peer_id},
                                            mode="testnet",
                                        )
                                        logger.info(
                                            f"[AlgoBot] {symbol}: cancelled peer algo {_peer_id} "
                                            f"(OUO — {client_algo_id} filled)"
                                        )
                                except Exception as _cancel_e:
                                    logger.warning(
                                        f"[AlgoBot] {symbol}: peer algo cancel failed: {_cancel_e}"
                                    )

                    await self._reconcile_exchange_state(
                        session_id, strategy, symbol,
                        candle_high=None, candle_low=None,
                    )
            _uds.register_fill_callback(symbol, _on_fill)
            _fill_cb_registered = True

        stop_event = self._stop_signals.get(session_id)
        # btcusdt@kline_1h  — Binance stream name format
        ws_symbol = symbol.lower()
        ws_url = f"wss://fstream.binancefuture.com/ws/{ws_symbol}@kline_{timeframe}"
        # Capped exponential backoff + full jitter (mirrors UserDataStreamManager
        # ._run_ws in services/user_data_stream.py). A Chaos session can hold ~80
        # symbols, each running this same loop — a flat retry delay would have
        # every symbol reconnect in lockstep on any shared gateway blip. Jitter
        # spreads reconnect attempts out so they don't all hit Binance at once.
        reconnect_backoff = 1

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
                        reconnect_backoff = 1  # Reset on successful connect
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

                            try:
                                # Two-phase contract (live): re-run the one-time
                                # vectorized prepare() on the rolling ≤500-candle
                                # window each closed candle, set index to the last
                                # row, then before() is a pure index lookup —
                                # identical indicator math to the backtest path,
                                # O(≤500) per candle (~once/hr), no drift.
                                strategy.index = len(strategy.candles) - 1
                                strategy.prepare(strategy.candles)

                                # Plan 5 Step 5.4 (ENG-3): serialize against
                                # _on_fill's reconcile call above — see its
                                # comment for why this lock exists.
                                async with self._get_symbol_lock(session_id, symbol):
                                    # Phase 5: Reconcile state with exchange BEFORE any decision
                                    # Unconditionally syncs positions AND open orders every loop.
                                    # Self-heals when engine wrongly believes it is flat (F-004),
                                    # reconciles open orders (F-002), and uses exchange data
                                    # as single source of truth (F-001).
                                    await self._reconcile_exchange_state(
                                        session_id, strategy, symbol,
                                        candle_high=candle[3], candle_low=candle[4],
                                    )

                                    # Setup execution algorithm if configured (A-016 parity with backtest path)
                                    exec_algo = None
                                    exec_algo_cfg = params.get("exec_algo") if isinstance(params, dict) else None
                                    if exec_algo_cfg and isinstance(exec_algo_cfg, dict):
                                        algo_type = exec_algo_cfg.get("type")
                                        algo_params = exec_algo_cfg.get("params", {})
                                        try:
                                            from core.models.exec_algo import TWAPAlgorithm, VWAPAlgorithm, IcebergAlgorithm
                                        except ImportError:
                                            from engine.core.models.exec_algo import TWAPAlgorithm, VWAPAlgorithm, IcebergAlgorithm

                                        if algo_type == "twap":
                                            exec_algo = TWAPAlgorithm(strategy, symbol, algo_params)
                                        elif algo_type == "vwap":
                                            exec_algo = VWAPAlgorithm(strategy, symbol, algo_params)
                                        elif algo_type == "iceberg":
                                            exec_algo = IcebergAlgorithm(strategy, symbol, algo_params)

                                    adapter = LiveAdapter(self, session_id)
                                    kernel = ExecutionKernel(adapter, exec_algo)
                                    time_t = datetime.fromtimestamp(candle[0] / 1000, tz=timezone.utc)

                                    await kernel.check_exits(
                                        strategy=strategy,
                                        symbol=symbol,
                                        candle=candle,
                                        is_live=True,
                                        index_t=strategy.index,
                                        time_t=time_t,
                                    )

                                    await kernel.evaluate_and_route(
                                        strategy=strategy,
                                        symbol=symbol,
                                        candle=candle,
                                        is_live=True,
                                        index_t=strategy.index,
                                        time_t=time_t,
                                    )
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
                    delay = random.uniform(0, reconnect_backoff)
                    logger.warning(
                        f"[AlgoBot] {symbol}: WS disconnected ({e}), reconnecting in {delay:.1f}s "
                        f"(backoff={reconnect_backoff}s)"
                    )
                    await self._notify_node(session_id, {
                        "event": "log",
                        "eventData": {"type": "error", "message": f"{symbol}: WS disconnected — reconnecting in {delay:.1f}s"}
                    })
                    await asyncio.sleep(delay)
                    reconnect_backoff = min(reconnect_backoff * 2, 60)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[AlgoBot] Unexpected error in symbol loop [{symbol}]: {e}")
        finally:
            if _fill_cb_registered:
                try:
                    _uds.unregister_fill_callback(symbol, _on_fill)
                except Exception:
                    pass


    async def _close_position_on_stop(
        self, session_id: str, symbol: str, _pos_info: dict | None, session: dict
    ) -> bool:
        """Force-close a position on Binance during session stop (F-003: direct).

        Called for every session symbol, not just those in open_positions, so
        that real Binance positions that the engine lost track of are still
        closed. Uses the engine's own Binance credentials — no Node hop.

        Returns True only if the symbol is confirmed flat on Binance after
        this call (no position existed, or the close order was accepted).
        Returns False on any failure — callers must NOT drop the symbol from
        open_positions tracking in that case, since it may still be open.
        """
        strategy = session.get("strategy_instances", {}).get(symbol)
        real_fill_price = None

        try:
            from services.binance_testnet import send_signed_request as _signed
            _api_key = session.get("api_key", "")
            _api_secret = session.get("api_secret", "")
            if not _api_key or not _api_secret:
                raise RuntimeError("Binance Testnet API credentials not configured")

            # Query current position on exchange to determine close side
            pos_data = await _signed(
                "GET", "/fapi/v2/positionRisk",
                _api_key, _api_secret,
                params={"symbol": symbol},
                mode="testnet",
            )
            position_amt = 0.0
            for p in (pos_data if isinstance(pos_data, list) else []):
                if p.get("symbol") == symbol:
                    position_amt = float(p.get("positionAmt", 0))
                    break

            if position_amt != 0:
                close_side = "SELL" if position_amt > 0 else "BUY"
                client_order_id = f"enma_{session_id[:8]}_{symbol}_{uuid4_hex8()}"
                close_params = {
                    "symbol": symbol,
                    "side": close_side,
                    "type": "MARKET",
                    "quantity": _fmt_num(abs(position_amt)),
                    "reduceOnly": "true",
                    "newOrderRespType": "RESULT",
                    "newClientOrderId": client_order_id,
                }
                order_result = await _signed(
                    "POST", "/fapi/v1/order",
                    _api_key, _api_secret,
                    params=close_params,
                    mode="testnet",
                )
                real_fill_price = _extract_fill_price(order_result)
                if real_fill_price is None:
                    real_fill_price = await _query_real_fill_price(_api_key, _api_secret, symbol, client_order_id)
                logger.info(f"[AlgoBot] Close-position filled for {symbol} on stop (amt={position_amt}) @ {real_fill_price}")
            else:
                logger.info(f"[AlgoBot] {symbol}: no position to close on stop")
        except Exception as e:
            logger.error(f"[AlgoBot] Close-position failed for {symbol} on stop: {e}")
            return False

        # Update local PnL tracking if the engine knew about this position
        if strategy and strategy.position:
            pos = strategy.position
            sl_price = strategy.stop_loss[1] if strategy.stop_loss else None
            tp_price = strategy.take_profit[1] if strategy.take_profit else None
            entry_time_str = session["open_positions"].get(symbol, {}).get("timestamp")
            entry_time = datetime.fromisoformat(entry_time_str.replace("Z", "+00:00")) if entry_time_str else datetime.now(timezone.utc)
            executed_by = session.get("strategy_name", "unknown")
            exit_time = datetime.now(timezone.utc)
            # Plan 5 Step 5.2 (ENG-2): real fill price when the exchange gave
            # us one; strategy.price (last candle close) only as a documented
            # last resort when the close order response never carried it.
            exit_price = real_fill_price if real_fill_price is not None else strategy.price
            if real_fill_price is None:
                logger.warning(f"[AlgoBot] {symbol}: no real fill price on stop-close, booking with last price ${exit_price}")

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
                user_id=session.get("user_id", ""),
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
        return True

    async def _reconcile_exchange_state(
        self, session_id: str, strategy, symbol: str,
        candle_high: float | None = None, candle_low: float | None = None,
    ) -> dict:
        """Unified state reconciliation (F-001/F-002/F-004).

        Queries Binance for the current position AND open orders on this symbol
        and reconciles the engine's local state to match exchange truth.  Runs
        unconditionally every loop (self-healing even when the engine wrongly
        believes it is flat).  Returns the reconciled state dict.

        Three cases handled:
          1. Exchange has a position but engine does not → restore it.
          2. Engine has a position but exchange does not → close locally,
             record trade with ``exchange_sync`` reason.
          3. Both have a position → update unrealised PnL from exchange mark
             price.
        """
        session = self.sessions.get(session_id)
        if not session:
            return {"position": None, "open_orders": []}

        # ── 1. Query exchange state directly (F-003: no Node hop) ────────────
        from services.binance_testnet import send_signed_request as _signed
        _api_key = session.get("api_key", "")
        _api_secret = session.get("api_secret", "")

        exchange_pos = None
        open_orders = []

        if _api_key and _api_secret:
            try:
                pos_data = await _signed(
                    "GET", "/fapi/v2/positionRisk",
                    _api_key, _api_secret,
                    params={"symbol": symbol},
                    mode="testnet",
                )
                if isinstance(pos_data, list):
                    for p in pos_data:
                        if p.get("symbol") == symbol:
                            exchange_pos = p
                            break
            except Exception as e:
                logger.warning(f"[AlgoBot] {symbol}: reconcile (position) failed — {e}")

            try:
                order_data = await _signed(
                    "GET", "/fapi/v1/openOrders",
                    _api_key, _api_secret,
                    params={"symbol": symbol},
                    mode="testnet",
                )
                if isinstance(order_data, list):
                    open_orders = order_data
                    # Also fetch algo orders (SL/TP)
                    try:
                        algo_orders = await _signed(
                            "GET", "/fapi/v1/openAlgoOrders",
                            _api_key, _api_secret,
                            params={"symbol": symbol},
                            mode="testnet",
                        )
                        if isinstance(algo_orders, list):
                            for ao in algo_orders:
                                normalized = {
                                    "orderId": ao.get("algoId"),
                                    "clientOrderId": ao.get("clientAlgoId"),
                                    "symbol": ao.get("symbol"),
                                    "type": ao.get("orderType"),
                                    "status": ao.get("orderStatus"),
                                    "stopPrice": ao.get("triggerPrice"),
                                    "origQty": ao.get("quantity"),
                                    "executedQty": "0",
                                    "side": ao.get("side"),
                                    "time": ao.get("createTime"),
                                }
                                open_orders.append(normalized)
                    except Exception:
                        pass
            except Exception as e:
                logger.warning(f"[AlgoBot] {symbol}: reconcile (orders) failed — {e}")

        # ── 2. Parse exchange data ──────────────────────────────────────────
        exchange_amt = 0.0
        exchange_entry = 0.0
        exchange_side = None
        exchange_unrealized_pnl = None
        exchange_mark_price = None
        exchange_leverage = None
        exchange_iso_wallet = None
        exchange_liq_price = None

        if exchange_pos:
            exchange_amt = float(exchange_pos.get("positionAmt", 0))
            if exchange_amt != 0:
                exchange_entry = float(exchange_pos.get("entryPrice", 0))
                exchange_side = "long" if exchange_amt > 0 else "short"
                # I-05: unRealizedProfit of 0.0 is legitimate (flat PnL) — keep it
                # as a number; only a missing/invalid value becomes None.
                exchange_unrealized_pnl = _safe_float(exchange_pos.get("unRealizedProfit"), None)
                # I-05: markPrice fallback chain (mark → cached last → engine last).
                # Do NOT coerce a missing key to 0.0 — that made price_missing dead.
                exchange_mark_price = _safe_float(exchange_pos.get("markPrice"), None)
                if exchange_mark_price is not None and exchange_mark_price <= 0:
                    exchange_mark_price = None
                if exchange_mark_price is None:
                    _tk = get_ticker_data("Binance Futures", symbol)
                    if _tk and _tk.get("lastPrice"):
                        exchange_mark_price = _tk.get("lastPrice")
                    elif getattr(strategy, "price", None):
                        exchange_mark_price = float(strategy.price)
                # I-07: exchange-truth leverage / isolated wallet / liq price for restore
                exchange_leverage = _safe_float(exchange_pos.get("leverage"), None)
                exchange_iso_wallet = _safe_float(exchange_pos.get("isolatedWallet"), None)
                exchange_liq_price = _safe_float(exchange_pos.get("liquidationPrice"), None)

        has_exchange_position = exchange_amt != 0
        has_local_position = strategy.position is not None

        # ── 3. Case 1 — position on exchange but not locally (recover) ──────
        if has_exchange_position and not has_local_position:
            logger.info(f"[AlgoBot] {symbol}: reconciled — restoring {exchange_side} position from exchange")
            # I-07: restore with exchange-truth leverage / isolated wallet so margin,
            # ROE and liquidation price are correct — not a bare qty/entry position
            # with leverage=1 and a liquidation price computed from nothing.
            _restored_lev = exchange_leverage if exchange_leverage and exchange_leverage > 0 else strategy.leverage
            strategy.position = Position(
                exchange_side, abs(exchange_amt), exchange_entry,
                leverage=_restored_lev,
                isolated_wallet=exchange_iso_wallet,
            )
            if exchange_liq_price and exchange_liq_price > 0:
                strategy.position.liquidation_price = exchange_liq_price

            # I-07: rebuild SL/TP brackets + algo_ids from the open algo orders so the
            # engine view is protected and the F-019 OUO peer-cancel can fire for a
            # restored position (it keys off algo_ids).
            restored_algo_ids = {"sl": None, "tp": None}
            for order in open_orders:
                _cid = str(order.get("clientOrderId") or "")
                _otype = str(order.get("type") or "").upper()
                _trigger = _safe_float(order.get("stopPrice"), None)
                if _trigger is None or _trigger <= 0:
                    continue
                is_sl = _cid.endswith("sl") or "STOP" in _otype
                is_tp = _cid.endswith("tp") or "TAKE_PROFIT" in _otype
                if is_tp:
                    strategy.take_profit = (abs(exchange_amt), _trigger)
                    restored_algo_ids["tp"] = order.get("orderId")
                elif is_sl:
                    strategy.stop_loss = (abs(exchange_amt), _trigger)
                    restored_algo_ids["sl"] = order.get("orderId")

            pos_info = {
                "symbol": symbol,
                "side": exchange_side,
                "qty": str(abs(exchange_amt)),
                "price": str(exchange_entry),
                "leverage": _restored_lev,
                "algo_ids": restored_algo_ids,
                "mark_price": str(exchange_mark_price) if exchange_mark_price is not None else None,
                "unrealized_pnl": str(round(exchange_unrealized_pnl, 2)) if exchange_unrealized_pnl is not None else None,
                "price_missing": exchange_mark_price is None,
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

        # ── 4. Case 2 — position locally but not on exchange (closed) ───────
        elif has_local_position and not has_exchange_position:
            logger.warning(f"[AlgoBot] {symbol}: reconciled — exchange has no position, closing local state")
            pos = strategy.position
            sl_price = strategy.stop_loss[1] if strategy.stop_loss else None
            tp_price = strategy.take_profit[1] if strategy.take_profit else None
            exit_time = datetime.now(timezone.utc)
            entry_time_str = session["open_positions"].get(symbol, {}).get("timestamp")
            entry_time = datetime.fromisoformat(entry_time_str.replace("Z", "+00:00")) if entry_time_str else exit_time

            # Plan 5 Step 5.2 (ENG-2): reconstruct the real close from
            # Binance's own trade history first — the candle/SL-TP guess
            # below is now a last-resort fallback, not the primary path.
            real_exit = None
            net_realized_pnl_from_exchange = None
            api_key = session.get("api_key", "")
            api_secret = session.get("api_secret", "")
            if api_key and api_secret:
                real_exit_result = await _query_real_exit_from_user_trades(api_key, api_secret, symbol, entry_time)
                if real_exit_result is not None:
                    real_exit, net_realized_pnl_from_exchange = real_exit_result

            if real_exit is not None:
                estimated_exit = real_exit
            else:
                logger.warning(f"[AlgoBot] {symbol}: no Binance trade history found for this close — falling back to candle/SL-TP estimate")
                estimated_exit = strategy.price
                if pos.type == "long":
                    if sl_price is not None and candle_low is not None and candle_low <= sl_price:
                        estimated_exit = sl_price
                    elif tp_price is not None and candle_high is not None and candle_high >= tp_price:
                        estimated_exit = tp_price
                else:
                    if sl_price is not None and candle_high is not None and candle_high >= sl_price:
                        estimated_exit = sl_price
                    elif tp_price is not None and candle_low is not None and candle_low <= tp_price:
                        estimated_exit = tp_price

            fee = strategy.execution_model.exit_fee(strategy, pos.qty, estimated_exit)
            pos.close(estimated_exit)
            # Prefer Binance's own realizedPnl (already net of its commission)
            # when we have it — it's the authoritative number, not our
            # recomputation from an average fill price.
            realized_pnl = net_realized_pnl_from_exchange if net_realized_pnl_from_exchange is not None else (pos.pnl - fee)
            strategy.balance += realized_pnl
            session["pnl"] += realized_pnl

            event_data = {
                "symbol": symbol,
                "pnl": str(round(realized_pnl, 2)),
                "exitPrice": str(estimated_exit),
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
                exit_price=str(estimated_exit),
                sl_order_price=str(sl_price) if sl_price is not None else None,
                tp_order_price=str(tp_price) if tp_price is not None else None,
                margin=str(pos.margin) if pos.margin else None,
                liquidation_price=str(pos.liquidation_price) if pos.liquidation_price else None,
                leverage=pos.leverage if pos.leverage else None,
                net_pnl=str(round(realized_pnl, 2)),
                pnl_pct=str(round(pos.pnl_pct, 2)) if pos.pnl_pct else None,
                fee=str(round(fee, 2)) if fee else None,
                exit_reason="exchange_sync",
                user_id=session.get("user_id", ""),
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

        # ── 5. Case 3 — both have a position: update PnL from exchange mark price ──
        elif has_local_position and has_exchange_position:
            if exchange_mark_price is not None:
                strategy.position.update_pnl(exchange_mark_price)

            # Update cached position info with exchange-truth data
            existing_info = session["open_positions"].get(symbol, {})
            existing_info["mark_price"] = str(exchange_mark_price) if exchange_mark_price is not None else existing_info.get("mark_price")
            existing_info["unrealized_pnl"] = str(round(exchange_unrealized_pnl, 2)) if exchange_unrealized_pnl is not None else existing_info.get("unrealized_pnl")
            existing_info["price_missing"] = exchange_mark_price is None
            if symbol in session["open_positions"]:
                session["open_positions"][symbol] = existing_info

        # ── 6. Check for orders filled on exchange that engine hasn't processed ──
        _tracked_algo_ids: dict[str, str | None] = {"sl": None, "tp": None}
        _pos_info_stored = session.get("open_positions", {}).get(symbol, {})
        if "algo_ids" in _pos_info_stored:
            _tracked_algo_ids = _pos_info_stored["algo_ids"]

        if open_orders and has_local_position and has_exchange_position:
            # ── F-019: OUO — find which tracked algo orders are still open ──
            _still_open_algo_ids: set[str] = set()
            for order in open_orders:
                order_status = order.get("status", "")
                _cid = order.get("clientOrderId", "")
                if _cid and (_cid.startswith("tpsl_") or _cid.startswith("oco_")):
                    if order_status in ("NEW", "PARTIALLY_FILLED"):
                        _still_open_algo_ids.add(order.get("orderId", ""))

                orig_qty = abs(float(order.get("origQty", 0)))
                executed_qty = abs(float(order.get("executedQty", 0)))
                order_type = order.get("type", "")

                if executed_qty > 0 and orig_qty > 0 and (order_status == "FILLED" or executed_qty >= orig_qty):
                    logger.info(f"[AlgoBot] {symbol}: detected filled order {order.get('orderId')} ({order_type}) on exchange")

            # If a tracked algo leg is no longer open, cancel its peer
            if has_exchange_position:
                for _leg, _id in _tracked_algo_ids.items():
                    if _id and _id not in _still_open_algo_ids:
                        _peer_leg = "tp" if _leg == "sl" else "sl"
                        _peer_id = _tracked_algo_ids.get(_peer_leg)
                        if _peer_id and _peer_id in _still_open_algo_ids:
                            try:
                                await _signed(
                                    "DELETE", "/fapi/v1/algoOrder",
                                    _api_key, _api_secret,
                                    params={"symbol": symbol, "algoId": _peer_id},
                                    mode="testnet",
                                )
                                logger.info(
                                    f"[AlgoBot] {symbol}: reconciled — cancelled peer algo "
                                    f"{_peer_id} ({_leg} triggered, OUO)"
                                )
                            except Exception as _re_cancel_e:
                                logger.warning(
                                    f"[AlgoBot] {symbol}: reconcile peer-cancel failed: {_re_cancel_e}"
                                )

        return {
            "position": {
                "has_position": has_exchange_position,
                "side": exchange_side,
                "qty": abs(exchange_amt),
                "entry_price": exchange_entry,
                "unrealized_pnl": exchange_unrealized_pnl,
                "mark_price": exchange_mark_price,
                "price_missing": has_exchange_position and exchange_mark_price is None,
            } if has_exchange_position else None,
            "open_orders": open_orders,
        }

    async def _push_stats(self, session_id: str) -> None:
        """Push periodic stats update to Node including exchange-truth position
        details with mark-price PnL (F-023/A-013)."""
        session = self.sessions.get(session_id)
        if not session:
            return
        total_pnl = sum(
            strat.position.pnl if strat.position else 0.0
            for strat in session.get("strategy_instances", {}).values()
        ) + session["pnl"]
        # Position details with exchange-truth data for the UI (F-023)
        position_details = {}
        for sym, info in session.get("open_positions", {}).items():
            strat = session.get("strategy_instances", {}).get(sym)
            pos_obj = strat.position if strat else None
            unrealized = info.get("unrealized_pnl")
            if unrealized is None and pos_obj is not None:
                unrealized = str(round(pos_obj.pnl, 2))
            position_details[sym] = {
                "side": info.get("side"),
                "qty": info.get("qty"),
                "price": info.get("price"),
                "leverage": info.get("leverage"),
                "mark_price": info.get("mark_price"),
                "unrealized_pnl": unrealized,
                "price_missing": info.get("price_missing", False) or (unrealized is None and pos_obj is not None),
            }
        await self._notify_node(session_id, {
            "pnl": str(round(total_pnl, 2)),
            "openPositions": list(session.get("open_positions", {}).keys()),
            "status": "running",
            "trading_state": session.get("trading_state", "active"),
            "positionDetails": position_details,
        })

    async def _notify_node(self, session_id: str, data: dict) -> None:
        """Send stats/event update to Node server via HTTP PATCH."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.patch(
                    f"{SERVER_URL}/internal/algo/sessions/{session_id}/stats",
                    json=data,
                    headers=_internal_headers(),
                )
        except Exception as e:
            logger.warning(f"[AlgoBot] Failed to notify Node for session {session_id}: {e}")

    async def _call_node_internal(self, session_id: str, path: str, body: dict) -> dict:
        """Call a Node internal endpoint and return parsed JSON response."""
        try:
            async with httpx.AsyncClient(timeout=45.0) as client:
                resp = await client.post(f"{SERVER_URL}{path}", json=body, headers=_internal_headers())
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


def _fmt_num(value: float) -> str:
    """Format a numeric value for Binance API (strip trailing zeros/dot)."""
    s = f"{value:.8f}".rstrip('0').rstrip('.')
    return s if s else '0'


def _extract_fill_price(order_result: dict) -> float | None:
    """Real avgPrice from a Binance order response, or None if unusable.

    Plan 5 Step 5.2 (ENG-2): the caller must NEVER fall back to a candle/
    trigger-price estimate silently — None here means "go query the order
    for its real fill," not "use the estimate and move on."
    """
    try:
        price = float(order_result.get("avgPrice", 0) or 0)
    except (TypeError, ValueError):
        return None
    return price if price > 0 else None


async def _query_real_fill_price(api_key: str, api_secret: str, symbol: str, client_order_id: str) -> float | None:
    """Fallback when the order response itself didn't carry a usable avgPrice
    (can happen if Binance processes the fill a beat after the ACK/RESULT
    response) — queries the order directly by its client id."""
    try:
        from services.binance_testnet import send_signed_request as _signed
        order = await _signed(
            "GET", "/fapi/v1/order",
            api_key, api_secret,
            params={"symbol": symbol, "origClientOrderId": client_order_id},
            mode="testnet",
        )
        return _extract_fill_price(order)
    except Exception as e:
        logger.error(f"[AlgoBot] {symbol}: fill-price re-query failed: {e}")
        return None


async def _query_real_exit_from_user_trades(
    api_key: str, api_secret: str, symbol: str, entry_time: datetime,
) -> tuple[float, float] | None:
    """Plan 5 Step 5.2 (ENG-2): reconstruct a close the engine didn't itself
    execute (SL/TP fired exchange-side, or state drifted) from Binance's own
    trade history instead of guessing from candle/SL/TP levels.

    Returns (avg_exit_price, net_realized_pnl) — net_realized_pnl is
    Binance's own realizedPnl minus its own commission for the matched
    fills, i.e. already the authoritative post-fee number — or None if no
    matching fills are found.
    """
    try:
        from services.binance_testnet import send_signed_request as _signed
        trades = await _signed(
            "GET", "/fapi/v1/userTrades",
            api_key, api_secret,
            params={"symbol": symbol, "limit": 20},
            mode="testnet",
        )
    except Exception as e:
        logger.error(f"[AlgoBot] {symbol}: userTrades query failed: {e}")
        return None

    if not isinstance(trades, list) or not trades:
        return None

    entry_ms = entry_time.timestamp() * 1000
    relevant = [t for t in trades if _safe_float(t.get("time"), 0) >= entry_ms]
    if not relevant:
        # Clock skew or an entry_time we don't fully trust — best-effort fall
        # back to the most recent fills rather than finding nothing.
        relevant = trades[-3:]

    total_qty = sum(abs(_safe_float(t.get("qty"), 0)) for t in relevant)
    if total_qty <= 0:
        return None

    avg_price = sum(_safe_float(t.get("price"), 0) * abs(_safe_float(t.get("qty"), 0)) for t in relevant) / total_qty
    total_realized_pnl = sum(_safe_float(t.get("realizedPnl"), 0) for t in relevant)
    total_commission = sum(_safe_float(t.get("commission"), 0) for t in relevant)
    return avg_price, total_realized_pnl - total_commission


def uuid4_hex8() -> str:
    """Return the first 8 hex chars of a random UUID — short unique prefix."""
    return uuid4().hex[:8]


# Singleton instance
live_bot_manager = LiveBotManager()
