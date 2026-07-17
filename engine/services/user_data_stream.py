"""Binance User Data Stream manager (F-020).

Listens for real-time order fill events (``ORDER_TRADE_UPDATE``) and position
changes (``ACCOUNT_UPDATE``) via the Binance Futures user data WebSocket, so the
engine knows about fills immediately instead of waiting for the next kline close.

Architecture
------------
One listen key per set of API credentials (singleton).  Events are dispatched to
registered callbacks keyed by symbol.  The live bot manager registers per-symbol
callbacks when it starts a symbol loop.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time

import httpx
import websockets

from services.binance_testnet import send_signed_request

logger = logging.getLogger(__name__)

_BINANCE_FUTURES_WS = "wss://fstream.binancefuture.com/ws"
_KEEPALIVE_INTERVAL = 1800  # 30 minutes — Binance requires keep-alive every 60 min


class _Event:
    """Enum-like constants for user data stream event types."""
    ORDER_TRADE_UPDATE = "ORDER_TRADE_UPDATE"
    ACCOUNT_UPDATE = "ACCOUNT_UPDATE"
    MARGIN_CALL = "MARGIN_CALL"
    LISTEN_KEY_EXPIRED = "listenKeyExpired"

    @classmethod
    def parse(cls, raw: dict) -> str | None:
        etype = raw.get("e")
        if etype in (cls.ORDER_TRADE_UPDATE, cls.ACCOUNT_UPDATE, cls.MARGIN_CALL, cls.LISTEN_KEY_EXPIRED):
            return etype
        return None


class UserDataStreamManager:
    """Manages a single Binance Futures user data WebSocket connection.

    Callers register per-symbol callbacks via ``register_fill_callback``.
    On ``ORDER_TRADE_UPDATE`` events the manager looks up the callback by
    symbol and invokes it asynchronously.
    """

    def __init__(self, api_key: str = "", api_secret: str = "") -> None:
        self._api_key = api_key
        self._api_secret = api_secret
        self._fill_callbacks: dict[str, list[callable]] = {}
        # F7 fix: per-symbol ACCOUNT_UPDATE callbacks. Binance emits an
        # ACCOUNT_UPDATE on *any* position change (plain order, conditional/
        # algo order, liquidation, ADL), so this is the event-type-agnostic
        # signal the fill path was missing for /fapi/v1/algoOrder TP-SL fills.
        self._account_callbacks: dict[str, list[callable]] = {}
        self._stream_callbacks: list[callable] = []
        self._listen_key: str | None = None
        self._ws_task: asyncio.Task | None = None
        self._keepalive_task: asyncio.Task | None = None
        self._running = False
        self._stop_event = asyncio.Event()

    # ── Public API ──────────────────────────────────────────────────────────

    def register_stream_callback(self, callback: callable) -> None:
        """Register an async callback for EVERY order/account event, unfiltered.

        Unlike ``register_fill_callback`` (per-symbol, FILLED/PARTIALLY_FILLED
        only — used by the live bot's fill-detection path), this fires for
        every ``ORDER_TRADE_UPDATE`` status (NEW, CANCELED, EXPIRED, etc.) and
        every ``ACCOUNT_UPDATE``, across all symbols. Intended for consumers
        that mirror full account state (e.g. the manual-trading stream relay)
        rather than reacting only to fills.

        The callback is called as::

            await callback(event_type: str, payload: dict)

        where ``event_type`` is ``"ORDER_TRADE_UPDATE"`` or ``"ACCOUNT_UPDATE"``
        and ``payload`` is the raw ``o``/``a`` sub-object from the event.
        """
        self._stream_callbacks.append(callback)

    def unregister_stream_callback(self, callback: callable) -> None:
        self._stream_callbacks = [cb for cb in self._stream_callbacks if cb is not callback]

    def register_fill_callback(self, symbol: str, callback: callable) -> None:
        """Register an async callback for fill events on *symbol*.

        The callback is called as::

            await callback(order_data: dict)

        where ``order_data`` is the parsed ``o`` field from the
        ``ORDER_TRADE_UPDATE`` event.
        """
        if symbol not in self._fill_callbacks:
            self._fill_callbacks[symbol] = []
        self._fill_callbacks[symbol].append(callback)

    def unregister_fill_callback(self, symbol: str, callback: callable | None = None) -> None:
        """Remove a previously registered callback.  If *callback* is None
        remove all callbacks for *symbol*."""
        if symbol not in self._fill_callbacks:
            return
        if callback is None:
            self._fill_callbacks.pop(symbol, None)
        else:
            self._fill_callbacks[symbol] = [
                cb for cb in self._fill_callbacks[symbol] if cb is not callback
            ]
            if not self._fill_callbacks[symbol]:
                self._fill_callbacks.pop(symbol, None)

    def register_account_callback(self, symbol: str, callback: callable) -> None:
        """Register an async callback for ACCOUNT_UPDATE position deltas on
        *symbol* (F7 fix).

        The callback is called as::

            await callback(position_data: dict)

        where ``position_data`` is one entry of the ``a.P`` array from an
        ``ACCOUNT_UPDATE`` event (fields: ``s`` symbol, ``pa`` positionAmt,
        ``ep`` entryPrice, ``up`` unrealizedPnl, …). Unlike the fill callback
        (which only fires on ``ORDER_TRADE_UPDATE`` FILLED/PARTIALLY_FILLED and
        so misses conditional/algo-order fills), this fires on every position
        change Binance reports — the reliable close signal for the live bot.
        """
        if symbol not in self._account_callbacks:
            self._account_callbacks[symbol] = []
        self._account_callbacks[symbol].append(callback)

    def unregister_account_callback(self, symbol: str, callback: callable | None = None) -> None:
        """Remove a previously registered ACCOUNT_UPDATE callback.  If
        *callback* is None remove all callbacks for *symbol*."""
        if symbol not in self._account_callbacks:
            return
        if callback is None:
            self._account_callbacks.pop(symbol, None)
        else:
            self._account_callbacks[symbol] = [
                cb for cb in self._account_callbacks[symbol] if cb is not callback
            ]
            if not self._account_callbacks[symbol]:
                self._account_callbacks.pop(symbol, None)

    async def start(self) -> None:
        """Create a listen key and start the WebSocket listener."""
        if self._running:
            return
        self._running = True
        self._stop_event.clear()

        self._listen_key = await self._create_listen_key()
        ws_url = f"{_BINANCE_FUTURES_WS}/{self._listen_key}"
        logger.info(f"[UserDataStream] Starting — listen_key={self._listen_key[:8]}...")

        self._ws_task = asyncio.create_task(self._run_ws(ws_url))
        self._keepalive_task = asyncio.create_task(self._run_keepalive())

    async def stop(self) -> None:
        """Stop the listener and release the listen key."""
        self._running = False
        self._stop_event.set()

        if self._keepalive_task is not None:
            self._keepalive_task.cancel()
            self._keepalive_task = None
        if self._ws_task is not None:
            self._ws_task.cancel()
            self._ws_task = None

        await self._delete_listen_key()
        self._listen_key = None
        self._fill_callbacks.clear()
        self._account_callbacks.clear()
        self._stream_callbacks.clear()
        logger.info("[UserDataStream] Stopped.")

    # ── Internal helpers ────────────────────────────────────────────────────

    async def _create_listen_key(self) -> str:
        """POST /fapi/v1/listenKey returns a listen key."""
        if not self._api_key or not self._api_secret:
            raise RuntimeError("API credentials not set on UserDataStreamManager")

        # Use send_signed_request which handles HMAC; for listenKey a POST
        # with no params works.
        data = await send_signed_request(
            "POST", "/fapi/v1/listenKey",
            self._api_key, self._api_secret, mode="testnet",
        )
        return data["listenKey"]

    async def _delete_listen_key(self) -> None:
        """DELETE /fapi/v1/listenKey to clean up."""
        if not self._api_key or not self._api_secret:
            return
        try:
            await send_signed_request(
                "DELETE", "/fapi/v1/listenKey",
                self._api_key, self._api_secret, mode="testnet",
            )
        except Exception as e:
            logger.warning(f"[UserDataStream] Listen key delete failed: {e}")

    async def _keepalive_listen_key(self) -> None:
        """PUT /fapi/v1/listenKey to extend the TTL."""
        if not self._api_key or not self._api_secret:
            return
        try:
            await send_signed_request(
                "PUT", "/fapi/v1/listenKey",
                self._api_key, self._api_secret, mode="testnet",
            )
            logger.debug("[UserDataStream] Listen key keep-alive OK")
        except Exception as e:
            logger.warning(f"[UserDataStream] Keep-alive failed: {e}")

    async def _run_keepalive(self) -> None:
        """Periodically refresh the listen key until stopped."""
        try:
            while self._running and not self._stop_event.is_set():
                await asyncio.sleep(_KEEPALIVE_INTERVAL)
                await self._keepalive_listen_key()
        except asyncio.CancelledError:
            pass

    async def _run_ws(self, ws_url: str) -> None:
        """Connect to the user data WebSocket and process events."""
        backoff = 1
        while self._running and not self._stop_event.is_set():
            try:
                async with websockets.connect(
                    ws_url, ping_interval=20, ping_timeout=20, close_timeout=5,
                ) as ws:
                    logger.info(f"[UserDataStream] WS connected")
                    backoff = 1  # Reset on successful connect
                    async for raw in ws:
                        if not self._running or self._stop_event.is_set():
                            return
                        try:
                            msg = json.loads(raw)
                        except json.JSONDecodeError:
                            continue

                        # F7 diagnostic (2026-07-16): log the raw event type of
                        # every user-data frame so a live reproduction shows
                        # exactly what Binance emits for an algo/conditional
                        # (/fapi/v1/algoOrder) TP-SL fill — whether it arrives as
                        # ORDER_TRADE_UPDATE at all, as a different event type
                        # (e.g. CONDITIONAL_ORDER_TRADE_UPDATE / STRATEGY_UPDATE)
                        # that _Event.parse currently drops, or only as an
                        # ACCOUNT_UPDATE. Remove once the fill-path root cause is
                        # addressed (Plan 5 Step 5.6).
                        _raw_etype = msg.get("e")
                        logger.info(f"[UserDataStream] frame e={_raw_etype}")

                        etype = _Event.parse(msg)
                        if etype == _Event.ORDER_TRADE_UPDATE:
                            _o = msg.get("o", {})
                            logger.info(
                                f"[UserDataStream] ORDER_TRADE_UPDATE raw: sym={_o.get('s')} "
                                f"X={_o.get('X')} type={_o.get('o')} origType={_o.get('ot')} "
                                f"clientId={_o.get('c')} orderId={_o.get('i')}"
                            )
                            await self._handle_order_trade_update(_o)
                            await self._dispatch_stream_callbacks(etype, _o)
                        elif etype == _Event.ACCOUNT_UPDATE:
                            await self._handle_account_update(msg.get("a", {}))
                            await self._dispatch_stream_callbacks(etype, msg.get("a", {}))
                        elif etype == _Event.MARGIN_CALL:
                            logger.warning(f"[UserDataStream] MARGIN_CALL: {raw}")
                        elif etype == _Event.LISTEN_KEY_EXPIRED:
                            logger.warning("[UserDataStream] Listen key expired — reconnecting")
                            self._listen_key = await self._create_listen_key()
                            ws_url = f"{_BINANCE_FUTURES_WS}/{self._listen_key}"
                            # A-3 fix: `return` here exited the whole _run_ws
                            # coroutine (there is no caller that re-invokes
                            # it), silently killing the user-data stream for
                            # the rest of the session — the old comment
                            # claiming "reconnect loop picks it up" was wrong.
                            # `break` exits only the `async for` (and, via the
                            # `async with`, the current ws connection), so the
                            # outer `while self._running` loop re-enters and
                            # reconnects using the refreshed `ws_url` above.
                            break
                        else:
                            # UNRECOGNIZED by _Event.parse — the key F7 diagnostic.
                            # If an algo/conditional TP-SL fill surfaces here, the
                            # real-time fill path never sees it (parse returns None;
                            # the frame was previously dropped with no trace). Dump
                            # the whole frame so the reproduction captures Binance's
                            # actual event name + shape.
                            logger.warning(
                                f"[UserDataStream] UNHANDLED event e={_raw_etype} — full frame: {raw}"
                            )
            except asyncio.CancelledError:
                return
            except Exception as e:
                if not self._running:
                    return
                logger.warning(
                    f"[UserDataStream] WS error ({e}) — reconnecting in {backoff}s"
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)
                # Refresh listen key on reconnect
                try:
                    self._listen_key = await self._create_listen_key()
                    ws_url = f"{_BINANCE_FUTURES_WS}/{self._listen_key}"
                except Exception as ke:
                    logger.warning(f"[UserDataStream] Listen key refresh failed: {ke}")

    async def _handle_order_trade_update(self, order_data: dict) -> None:
        """Dispatch an ORDER_TRADE_UPDATE to registered callbacks.

        The ``o`` payload has fields (Binance doc):
            s — symbol
            X — current order status (NEW, PARTIALLY_FILLED, FILLED, etc.)
            z — cumulative filled quantity
            Z — cumulative filled notional
            l — last executed price
            L — last executed quantity
            p — price
            q — original quantity
            Y — last filled notional
            T — transaction time
            S — side (BUY/SELL)
            o — order type
            f — time in force
            ap — average price
            sp — stop price
        """
        symbol = order_data.get("s", "")
        status = order_data.get("X", "")
        if not symbol:
            return

        callbacks = self._fill_callbacks.get(symbol, [])
        if not callbacks:
            # No one is listening for this symbol — skip
            return

        if status in ("FILLED", "PARTIALLY_FILLED"):
            logger.info(
                f"[UserDataStream] {symbol}: order {order_data.get('i')} "
                f"{status} qty={order_data.get('z')} @ {order_data.get('ap')}"
            )
            for cb in callbacks:
                try:
                    await cb(order_data)
                except Exception as e:
                    logger.error(
                        f"[UserDataStream] {symbol}: callback error: {e}"
                    )

    async def _dispatch_stream_callbacks(self, event_type: str, payload: dict) -> None:
        """Fan out *every* order/account event to unfiltered stream callbacks."""
        for cb in self._stream_callbacks:
            try:
                await cb(event_type, payload)
            except Exception as e:
                logger.error(f"[UserDataStream] stream callback error: {e}")

    async def _handle_account_update(self, account_data: dict) -> None:
        """Process ACCOUNT_UPDATE events (position/balance changes)."""
        # B — balance updates, P — position updates
        positions = account_data.get("P", [])
        for pos in positions:
            symbol = pos.get("s")
            if not symbol:
                continue
            amt = float(pos.get("pa", 0))
            entry_price = float(pos.get("ep", 0))
            # F7 diagnostic: INFO (was debug) so a fast conditional-order
            # close's position-goes-to-zero delta is visible at default level,
            # timestamped against the candle-close reconcile.
            logger.info(
                f"[UserDataStream] {symbol}: account update — positionAmt={amt} entryPrice={entry_price}"
            )
            # F7 fix: dispatch to per-symbol ACCOUNT_UPDATE callbacks. This is
            # the event-agnostic close signal — it fires for conditional/algo
            # (/fapi/v1/algoOrder) TP-SL fills that never surface as an
            # ORDER_TRADE_UPDATE the fill path can see, closing the ~60s window
            # where the engine still believed a Binance-closed position was open.
            for cb in self._account_callbacks.get(symbol, []):
                try:
                    await cb(pos)
                except Exception as e:
                    logger.error(
                        f"[UserDataStream] {symbol}: account callback error: {e}"
                    )


# No module-level singleton — each live session creates its own
# UserDataStreamManager(api_key=..., api_secret=...) in live_bot_manager.py.
