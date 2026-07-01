# Plan: Google OAuth + Multi-User Support

## Context

Enma was built single-user (no `user_id` anywhere by design). We are adding:
- **Google OAuth** login gate — invite-only, email whitelist managed by admin
- **Full data isolation** — each user has their own Binance account, API keys, backtests, live sessions, and trades
- **Shared strategies** — strategy files and metadata stay global (no per-user partitioning)
- **Public landing page** — explains invite-only nature, has "Sign in with Google" CTA

This overrides the previous constraint of "no user_id on any Mongoose model". The server `CLAUDE.md` and `AGENTS.md` must be updated after implementation (Phase 6) to reflect the new multi-user architecture.

**Auth pattern:** Google OAuth → Passport.js → server issues signed JWT in `httpOnly` cookie → all `/api/v1/*` routes protected by `verifyJWT` middleware → Socket.IO handshake reads the same cookie.

**Invite system:** Admin adds trusted emails to a `PlatformConfig` MongoDB singleton. Users sign in with Google; if their email isn't on the list, they're redirected to the landing page with `?error=not_invited`.

**Admin model:** Single hardcoded `ADMIN_EMAIL` in `.env`. When that email logs in via Google, the server auto-promotes `role = 'admin'`. Admin sees the same app plus one extra page (`/admin`) to manage the email whitelist. Admin has **no access to any user's data** (backtests, sessions, trades, settings).

---

## Existing Data Migration

> **Decision needed before Phase 3:** If existing MongoDB documents (BacktestResult, LiveSession, etc.) contain test data that can be discarded, treat them as orphaned — no migration needed. If any data must be kept, a backfill script is required to stamp a `userId` on all existing documents. Confirm before starting Phase 3.

---

## New Packages

**Server** (add to `server/package.json`):
- `passport`
- `passport-google-oauth20`
- `jsonwebtoken`
- `cookie-parser`

**Client:** none — the Google sign-in is a plain `<a href="/api/v1/auth/google">` anchor.

---

## New Environment Variables (root `.env`)

```
GOOGLE_CLIENT_ID=<from Google Cloud Console>
GOOGLE_CLIENT_SECRET=<from Google Cloud Console>
ADMIN_EMAIL=admin.enmaquant@gmail.com
JWT_SECRET=<long random string>
# ENCRYPTION_KEY already exists (used by encryption.js for API key AES-256-GCM)
```

Google Cloud Console setup (prerequisite — must exist before Phase 1 can be tested):
1. Create project → APIs & Services → Credentials → OAuth 2.0 Client ID (Web application)
2. Authorized redirect URIs: `http://localhost:5000/api/v1/auth/google/callback` (dev) + production URL
3. App status: **Testing** — add trusted test user emails manually

---

## Phase 1 — Auth Foundation (Server)

### New Models

**`server/src/models/User.js`**
```
googleId: String, required, unique, indexed
email: String, required, unique, lowercase, indexed
name: String, required
avatar: String, default ''
role: String, enum ['user','admin'], default 'user'
isActive: Boolean, default true
lastLoginAt: Date
timestamps: true
```

**`server/src/models/PlatformConfig.js`** (singleton, `_id: 'platform'`)
```
allowedEmails: [{ email: String (lowercase), addedBy: String, addedAt: Date }]
```
On server startup: if no PlatformConfig doc exists, create one with `allowedEmails: [{ email: ADMIN_EMAIL }]`.

### New Config: `server/src/config/passport.js`

Register `GoogleStrategy`:
- `callbackURL: ${SERVER_URL}/api/v1/auth/google/callback`
- scope: `['profile', 'email']`
- Verify callback:
  1. Lowercase the Google profile email
  2. Check `PlatformConfig.allowedEmails` — if not found: `done(null, false, { message: 'not_invited' })`
  3. `User.findOneAndUpdate({ googleId }, { $set: { email, name, avatar, lastLoginAt } }, { upsert: true, new: true })`
  4. If `email === ADMIN_EMAIL` and `user.role !== 'admin'` → promote to admin
  5. `done(null, user)`

Call `passport.initialize()` only — **no** `passport.session()`.

### New Middleware: `server/src/middleware/auth.middleware.js`

**`verifyJWT(req, res, next)`**:
- Read `req.cookies?.enma_jwt`
- `jwt.verify(token, JWT_SECRET)` → look up `User.findById(decoded.userId)`
- If missing/inactive → `ApiError(401, 'UNAUTHORIZED')`
- Attach `req.user = user` and `next()`

**`requireAdmin(req, res, next)`**:
- `req.user?.role !== 'admin'` → `ApiError(403, 'FORBIDDEN')`

### New Routes + Controllers

**`server/src/routes/auth.routes.js`**
```
GET  /api/v1/auth/google           → passport.authenticate('google')
GET  /api/v1/auth/google/callback  → passport.authenticate → googleCallback
POST /api/v1/auth/logout           → logout
GET  /api/v1/auth/me               → verifyJWT → getMe
```

**`server/src/controllers/auth.controller.js`**
- `googleCallback`: on success → sign JWT (`{ userId, role }`, 7d) → set cookie (`httpOnly, secure in prod, sameSite: 'lax'`) → redirect to `CLIENT_URL/dashboard`. On failure (`not_invited`) → redirect to `CLIENT_URL/?error=not_invited`
- `logout`: `res.clearCookie('enma_jwt')` → JSON success
- `getMe`: return `{ id, email, name, avatar, role }` from `req.user`

**`server/src/routes/admin.routes.js`** (all behind `verifyJWT + requireAdmin`)
```
GET    /api/v1/admin/allowed-emails
POST   /api/v1/admin/allowed-emails         body: { email }
DELETE /api/v1/admin/allowed-emails/:email
```

**`server/src/controllers/admin.controller.js`**
- `getAllowedEmails`: `PlatformConfig.findById('platform')` → return `allowedEmails`
- `addAllowedEmail`: check email exists first, then `$push` if not present (avoid duplicates)
- `removeAllowedEmail`: `$pull: { allowedEmails: { email: req.params.email.toLowerCase() } }`

Note: No `listUsers` endpoint — admin only manages the email whitelist. Admin has no visibility into user data.

### Rewrite `server/src/app.js`

```js
app.use(cookieParser())        // ADD — must be before verifyJWT
app.use(helmet())
app.use(cors({ origin: CLIENT_URL, credentials: true }))  // ADD credentials: true
app.use(morgan('dev'))
app.use(express.json())
app.use(passport.initialize()) // ADD

// Unprotected
app.get('/api/v1/health', ...)
app.use('/api/v1/auth', authRoutes)   // ADD — must be BEFORE verifyJWT
app.use('/internal', internalRoutes)  // stays unprotected (engine callbacks)

// Protected — apply verifyJWT to all remaining /api/v1/* routes
app.use('/api/v1', verifyJWT)         // ADD
app.use('/api/v1/strategies', strategyRoutes)
app.use('/api/v1/candles', candleRoutes)
// ... all other existing routes ...
app.use('/api/v1/admin', adminRoutes) // ADD

app.use(errorHandler)
```

Note: `cors` must have `credentials: true` or the browser won't send cookies cross-origin.

### Socket.IO Auth: `server/src/config/socket.js`

Add `io.use()` middleware before `io.on('connection')`:
```js
io.use(async (socket, next) => {
  const cookies = parseCookies(socket.handshake.headers.cookie)
  const token = cookies.enma_jwt
  if (!token) return next(new Error('UNAUTHORIZED'))
  const decoded = jwt.verify(token, JWT_SECRET)
  const user = await User.findById(decoded.userId).lean()
  if (!user?.isActive) return next(new Error('UNAUTHORIZED'))
  socket.user = user
  next()
})
```

In `connection` handler: immediately `socket.join(`user:${socket.user._id}`)`.

---

## Phase 2 — Per-User Settings + API Keys (Server)

### Migrate `server/src/models/Settings.js`

Changes:
1. Remove `_id: { type: String, default: 'global' }` — use MongoDB auto ObjectId
2. Add `userId: { type: String, required: true, unique: true, index: true }`
3. Add `encryptedApiKey: { type: String, default: '' }`
4. Add `encryptedApiSecret: { type: String, default: '' }`

All other fields unchanged.

**Migration note:** The existing `_id: 'global'` document becomes orphaned but doesn't break anything — first user login creates a fresh Settings doc. No automated migration needed for Settings.

### Rewrite `server/src/controllers/settings.controller.js`

Helper:
```js
function _getOrCreate(userId) {
  return Settings.findOneAndUpdate(
    { userId },
    { $setOnInsert: { userId } },
    { upsert: true, new: true }
  )
}
```

Replace every `Settings.findById('global')` → `Settings.findOne({ userId: req.user.id })`.
Replace every `Settings.findByIdAndUpdate('global', ...)` → `Settings.findOneAndUpdate({ userId: req.user.id }, ..., { upsert: true, new: true })`.

### Rewrite `server/src/middleware/requireBinanceCredentials.js`

```js
const settings = await Settings.findOne({ userId: String(req.user._id) })
const apiKey = settings?.encryptedApiKey ? decrypt(settings.encryptedApiKey) : ''
const apiSecret = settings?.encryptedApiSecret ? decrypt(settings.encryptedApiSecret) : ''
if (!apiKey || !apiSecret) throw new ApiError(400, 'NO_CREDENTIALS', 'Binance API keys not configured. Add them in Settings.')
req.binanceHeaders = { 'X-Binance-API-Key': apiKey, 'X-Binance-API-Secret': apiSecret, 'X-Binance-Mode': settings?.mode || 'testnet' }
```

Uses existing `server/src/utils/encryption.js` (`encrypt`/`decrypt`) — already AES-256-GCM, already reads `ENCRYPTION_KEY` from env.

### Update `server/src/controllers/trade.controller.js`

**`getSettingsKeys`**: return `{ mode, hasApiKey: !!(settings?.encryptedApiKey), hasApiSecret: !!(settings?.encryptedApiSecret) }` — never return raw keys.

**`saveSettingsKeys`**: accept `{ apiKey, apiSecret, mode }` → encrypt + store in user's Settings via `findOneAndUpdate({ userId }, $set, { upsert: true })`.

**`verifySettings`**: read + decrypt from user's Settings instead of `process.env`.

### Fix `_getBinanceHeaders` in `server/src/controllers/algo.controller.js`

This function is called from `/internal/*` routes (no `req.user`). Change signature to accept `sessionId`:
```js
async function _getBinanceHeaders(sessionId) {
  const session = await LiveSession.findById(sessionId).select('userId').lean()
  const settings = await Settings.findOne({ userId: session.userId })
  const apiKey = decrypt(settings?.encryptedApiKey || '')
  const apiSecret = decrypt(settings?.encryptedApiSecret || '')
  if (!apiKey || !apiSecret) throw new Error(`No Binance credentials for session ${sessionId}`)
  return { 'X-Binance-API-Key': apiKey, 'X-Binance-API-Secret': apiSecret, 'X-Binance-Mode': settings?.mode || 'testnet' }
}
```

Update all callers (`handleAlgoPlaceOrder`, `handleAlgoClosePosition`, `handleAlgoSetLeverage`, `handleAlgoGetPosition`, `handleAlgoGetOpenOrders`) to pass `req.params.id`.

### Risk controller: `server/src/controllers/risk.controller.js`

- Replace `Settings.findById('global')` → `Settings.findOne({ userId: req.user.id })`
- Change Redis cache key: `risk:live-metrics:${req.user.id}` (was `risk:live-metrics:global`)
- Each user sees only their own risk data (no global aggregate for admin)

---

## Phase 3 — Data Isolation (Server Models + Controllers)

### Add `userId` to Mongoose Models

Add `userId: { type: String, required: true, index: true }` to:
- `BacktestResult.js` — also add compound index `{ userId: 1, createdAt: -1 }`
- `BacktestTrade.js`
- `BacktestLeverageScenario.js`
- `LiveSession.js`
- `TradeOrder.js`
- `TradeExecution.js`
- `TradeTransaction.js`
- `TradeRecord.js` — use `required: false` (engine is sole writer; field added gradually after engine update)

**Strategy.js: NO change** — stays global/shared.

> See migration decision above. If existing documents can be discarded, proceed. Otherwise add a backfill step here before marking Phase 3 complete.

### Controller Query Changes

**`backtest.controller.js`**:
- `runBacktest`: add `userId: req.user.id` to `BacktestResult.create(...)` and to the BullMQ job payload
- `listBacktests`: add `filter.userId = req.user.id`
- `getBacktest`, `cancelBacktest`, `getBacktestBenchmark`: `BacktestResult.findOne({ jobId, userId: req.user.id })`
- `getBacktestTrades`: verify BacktestResult ownership first, then query trades by jobId

**`algo.controller.js`**:
- `startSession`: add `userId: req.user.id` to `LiveSession.create(...)`; pass `user_id`, `api_key` (decrypted), `api_secret` (decrypted) to the engine
- `startChaos`: decrypt API keys once before the loop; add `userId` to every `LiveSession.create(...)`
- `listSessions`: `LiveSession.find({ userId: req.user.id })`
- `getSession`, `stopSession`, `setTradingState`, `deleteSession`, `getSessionEquity`: use `LiveSession.findOne({ _id: req.params.id, userId: req.user.id })`
- `deleteAllStopped`: add `userId: req.user.id` to the `deleteMany` filter
- `handleEngineStats` (internal, no `req.user`): fetch `session.userId` from DB, then emit to `user:${session.userId}` room instead of broadcast

**`dashboard.controller.js`**:
- Pass `userId: req.user.id` as query param to engine: `engineClient.get('/dashboard/stats', { params: { userId: req.user.id } })`
- Same for `/dashboard/performance-calendar`

**`orderHistory.controller.js`**:
- Add `filter.userId = req.user.id` to the TradeRecord query

**`trade.controller.js`** (TradeOrder/Execution/Transaction):
- `upsertTradeOrder()`: add `userId: req.user.id` to the `$set`
- `getTradeOrders`, `getTradeExecutions`, `getTradeTransactions`: add `userId: req.user.id` to filter

### Socket.IO Emit Scoping

Change all `io.emit(...)` calls in `algo.controller.js` to room-scoped:
```js
io.to(`user:${session.userId}`).emit('algo:session:update', {...})
io.to(`user:${session.userId}`).emit('algo:session:log', {...})
io.to(`user:${session.userId}`).emit('algo:position:open', {...})
io.to(`user:${session.userId}`).emit('algo:position:close', {...})
```

Backtest emits (`io.to('backtest:{jobId}').emit(...)`) are already room-scoped — no change needed.

### Backtest Worker: `server/src/workers/backtest.worker.js`

Destructure `userId` from `job.data` and forward to engine:
```js
const { jobId, userId, ...rest } = job.data
await engineClient.post('/backtest/run', { jobId, userId, ...rest })
```

---

## Phase 4 — Engine Changes

### `engine/routers/backtest.py`

Add to `BacktestRequest` Pydantic model:
```python
user_id: str = ""
```
Pass `user_id=request.user_id` to `run_backtest_simulation()`.

### `engine/services/backtest_runner.py`

Signature: `async def run_backtest_simulation(..., user_id: str = ""):`

In the MongoDB success-path write (`update_one`): add `"userId": user_id` to the `$set` dict.

In the bulk trade insert: add `"userId": user_id` to each doc in `trade_docs`.

### `engine/services/trade_recorder.py`

Add `user_id: str = ""` parameter to `build_trade_record(*)` and add `"userId": user_id` to the returned dict.

### `engine/routers/algo.py`

Add to `StartSessionRequest`:
```python
user_id: str = ""
api_key: str = ""
api_secret: str = ""
```

Since `session_config = request.model_dump()` passes the full model, these fields flow into `live_bot_manager.start_session()` automatically.

### `engine/core/live_bot_manager.py`

In `start_session()`, extract from config:
```python
user_id = session_config.get("user_id", "")
api_key = session_config.get("api_key", "")
api_secret = session_config.get("api_secret", "")
```

Store in per-session dict: `self.sessions[session_id]["user_id"] = user_id`, `["api_key"] = api_key`, `["api_secret"] = api_secret`.

Create a **per-session** `UserDataStreamManager`:
```python
from services.user_data_stream import UserDataStreamManager
uds = UserDataStreamManager(api_key=api_key, api_secret=api_secret)
await uds.start()
self.sessions[session_id]["uds_manager"] = uds
```

Replace ALL `os.getenv("BINANCE_TESTNET_API_KEY")` → `session["api_key"]`
Replace ALL `os.getenv("BINANCE_TESTNET_SECRET")` → `session["api_secret"]`

In `stop_session()`: `await self.sessions[session_id]["uds_manager"].stop()` before cleanup.

In all `build_trade_record(...)` calls: add `user_id=session.get("user_id", "")`.

### `engine/services/user_data_stream.py`

Change `__init__` to accept credentials:
```python
def __init__(self, api_key: str = "", api_secret: str = "") -> None:
    self._api_key = api_key
    self._api_secret = api_secret
    ...
```

Replace `os.getenv("BINANCE_TESTNET_API_KEY")` → `self._api_key` everywhere in the file.
Replace `os.getenv("BINANCE_TESTNET_SECRET")` → `self._api_secret` everywhere.

**Remove the module-level singleton:** delete `user_data_stream = UserDataStreamManager()`.

### `engine/main.py`

Remove global UDS startup/shutdown from the lifespan context — UDS is now lifecycle-managed per session.

### `engine/routers/dashboard.py`

Both `get_dashboard_stats` and `get_performance_calendar` accept optional `userId: str = Query(default=None)` and add `{ "userId": userId }` to the MongoDB filter when provided.

---

## Phase 5 — Client

### New `client/src/pages/Landing.jsx` (public, no Navbar)

- Route: `/` (replaces the redirect to Dashboard)
- Full-screen dark layout (`bg-[#060a0f]`), ENMA wordmark in `text-emerald-400`
- "This platform is invite-only. Trusted members only."
- "Sign in with Google" — `<a href="/api/v1/auth/google">` (plain anchor, full-page navigation)
- Read `?error=not_invited` via `useSearchParams` → show inline error banner

### New `client/src/hooks/useAuth.js`

```js
export function useAuth() {
  const { data: user, isLoading } = useQuery({
    queryKey: ['auth', 'me'],
    queryFn: () => api.get('/api/v1/auth/me').then(r => r.data.data),
    retry: false,
    staleTime: 5 * 60 * 1000,
  })
  return { user: user ?? null, isLoading, isAuthenticated: !!user }
}
```

### New `client/src/components/auth/ProtectedRoute.jsx`

```jsx
export default function ProtectedRoute({ children }) {
  const { user, isLoading } = useAuth()
  if (isLoading) return <div className="min-h-screen bg-[#060a0f]" />
  if (!user) return <Navigate to="/" replace />
  return children
}
```

### Rewrite `client/src/App.jsx`

- `/` → `<Landing />` (public, no Navbar)
- `/dashboard` → Dashboard (moved from `/`; all existing routes stay, prefixed under ProtectedRoute)
- All existing routes wrapped in `<ProtectedRoute>` inside a `<Layout>` (Navbar wrapper)
- Add `/admin` → `<AdminPanel />` (behind ProtectedRoute; server enforces admin role)

### Update `client/src/lib/axios.js`

Add `withCredentials: true` and a 401 interceptor → `window.location.href = '/'`.

### Update `client/src/lib/socket.js`

Add `withCredentials: true`.

### Update `client/src/components/layout/Navbar.jsx`

- Dashboard nav item: `to="/"` → `to="/dashboard"`
- Right side: user avatar + name + Logout button
- Admin nav item (role=admin only) → `/admin`

### Update `client/src/pages/Settings.jsx`

Add "API Keys" section: configure/verify Binance API key + secret per user. Show configured status badges only (no pre-filling inputs with raw keys).

### New `client/src/pages/AdminPanel.jsx`

Single-page interface for the admin email. Shows:
- List of allowed emails (email + date added)
- Add email form
- Remove button per email

No user data visible. No stats. No user list.

---

## Phase 6 — Docs + Architecture Update

- Update `server/CLAUDE.md`: remove single-user constraints, document auth architecture
- Update `workspace/docs/state/CURRENT_STATE.md`: remove single-user constraint from Current Constraints table, document auth under Implemented Features
- Update `AGENTS.md`: reflect new multi-user architecture
- Run `/sync-spec`

---

## Edge Cases + Warnings

| Issue | Resolution |
|-------|-----------|
| `sameSite: 'lax'` required | `strict` drops the cookie on Google redirect-back |
| `cors credentials: true` | Required or browser won't send cookie cross-origin |
| `startChaos` multiple sessions | Decrypt API keys once before loop |
| `/internal/*` has no `req.user` | `_getBinanceHeaders(sessionId)` looks up userId via LiveSession |
| `TradeRecord.userId` engine-written | Set `required: false` on Mongoose model |
| Dashboard route `/` → `/dashboard` | Update Navbar link + any internal `navigate('/')` calls |
| Strategy queries | NO userId filter — strategies are shared |
| Admin email whitelist | ADMIN_EMAIL always present in whitelist (seeded on startup); cannot be removed via API |

---

## Verification

### Auth Flow
1. `/` → Landing page, no Navbar
2. "Sign in with Google" → OAuth → `/dashboard`
3. Any `/api/v1/*` without cookie → 401

### Invite Flow
1. Admin adds email → user signs in → access granted
2. Remove email → user signs in again → `?error=not_invited`
3. Non-admin → `/api/v1/admin/*` → 403

### Data Isolation
1. User A runs backtest → User B cannot see it via `GET /api/v1/backtest`
2. User A calls `GET /api/v1/backtest/:userA-jobId` as User B → 404

### Admin Panel
1. Admin can add/remove emails from the whitelist
2. Admin cannot access any user's backtests, sessions, or settings
3. Removing ADMIN_EMAIL from whitelist via API is blocked (server enforces this)
