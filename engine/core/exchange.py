"""Plan 6 Step 6.2 (ENG-4): a real `Exchange` abstraction over Binance
Futures testnet/mainnet, so testnet-vs-mainnet is a config-selected
implementation instead of `mode="testnet"` literals scattered through
`reconciler.py`/`live_bot_manager.py`/`user_data_stream.py`.

**Not wired to any existing call site yet — deliberately.** This ships the
interface itself, contract-tested against both implementations, as a safe,
additive, zero-risk-to-the-live-path first slice. Migrating the ~24 existing
`send_signed_request(..., mode="testnet")` call sites across those three
files is separate, larger, live-trading-critical work with no golden-master
safety net (this file has zero import overlap with the backtest path) —
left for its own dedicated pass rather than rushed into this one.

**`BinanceFuturesMainnet` existing as a class is not a live-trading gate.**
Per this plan step's own note: "mainnet must stay gated behind Plan 5 being
Shipped — wiring the class is fine; enabling mainnet trading is a separate
product gate." Nothing in this file starts a session or places a real order;
whatever eventually constructs one of these per-session from config is
where that gate belongs.

**Deliberately excludes the live kline/candle WebSocket stream.** Per Plan
21 A-12 (DECISIONS.md #24), the kline stream is ALWAYS sourced from
Binance's public mainnet WS regardless of session mode — it's unauthenticated
market data, and testnet's own feed is illiquid/discontinuous. That is a
documented design decision, not something this abstraction should paper
over by pretending kline data varies by mode. What DOES vary by mode is the
authenticated User Data Stream (listen-key WS) — `user_data_ws_url()` below.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from services.binance_testnet import send_signed_request


class Exchange(ABC):
    """One Binance Futures account context (testnet or mainnet) — order
    placement/cancel/query, algo (SL/TP) order management, position/account/
    trade-history queries, leverage/margin-type, and listen-key lifecycle.

    Every method signs with the given `api_key`/`api_secret` and routes
    through `send_signed_request` using this instance's own `mode` — callers
    never pass `mode=` themselves, closing off the class of bug where a
    testnet session's call accidentally lands on `mode="mainnet"` (or
    vice versa) because a literal was copy-pasted at some call site.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable identity for logs, e.g. \"Binance Futures Testnet\"."""

    @property
    @abstractmethod
    def mode(self) -> str:
        """The string `send_signed_request` keys its base-URL lookup by —
        `"testnet"` or `"mainnet"`."""

    @property
    @abstractmethod
    def user_data_ws_base(self) -> str:
        """Base WS URL for the authenticated User Data Stream (listen-key
        events) — appended with `/{listen_key}` by the caller. Mode-dependent
        (unlike the public kline stream — see module docstring)."""

    async def _signed(
        self, method: str, path: str, api_key: str, api_secret: str, params: dict | None = None,
    ) -> Any:
        return await send_signed_request(method, path, api_key, api_secret, params=params, mode=self.mode)

    # ── Orders ───────────────────────────────────────────────────────────
    async def place_order(self, api_key: str, api_secret: str, params: dict) -> Any:
        return await self._signed("POST", "/fapi/v1/order", api_key, api_secret, params)

    async def cancel_order(self, api_key: str, api_secret: str, params: dict) -> Any:
        return await self._signed("DELETE", "/fapi/v1/order", api_key, api_secret, params)

    async def query_order(self, api_key: str, api_secret: str, params: dict) -> Any:
        return await self._signed("GET", "/fapi/v1/order", api_key, api_secret, params)

    # ── Algo (conditional SL/TP) orders ─────────────────────────────────
    async def place_algo_order(self, api_key: str, api_secret: str, params: dict) -> Any:
        return await self._signed("POST", "/fapi/v1/algoOrder", api_key, api_secret, params)

    async def cancel_algo_order(self, api_key: str, api_secret: str, params: dict) -> Any:
        return await self._signed("DELETE", "/fapi/v1/algoOrder", api_key, api_secret, params)

    async def query_open_algo_orders(self, api_key: str, api_secret: str, params: dict) -> Any:
        return await self._signed("GET", "/fapi/v1/openAlgoOrders", api_key, api_secret, params)

    # ── Positions / account / history ───────────────────────────────────
    async def query_open_orders(self, api_key: str, api_secret: str, params: dict) -> Any:
        return await self._signed("GET", "/fapi/v1/openOrders", api_key, api_secret, params)

    async def query_position_risk(self, api_key: str, api_secret: str, params: dict) -> Any:
        return await self._signed("GET", "/fapi/v2/positionRisk", api_key, api_secret, params)

    async def query_account(self, api_key: str, api_secret: str, params: dict | None = None) -> Any:
        return await self._signed("GET", "/fapi/v2/account", api_key, api_secret, params)

    async def query_user_trades(self, api_key: str, api_secret: str, params: dict) -> Any:
        return await self._signed("GET", "/fapi/v1/userTrades", api_key, api_secret, params)

    # ── Account configuration ───────────────────────────────────────────
    async def set_leverage(self, api_key: str, api_secret: str, params: dict) -> Any:
        return await self._signed("POST", "/fapi/v1/leverage", api_key, api_secret, params)

    async def set_margin_type(self, api_key: str, api_secret: str, params: dict) -> Any:
        return await self._signed("POST", "/fapi/v1/marginType", api_key, api_secret, params)

    # ── Listen key (User Data Stream) lifecycle ─────────────────────────
    async def create_listen_key(self, api_key: str, api_secret: str) -> str:
        data = await self._signed("POST", "/fapi/v1/listenKey", api_key, api_secret)
        return data["listenKey"]

    async def keepalive_listen_key(self, api_key: str, api_secret: str) -> None:
        await self._signed("PUT", "/fapi/v1/listenKey", api_key, api_secret)

    async def close_listen_key(self, api_key: str, api_secret: str) -> None:
        await self._signed("DELETE", "/fapi/v1/listenKey", api_key, api_secret)

    def user_data_ws_url(self, listen_key: str) -> str:
        return f"{self.user_data_ws_base}/{listen_key}"


class BinanceFuturesTestnet(Exchange):
    @property
    def name(self) -> str:
        return "Binance Futures Testnet"

    @property
    def mode(self) -> str:
        return "testnet"

    @property
    def user_data_ws_base(self) -> str:
        return "wss://fstream.binancefuture.com/ws"


class BinanceFuturesMainnet(Exchange):
    """Constructible today (Step 6.2's own scope), but nothing in this repo
    yet selects it for a live session — mainnet trading is gated behind
    Plan 5 being fully shipped (it is) AND a deliberate, separate product
    decision to actually offer it, per this step's own acceptance note."""

    @property
    def name(self) -> str:
        return "Binance Futures Mainnet"

    @property
    def mode(self) -> str:
        return "mainnet"

    @property
    def user_data_ws_base(self) -> str:
        return "wss://fstream.binance.com/ws"
