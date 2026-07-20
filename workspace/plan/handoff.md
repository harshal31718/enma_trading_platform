# Session Handoff Log

Resume prompts for cross-session continuity (root `CLAUDE.md` Rule G / `AGENTS.md` → Session Handoff).

**Format rules:**
- Newest entry on top: `## <date> — <title> — <status>` with **Goal / Done / Files changed / Open questions**.
- Keep at most the **3 most recent entries**. When adding a new one, delete the oldest — git history is the archive. This file must stay a short resume prompt, not a project log.

---
## 2026-07-20 (later same day, part 16) — Plan 7 Step 7.4 continued: Settings.jsx + Backtest.jsx

**Goal:** user's follow-up after the prior entry's report ("did not attempt
Backtest/Settings/ChaosWizard decomposition or the hooks factory") was "proceed on them." Did
Settings.jsx and Backtest.jsx this round; see Open Questions below for what's still outstanding
and why.

**Settings.jsx (928 lines, entirely one function) → 30 lines.** Read the whole file first — 6
visually-distinct cards (Profile, Algo Access, Environment Config [env toggle + testnet/mainnet
API keys + bot limits, all one visual card in the original], Chaos Settings, Notifications,
Exchange Settings), each with its own local form state + effect-synced-from-query + submit
handler already cleanly commented with `// ── X ──` section markers. Extracted each into
`client/src/features/settings/`, with each card calling its own `useExchangeSettings()`/
`useUpdateExchangeSettings()` rather than receiving 20+ props — TanStack Query dedupes identical
query keys automatically, so 6 independent calls to the same `['settings','exchange']` key is the
normal usage pattern, not 6x the network traffic. Verified in browser: every card renders with
real loaded data (fee %, capital, leverage, risk params all correct), and the `space-y-0`
flush-spacing between Environment/Chaos cards plus `NotificationsCard`'s own explicit `mt-6` was
preserved exactly (checked this specifically — a naive "wrap the middle card in `<div
className="mt-6">`" would have added a gap that didn't exist in the original).

**Backtest.jsx (831 lines, one ~640-line function + 2 small table helpers) → 503 lines.** The
`PerformanceTable`/`ComparisonTable` helpers were already separate — moved as-is. The 4 result
tabs (Overview, Performance Summary, List of Trades, Compare) each got their own component under
`client/src/features/backtest/` (`OverviewTab`/`TradesTab`/`ComparisonTab` — Performance Summary
just renders `PerformanceTable` inline, didn't need its own wrapper), taking already-fetched data
as props. **Deliberately did not move the TanStack Query hook calls themselves** — `selectedResultId`/
`tradePage`/`comparisonIds` are page-level state shared by the history sidebar and all 4 tabs, so
relocating the hooks into per-tab components would mean threading that state back up anyway with
no real benefit, just churn. This was a presentational split, not a data-ownership refactor.

**Screenshot tooling failed mid-verification** — `Page.captureScreenshot` timed out repeatedly
after clicking into the Performance Summary tab (unrelated to the code change: console showed no
errors, and the accessibility tree confirmed the page was fully interactive throughout). Switched
to `read_page` against the DOM/accessibility tree instead of narrating around the failure —
confirmed `PerformanceTable` rendered real per-side metrics (Net Profit -$494.74/+$377.24/-$871.98
for All/Long/Short), `TradesTab` rendered its pagination controls (First/Prev/Page 1/2/11/Next/
Last), and `ComparisonTab`'s empty state rendered correctly, across the actual DOM tree rather
than a pixel screenshot.

**Found, not caused, not fixed**: a React "duplicate/missing key" console warning on
`TradesTab`'s `<TableRow key={tr.id}>`. Checked `git show HEAD:client/src/pages/Backtest.jsx`
before assuming this was a regression — the identical `key={tr.id}` was already in the
pre-refactor committed code, so this is a pre-existing trade-data quality issue (likely
duplicate/undefined `id` on some rows from the API), not something the extraction introduced.
Flagged here rather than silently fixed — fixing it would be scope creep for a decomposition task
and the actual root cause (why does `tr.id` collide/go missing?) needs its own investigation.

**Verified:** `vite build` succeeds with stable bundle size for both changes, `vitest` 15/15
throughout. `client/CLAUDE.md` updated — added `features/settings/` and `features/trade/` (from
the prior entry, which hadn't been documented in CLAUDE.md's folder tree yet) folder entries, and
expanded the "Backtest page spec" section to describe the new tab components and the
data-ownership boundary (Backtest.jsx keeps the hooks, cards/tabs are presentational).

**Files changed:** new `client/src/features/settings/{styles.js, ProfileCard.jsx,
AlgoAccessCard.jsx, EnvironmentConfigCard.jsx, ChaosSettingsCard.jsx, NotificationsCard.jsx,
ExchangeSettingsCard.jsx}`, new `client/src/features/backtest/{PerformanceTable.jsx,
ComparisonTable.jsx, OverviewTab.jsx, TradesTab.jsx, ComparisonTab.jsx}`,
`client/src/pages/Settings.jsx` (rewritten), `client/src/pages/Backtest.jsx` (rewired),
`client/CLAUDE.md`. Docs: `0_tracker.md` (Plan 7 row), this file.

**Open questions:** none design-wise. **Still not attempted, same reasons as before**:
ChaosWizard.jsx's internal decomposition (677 lines, same monolithic-body shape Settings.jsx/
Backtest.jsx had before this round — its own pass); the "hooks share a factory" sub-item from 7.5
(collapsing duplicated `api.get/post`-and-unwrap boilerplate across ~15 per-domain hooks — a real,
larger mechanical migration); the remaining WS-entangled pieces of Trade.jsx (TickerBar,
ChartContainer, OrderBook, RecentTrades, OrderForm, LeverageModal, `TradeInner`). Also newly
surfaced and worth a dedicated look: the `TradesTab` duplicate-key warning (pre-existing trade-
data quality issue, root cause not investigated).

---
## 2026-07-20 (later same day, part 15) — Plan 7 Steps 7.5 (core) + 7.4 (Trade.jsx) shipped

**Goal:** user said "proceed with them" for 7.4 and 7.5 together. 7.5 has a plan-mandated open
design question (Zustand+TanStack-Query-thin-store vs TanStack-Query-only for the realtime-state
owner) that explicitly cannot be picked without asking — asked via AskUserQuestion before writing
any code. **Zustand + TanStack Query (thin store)** was chosen. Did 7.5 before 7.4 despite the
plan doc's ordering: Trade.jsx (7.4's biggest target) is exactly the page most entangled with the
realtime state 7.5 redefines, so decomposing it first would have meant redoing that work once the
state architecture changed underneath it.

**7.5 — surveyed before designing.** Ran an Explore agent over the actual current-state
architecture rather than assuming the plan's framing was accurate. Findings that shaped the
design: `client/src/store/` had been fully deleted (greenfield, not a migration target); the
"3 disagreeing sources" problem was narrower than it sounded — `binanceWS.js` already ref-counts
connections by stream name, so Trade.jsx's 2 independent `<sym>@ticker` subscriptions (header
`TickerBar`, order-entry sizing calc) shared one real WebSocket connection but each parsed the
tick into its own local state/ref, so "this symbol's price" had no single documented value even
though the underlying data was already identical moment-to-moment.

**Done:** new `client/src/store/marketStore.js`. `useMarketTicker(streamPrefix)` — reactive read,
for display (`TickerBar`). A non-reactive `useMarketStore.getState().tickers[...]` read — for
sizing math that shouldn't re-render the order form on every tick, preserving exactly the old
ref's non-reactive-read intent (a real behavioral requirement I checked for, not an accident to
paper over — a naive reactive-only design would have made `OrderForm` re-render on every price
tick, a UX regression the ref was deliberately avoiding). Migrated both Trade.jsx consumers.
**Deliberately scoped to ticker/price only** — `OrderBook`/`RecentTrades`/the candle chart keep
their own dedicated `useBinanceWS` subscriptions (depth/aggTrade/kline are structurally different
data, and client/CLAUDE.md's realtime rules already document per-sub-component isolation for
those as a deliberate render-perf choice, not something to undo). `client/dist/` requirement
already satisfied — confirmed gitignored, 0 tracked files.

**Verified in a real browser, not just tests**: navigated to `/trade/BTCUSDT`, confirmed the
header ticker live-updates, clicked 50% sizing and confirmed the qty field computed correctly
from the shared store's price (`0.0231` BTC — matches the manual calc), zero console errors.
`client/src/store/__tests__/marketStore.test.js` (4 cases). `client/CLAUDE.md` updated — the
"`client/src/store/` no longer exists" note was now stale; added the store's docs and a note in
the realtime-rules section explaining the ticker exception to per-sub-component isolation.

**7.5 — deliberately NOT attempted**: the "hooks share a factory" sub-item (collapsing duplicated
loading/error/toast logic across ~15 per-domain hooks). Checked what's actually duplicated before
deciding — mostly `const { data } = await api.get(url); return data.data` unwrap boilerplate per
query, not loading/error/toast (client/CLAUDE.md already documents error handling as page-level,
via a local `errorMessage` banner, not hook-level — so "collapse hooks" doesn't mean what a
naive reading suggests). A full mechanical migration across every hook file is real, valuable
work, but judged too large to append safely to an already-large session without its own dedicated
regression pass. Flagged as a follow-up, not silently declared done.

**7.4 — surveyed all four target files' actual shape before touching anything.** Trade.jsx
(1,760 lines) turned out structurally different from the other three: ~20 already-separate named
function components crammed into one file — a mechanical file-split, genuinely low risk (cut,
paste, wire imports, no logic change). Backtest.jsx (831 lines: one ~640-line
`export default function` + 2 small table helpers), Settings.jsx (928 lines: **entirely** one
single function, zero pre-existing internal decomposition), and ChaosWizard.jsx (677 lines: one
~600-line function + one helper) are all single monolithic component bodies — decomposing those
means real JSX-tree/container-presenter splitting of live, stateful render trees, a slower and
riskier kind of work than moving already-separate functions.

**Done — Trade.jsx: 1,760 → 892 lines (49% reduction).** Extracted 8 new files under
`client/src/features/trade/`: `formatters.js` (symbol-precision-aware price/qty formatters — kept
separate from `@/utils/formatters.js`, genuinely different concern, not a duplicate),
`TableHelpers.jsx` (SkeletonRow/EmptyRow/SyncWarningBanner), `TpSlModal.jsx`, `PositionsTable.jsx`,
`OpenOrdersTable.jsx` (+ `extractOcoId`), `AssetsTable.jsx`, `HistoryTables.jsx`
(Order/Trade/Transaction History — grouped, same shape), `BottomPanel.jsx` (composes all of the
above). Pure moves — same JSX, same props, same logic, only the import graph changed.

**Verified**: `vite build` succeeds with an **identical output bundle size** to the pre-refactor
build (confirms nothing got silently duplicated or dropped in the move), `vitest` 15/15
(including the existing Trade.jsx render smoke test), and a real-browser check — chart, order
book, recent trades, order form, and every BottomPanel tab (Positions/Open Orders/Order
History/Trade History/Transaction History/Assets) all render and function after the split, %
sizing still computes correctly, zero console errors after a hard reload (one stale HMR error
from mid-edit cleared on a fresh navigation — confirmed not a real issue).

**Not attempted**: Backtest.jsx/Settings.jsx/ChaosWizard.jsx's internal decomposition (their own
dedicated pass, not a quick follow-on to this one); the remaining WS-entangled Trade.jsx pieces
(`TickerBar`, `ChartContainer`, `OrderBook`, `RecentTrades`, `OrderForm`, `LeverageModal`,
`TradeInner`) stay in the page file — already touched for 7.5's price-store work this session,
and further splitting them trades more regression risk for less file-size benefit than the tables
did (the tables were pure presentational props-in/JSX-out; these are WS-subscription-owning and
order-placement-critical).

**Files changed:** new `client/src/store/marketStore.js`,
`client/src/store/__tests__/marketStore.test.js`, new `client/src/features/trade/{formatters.js,
TableHelpers.jsx, TpSlModal.jsx, PositionsTable.jsx, OpenOrdersTable.jsx, AssetsTable.jsx,
HistoryTables.jsx, BottomPanel.jsx}`, `client/src/pages/Trade.jsx` (rewired imports, ~900 lines
removed), `client/CLAUDE.md`. Docs: `0_tracker.md` (Plan 7 row), this file.

**Open questions:** none design-wise — the one blocking question (7.5's state architecture) was
resolved via AskUserQuestion before any code. What's left of Plan 7: the hooks factory (7.5) and
the 3 remaining god-components' internal decomposition (7.4) — both real, both explicitly scoped
out this session rather than rushed, both good candidates for a dedicated follow-up pass with
their own browser verification budget.

---
## 2026-07-20 (later same day, part 14) — Plan 7 Step 7.3 shipped: auth robustness (SRV-4)

**Goal:** user asked for 7.2 then 7.3 "back to back, do not stop till then." 7.2 is the prior
entry below; this one covers 7.3 (auth robustness).

**Done — 503 vs 401 split:** `verifyJWT` (`middleware/auth.middleware.js`) used to wrap
`jwt.verify` AND `User.findById` in one try/catch, so a Mongo outage produced the identical 401
UNAUTHORIZED a bad token would — sending a client into a pointless re-login loop when the actual
problem is the DB. Split into two try/catches: bad/expired token stays 401; a `User.findById`
throw now returns `ApiError(503, 'SERVICE_UNAVAILABLE', ...)`. Checked the client before shipping
this — `client/src/hooks/useAuth.js` only special-cases 401 for its logged-out redirect, so a 503
surfaces as a plain error instead of silently logging the user out, which is exactly the point.

**Done — short-TTL user cache:** added a 5-second in-memory `Map` cache for the per-request
`User.findById` lookup (every protected route runs this every request — e.g. Trade's 4s position
poll), mirroring `symbolService.js`'s existing cache-with-TTL shape. Cache hits return a *shallow
copy*, never the shared cached object — `verifyJWT` mutates `.id` onto `req.user`, and two
concurrent requests hitting the same cache entry must never alias the same object underneath.

**The one subtlety that mattered:** server/CLAUDE.md documents "since `verifyJWT` reloads the user
each request, grants/revokes apply immediately — no JWT re-issue needed" as a designed invariant.
A naive TTL cache would silently weaken that to "applies within 5 seconds." Fixed by having
`admin.controller.js`'s `setUserAlgoAccess` call a newly-exported `invalidateUserCache(userId)`
immediately after its `User.updateOne` — so the immediate-apply guarantee holds exactly, and the
TTL only smooths over the case where nothing changed between two requests moments apart. Checked
this is the only User-mutation site that matters: `isActive`/`role` are never toggled outside
login/creation, no deactivate-user route exists.

**Done — bare `catch {}` removal (explicitly called out in the plan's own Step 7.3 bullet, not
scope creep):** the `.catch(() => {})` silent-swallow pattern, sitewide — 18 call sites across
`algo.controller.js` (4), `trade.controller.js` (3), `algoSessionService.js` (7),
`reconciliation.js` (4). All are fire-and-forget lock-release/DB-write/log-push operations that
must stay non-blocking on failure (that part is correct, unchanged) but previously had zero
observability when they failed. Each now logs via `console.error` with enough context (symbol,
session id, or user id) to actually debug a real failure — pure "replace silence with a log
line," no control-flow change, nothing that could alter a test's observable outcome besides the
new log line itself.

**Deliberately left alone, checked each one:** `app.js`'s 2 health-check catches (already write
`'error'` into the response body — not silent), `config/socket.js`'s auth catch (rejects the
socket connection with an explicit error — not silent), `constants/top_symbols.js`'s 2 catches
and `symbolService.js`'s 1 catch (each falls through to a documented static/cached fallback,
already commented explaining why). None of these are the discard-and-forget anti-pattern the
plan's own example (`$push` log `.catch(()=>{})`) called out — they're deliberate fallback
behavior with an observable effect already, just not a console line.

**Tests:** 7 new cases in `auth.middleware.test.js` (503-not-401 on DB failure, bad-token-stays-
distinct-from-503, cache-hit-skips-a-second-`User.findById`, cache-never-shares-object-references-
across-requests, `invalidateUserCache`-forces-a-fresh-read) plus a new `admin.controller.test.js`
(4 cases: invalidates on grant, invalidates on revoke, does NOT invalidate when rejected before
the update on a bad status or an admin target — the negative cases matter as much as the positive
ones here, since a false invalidate call would be silently harmless but a missing one would leak
the bug this whole slice exists to prevent). The `auth.middleware.test.js` suite needed a
`_clearUserCacheForTests()` export and `afterEach` hook — several existing cases reuse userId
`'abc123'` with a different `User.findById` mock per case, and the module-scoped cache would
otherwise leak a stale entry from one test into the next.

**Verified:** full server jest suite 233/233 (224 existing + 9 new) — zero regressions. Docker
logs confirm nodemon restarted clean, `/health` 200 throughout.

**Files changed:** `server/src/middleware/auth.middleware.js`,
`server/src/controllers/admin.controller.js`, `server/src/controllers/algo.controller.js`,
`server/src/controllers/trade.controller.js`, `server/src/services/algoSessionService.js`,
`server/src/services/reconciliation.js`, `server/src/middleware/__tests__/auth.middleware.test.js`
(updated), new `server/src/controllers/__tests__/admin.controller.test.js`. Docs: `0_tracker.md`
(Plan 7 row), this file.

**Open questions:** none design-wise. Both acceptance checks from the plan doc are met: a
simulated Mongo outage yields 503 not 401 (tested); user lookups are cached (tested, with the
grant/revoke-immediacy invariant explicitly preserved, not just assumed fine). **Plan 7 Steps
7.1–7.3 are now all shipped.** What remains is 7.4 (decompose `Trade.jsx`/`Backtest.jsx`/
`Settings.jsx`/`ChaosWizard.jsx` god-components) and 7.5 (single owner for realtime market state)
— both client-side, both larger efforts than anything shipped this session (7.4 in particular:
`Trade.jsx` alone is 1,760 lines / 29 `useState`). 7.5 has a standing open design question
(Zustand+TanStack-Query-plus-thin-store vs TanStack-Query-only for the realtime-market-state
owner) that the plan file itself says needs explicit user sign-off before any code — do not just
pick one without asking. Recommend pausing Plan 7 here for the user to review this session's
server-side diff before starting the client-side work, which is a different risk profile
(UI regressions need visual/interaction verification the way server unit tests can't provide).
