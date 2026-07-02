# Session Handoff Log

Resume prompts for cross-session continuity (root `CLAUDE.md` Rule G / `AGENTS.md` → Session Handoff).

**Format rules:**
- Newest entry on top: `## <date> — <title> — <status>` with **Goal / Done / Files changed / Open questions**.
- Keep at most the **3 most recent entries**. When adding a new one, delete the oldest — git history is the archive. This file must stay a short resume prompt, not a project log.

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

---
## 2026-07-02 — Manual Trading WebSocket User Data Stream (Tier 3 fix) — COMPLETE ✅

**Goal:** User picked "Tier 3" from a 3-tier options list for fixing the `open-orders` rate-limit
weight problem found in the prior session (see entry below) — replace the Trade page's
high-frequency REST polling with the same WebSocket User Data Stream mechanism already built for
live bots (`UserDataStreamManager`, F-020), per Binance's own recommended architecture, rather than
a smaller mechanical fix. Explicitly scoped as a real cross-service feature build (6 phases,
outlined upfront per Rule F) — not a quick doc/API-url correction like the prior two fixes.

**Done — all 6 phases:**
1. **`engine/services/user_data_stream.py`**: added `register_stream_callback()`/
   `unregister_stream_callback()` — an unfiltered dispatch path firing on every
   `ORDER_TRADE_UPDATE` status and every `ACCOUNT_UPDATE`, kept fully separate from the existing
   per-symbol FILLED-only `register_fill_callback()` path the live bot uses, so live-trading fill
   detection was not touched.
2. **New `engine/services/manual_trade_stream.py`**: per-user registry — `start_for_user`/
   `stop_for_user`, a 5-minute idle reaper (heartbeat-based), publishes events to Redis
   `trade-stream:{userId}`.
3. **`engine/routers/trade.py`**: `POST /trade/stream/start` / `/stop`, `userId` as a query param
   (matching the existing dashboard-stats convention for user-scoped engine endpoints).
4. **Server**: `POST /api/v1/trade/stream/start` / `/stop` (`trade.controller.js`,
   `trade.routes.js`); `socketEmitter.js` gained `subscribeToTradeStream`/`unsubscribeFromTradeStream`
   relaying `trade-stream:{userId}` → `io.to('user:{userId}').emit('trade:stream-update', ...)`.
5. **Client**: `useTradeStream()` in `useTrade.js` — starts on mount, 120s heartbeat re-POST, stops
   on unmount; patches the `open-orders` query cache directly by `orderId` (zero REST cost) on
   `ORDER_TRADE_UPDATE`; debounces (2s) a real REST refetch of positions/account on `ACCOUNT_UPDATE`
   since that event lacks `markPrice`/`liquidationPrice`. Wired into `TradeInner()` in `Trade.jsx`.
   REST safety-net intervals lengthened: account 30s→90s, positions 3s→30s, open-orders 10s→60s.
6. **Docs**: `API_CONTRACTS.md` (new endpoints + `trade:stream-update` event),
   `live-trading/SPEC.md` (full Data Flow rewrite, also fixed a leftover dangling sentence from an
   earlier edit), `ARCHITECTURE.md` rule 5, `DECISIONS.md` #20, `CURRENT_STATE.md` (Known Technical
   Debt entry updated to resolved, Current Constraints row, new Live Trading bullet).

**Verification note — real, not glossed over:** Docker wasn't running locally for any of this
session, so nothing here has been exercised against a live Binance account. Checked instead: Python
syntax (`ast.parse`) on all 3 new/changed engine files, Node syntax (`node --check`) on all changed
server files, and an `esbuild` transpile-only pass on `Trade.jsx` (validates JSX/JS syntax without
resolving imports). **Explicitly unconfirmed**: whether Binance actually emits `ORDER_TRADE_UPDATE`
for algo/conditional orders (`/fapi/v1/algoOrder`, this platform's TP/SL mechanism) before they
trigger. The cache-patch code is written defensively either way (only touches entries matching a
received `orderId`, never fabricates data), so an unconfirmed-negative here means algo orders fall
back to the 60s REST poll, not that they'd show wrong data — but this needs a real check next time
the stack is up.

**Files changed:** `engine/services/{user_data_stream,manual_trade_stream}.py`,
`engine/routers/trade.py`; `server/src/{controllers/trade.controller.js,routes/trade.routes.js,
services/socketEmitter.js}`; `client/src/hooks/useTrade.js`, `client/src/pages/Trade.jsx`;
`workspace/docs/core/{API_CONTRACTS,ARCHITECTURE,DECISIONS}.md`,
`workspace/docs/features/live-trading/SPEC.md`, `workspace/docs/state/CURRENT_STATE.md`.

**Open questions:** Verify against a real running stack: (1) does `ORDER_TRADE_UPDATE` actually
fire for algo/conditional orders pre-trigger, (2) does the 5-minute idle reaper correctly stop
abandoned streams without also killing active ones on a slow connection, (3) end-to-end smoke test
of the full chain (place an order manually → confirm the Open Orders table updates without a
network request in devtools).

---
## 2026-07-02 — Two Deferred Code Fixes Resolved via Web Research — COMPLETE ✅

**Goal:** Resolve the two code-level items deferred at the end of the CURRENT_STATE.md relocation
work (see entry below) — a testnet-host mismatch and a "polling interval undercuts the documented
floor" discrepancy — by researching Binance's actual current API docs rather than guessing.

**Done:**
1. **Testnet-host mismatch — fixed.** Binance's official Open Platform docs
   (developers.binance.com/docs/derivatives/usds-margined-futures/general-info) confirm the current
   documented USDS-M Futures Testnet REST base is `https://demo-fapi.binance.com`, matching
   `engine/services/binance_testnet.py`. `engine/utils/symbols.py` had 4 hardcoded URLs
   (`_LEVERAGE_BRACKET_URLS`, `_EXCHANGE_INFO_URLS`, `_TICKER_URLS`, `_BOOK_TICKER_URLS`) pointing at
   `https://testnet.binancefuture.com` instead — a legacy/community domain, not the currently
   documented one. Changed all 4 to `https://demo-fapi.binance.com`. Verified Python syntax parses;
   **Docker wasn't running locally so no container smoke test was done** — worth a real
   `GET /api/v1/candles/symbols` check next time the stack is up.
2. **Polling-interval "discrepancy" — resolved by correcting the framing, not the code.** Researched
   Binance's actual rate-limit model: `REQUEST_WEIGHT` 2400/min **per source IP**, not a flat
   per-endpoint interval floor. At its real weight (5), `positions` polling every 3s (100 weight/min)
   was never the risk — the stated "never lower than 10s" floor was measuring the wrong thing.
   **Found instead, not previously documented anywhere**: `GET /fapi/v1/openOrders` and
   `/fapi/v1/openAlgoOrders` cost weight **40 each without a `symbol` param** (vs. 1 with one), and
   `engine/routers/trade.py`'s `get_open_orders` never passes one — 480 weight/min from that single
   10s-interval call. Since this server proxies every user's signed Binance calls through one
   outbound IP, that 2400/min budget is **shared across all concurrently active users**, not
   per-user — ~590 weight/min/active-user means roughly 4 concurrent Trade-page users exhausts it,
   before bot sessions or backtest workers add their own calls on the same IP. Documented this
   accurately everywhere the old wrong framing lived; **did not** silently scope `open-orders` to
   the active symbol to fix it, since that changes UI behavior (hides other-symbol orders) — flagged
   as new Known Technical Debt in `CURRENT_STATE.md` for a product decision instead.

**Files changed:** `engine/utils/symbols.py` (code fix); `workspace/docs/core/{ARCHITECTURE,
DECISIONS,binance-api}.md`, `workspace/docs/features/live-trading/SPEC.md`,
`workspace/docs/state/CURRENT_STATE.md` (new Known Technical Debt entry), `workspace/plan/
current_state_relocation.md` (marked both items resolved).

**Open questions:** Whether/how to fix the `open-orders` weight-40 issue — scope to active symbol
(cuts weight 40x, loses cross-symbol visibility in that view) vs. reduce poll frequency vs. accept
the current concurrent-user ceiling. Needs a product call, not a drift fix.

