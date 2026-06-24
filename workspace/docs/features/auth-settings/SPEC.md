# Feature: Authentication & Settings

**Status:** Settings implemented; no authentication layer  
**Last updated:** 2026-06-20

---

## What It Does

Manages platform configuration: trading mode (Testnet/Mainnet), Binance API credential verification, and exchange trading settings. The Exchange Settings section centralizes all trading parameters (fees, slippage, funding) and form defaults — all values are stored as variables, not hardcoded. **There is no authentication layer** — no register/login routes, no auth middleware, no `User` model. The former auth scaffolding was **fully removed 2026-06-22**: `bcryptjs`/`jsonwebtoken` deleted from `server/package.json`, `client/src/store/useAuthStore.js` deleted, and the JWT/401 interceptors stripped from `client/src/lib/axios.js` (see `../../state/DEPRECATED.md` → "Client Auth Scaffolding"). This is a single-user, self-hosted platform; a login gate is unnecessary unless multi-user support is added.

---

## Data Flow

### Settings page — trading mode

```
Client navigates to Settings page
        ↓
GET /api/v1/trade/settings/keys
        ↓
Server reads Mode from MongoDB Settings collection
        ↓
Returns: { mode: 'testnet' | 'mainnet' }

User changes mode and saves
        ↓
POST /api/v1/trade/settings/keys  { mode: 'testnet' | 'mainnet' }
        ↓
Server validates and writes to Settings collection
```

### Settings page — credential verification

```
User clicks "Verify Credentials"
        ↓
POST /api/v1/trade/settings/verify
        ↓
Server calls engine POST /trade/verify (with credentials from .env)
        ↓
Engine calls Binance /fapi/v2/account as a test request
        ↓
Returns: { valid: true } or { valid: false, error: string }
```

### Settings page — exchange settings

```
Client navigates to Settings page → Exchange Settings section
        ↓
GET /api/v1/settings/exchange
        ↓
Server reads Settings doc from MongoDB
        ↓
Returns: {
  takerFee, makerFee,                     ← Trading Fees (0.0005 = 0.05%)
  defaultCapital, defaultLeverage,        ← Backtest Defaults
  defaultBotCapital, defaultBotLeverage,  ← Bot Defaults
  slippagePct, fundingEnabled, fundingRate ← Simulation Realism
}

Client displays as percentage form (multiply by 100)
User updates and saves
        ↓
PUT /api/v1/settings/exchange  { takerFee: 0.0005, ... }
        ↓
Server validates ranges and writes to Settings doc
        ↓
Response: { success: true, data: {...} }

When forms load (BacktestConfigForm, NewSessionWizard):
  → useExchangeSettings() hook fetches settings
  → Capital and leverage pre-fill from defaults (one-time, non-overriding)
```

### Authentication — not implemented

There are **no** `/api/v1/auth/*` routes, no auth middleware, and no `User` model. This is a
single-user, self-hosted platform, so no login gate is needed. The old client/server auth scaffolding
(`useAuthStore.js`, axios JWT interceptors, `bcryptjs`/`jsonwebtoken`) was deleted 2026-06-22 — add
real auth (register/login + middleware) from scratch only if multi-user support is ever introduced.

---

## Service Responsibilities

| Layer | Owns | Does NOT own |
|-------|------|-------------|
| Client | Settings form, mode selector | Credential storage |
| Node server | Settings MongoDB doc, credential injection into proxy headers | Credential validation |
| Python engine | Binance credential test call | Storing credentials |

---

## Key Invariants

- **Credentials live in `.env`.** Binance API key/secret are read from server environment variables (`BINANCE_TESTNET_KEY`, `BINANCE_TESTNET_SECRET`, `BINANCE_LIVE_KEY`, `BINANCE_LIVE_SECRET`) — they are not stored in MongoDB. The AES-256 encryption util (`server/src/utils/encryption.js`) exists for future use but is not currently wired.
- **Single-user model.** No `user_id` on any schema. No authentication layer exists; the former `bcryptjs`/`jsonwebtoken` deps and `useAuthStore` scaffolding were deleted 2026-06-22 — nothing auth-related remains.
- **Do not modify `.env` files.** Settings changes (mode) go to MongoDB Settings collection only.
- **Mainnet not implemented.** Switching mode to `mainnet` in Settings has no effect on the current trade route behavior — all orders still target Testnet. Full mainnet support requires swapping the base URL in the engine.

---

## MongoDB Settings Model

**Collection:** `settings`  
**Document:** Singleton (`_id: 'global'`)

| Field | Type | Description |
|-------|------|-------------|
| `_id` | String | Fixed value `'global'` |
| `mode` | Enum | `'testnet'` or `'mainnet'` |
| **Trading Fees** | | |
| `takerFee` | Number | Taker fee rate (decimal: 0.0005 = 0.05%), default 0.0005 |
| `makerFee` | Number | Maker fee rate (decimal: 0.0002 = 0.02%), default 0.0002 |
| **Simulation Realism** | | |
| `slippagePct` | Number | Market fill slippage (decimal: 0.0005 = 0.05%), default 0.0005 |
| `fundingEnabled` | Boolean | Whether to charge funding during backtests, default false |
| `fundingRate` | Number | Funding rate per 8h period (decimal: 0.0001 = 0.01%), default 0.0001 |
| **Backtest Defaults** | | |
| `defaultCapital` | Number | Starting capital for new backtests, default 10000 |
| `defaultLeverage` | Number | Default leverage for backtests (1-125), default 1 |
| **Bot Defaults** | | |
| `defaultBotCapital` | Number | Starting capital for new bot sessions, default 1000 |
| `defaultBotLeverage` | Number | Default leverage for bot sessions (1-125), default 1 |
| **Risk Model Defaults** | | |
| `riskPct` | Number | Risk per trade as fraction of equity (0.01 = 1%), default 0.01 |
| `riskRewardRatio` | Number | Reward:risk multiple for take-profit, default 2.0 |
| `maxSessionDrawdown` | Number | Max equity drawdown before halting new entries (0.20 = 20%), default 0.20 |
| `liqBufferPct` | Number | Min gap between stop-loss and liquidation price, default 0.005 |
| `minEdgeMult` | Number | Cost Model minimum edge multiplier, default 0.0 |
| **Chaos Mode Defaults** | | |
| `chaosMaxStrategies` | Number | Hard cap on strategies per chaos run, default 10 |
| `chaosMaxManualSymbols` | Number | Max hand-picked symbols per strategy, default 5 |
| `chaosDefaultCapital` | Number | Per-strategy capital pre-fill, default 500 |
| `chaosDefaultLeverage` | Number | Leverage pre-fill, default 50 |
| `chaosDefaultTimeframe` | String | Default chaos timeframe, default `'1m'` |

---

## Auth Status

| Component | Status | Notes |
|-----------|--------|-------|
| `POST /api/v1/auth/register` | Does not exist | No route file or controller |
| `POST /api/v1/auth/login` | Does not exist | No route file or controller |
| JWT middleware | Does not exist | `server/src/middleware/auth.js` never existed |
| Login gate in UI | Does not exist | Single-user model — no gate needed |
| `useAuthStore` (Zustand) | Deleted 2026-06-22 | Removed with the rest of the auth scaffolding |

---

## REST Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/trade/settings/keys` | Get current trading mode |
| POST | `/api/v1/trade/settings/keys` | Save trading mode |
| POST | `/api/v1/trade/settings/verify` | Verify Binance API credentials |
| GET | `/api/v1/settings/exchange` | Get all exchange settings (fees, defaults, simulation params) |
| PUT | `/api/v1/settings/exchange` | Update exchange settings |

---

## Related Files

| File | Role |
|------|------|
| `client/src/pages/Settings.jsx` | Environment Configuration + Exchange Settings form (4 sections) |
| `client/src/hooks/useExchangeSettings.js` | TanStack Query hooks: `useExchangeSettings()` (GET), `useUpdateExchangeSettings()` (PUT) |
| `client/src/features/backtest/BacktestConfigForm.jsx` | Pre-fills capital/leverage from `defaultCapital`/`defaultLeverage` |
| `client/src/components/algo/NewSessionWizard.jsx` | Pre-fills capital/leverage from `defaultBotCapital`/`defaultBotLeverage` |
| `server/src/routes/settings.routes.js` | Exchange settings GET + PUT routes |
| `server/src/routes/trade.routes.js` | Settings keys routes (GET + POST + verify) |
| `server/src/controllers/settings.controller.js` | `getExchangeSettings`, `updateExchangeSettings` |
| `server/src/controllers/trade.controller.js` | `getSettingsKeys`, `saveSettingsKeys`, `verifySettings` |
| `server/src/controllers/algo.controller.js` | Reads `takerFee` from Settings on session start, injects into engine call |
| `server/src/controllers/backtest.controller.js` | Reads trading fees, slippage, funding from Settings on backtest start |
| `server/src/models/Settings.js` | Singleton Settings document with all exchange configuration |
| `server/src/middleware/requireBinanceCredentials.js` | Ensures .env credentials exist before trade routes |
| `server/src/utils/encryption.js` | AES-256 encrypt/decrypt for API keys |
| `engine/routers/backtest.py` | Accepts `slippagePct`, `fundingEnabled`, `fundingRate` in backtest request |
| `engine/routers/trade.py` | `POST /verify` — Binance credential test |
| `engine/core/live_bot_manager.py` | Reads `fee_rate` from session_config (injected by server) |
| `engine/services/backtest_runner.py` | Uses per-run parameters for slippage, funding instead of module constants |
