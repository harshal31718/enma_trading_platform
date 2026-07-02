# Binance API Integration Reference Manual: Mainnet & Testnet

## 1. Environment Configurations & Base URLs
To execute transactional order placements safely across production and sandbox environments, use the official separate environments.

Note that while the main front-end demo trading interface is unified at demo.binance.com, the underlying developer API backends and domain names remain structurally isolated to keep matching engines clean.

### Spot Environments
- Mainnet (Production Execution): `https://api.binance.com`
- Testnet (Sandbox Execution): `https://testnet.binance.vision`
- Mainnet Live WebSocket: `wss://stream.binance.com:9443/ws`
- Testnet Live WebSocket: `wss://stream.testnet.binance.vision:9443/ws`

### Futures Environments (USDⓈ-M)
- Mainnet (Production Execution): `https://fapi.binance.com`
- Testnet (Demo Simulation): `https://demo-fapi.binance.com`
- Mainnet Live WebSocket: `wss://fstream.binance.com/ws`
- Testnet Live WebSocket: `wss://fstream.binancefuture.com`
- **Actual client paths (not bare `/ws`):** `client/src/lib/binanceWS.js` connects to
  `wss://fstream.binance.com/public/ws` for depth streams and
  `wss://fstream.binance.com/market/ws` for everything else — no code connects to the bare `/ws` path.
- **User Data Stream** (private account/order updates, not public market data):
  `wss://fstream.binancefuture.com/ws` — see §7 below for the `listenKey` lifecycle.

---

## 2. Global Data-Fetching Optimization Guardrail
📊 **Architectural Constraint**: To guarantee complete historical alignment, accuracy, and uninterrupted data feeds for your charting framework, all OHLCV/Candlestick time-series queries should be routed exclusively through the official Mainnet production endpoints.

Testnet endpoints are designed for transactional load testing, meaning their historical data pools can be heavily fragmented, clean-wiped without notice, or contain simulated price anomalies.

### Global Chart-Populating Streams (Production Base Only)
- Spot Historical OHLCV: `GET https://api.binance.com/api/v3/klines`
- Futures Historical OHLCV: `GET https://fapi.binance.com/fapi/v1/klines`
- Futures Historical Mark Price: `GET https://fapi.binance.com/fapi/v1/markPriceKlines`
- Spot Real-Time Feed: WebSocket `wss://stream.binance.com:9443/ws/[symbol]@kline_[interval]`
- Futures Real-Time Feed: WebSocket `wss://fstream.binance.com/ws/[symbol]@kline_[interval]`

---

## 3. Order Execution (Entry Operations)

### Spot Order Placement — unimplemented, reserved
- Mainnet Endpoint: `POST https://api.binance.com/api/v3/order`
- Testnet Endpoint: `POST https://testnet.binance.vision/api/v3/order`
- **Usage**: Transmits signed BUY or SELL payloads to execute immediate fills or order-book placements.
- **Status**: The platform is futures-only for trading. No call site in `engine/`, `server/`, or
  `client/` hits this endpoint or the Spot OCO endpoint below — Spot candle *import* endpoints are
  used (see §2), but Spot order placement is not. Kept here as a reference for when/if Spot trading
  is added, not as documentation of an active integration.

### Futures Order Placement
- Mainnet Endpoint: `POST https://fapi.binance.com/fapi/v1/order`
- Testnet Endpoint: `POST https://demo-fapi.binance.com/fapi/v1/order`
- **Usage**: Opens or closes isolated directional leveraged contracts (LONG / SHORT).

---

## 4. Bracket Orders (Exit Operations)

### Spot OCO (One-Cancels-the-Other) Placement — unimplemented, reserved
- Mainnet Endpoint: `POST https://api.binance.com/api/v3/order/oco`
- Testnet Endpoint: `POST https://testnet.binance.vision/api/v3/order/oco`
- **Usage**: Submits a target profit limit and a protective stop-loss limit simultaneously. When one executes, the engine automatically purges the other.
- **Status**: unused — see Spot Order Placement note above.

### Futures TP/SL Bracket — actual endpoint is `/fapi/v1/algoOrder`, not `/fapi/v1/order`
- Mainnet Endpoint: `POST https://fapi.binance.com/fapi/v1/algoOrder`
- Testnet Endpoint: `POST https://demo-fapi.binance.com/fapi/v1/algoOrder`
- **Usage**: Every bracket/conditional order Enma places (manual OCO, live-bot entry brackets, DCA
  adjustments) uses `"algoType": "CONDITIONAL"` on this endpoint — not `"type": "TAKE_PROFIT_MARKET"`
  / `"STOP_MARKET"` with `"closePosition": "true"` on the plain order endpoint. Call sites:
  `engine/routers/trade.py` (`/order/oco_futures`), `engine/core/live_bot_manager.py`
  (entry SL/TP, DCA adjustments).
- **Cancel**: `DELETE https://<base>/fapi/v1/algoOrder` (`engine/routers/trade.py`,
  `engine/core/live_bot_manager.py`).
- **Query open/history**: `GET /fapi/v1/openAlgoOrders`, `GET /fapi/v1/historicalAlgoOrders`,
  `GET /fapi/v1/algoOpenOrders` (`engine/routers/trade.py`).
- **⚠️ If you are adding a new bracket order type, route it through `/fapi/v1/algoOrder`.** Building
  against the plain `/fapi/v1/order` `TAKE_PROFIT_MARKET`/`STOP_MARKET` params (as this doc previously
  instructed) does not match how any existing bracket order in this codebase is actually placed.

---

## 5. Margin & Risk Management (Isolated Only)

### Set Isolated Margin Mode
- Mainnet Endpoint: `POST https://fapi.binance.com/fapi/v1/marginType`
- Testnet Endpoint: `POST https://demo-fapi.binance.com/fapi/v1/marginType`
- **Usage**: Locks the trading pair asset pool exclusively into ISOLATED mode to ring-fence your account balance from liquidation risk.

### Configure Leverage Multiplier
- Mainnet Endpoint: `POST https://fapi.binance.com/fapi/v1/leverage`
- Testnet Endpoint: `POST https://demo-fapi.binance.com/fapi/v1/leverage`
- **Usage**: Configures the precise leverage index, adjusting the initial margin deposit required to hold open positions.

### Add/Reduce Position Margin
- Mainnet Endpoint: `POST https://fapi.binance.com/fapi/v1/positionMargin`
- Testnet Endpoint: `POST https://demo-fapi.binance.com/fapi/v1/positionMargin`
- **Usage**: Programmatically allocates additional buffer margin (`"type": 1`) to dynamically defend an open position against approaching liquidations, or extracts excess collateral (`"type": 2`).

### Leverage Bracket Lookup
- Mainnet Endpoint: `GET https://fapi.binance.com/fapi/v1/leverageBracket`
- Testnet Endpoint: `GET https://demo-fapi.binance.com/fapi/v1/leverageBracket`
- **Usage**: Returns per-symbol max-leverage tiers, used by `engine/utils/symbols.py` to populate the
  `rules` field of `GET /api/v1/candles/symbols`. Request weight 1 (signed).
- **Fixed 2026-07-02**: `engine/utils/symbols.py`'s `_LEVERAGE_BRACKET_URLS` (and its
  `_EXCHANGE_INFO_URLS`/`_TICKER_URLS`/`_BOOK_TICKER_URLS` siblings) previously pointed at
  `https://testnet.binancefuture.com` — a different, legacy testnet host than
  `engine/services/binance_testnet.py`'s canonical `https://demo-fapi.binance.com`. Confirmed via
  Binance's official Open Platform docs that `demo-fapi.binance.com` is the current documented REST
  base; all four dicts now use it. See `workspace/docs/core/DECISIONS.md` §9.

---

## 6. Account, Position & Order-History Queries

- **Account snapshot**: `GET /fapi/v2/account` (weight 5) — `engine/routers/trade.py`. Called with
  `X-Binance-Mode: testnet` for the Trade page and `X-Binance-Mode: mainnet` for the Dashboard's
  **read-only** mainnet balance tile. The server's `getBalances` (`server/src/controllers/trade.controller.js`,
  backing `GET /api/v1/trade/balances`) fans out one call per environment. **Mainnet is read-only** —
  no order/trading endpoint is ever called with mainnet keys (`X-Binance-Mode` is pinned to `testnet`
  on all trade routes; see `requireBinanceCredentials.js` and `DECISIONS.md`). Mainnet may be
  geo-blocked (451 / `-2015`) from the server's egress IP; the balances endpoint returns a per-env
  `{ok:false,error}` in that case rather than failing the whole response.
- **Position risk**: `GET /fapi/v2/positionRisk` — `engine/routers/trade.py`, `engine/core/live_bot_manager.py`.
- **Open orders**: `GET /fapi/v1/openOrders` — `engine/routers/trade.py`, `engine/core/live_bot_manager.py`.
- **Single order status**: `GET /fapi/v1/order` — `engine/routers/trade.py` (backs
  `GET /api/v1/trade/order`).
- **Cancel single order**: `DELETE /fapi/v1/order` — `engine/routers/trade.py`.
- **Cancel all open orders**: `DELETE /fapi/v1/allOpenOrders` — `engine/routers/trade.py`.
- **Order history**: `GET /fapi/v1/allOrders` — `engine/routers/trade.py`.
- **Trade/fill history**: `GET /fapi/v1/userTrades` — `engine/routers/trade.py`.
- **Income history** (funding fees, realized PnL): `GET /fapi/v1/income` — `engine/routers/trade.py`.

All of the above are signed requests routed through `send_signed_request` in
`engine/services/binance_testnet.py` per the base-URL rule in §1.

## 7. User Data Stream (`listenKey`)

Private account/order-update WebSocket, separate from the public market-data streams in §1–2.

- **Create**: `POST /fapi/v1/listenKey`
- **Keepalive**: `PUT /fapi/v1/listenKey`
- **Close**: `DELETE /fapi/v1/listenKey`
- **WebSocket**: `wss://fstream.binancefuture.com/ws`

Implemented in `engine/services/user_data_stream.py`, which owns the create/keepalive/close lifecycle
and the WS connection.
