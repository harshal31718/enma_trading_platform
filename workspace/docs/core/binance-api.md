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

### Spot Order Placement
- Mainnet Endpoint: `POST https://api.binance.com/api/v3/order`
- Testnet Endpoint: `POST https://testnet.binance.vision/api/v3/order`
- **Usage**: Transmits signed BUY or SELL payloads to execute immediate fills or order-book placements.

### Futures Order Placement
- Mainnet Endpoint: `POST https://fapi.binance.com/fapi/v1/order`
- Testnet Endpoint: `POST https://demo-fapi.binance.com/fapi/v1/order`
- **Usage**: Opens or closes isolated directional leveraged contracts (LONG / SHORT).

---

## 4. Bracket Orders (Exit Operations)

### Spot OCO (One-Cancels-the-Other) Placement
- Mainnet Endpoint: `POST https://api.binance.com/api/v3/order/oco`
- Testnet Endpoint: `POST https://testnet.binance.vision/api/v3/order/oco`
- **Usage**: Submits a target profit limit and a protective stop-loss limit simultaneously. When one executes, the engine automatically purges the other.

### Futures Take Profit (TP) Placement
- Mainnet Endpoint: `POST https://fapi.binance.com/fapi/v1/order`
- Testnet Endpoint: `POST https://demo-fapi.binance.com/fapi/v1/order`
- **Usage**: Deploys a position-linked exit payload utilizing `"type": "TAKE_PROFIT_MARKET"` paired with `"closePosition": "true"` at a target profit boundary.

### Futures Stop Loss (SL) Placement
- Mainnet Endpoint: `POST https://fapi.binance.com/fapi/v1/order`
- Testnet Endpoint: `POST https://demo-fapi.binance.com/fapi/v1/order`
- **Usage**: Deploys a risk protection payload utilizing `"type": "STOP_MARKET"` paired with `"closePosition": "true"`. Wipes the rest of the bracket if triggered.

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
