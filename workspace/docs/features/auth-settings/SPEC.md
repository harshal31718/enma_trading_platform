# Feature: Authentication & Settings

**Status:** Settings implemented; Google OAuth + JWT authentication implemented (Auth Branch, shipped 2026-06-22)
**Last updated:** 2026-07-02 — full rewrite; this doc previously described the pre-Auth-Branch
single-user state (no login, `.env` credentials) which had become the exact inverse of what's
actually shipped. See `workspace/docs/state/CURRENT_STATE.md` → "Auth & Access Control" as the
higher-authority source if this doc drifts again.

---

## What It Does

Manages platform configuration: trading mode (Testnet/Mainnet), Binance API credential storage,
exchange trading settings, and multi-user access (open login + per-user Algo Trading gate). The Exchange Settings section
centralizes all trading parameters (fees, slippage, funding, risk defaults, Chaos Mode defaults) —
all values are stored as variables, not hardcoded, and are scoped per user. **Authentication is
Google OAuth 2.0 + JWT**: `server/src/config/passport.js` (Passport, sessionless), issuing a 7-day
JWT in an `httpOnly` cookie (`enma_jwt`), verified by `verifyJWT` middleware
(`server/src/middleware/auth.middleware.js`) mounted on all `/api/v1/*` routes except `/auth/*` and
`/health`. **Login is open** — any valid Google account signs in. Feature access is gated per-user:
the `requireAlgoAccess` middleware gates only the Algo Trading start actions
(`POST /algo/sessions`, `POST /algo/chaos`); admins bypass via role. Users request access from
Settings; an admin panel (`requireAdmin`-gated) grants/revokes it per user.

---

## Data Flow

### Settings page — API keys (two environments)

```
Client navigates to Settings page
        ↓
GET /api/v1/trade/settings/keys
        ↓
Server reads Settings collection
        ↓
Returns: { mode: 'testnet', hasApiKey, hasApiSecret,
           hasMainnetApiKey, hasMainnetApiSecret }   (booleans; mode always 'testnet')

User saves TESTNET keys (trading pair)
        ↓
POST /api/v1/trade/settings/keys  { env: 'testnet', apiKey?, apiSecret? }
        ↓
Server encrypts + writes encryptedApiKey/Secret (partial update allowed)

User saves MAINNET keys (read-only, balance display)
        ↓
POST /api/v1/trade/settings/keys  { env: 'mainnet', apiKey, apiSecret }   (both required)
        ↓
Server calls engine POST /trade/verify (X-Binance-Mode: mainnet) BEFORE storing
        ↓ (invalid) 400 VERIFICATION_FAILED, nothing saved
        ↓ (valid)   encrypts + writes encryptedMainnetApiKey/Secret
```

> Sending a `mode` field to `POST /settings/keys` is **rejected** (400). Mainnet is read-only —
> trading cannot be switched to mainnet; `X-Binance-Mode` is pinned to `testnet` on all trade routes.

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

### Authentication — Google OAuth + JWT

```
Client hits "Sign in with Google" → GET /api/v1/auth/google
        ↓
Redirects to Google OAuth consent (Passport, scopes: profile email, sessionless)
        ↓
Google redirects → GET /api/v1/auth/google/callback
        ↓ (login is open — no whitelist check)
Upsert User doc (googleId, email, name, avatar, lastLoginAt); ADMIN_EMAIL auto-promoted to role admin
        ↓
Sign 7-day JWT ({ userId, role })
        ↓
Set httpOnly enma_jwt cookie (sameSite: lax, secure in prod) → redirect to CLIENT_URL/
(genuine OAuth error → CLIENT_URL/login?error=auth_failed)

Every subsequent /api/v1/* request (except /auth/*, /health):
        ↓
verifyJWT middleware reads enma_jwt cookie, verifies, attaches req.user (lean User doc)
        ↓ (invalid/missing)              ↓ (valid)
401 UNAUTHORIZED                     Controller runs, scoped to req.user.id

Socket.IO: io.use() middleware parses the same cookie, verifies JWT, attaches socket.user;
on connection the socket joins room user:<userId>. All server emits use
io.to('user:<userId>').emit(...) — never a global io.emit().

Logout: POST /api/v1/auth/logout clears the enma_jwt cookie.
```

`requireAdmin` (checks `req.user.role === 'admin'`) gates `GET /api/v1/admin/users` and
`PATCH /api/v1/admin/users/:id/algo-access`. `requireAlgoAccess` (passes if `role === 'admin'` OR
`algoAccess.status === 'granted'`; else 403 `ALGO_ACCESS_REQUIRED`) gates the Algo start actions
(`POST /algo/sessions`, `POST /algo/chaos`). Users self-request via `POST /api/v1/algo/access-request`
(idempotent `none`→`requested`). Access state lives on the `User` doc (`algoAccess.status`); since
`verifyJWT` reloads the user each request, grants/revokes take effect immediately without re-login.
The former `PlatformConfig` email whitelist and `/admin/allowed-emails` CRUD were removed 2026-07-07.

---

## Service Responsibilities

| Layer | Owns | Does NOT own |
|-------|------|-------------|
| Client | Settings form, mode selector | Credential storage |
| Node server | Settings MongoDB doc, credential injection into proxy headers | Credential validation |
| Python engine | Binance credential test call | Storing credentials |

---

## Key Invariants

- **Credentials live in MongoDB, per user, AES-256 encrypted.** The testnet trading pair is
  `encryptedApiKey`/`encryptedApiSecret`; the mainnet read-only pair is
  `encryptedMainnetApiKey`/`encryptedMainnetApiSecret`. All four are encrypted/decrypted via
  `server/src/utils/encryption.js`. `requireBinanceCredentials.js` decrypts the **testnet** pair
  per-request for trade routes (mainnet keys are used only by `getBalances`). Not read from `.env`.
- **Mainnet is read-only.** Mainnet keys must be created on Binance with **Read Only** permission and
  are used solely to display the mainnet balance on the Dashboard (`GET /api/v1/trade/balances`). They
  are verified against Binance before storage. `X-Binance-Mode` is pinned to `testnet` on every trade
  route (`requireBinanceCredentials.js`), so a mainnet key can never reach an order endpoint even if it
  were (incorrectly) granted trade permission. See `DECISIONS.md`.
- **Multi-user, open login + per-feature gating.** `userId` scopes every mutable Mongoose model (`BacktestResult`,
  `BacktestTrade`, `BacktestLeverageScenario`, `LiveSession`, `Settings`, `TradeOrder`,
  `TradeExecution`, `TradeTransaction`, `TradeRecord`). `Strategy` stays global by design — no
  `userId`. Login is open to any Google account; Algo Trading start actions are gated per-user via
  `requireAlgoAccess` (`User.algoAccess.status`), granted/revoked by admins.
- **Do not modify `.env` files.** Settings changes (mode, credentials, risk defaults, etc.) go to each
  user's MongoDB `Settings` doc only.
- **Mainnet trading not implemented (by design).** Only mainnet *balance display* is supported
  (read-only). All orders target Testnet. The `mode` field is vestigial (retained to avoid a
  migration); it no longer switches trade routing.

---

## MongoDB Settings Model

**Collection:** `settings`
**Document:** One per user — `userId` field, required + unique (not a singleton)

| Field | Type | Description |
|-------|------|-------------|
| `userId` | ObjectId | Required, unique — owning user |
| `encryptedApiKey` / `encryptedApiSecret` | String | AES-256 encrypted **testnet** Binance credentials (trading pair) |
| `encryptedMainnetApiKey` / `encryptedMainnetApiSecret` | String | AES-256 encrypted **mainnet** credentials — READ-ONLY, balance display only (verified before storage) |
| `mode` | Enum | `'testnet'` or `'mainnet'` — **vestigial**; trading is pinned to testnet regardless |
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
| `chaosMaxManualSymbols` | Number | Max hand-picked symbols per strategy, default 5 |
| `chaosDefaultCapital` | Number | Per-strategy capital pre-fill, default 500 |
| `chaosDefaultLeverage` | Number | Leverage pre-fill, default 50 |
| `chaosDefaultTimeframe` | String | Default chaos timeframe, default `'1m'` |
| `chaosMaxTotalSymbols` | Number | Ceiling on symbols across one whole chaos run (all strategies combined), default 120, max 250 (2026-07-03) |
| **Bot Session Limits** (`limits.*`, 2026-07-03) | | |
| `limits.testnet.maxSymbolsPerBot` | Number | Per-bot symbol cap, default 15, max 30. Applies to manual bots and each Chaos strategy |
| `limits.testnet.maxConcurrentBots` | Number | Max simultaneously running sessions (manual + Chaos combined), default 10, max 20. Supersedes the removed `chaosMaxStrategies` |
| `limits.mainnet.maxSymbolsPerBot` / `limits.mainnet.maxConcurrentBots` | Number | Same shape as testnet. Future-proofing only — no code path can start a mainnet session today |
| `globalHardLimits` | Object | Risk Dashboard: `{ maxLeverageAllowed, maxSessionDrawdown, maxRiskPctPerTrade, cooldownPeriodHours }` |
| `strategyOverrides` | Object | Risk Dashboard: `{ [strategyName]: { riskPct?, riskRewardRatio?, maxSessionDrawdown?, liqBufferPct?, minEdgeMult?, customAtrMult? } }` |
| `symbolOverrides` | Object | Risk Dashboard: `{ [symbol]: { maxLeverage?, volatilityMultiplier?, maxExposureNotional? } }` |

---

## Auth Status

| Component | Status | Notes |
|-----------|--------|-------|
| `GET /api/v1/auth/google` / `/google/callback` | **Implemented** | `server/src/routes/auth.routes.js`, `auth.controller.js`, Passport Google OAuth 2.0 |
| `POST /api/v1/auth/logout`, `GET /api/v1/auth/me` | **Implemented** | Same files as above |
| JWT middleware (`verifyJWT`, `requireAdmin`) | **Implemented** | `server/src/middleware/auth.middleware.js`, mounted on all `/api/v1/*` routes |
| Login gate in UI | **Implemented** | `client/src/pages/Login.jsx`; unauthenticated requests 401 via `verifyJWT` |
| `User` model | **Implemented** | `server/src/models/User.js` (`googleId`, `email`, `name`, `avatar`, `role`, `isActive`, `algoAccess`) |
| Per-user algo-access gate | **Implemented** | `requireAlgoAccess` in `auth.middleware.js`; admin grant/revoke via `admin.routes.js` (`/admin/users*`); user request via `/algo/access-request` |

---

## REST Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/trade/settings/keys` | Key-status booleans for both envs (testnet + mainnet) |
| POST | `/api/v1/trade/settings/keys` | Save keys for `env: 'testnet'\|'mainnet'` (mainnet verified before save; `mode` rejected) |
| POST | `/api/v1/trade/settings/verify` | Verify Binance API credentials for the selected `env` |
| GET | `/api/v1/trade/balances` | Combined testnet + mainnet balance snapshot (backs Dashboard `AccountOverview`) |
| GET | `/api/v1/settings/exchange` | Get all exchange settings (fees, defaults, simulation, risk, chaos params) — per-user |
| PUT | `/api/v1/settings/exchange` | Update exchange settings — per-user |
| GET | `/api/v1/auth/google` | Begin Google OAuth flow |
| GET | `/api/v1/auth/google/callback` | Google OAuth callback — issues JWT cookie |
| POST | `/api/v1/auth/logout` | Clear JWT cookie |
| GET | `/api/v1/auth/me` | Current user identity (incl. `algoAccess`) |
| GET | `/api/v1/admin/users` | Admin-only user list (`requireAdmin`) |
| PATCH | `/api/v1/admin/users/:id/algo-access` | Admin-only grant/revoke (`requireAdmin`) |
| POST | `/api/v1/algo/access-request` | User requests Algo Trading access |

---

## Related Files

| File | Role |
|------|------|
| `client/src/pages/Settings.jsx` | Environment Configuration + Exchange Settings form (4 sections) |
| `client/src/hooks/useExchangeSettings.js` | TanStack Query hooks: `useExchangeSettings()` (GET), `useUpdateExchangeSettings()` (PUT) |
| `client/src/hooks/useAuth.js` | TanStack Query: `useAuth()` (`GET /auth/me`, 5-min stale, 401→null), `useLogout()` |
| `client/src/pages/Login.jsx` | Google OAuth entry point (public route) |
| `client/src/pages/AdminPanel.jsx` | Admin-only user table: grant/revoke algo access, category filter + sort |
| `client/src/components/algo/NewSessionWizard.jsx` | Pre-fills capital/leverage from `defaultBotCapital`/`defaultBotLeverage` |
| `server/src/routes/settings.routes.js` | Exchange settings GET + PUT routes |
| `server/src/routes/trade.routes.js` | Settings keys routes (GET + POST + verify) |
| `server/src/routes/auth.routes.js` | Google OAuth routes (unprotected) |
| `server/src/routes/admin.routes.js` | Allowed-emails CRUD (`requireAdmin`) |
| `server/src/controllers/settings.controller.js` | `getExchangeSettings`, `updateExchangeSettings` |
| `server/src/controllers/trade.controller.js` | `getSettingsKeys`, `saveSettingsKeys`, `verifySettings`, `getBalances` |
| `server/src/controllers/auth.controller.js` | OAuth callback, JWT issuance, `/me`, logout |
| `server/src/controllers/admin.controller.js` | User management: `listUsers` + `setUserAlgoAccess` |
| `server/src/controllers/algo.controller.js` | Reads `takerFee` from Settings on session start, injects into engine call |
| `server/src/controllers/backtest.controller.js` | Reads trading fees, slippage, funding from Settings on backtest start |
| `server/src/config/passport.js` | Google OAuth 2.0 strategy (sessionless) |
| `server/src/middleware/auth.middleware.js` | `verifyJWT`, `requireAdmin` |
| `server/src/models/User.js` | `googleId`, `email`, `name`, `avatar`, `role`, `isActive`, `algoAccess` |
| `server/src/models/Settings.js` | Per-user Settings document with all exchange configuration + encrypted credentials |
| `server/src/middleware/requireBinanceCredentials.js` | Decrypts per-user MongoDB credentials before trade routes |
| `server/src/utils/encryption.js` | AES-256 encrypt/decrypt for API keys |
| `engine/routers/backtest.py` | Accepts `slippagePct`, `fundingEnabled`, `fundingRate` in backtest request |
| `engine/routers/trade.py` | `POST /verify` — Binance credential test |
| `engine/core/live_bot_manager.py` | Reads `fee_rate` from session_config (injected by server) |
| `engine/services/backtest_runner.py` | Uses per-run parameters for slippage, funding instead of module constants |
