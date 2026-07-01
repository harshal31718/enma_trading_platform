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
        self._listen_key: str | None = None
        self._ws_task: asyncio.Task | None = None
        self._keepalive_task: asyncio.Task | None = None
        self._running = False
        self._stop_event = asyncio.Event()

    # ── Public API ──────────────────────────────────────────────────────────

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

                        etype = _Event.parse(msg)
                        if etype == _Event.ORDER_TRADE_UPDATE:
                            await self._handle_order_trade_update(msg.get("o", {}))
                        elif etype == _Event.ACCOUNT_UPDATE:
                            await self._handle_account_update(msg.get("a", {}))
                        elif etype == _Event.MARGIN_CALL:
                            logger.warning(f"[UserDataStream] MARGIN_CALL: {raw}")
                        elif etype == _Event.LISTEN_KEY_EXPIRED:
                            logger.warning("[UserDataStream] Listen key expired — reconnecting")
                            self._listen_key = await self._create_listen_key()
                            ws_url = f"{_BINANCE_FUTURES_WS}/{self._listen_key}"
                            return  # Reconnect loop picks up the new URL
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
            logger.debug(
                f"[UserDataStream] {symbol}: account update — positionAmt={amt} entryPrice={entry_price}"
            )


# No module-level singleton — each live session creates its own
# UserDataStreamManager(api_key=..., api_secret=...) in live_bot_manager.py.
