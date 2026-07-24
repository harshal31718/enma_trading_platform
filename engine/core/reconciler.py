"""Exchange-truth reconciliation, algo-order cancel/amend, and Session Risk
Governor breach application for live sessions.

Extracted from `LiveBotManager` (Plan 6 Step 6.1, ENG-1) as a behavior-
preserving move — see golden-master before/after comparison in
`workspace/plan/6_engine-decomposition-and-exchange-abstraction.md`.

Still holds one real coupling back to `LiveBotManager` (`self._manager`),
used ONLY to construct a `LiveAdapter` for the naked-position force-close
path inside `reconcile_exchange_state` (A-7). Fully severing this is Step
6.4's job (inject an adapter factory instead of a raw manager reference) —
out of scope for this mechanical extraction, documented rather than hidden.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from decimal import ROUND_DOWN, ROUND_UP

from core.position import Position
from core.money import add_money
from core.exchange import Exchange, BinanceFuturesTestnet
from services.trade_recorder import record_trade, build_trade_record
from services.event_log import append_event
from utils.symbols import round_price, get_ticker_data, enforce_min_trigger_distance

logger = logging.getLogger(__name__)


def _resolve_exchange(session: dict) -> Exchange:
    """Plan 6 Step 6.2 (ENG-4): every method below used to hardcode
    `mode="testnet"` on each `send_signed_request` call — this resolves the
    session's own `Exchange` instance instead (set once in `start_session`),
    falling back to `BinanceFuturesTestnet()` for sessions/tests that don't
    carry one (defensive default, matches today's only-ever-testnet reality
    exactly — mainnet selection is a separate, later product gate)."""
    return session.get("exchange") or BinanceFuturesTestnet()


class Reconciler:
    """Reconciles local session/position state against Binance exchange
    truth, cancels/amends resting SL/TP algo orders, and applies Session
    Risk Governor breach verdicts."""

    def __init__(self, registry, notifier, manager):
        self._registry = registry
        self._notifier = notifier
        # Only used to construct a LiveAdapter for the naked-position
        # force-close path — see module docstring.
        self._manager = manager

    async def cancel_symbol_algo_orders(
        self, session: dict, symbol: str, algo_ids: dict | None = None,
    ) -> None:
        """Plan 21 Step 21.3 (A-4/A-5): cancel every resting SL/TP conditional
        (`/fapi/v1/algoOrder`) order for *symbol* after any close.

        These brackets are placed with `closePosition:"true"` — a stale
        trigger left armed after a close will market-close *whatever
        position exists on that symbol later*: the same session re-entering,
        a later bot session on the same symbol, or a user manually trading
        it once the Redis lock releases. This is a wrong-money-outcome bug,
        not hygiene, and industry-standard (freqtrade cancels the exchange
        stoploss on every exit; nautilus ties bracket lifecycle to the
        position via `ContingencyType`).

        Call from every close path: `execute_exit` success, session-stop
        close, the F-018 emergency-exit path, and reconcile Case 2 (the
        exchange-side SL/TP-fired case, where the WS/reconcile OUO
        peer-cancel structurally can't fire — see A-5).

        If *algo_ids* (the `{"sl": id, "tp": id}` dict this engine tracked
        for the position, from `session["open_positions"][symbol]
        ["algo_ids"]`) is given and has at least one id, cancel exactly
        those — no extra Binance call. Otherwise fall back to
        `GET /fapi/v1/openAlgoOrders` for the symbol and cancel everything
        found, so untracked/orphaned brackets (a restored position, a
        session-stop close on a symbol the engine never fully tracked)
        don't survive either.

        Best-effort: failures are logged, never raised. The position this
        bracket protected is already closed by the time this runs, so a
        cancel failure here is a "loose resting order" alert, not a reason
        to fail the close that triggered it. An already-triggered/expired
        id failing to cancel is an expected, common case (e.g. the peer leg
        already died via OUO peer-cancel) — not worth a warning-level log.
        """
        from core.live_bot_manager import (
            _binance_error_detail, _classify_exchange_sync_exit_reason, _extract_fill_price,
            _fmt_num, _make_client_id, _query_real_exit_from_user_trades, _query_real_fill_price,
            _safe_float, uuid4_hex8, _NAKED_POSITION_MAX_REARM_ATTEMPTS,
        )
        api_key = session.get("api_key", "")
        api_secret = session.get("api_secret", "")
        if not api_key or not api_secret:
            return

        exchange = _resolve_exchange(session)

        ids_to_cancel: list[str] = []
        if algo_ids:
            ids_to_cancel = [str(v) for v in algo_ids.values() if v]

        if not ids_to_cancel:
            try:
                open_algo = await exchange.query_open_algo_orders(
                    api_key, api_secret, params={"symbol": symbol},
                )
                if isinstance(open_algo, list):
                    ids_to_cancel = [str(ao.get("algoId")) for ao in open_algo if ao.get("algoId")]
            except Exception as e:
                logger.warning(
                    f"[AlgoBot] {symbol}: openAlgoOrders lookup for post-close bracket "
                    f"cleanup failed — {_binance_error_detail(e)}"
                )
                return

        for algo_id in ids_to_cancel:
            try:
                await exchange.cancel_algo_order(
                    api_key, api_secret, params={"symbol": symbol, "algoId": algo_id},
                )
                logger.info(f"[AlgoBot] {symbol}: cancelled resting algo order {algo_id} after close")
            except Exception as e:
                logger.info(
                    f"[AlgoBot] {symbol}: algo order {algo_id} cancel skipped (likely already "
                    f"gone) — {_binance_error_detail(e)}"
                )

    async def maybe_amend_exchange_sl(
        self, session: dict, session_id: str, strategy, symbol: str,
    ) -> None:
        """M-4 fix (Plan 21.4): cancel+replace the resting exchange SL algo
        order when the risk model's maintain path (`DefaultExecution.route()`
        Path 5, `engine/core/models/execution.py` — shared with backtest, NOT
        touched by this fix) tightens `strategy.stop_loss` — trailing stops,
        breakeven moves, Chandelier exits. Previously the tightened value
        was written to `strategy.stop_loss` LOCALLY ONLY; the exchange-side
        `closePosition:"true"` STOP_MARKET order stayed at its ORIGINAL,
        widest trigger for the position's entire life. Between candles, only
        the stale wide stop protected the position on Binance — real
        enforcement of the tightened stop was entirely the engine's own
        candle-close wick check (`kernel.check_exits`), up to one candle
        late, and it market-closes while the stale conditional stays armed
        (compounding A-4/A-5's hazard class). Industry pattern (freqtrade
        `stoploss_on_exchange` adjustment): amend the exchange stop on every
        tighten ≥ 1 tick.

        Deliberately live-only — this method is called from
        `_run_symbol_loop` after `kernel.evaluate_and_route()`, never from
        the backtest path, so it cannot affect backtest outputs (no
        golden-master re-baseline needed, matching the rest of Plan 21).

        No-ops if there's no open position, no `stop_loss`, or the stop
        hasn't tightened since the last amend (tracked via
        `open_positions[symbol]["armed_sl_price"]` — direction-aware: a
        higher SL is a tighten for longs, a lower SL is a tighten for
        shorts; anything else, including a widening, is left alone since the
        risk model's own stop-tightening logic (e.g. AtrBracketRiskModel's
        RiskConstraints, consumed by route()) is documented to only ever
        tighten, never loosen).
        """
        from core.live_bot_manager import (
            _binance_error_detail, _classify_exchange_sync_exit_reason, _extract_fill_price,
            _fmt_num, _make_client_id, _query_real_exit_from_user_trades, _query_real_fill_price,
            _safe_float, uuid4_hex8, _NAKED_POSITION_MAX_REARM_ATTEMPTS,
        )
        # Plan 6 Step 6.3 phase (d3): read from active_bracket (persisted by
        # route()/kernel every candle) instead of strategy.stop_loss directly
        # — this method runs from _run_symbol_loop AFTER kernel.evaluate_and_
        # route() for this same candle, so active_bracket already reflects
        # whatever route() just wrote, same as strategy.stop_loss would.
        if (
            strategy.position is None or not strategy.position.is_open
            or strategy.active_bracket is None or strategy.active_bracket.stop_loss is None
        ):
            return

        pos_info = session.get("open_positions", {}).get(symbol)
        if not pos_info:
            return

        new_sl_price = strategy.active_bracket.stop_loss
        if new_sl_price is None:
            return

        armed_sl_price = _safe_float(pos_info.get("armed_sl_price"), None)
        if armed_sl_price is None:
            # Nothing recorded yet (session just started, or the first pass
            # after a Case-1 restore) — the entry-time placement or the
            # restore is already the armed order; record the baseline
            # without amending anything.
            pos_info["armed_sl_price"] = str(new_sl_price)
            session["open_positions"][symbol] = pos_info
            return

        is_long = strategy.position.type == "long"
        tightened = (new_sl_price > armed_sl_price) if is_long else (new_sl_price < armed_sl_price)
        if not tightened:
            return

        api_key = session.get("api_key", "")
        api_secret = session.get("api_secret", "")
        if not api_key or not api_secret:
            return

        exchange = _resolve_exchange(session)

        sl_rounding = ROUND_DOWN if is_long else ROUND_UP
        # Same -2021 "would immediately trigger" guard execute_entry applies
        # at entry time — a trail/breakeven tighten can land the new stop
        # too close to the current price too, and this is the amend path's
        # own live-only order submission, see enforce_min_trigger_distance.
        if strategy.price and strategy.price > 0:
            new_sl_price = enforce_min_trigger_distance(new_sl_price, strategy.price, is_below=is_long)
        rounded_sl = round_price(symbol, "Binance Futures", new_sl_price, rounding=sl_rounding)
        if rounded_sl is None:
            return

        old_algo_ids = dict(pos_info.get("algo_ids") or {})
        old_sl_id = old_algo_ids.get("sl")

        try:
            # closePosition:"true" conditional orders don't support amend-
            # in-place — cancel+replace is the only path. Cancel first; if
            # the old id is already gone (e.g. it triggered right before we
            # got here) that's fine, proceed to place the new one anyway.
            if old_sl_id:
                try:
                    await exchange.cancel_algo_order(
                        api_key, api_secret, params={"symbol": symbol, "algoId": old_sl_id},
                    )
                except Exception as _cancel_e:
                    logger.info(
                        f"[AlgoBot] {symbol}: old SL {old_sl_id} cancel-before-amend "
                        f"skipped (likely already gone) — {_binance_error_detail(_cancel_e)}"
                    )

            close_side = "SELL" if is_long else "BUY"
            result = await exchange.place_algo_order(
                api_key, api_secret,
                params={
                    "algoType": "CONDITIONAL",
                    "symbol": symbol,
                    "side": close_side,
                    "type": "STOP_MARKET",
                    "triggerPrice": _fmt_num(rounded_sl),
                    "workingType": "MARK_PRICE",
                    "closePosition": "true",
                    "clientAlgoId": f"tpsl_{uuid4_hex8()}_sl",
                },
            )
            old_algo_ids["sl"] = result.get("algoId")
            pos_info["algo_ids"] = old_algo_ids
            pos_info["armed_sl_price"] = str(rounded_sl)
            session["open_positions"][symbol] = pos_info
            logger.info(
                f"[AlgoBot] {symbol}: exchange SL amended (tighten) "
                f"{armed_sl_price} -> {rounded_sl} algoId={result.get('algoId')}"
            )
        except Exception as e:
            logger.warning(
                f"[AlgoBot] {symbol}: exchange SL amend-on-tighten failed — "
                f"{_binance_error_detail(e)} (engine-side candle-close wick-check "
                f"remains as fallback protection until the next successful amend)"
            )

    async def close_position_on_stop(
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
        from core.live_bot_manager import (
            _binance_error_detail, _classify_exchange_sync_exit_reason, _extract_fill_price,
            _fmt_num, _make_client_id, _query_real_exit_from_user_trades, _query_real_fill_price,
            _safe_float, uuid4_hex8, _NAKED_POSITION_MAX_REARM_ATTEMPTS,
        )
        strategy = session.get("strategy_instances", {}).get(symbol)
        real_fill_price = None

        try:
            exchange = _resolve_exchange(session)
            _api_key = session.get("api_key", "")
            _api_secret = session.get("api_secret", "")
            if not _api_key or not _api_secret:
                raise RuntimeError("Binance Testnet API credentials not configured")

            # Query current position on exchange to determine close side
            pos_data = await exchange.query_position_risk(
                _api_key, _api_secret, params={"symbol": symbol},
            )
            position_amt = 0.0
            for p in (pos_data if isinstance(pos_data, list) else []):
                if p.get("symbol") == symbol:
                    position_amt = float(p.get("positionAmt", 0))
                    break

            if position_amt != 0:
                close_side = "SELL" if position_amt > 0 else "BUY"
                client_order_id = _make_client_id(session_id, symbol)
                close_params = {
                    "symbol": symbol,
                    "side": close_side,
                    "type": "MARKET",
                    "quantity": _fmt_num(abs(position_amt)),
                    "reduceOnly": "true",
                    "newOrderRespType": "RESULT",
                    "newClientOrderId": client_order_id,
                }
                order_result = await exchange.place_order(_api_key, _api_secret, close_params)
                real_fill_price = _extract_fill_price(order_result)
                if real_fill_price is None:
                    real_fill_price = await _query_real_fill_price(
                        _api_key, _api_secret, symbol, client_order_id, exchange=exchange,
                    )
                logger.info(f"[AlgoBot] Close-position filled for {symbol} on stop (amt={position_amt}) @ {real_fill_price}")
            else:
                logger.info(f"[AlgoBot] {symbol}: no position to close on stop")
        except Exception as e:
            logger.error(f"[AlgoBot] Close-position failed for {symbol} on stop: {_binance_error_detail(e)}")
            return False

        # Update local PnL tracking if the engine knew about this position
        if strategy and strategy.position:
            pos = strategy.position
            # Plan 6 Step 6.3 phase (d3): active_bracket instead of the
            # mutable tuples — see maybe_amend_exchange_sl's comment above.
            _ab = strategy.active_bracket
            sl_price = _ab.stop_loss if _ab else None
            tp_price = _ab.take_profit if _ab else None
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
            strategy.balance = add_money(strategy.balance, realized_pnl)
            session["pnl"] = add_money(session["pnl"], realized_pnl)
            if session.get("risk_governor") is not None:
                session["risk_governor"].record_realized_pnl(realized_pnl, datetime.now(timezone.utc))

            # Plan 22 Step 22.3: a session-stop force-close is a deliberate
            # user action, not a stoploss — CooldownPeriod still applies (the
            # symbol shouldn't be immediately re-entered by a fresh session),
            # but this never counts toward StoplossGuard's tally (exit_reason
            # "session_stop" isn't in its tracked set).
            _protection_manager_s = session.get("protection_manager")
            if _protection_manager_s is not None:
                _protection_manager_s.record_trade_close(
                    pair=symbol, side=pos.type, exit_reason="session_stop",
                    profit=realized_pnl, close_timestamp=exit_time.timestamp(),
                )

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
            await append_event(
                session_id=session_id, symbol=symbol, event_type="fill",
                payload={"side": "exit", "qty": pos.qty, "price": exit_price, "realizedPnl": realized_pnl, "reason": "session_stop"},
            )

        # A-4 fix (Plan 21.3): cancel any resting SL/TP brackets for this
        # symbol before dropping local tracking — called for every session
        # symbol (not just ones the engine still tracked), so pass tracked
        # ids if we have them (cheap) and let the helper fall back to
        # discovering + cancelling untracked ones otherwise.
        await self.cancel_symbol_algo_orders(
            session, symbol, (_pos_info or {}).get("algo_ids"),
        )

        session["open_positions"].pop(symbol, None)
        return True

    async def _get_batched_reconcile_snapshot(
        self, session: dict, wave_key: int, exchange: Exchange, api_key: str, api_secret: str,
    ) -> tuple[bool, dict, dict]:
        """Plan 21 Step 21.5c (A-9c): one un-parametered `positionRisk` +
        `openOrders` + `openAlgoOrders` call per session per candle wave,
        shared by every symbol's `reconcile_exchange_state` call for that
        wave, instead of each symbol paying for its own per-symbol calls.

        Confirmed against Binance's own docs before implementing (not
        assumed): `positionRisk` is a FLAT weight-5 call regardless of
        whether `symbol` is given — batching it is a pure win, N calls of
        weight 5 collapse to one. `openOrders`/`openAlgoOrders` are weight 1
        per-symbol but weight 40 when `symbol` is omitted — batching only
        nets a win once a session has enough symbols that
        `7*N > 5+40+40=85`, i.e. **N > ~13 symbols**. That's exactly this
        step's own stated target ("the big weight win for Chaos runs"), not
        small manual sessions — this is a deliberate, session-wide batch
        call, not a universally cheaper one.

        `wave_key` is the closed candle's own open-time in ms
        (`int(candle[0])`) — identical across every symbol in a session
        since they all share one `timeframe`, so it's a natural, free
        cache key with no extra coordination needed. Cached per session in
        `session["_reconcile_batch"]`; a per-session `asyncio.Lock` ensures
        that when many symbol tasks arrive for the same wave at once, only
        the first one actually calls Binance — the rest await the same
        in-flight fetch instead of triggering their own redundant batch call
        (which would defeat the whole point).

        Returns `(position_query_ok, positions_by_symbol, orders_by_symbol)`
        — `position_query_ok` mirrors A-15's per-call flag: True only if the
        batched `positionRisk` call itself succeeded, so a symbol absent
        from a successful batch is genuinely flat (safe for Case 2), while a
        failed batch leaves every symbol's `position_query_ok=False` (Case 2
        must not fire on an unconfirmed query, same invariant as the
        per-symbol path).
        """
        if "_reconcile_batch" not in session:
            session["_reconcile_batch"] = {
                "wave_key": None, "position_query_ok": False,
                "positions": {}, "orders": {}, "lock": asyncio.Lock(),
            }
        batch = session["_reconcile_batch"]

        if batch["wave_key"] == wave_key:
            return batch["position_query_ok"], batch["positions"], batch["orders"]

        async with batch["lock"]:
            # Re-check: another symbol's task may have already fetched this
            # exact wave while we were waiting for the lock.
            if batch["wave_key"] == wave_key:
                return batch["position_query_ok"], batch["positions"], batch["orders"]

            position_query_ok = False
            positions_by_symbol: dict = {}
            orders_by_symbol: dict = {}

            try:
                pos_data = await exchange.query_position_risk(api_key, api_secret, params={})
                position_query_ok = True
                if isinstance(pos_data, list):
                    for p in pos_data:
                        _sym = p.get("symbol")
                        if _sym:
                            positions_by_symbol[_sym] = p
            except Exception as e:
                logger.warning(f"[AlgoBot] batched reconcile (wave={wave_key}): positionRisk (all symbols) failed — {e}")

            try:
                order_data = await exchange.query_open_orders(api_key, api_secret, params={})
                if isinstance(order_data, list):
                    for o in order_data:
                        _sym = o.get("symbol")
                        if _sym:
                            orders_by_symbol.setdefault(_sym, []).append(o)
                    try:
                        algo_orders = await exchange.query_open_algo_orders(api_key, api_secret, params={})
                        if isinstance(algo_orders, list):
                            for ao in algo_orders:
                                _sym = ao.get("symbol")
                                if not _sym:
                                    continue
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
                                orders_by_symbol.setdefault(_sym, []).append(normalized)
                    except Exception:
                        pass
            except Exception as e:
                logger.warning(f"[AlgoBot] batched reconcile (wave={wave_key}): openOrders (all symbols) failed — {e}")

            batch["wave_key"] = wave_key
            batch["position_query_ok"] = position_query_ok
            batch["positions"] = positions_by_symbol
            batch["orders"] = orders_by_symbol
            return position_query_ok, positions_by_symbol, orders_by_symbol

    async def reconcile_exchange_state(
        self, session_id: str, strategy, symbol: str,
        candle_high: float | None = None, candle_low: float | None = None,
        wave_key: int | None = None,
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

        Plan 21 Step 21.5c (A-9c): pass ``wave_key`` (the closed candle's own
        open-time in ms) from the routine per-candle-close call site to use
        one session-wide batched query (shared across every symbol closing
        that same candle) instead of this symbol's own 3 signed calls — see
        `_get_batched_reconcile_snapshot`. Event-driven call sites (`_on_fill`,
        `_on_account_update`) deliberately omit it — they need this symbol's
        state fresh, not a wave-cached snapshot possibly seconds old, and are
        rare/per-symbol by nature so batching wouldn't save anything anyway.
        """
        from core.live_bot_manager import (
            _binance_error_detail, _classify_exchange_sync_exit_reason, _extract_fill_price,
            _fmt_num, _make_client_id, _query_real_exit_from_user_trades, _query_real_fill_price,
            _safe_float, uuid4_hex8, _NAKED_POSITION_MAX_REARM_ATTEMPTS,
        )
        session = self._registry.sessions.get(session_id)
        if not session:
            return {"position": None, "open_orders": []}

        # ── 1. Query exchange state directly (F-003: no Node hop) ────────────
        exchange = _resolve_exchange(session)
        _api_key = session.get("api_key", "")
        _api_secret = session.get("api_secret", "")

        exchange_pos = None
        open_orders = []
        # A-15 fix (Plan 21.5): Case 2 below ("exchange has no position, close
        # locally") must only fire when we actually CONFIRMED the exchange is
        # flat — not whenever the positionRisk query merely failed (network
        # blip, timeout, or the new A-9 backpressure defer). Before this flag,
        # ANY query failure defaulted exchange_amt to 0.0, which Case 2 read as
        # "confirmed closed" and fabricated a real close on a position that may
        # still be open. Extends Plan 5.2 / A-6's real-fills-not-fabricated-
        # closes invariant to the query-failure case.
        position_query_ok = False

        if _api_key and _api_secret:
            if wave_key is not None:
                # Plan 21 Step 21.5c: session-wide batched snapshot for this
                # candle wave — see `_get_batched_reconcile_snapshot`'s
                # docstring for the weight math and the position_query_ok
                # semantics this mirrors exactly.
                try:
                    position_query_ok, _positions_by_symbol, _orders_by_symbol = (
                        await self._get_batched_reconcile_snapshot(
                            session, wave_key, exchange, _api_key, _api_secret,
                        )
                    )
                    exchange_pos = _positions_by_symbol.get(symbol)
                    open_orders = list(_orders_by_symbol.get(symbol, []))
                except Exception as e:
                    logger.warning(f"[AlgoBot] {symbol}: batched reconcile (wave={wave_key}) failed — {e}")
            else:
                try:
                    pos_data = await exchange.query_position_risk(
                        _api_key, _api_secret, params={"symbol": symbol},
                    )
                    position_query_ok = True
                    if isinstance(pos_data, list):
                        for p in pos_data:
                            if p.get("symbol") == symbol:
                                exchange_pos = p
                                break
                except Exception as e:
                    logger.warning(f"[AlgoBot] {symbol}: reconcile (position) failed — {e}")

                try:
                    order_data = await exchange.query_open_orders(
                        _api_key, _api_secret, params={"symbol": symbol},
                    )
                    if isinstance(order_data, list):
                        open_orders = order_data
                        # Also fetch algo orders (SL/TP)
                        try:
                            algo_orders = await exchange.query_open_algo_orders(
                                _api_key, _api_secret, params={"symbol": symbol},
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
            reconcile_seq = await append_event(
                session_id=session_id, symbol=symbol, event_type="reconcile_adjustment",
                payload={"nowOpen": True, "qty": abs(exchange_amt), "price": exchange_entry, "reason": "exchange_had_position_engine_did_not"},
            )
            await self._notifier.notify(session_id, {
                "pnl": str(round(session["pnl"], 2)),
                "openPositions": list(session["open_positions"].keys()),
                "status": "running",
                "seq": reconcile_seq,
                "event": "position:open",
                "eventData": pos_info,
            })

        # ── 4. Case 2 — position locally but not on exchange (closed) ───────
        # A-15: gated on position_query_ok — an unconfirmed (failed/deferred)
        # positionRisk query must never fabricate a close (see the flag's
        # definition above in step 1).
        elif has_local_position and not has_exchange_position and position_query_ok:
            logger.warning(f"[AlgoBot] {symbol}: reconciled — exchange has no position, closing local state")
            pos = strategy.position
            # Plan 6 Step 6.3 phase (d3): active_bracket instead of the
            # mutable tuples — see maybe_amend_exchange_sl's comment above.
            _ab = strategy.active_bracket
            sl_price = _ab.stop_loss if _ab else None
            tp_price = _ab.take_profit if _ab else None
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
                real_exit_result = await _query_real_exit_from_user_trades(
                    api_key, api_secret, symbol, entry_time, exchange=exchange,
                )
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
            strategy.balance = add_money(strategy.balance, realized_pnl)
            session["pnl"] = add_money(session["pnl"], realized_pnl)
            if session.get("risk_governor") is not None:
                session["risk_governor"].record_realized_pnl(realized_pnl, exit_time)

            # Plan 22 Step 22.3: feed protections (A-001) from this path too —
            # see _classify_exchange_sync_exit_reason's docstring for why this
            # matters more since A-13 (exchange brackets are now the sole
            # trigger while armed, so most real stoploss closes land here).
            # Internal classification only; the outward notification below
            # keeps the generic "exchange_sync" label unchanged.
            _protection_manager_r = session.get("protection_manager")
            if _protection_manager_r is not None:
                _inferred_reason = _classify_exchange_sync_exit_reason(estimated_exit, sl_price, tp_price)
                _protection_manager_r.record_trade_close(
                    pair=symbol, side=pos.type, exit_reason=_inferred_reason,
                    profit=realized_pnl, close_timestamp=exit_time.timestamp(),
                )

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

            # A-5 fix (Plan 21.3): Case 2 means the exchange SL/TP already
            # fired — the surviving peer leg is exactly the bracket that
            # section 6's OUO peer-cancel below CANNOT reach (it's guarded
            # by has_exchange_position, which is False here by definition).
            # Capture the tracked ids before dropping local tracking and
            # cancel both — whichever leg triggered is already gone on
            # Binance's side, cancelling it again is a harmless no-op.
            _closed_algo_ids = (session["open_positions"].get(symbol) or {}).get("algo_ids")

            strategy.position = None
            strategy.stop_loss = None
            strategy.take_profit = None
            strategy._pending_flip = None
            session["open_positions"].pop(symbol, None)
            await self.cancel_symbol_algo_orders(session, symbol, _closed_algo_ids)

            await record_trade(trade_record)
            exchange_sync_seq = await append_event(
                session_id=session_id, symbol=symbol, event_type="reconcile_adjustment",
                payload={"nowFlat": True, "realizedPnl": realized_pnl, "price": estimated_exit, "reason": "exchange_had_no_position_engine_did"},
            )

            await self._notifier.notify(session_id, {
                "pnl": str(round(session["pnl"], 2)),
                "openPositions": list(session["open_positions"].keys()),
                "status": "running",
                "seq": exchange_sync_seq,
                "event": "position:close",
                "eventData": event_data,
            })

        elif has_local_position and not has_exchange_position and not position_query_ok:
            # A-15: query failed/deferred (e.g. A-9 backpressure) and we have a
            # local position — do NOT guess either way. Leave local state
            # exactly as-is and try again next candle; this mirrors 5.2's
            # "ambiguous → leave open, don't fabricate" invariant.
            logger.info(
                f"[AlgoBot] {symbol}: reconcile skipped — positionRisk query unconfirmed "
                f"(failed or deferred), local position left untouched pending next pass"
            )

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

            # ── A-7 fix (Plan 21.4): naked-position detection + re-arm ──
            # Nothing previously verified an open position still has a live
            # protective stop on the exchange. Restored orphans (Case 1 with
            # no open algo orders), TP/SL-placement 400s (F7 item 2's
            # class), and A-6 emergency-close-failure survivors can all end
            # up running naked, silently, forever. freqtrade re-places a
            # missing exchange stoploss on every iteration; mirror that here.
            # Plan 6 Step 6.3 phase (d3): active_bracket instead of the
            # mutable tuple — see maybe_amend_exchange_sl's comment above.
            if strategy.active_bracket is not None and strategy.active_bracket.stop_loss is not None:
                _has_live_sl = any(
                    "STOP" in str(_o.get("type") or "").upper()
                    or str(_o.get("clientOrderId") or "").endswith("sl")
                    for _o in open_orders
                )
                _rearm_counters = session.setdefault("_naked_position_rearm_attempts", {})
                if not _has_live_sl:
                    _attempt_n = _rearm_counters.get(symbol, 0) + 1
                    logger.warning(
                        f"[AlgoBot] {symbol}: naked position detected — strategy has a "
                        f"stop_loss but no live SL algo order exists on the exchange "
                        f"(re-arm attempt {_attempt_n})"
                    )
                    _sl_price_raw = strategy.active_bracket.stop_loss
                    _sl_rounding = ROUND_DOWN if strategy.position.type == "long" else ROUND_UP
                    _sl_price_new = round_price(symbol, "Binance Futures", _sl_price_raw, rounding=_sl_rounding) if _sl_price_raw else None
                    _rearmed = False
                    if _api_key and _api_secret and _sl_price_new:
                        try:
                            _rearm_side = "SELL" if strategy.position.type == "long" else "BUY"
                            _rearm_result = await exchange.place_algo_order(
                                _api_key, _api_secret,
                                params={
                                    "algoType": "CONDITIONAL",
                                    "symbol": symbol,
                                    "side": _rearm_side,
                                    "type": "STOP_MARKET",
                                    "triggerPrice": _fmt_num(_sl_price_new),
                                    "workingType": "MARK_PRICE",
                                    "closePosition": "true",
                                    "clientAlgoId": f"tpsl_{uuid4_hex8()}_sl",
                                },
                            )
                            logger.warning(
                                f"[AlgoBot] {symbol}: naked-position SL re-armed @ "
                                f"{_sl_price_new} algoId={_rearm_result.get('algoId')}"
                            )
                            _existing_pi = session["open_positions"].get(symbol, {})
                            _aids = dict(_existing_pi.get("algo_ids") or {"sl": None, "tp": None})
                            _aids["sl"] = _rearm_result.get("algoId")
                            _existing_pi["algo_ids"] = _aids
                            session["open_positions"][symbol] = _existing_pi
                            _rearmed = True
                            _rearm_counters.pop(symbol, None)
                            await self._notifier.notify(session_id, {
                                "event": "log",
                                "eventData": {
                                    "type": "warning",
                                    "message": f"{symbol}: naked position detected — SL re-armed @ {_sl_price_new}",
                                },
                            })
                        except Exception as _rearm_e:
                            logger.error(
                                f"[AlgoBot] {symbol}: naked-position SL re-arm attempt "
                                f"{_attempt_n}/{_NAKED_POSITION_MAX_REARM_ATTEMPTS} FAILED: "
                                f"{_binance_error_detail(_rearm_e)}"
                            )
                    if not _rearmed:
                        _rearm_counters[symbol] = _attempt_n
                        await self._notifier.notify(session_id, {
                            "event": "log",
                            "eventData": {
                                "type": "error",
                                "message": (
                                    f"{symbol}: naked position — SL re-arm failed "
                                    f"({_attempt_n}/{_NAKED_POSITION_MAX_REARM_ATTEMPTS})"
                                ),
                            },
                        })
                        if _attempt_n >= _NAKED_POSITION_MAX_REARM_ATTEMPTS:
                            logger.error(
                                f"[AlgoBot] {symbol}: naked position SL re-arm failed "
                                f"{_NAKED_POSITION_MAX_REARM_ATTEMPTS}x — force-closing for safety "
                                f"rather than continuing to run unprotected"
                            )
                            await self._notifier.notify(session_id, {
                                "event": "log",
                                "eventData": {
                                    "type": "error",
                                    "message": (
                                        f"{symbol}: force-closing after "
                                        f"{_NAKED_POSITION_MAX_REARM_ATTEMPTS} failed SL re-arm "
                                        f"attempts — position was running unprotected too long"
                                    ),
                                },
                            })
                            _rearm_counters.pop(symbol, None)
                            from core.live_bot_manager import LiveAdapter
                            _force_close_adapter = LiveAdapter(self._manager, session_id)
                            await _force_close_adapter.execute_exit(
                                strategy=strategy, symbol=symbol,
                                qty=strategy.position.qty,
                                exit_price=exchange_mark_price if exchange_mark_price is not None else strategy.position.entry_price,
                                reason="naked_position_force_close",
                                time_t=datetime.now(timezone.utc),
                                index_t=getattr(strategy, "index", 0),
                                high_t=0.0, low_t=0.0,
                            )
                else:
                    _rearm_counters.pop(symbol, None)

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
                                await exchange.cancel_algo_order(
                                    _api_key, _api_secret,
                                    params={"symbol": symbol, "algoId": _peer_id},
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

    @staticmethod
    def compute_session_equity_and_margin(session: dict) -> tuple[float, float]:
        """Plan 22 Step 22.1: session-level aggregates the Session Risk
        Governor needs — equity (allocated capital + realized + unrealized
        PnL across ALL symbols) and total committed margin. Shared by
        `execute_entry`'s pre-trade check and `_push_stats`'s periodic
        check so the two never compute this differently.
        """
        from core.live_bot_manager import (
            _binance_error_detail, _classify_exchange_sync_exit_reason, _extract_fill_price,
            _fmt_num, _make_client_id, _query_real_exit_from_user_trades, _query_real_fill_price,
            _safe_float, uuid4_hex8, _NAKED_POSITION_MAX_REARM_ATTEMPTS,
        )
        instances = session.get("strategy_instances", {}).values()
        total_pnl = sum(
            strat.position.pnl if strat.position else 0.0 for strat in instances
        ) + session.get("pnl", 0.0)
        equity = session.get("capital", 0.0) + total_pnl
        used_margin = sum(
            strat.position.margin if strat.position else 0.0 for strat in instances
        )
        return equity, used_margin

    @staticmethod
    def compute_open_risk_breakdown(session: dict) -> dict[str, float]:
        """Plan 22 Step 22.2: per-symbol `|entry - stop| * qty` for every
        currently-open position, keyed by symbol. This is the TRUE
        cross-symbol aggregate `DefaultPortfolioModel.construct()`
        (`core/models/portfolio.py`) structurally cannot compute — each
        symbol's pipeline call only ever sees its own strategy instance, not
        the session's other open symbols (Plan 21 audit finding: despite the
        name, `max_portfolio_risk` there is a per-symbol check).

        Reads each symbol's *current* `strategy.active_bracket.stop_loss`
        (Plan 6 Step 6.3 phase (d3); not a stale entry-time snapshot) so a
        trailing/breakeven-tightened stop is reflected immediately — the
        same live value `_maybe_amend_exchange_sl` pushes to the exchange.
        `sum(breakdown.values())` is the aggregate; callers needing to name
        contributing symbols in a veto log use the breakdown directly (see
        `execute_entry`).
        """
        from core.live_bot_manager import (
            _binance_error_detail, _classify_exchange_sync_exit_reason, _extract_fill_price,
            _fmt_num, _make_client_id, _query_real_exit_from_user_trades, _query_real_fill_price,
            _safe_float, uuid4_hex8, _NAKED_POSITION_MAX_REARM_ATTEMPTS,
        )
        breakdown: dict[str, float] = {}
        for symbol, strat in session.get("strategy_instances", {}).items():
            if strat.position is None or not strat.position.is_open:
                continue
            # Plan 6 Step 6.3 phase (d3): active_bracket instead of the
            # mutable tuple — see maybe_amend_exchange_sl's comment above.
            if strat.active_bracket is None or strat.active_bracket.stop_loss is None:
                continue
            stop_price = strat.active_bracket.stop_loss
            breakdown[symbol] = abs(strat.position.entry_price - stop_price) * strat.position.qty
        return breakdown

    async def apply_governor_breach(
        self, session_id: str, session: dict, verdict,
    ) -> None:
        """Plan 22 Step 22.1: apply a periodic Session Risk Governor breach —
        edge-triggered (only fires the transition once, when trading_state is
        still "active"; a manual reset back to active via the existing
        update-trading-state endpoint re-arms it). Auto-flattens on `halted`
        only if the governor's `auto_flatten_on_halt` is set (DECISIONS.md
        #23 — opt-in, off by default). The governor itself never places
        orders (Part C's design constraint) — this method is the caller
        acting on its verdict, same relationship `ProtectionManager` already
        has with `execute_entry`.
        """
        from core.live_bot_manager import (
            _binance_error_detail, _classify_exchange_sync_exit_reason, _extract_fill_price,
            _fmt_num, _make_client_id, _query_real_exit_from_user_trades, _query_real_fill_price,
            _safe_float, uuid4_hex8, _NAKED_POSITION_MAX_REARM_ATTEMPTS,
        )
        risk_governor = session.get("risk_governor")
        new_state = risk_governor.breach_action if risk_governor else "reducing"
        session["trading_state"] = new_state
        logger.error(
            f"[AlgoBot] Session {session_id}: RISK GOVERNOR BREACH ({verdict.check_name}) — "
            f"{verdict.reason} — trading_state -> {new_state}"
        )
        await self._notifier.notify(session_id, {
            "event": "risk_breach",
            "eventData": {
                "checkName": verdict.check_name,
                "reason": verdict.reason,
                "newState": new_state,
            },
        })
        if new_state == "halted" and risk_governor is not None and risk_governor.auto_flatten_on_halt:
            logger.warning(f"[AlgoBot] Session {session_id}: auto-flatten enabled — force-closing all positions")
            for symbol in list(session.get("open_positions", {}).keys()):
                try:
                    await self.close_position_on_stop(
                        session_id, symbol, session["open_positions"].get(symbol), session,
                    )
                except Exception as e:
                    logger.error(f"[AlgoBot] Session {session_id}: auto-flatten close failed for {symbol}: {e}")

