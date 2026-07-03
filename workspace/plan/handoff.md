# Session Handoff Log

Resume prompts for cross-session continuity (root `CLAUDE.md` Rule G / `AGENTS.md` → Session Handoff).

**Format rules:**
- Newest entry on top: `## <date> — <title> — <status>` with **Goal / Done / Files changed / Open questions**.
- Keep at most the **3 most recent entries**. When adding a new one, delete the oldest — git history is the archive. This file must stay a short resume prompt, not a project log.

---
## 2026-07-03 — UI Fixes: Bot Stopping State, Session List Ranking, Dashboard Section Alignments — COMPLETE ✅

**Goal:** Resolve three user-reported UI issues on the Dashboard and AlgoTrading pages. (1) Stop button disappears during `'stopping'` state, and needs to remain visible displaying "Stopping" until completely stopped. (2) Bot sessions list needs customized ranking/sorting rules: running first (last started first), then stopped (last stopped first). (3) Strategy Leaderboard title is oversized and has inconsistent margin/padding compared to other Dashboard sections. (4) Align "Live Runs", "Recent Live Runs", and "Recent Backtests" into the same row (3 columns if active live runs exist, else 2 columns).

**Done:**
1. **Stop button visibility fix:** Updated `SessionCard.jsx` to render the Stop button when `session.status === 'running' || session.status === 'stopping'`. When `stopping` is true or status is `'stopping'`, the button is disabled and its label changes to "Stopping".
2. **Bot session ranking/sorting:** Wrapped the bot session list map in `AlgoTrading.jsx` with a custom `useMemo` comparator sorting running/starting/stopping sessions first (newest `createdAt` first), followed by stopped/errored sessions (newest `stoppedAt || createdAt` first).
3. **Strategy Leaderboard style alignment:** Stripped the `<Card>`, `<CardHeader>`, `<CardTitle>`, and `<CardContent>` wraps from `StrategyLeaderboard.jsx` to remove the excessive padding/margin and double borders. Wrapped `StrategyLeaderboard` in a `<PanelSection>` component inside `Dashboard.jsx` to match the layout and title text size of other panels.
4. **Three-column layout for active runs:** Refactored the Dashboard layout to group "Live Runs" (active sessions), "Recent Live Runs" (finished sessions), and "Recent Backtests" into a single flex/grid row that dynamically adapts: 3 columns if active live runs exist, 2 columns otherwise.

**Verification done:** Build compilation verified via `npm run build`.

**Files changed:** `client/src/components/algo/SessionCard.jsx`, `client/src/pages/AlgoTrading.jsx`, `client/src/features/dashboard/StrategyLeaderboard.jsx`, `client/src/pages/Dashboard.jsx`.

---
## 2026-07-03 — Chaos Mode Diagnosis + Bot Session Caps + Testnet-Invalid Symbol Blacklist — COMPLETE ✅

**Goal:** User reported chaos-mode WS disconnect storms + TP-order 400s, then a 53-real-vs-4-tracked
open-position gap. Diagnosed root causes, fixed them, added configurable per-environment session caps
per the user's exact spec, then fixed a Chaos Wizard UI bug and a distinct testnet-symbol-validity bug
found while verifying against the live stack.

**Done:**
1. **Diagnosis + fixes (DECISIONS.md #21/#22 context, no dedicated decision entry for these — see git
   history for the 6-finding writeup):** WS reconnect thundering herd (no backoff/jitter) → capped
   exponential backoff + full jitter. Stale exchange-rules cache causing TP algoOrder 400s → periodic
   30-min refresh + loud warning on cache-miss. Quarterly/delivery contracts (e.g. `ETHUSDT_260925`)
   reaching TP placement → `contractType` filtering in `get_all_symbols()`. `stop_session()`'s serial
   close loop timing out and silently reporting `openPositions: []` regardless of what actually closed
   → bounded-concurrency (semaphore=8) close loop, only reports confirmed-closed symbols.
   `reconciliation.js` wiping `openPositions` in Mongo before confirming closes → reordered to
   close-then-write. No full-account safety net → new periodic (10 min) `reconcileFullAccountPositions`
   sweep, alert-only (does not auto-close).
2. **Configurable bot session caps (DECISIONS.md #21):** new `Settings.limits.{testnet,mainnet}.
   {maxSymbolsPerBot,maxConcurrentBots}` + `Settings.chaosMaxTotalSymbols`, replacing the removed
   `chaosMaxStrategies` (one unified concurrent-bot cap now governs both manual bots and Chaos Mode).
   Enforced in `algo.controller.js`'s `startSession()`/`startChaos()` (chaos truncates to available
   slots and reports skips via `errors`, not a hard reject); `chaosAllocator.js`'s round-robin bounded
   by both the per-strategy and run-wide caps as running counters (not pool pre-truncation, to preserve
   tier-priority mix); `Settings.jsx` UI added (testnet card live, mainnet card marked "Future" — no
   enforcement path exists for mainnet, added as pure future-proofing per user instruction); engine
   `StartSessionRequest.symbols` got a defensive `max_length=250`. Also hardcoded `_getBinanceHeaders()`
   to `'testnet'` (was reading `Settings.mode`, a latent landmine — harmless today, fixed for
   consistency with every other Binance-header call site).
3. **`ChaosWizard.jsx` fix:** its client-side allocation-preview algorithm was a stale duplicate of the
   OLD unbounded round-robin (from before item 2) and still read the removed `chaosMaxStrategies` field
   — dialog showed 120+ symbols/strategy even though the server now correctly capped and truncated on
   launch ("bots started correctly, dialog box showing wrong" — user-reported). Rewrote the preview to
   mirror `chaosAllocator.js`'s bounded algorithm exactly.
4. **Testnet-invalid-symbol blacklist (DECISIONS.md #22):** ~60 symbols in demo-fapi's `exchangeInfo`
   (status=TRADING, contractType=PERPETUAL) are rejected outright by the testnet matching engine —
   confirmed via a definitive HTTP 400 on both `leverageBracket` and real order placement for the same
   symbols. New `is_symbol_invalid()` in `utils/symbols.py` blacklists on a definitive 400 specifically
   (not 429/5xx/timeout, which stay transient/retryable); `get_all_symbols()` excludes blacklisted
   symbols from future pairlists/Chaos pools; `live_bot_manager.py` aborts a symbol's loop immediately
   (right after the leverage probe, before opening a WS connection) instead of retrying a doomed order
   every candle close forever.

**Verification done:** All Python/Node files import/load-check clean in-container after every change.
Full `docker compose down && up --build -d` cycle run twice. **Environment gotcha worth remembering:**
`engine` and `client` both have `volumes: []` in `docker-compose.yml` — they rely entirely on
`docker compose watch` for live source sync, no bind mount fallback. Running `docker compose down`/`up`
kills any active watch process; a plain `up -d` (no `--build`) after that will silently run STALE code
with no error. Always `up --build -d` after `down` unless you know watch is actively running. Also hit
(twice, unrelated to any change here) a transient MongoDB Atlas (cloud, external — `MONGO_URI` is an
`mongodb+srv://` Atlas connection string, not local Mongo) `ETIMEDOUT` on server startup; resolved both
times with a plain `docker restart` on the server container.

**Files changed:** `engine/core/live_bot_manager.py`, `engine/utils/symbols.py`, `engine/main.py`,
`engine/routers/algo.py`; `server/src/services/{reconciliation,server}.js`,
`server/src/models/Settings.js`, `server/src/controllers/{settings,algo}.controller.js`,
`server/src/utils/chaosAllocator.js`; `client/src/pages/Settings.jsx`,
`client/src/components/algo/ChaosWizard.jsx`; docs: `workspace/docs/core/{API_CONTRACTS,DECISIONS}.md`
(#21, #22), `workspace/docs/state/DEPRECATED.md`, `workspace/docs/features/{auth-settings,
algo-trading}/SPEC.md`, `engine/CLAUDE.md`.

**Open questions:** (1) `_invalid_symbols` blacklist is in-memory only, resets on engine restart —
cheap to rediscover (~60 API calls, one each) but not persisted; revisit if restart frequency makes
that wasteful. (2) `startChaos()`'s concurrent-bot-slot check is a single non-atomic query — accepted
race for now, would need a distributed lock if concurrent chaos launches become common. (3) The Chaos
Wizard preview is still a client-side algorithm duplicate of the server's, not a real preview API call
— will drift again if the server algorithm changes without a matching client update; a dedicated
`POST /api/v1/algo/chaos/preview` endpoint would remove this whole class of bug.

---
## 2026-07-02 — Dashboard: Testnet+Mainnet Balances, Live Prices, Redesign — COMPLETE (unverified against live stack) ⚠️

**Goal:** Fetch Binance account balance for BOTH testnet and mainnet and show on the Dashboard;
keep prices live; declutter + mobile-responsive redesign. User-confirmed scope: **mainnet is
READ-ONLY** (balance display only; all trading stays testnet), live prices = open-position symbols +
BTC/ETH majors, restructure freely.

**Done — all 5 phases:**
- **Phase 0 (safety):** `requireBinanceCredentials.js` now hard-pins `X-Binance-Mode: 'testnet'`
  (was `settings.mode || 'testnet'`); `saveSettingsKeys` rejects a `mode` field. Closes the gap where
  saving mainnet keys + flipping mode would route real trading to mainnet.
- **Phase 1 (server):** `Settings.js` +`encryptedMainnetApiKey`/`Secret` (additive, no migration).
  `saveSettingsKeys` takes `env: 'testnet'|'mainnet'` (mainnet requires both fields + is verified via
  engine `/trade/verify` w/ `X-Binance-Mode: mainnet` before storage). `getSettingsKeys` returns
  `hasMainnet*` flags. `verifySettings` takes `env`. New `getBalances` → `GET /api/v1/trade/balances`
  (public route, JWT only, NOT `requireBinanceCredentials`): decrypts both pairs, `Promise.all` two
  engine `/trade/account` calls, returns trimmed per-env `{configured,ok,totalWalletBalance,
  totalMarginBalance,totalUnrealizedProfit,availableBalance}`. **Engine unchanged** (mode already
  threaded).
- **Phase 2 (Settings UI):** second key form "Mainnet — Read-Only" + amber Read-Only warning box;
  removed the "Coming Soon" toast/`handleMainnetClick`; mainnet env card now "Balance monitoring only".
- **Phase 3 (data+components):** `useAccountBalances()` in `useTrade.js` (60s poll) + added
  `['trade','balances']` to `useTradeStream`'s ACCOUNT_UPDATE invalidation. New
  `features/dashboard/{TickerStrip,AccountOverview,BacktestKpiStrip,CollapsibleSection}.jsx`.
  TickerStrip reuses `useBinanceWS(<sym>@ticker)` (browser-direct, capped 8 symbols, memoized).
- **Phase 4 (layout):** rewrote `Dashboard.jsx` — order: TickerStrip → AccountOverview →
  BacktestKpiStrip → Recent Live Runs + Recent Backtests → StrategyLeaderboard → collapsible
  TimescaleDB Cache. Per-section loading (live-data failure no longer blanks backtest sections).
  Tables already scroll via the `Table` primitive's `overflow-auto`. `StatCard` now orphaned.
- **Phase 5 (docs):** dashboard SPEC, API_CONTRACTS, auth-settings SPEC, DECISIONS §9, binance-api
  §6, CURRENT_STATE, client/CLAUDE.md Dashboard spec + useTrade hooks line, server/CLAUDE.md route
  list. (MODELS.md is the quant-arch doc, not DB schema — Settings schema doc lives in auth-settings.)

**Verification done:** `node --check` on all changed server files; `vite build` succeeds (2843
modules, no errors). **NOT verified** (Docker not run this session): live balances fetch for either
env, mainnet geo-block behavior from server egress IP, ticker strip against real WS, mobile layout.

**Files changed:** `server/src/{middleware/requireBinanceCredentials.js,models/Settings.js,
controllers/trade.controller.js,routes/trade.routes.js}`; `client/src/pages/{Settings,Dashboard}.jsx`,
`client/src/hooks/useTrade.js`, `client/src/features/dashboard/{TickerStrip,AccountOverview,
BacktestKpiStrip,CollapsibleSection}.jsx`; `workspace/docs/core/{API_CONTRACTS,DECISIONS,binance-api}.md`,
`workspace/docs/features/{dashboard,auth-settings}/SPEC.md`, `workspace/docs/state/CURRENT_STATE.md`,
`{client,server}/CLAUDE.md`.

**Follow-up (same session): removed `.env` Binance key reads.** `server/src/services/reconciliation.js`
read `process.env.BINANCE_TESTNET_API_KEY`/`_SECRET` at startup and used them to close positions across
every orphaned-session symbol — a violation of the documented "credentials live in MongoDB per user,
not `.env`" invariant, and the cause of the slow serial startup loop that made the server container
`unhealthy` (reconciliation blocked `listen()` >65s past the healthcheck window). Rewrote it to resolve
per-user testnet headers from each session owner's `Settings` doc (decrypt via `encryption.js`, cached
per pass, mode pinned testnet), reusing the `_getBinanceHeaders` pattern from `algo.controller.js`.
Section 3 (re-lock manual positions) now iterates users who have keys in `Settings` and fetches
per-user (also fixed a latent bug: it called the engine with no headers and read `data.data.positions`
when the engine returns the array at `data.data`). Result: reconciliation completes instantly, server
healthy in ~20s. **Nothing in the codebase now reads Binance keys from `.env`** (grep-verified).
**Dead `.env` entries remain** (`BINANCE_TESTNET_API_KEY/SECRET`, `BINANCE_API_KEY/SECRET`,
`BINANCE_MAINNET_API_KEY/SECRET`) — left untouched per the "don't modify `.env`" rule; safe to delete.

**Open questions:** (1) Does `fapi.binance.com` `/fapi/v2/account` succeed from the server's egress
IP, or is it geo-blocked (451/-2015)? The per-env `{ok:false,error}` shape absorbs it but needs a
real check. (2) End-to-end: open a non-major testnet position → confirm it appears in TickerStrip
within 30s and the uPnL tile is nonzero. (3) Mobile 375px pass.


