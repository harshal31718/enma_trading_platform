# Enma — UI Refinement Plan (Pre-Production Hardening)

**Status:** Phase 1 complete. Phase 2 partial — 3.1/3.2/3.3/3.4(client+server sort)/3.5/3.6/3.7/3.12/3.13 done; 3.9/3.10/3.11 and some 3.4/3.8 follow-ups deferred. See `workspace/plan/handoff.md` (2026-07-01 Phase 2 entry) for exact scope and an important note on `RiskDashboard.jsx` needing a manual review after an in-session file-truncation incident.
**Date:** 2026-07-01
**Branch:** `auth` (current)
**Scope:** `client/src/**` only, except §3.4 server-side sort (explicit user exception — touches `server/src/controllers/orderHistory.controller.js`).

---

## 0. Source of truth (what guides every fix)

Before touching any className, the canonical rules are:

- `client/CLAUDE.md` — stack, folder structure, styling rules, palette
- `workspace/docs/core/UI_STYLE_GUIDE.md` — visual design system
- `workspace/docs/state/CURRENT_STATE.md` — what features are implemented
- `workspace/docs/core/API_CONTRACTS.md` — wire contracts
- `workspace/docs/core/ARCHITECTURE.md` — boundary rules
- `workspace/docs/state/DEPRECATED.md` — what NOT to bring back (e.g. `useAuthStore.js`)

If any agent's finding contradicts these, **the docs win**. Per `AGENTS.md`: "Code always wins over docs — except when docs are the source of truth and the code is the drift."

---

## 1. How to read this plan

The plan is **phased by impact, not by file**. Phase 1 can ship in a day and unblocks production. Phase 2 is the next 1–2 weeks. Phase 3 is the polish sprint before launch.

| Phase | Effort | Why now |
|---|---|---|
| **1. Production blockers** | 1 day | Real risk: data loss, A11y blockers, broken flows, no-error-on-failure. |
| **2. Structural / convention** | 1–2 weeks | Aligns UI to docs (navbar, color palette, contracts), extracts patterns, adds shared primitives. |
| **3. Polish (incl. mobile)** | 1–2 weeks | Visual consistency, responsiveness, advanced UX (toasts, animations, error boundaries). |

Every item carries:
- `severity: critical | high | medium | low`
- `effort: S (<1h) | M (1–4h) | L (4h+ or refactor)`
- `file:line` evidence
- `type: bug | a11y | drift | refactor | polish`

**Total findings: ~100 across all lenses (UX/A11y: ~60, Drift: 20, Code Quality: 14, Design System: 6, Responsiveness: 10+).**

---

## 2. Phase 1 — Production Blockers (ship first)

These are items that would visibly embarrass the platform in front of a paying user or an investor demo. Fix in order.

### 2.1 `alert()` calls (5×) → inline error banner

- **Why critical:** Blocks the browser thread, breaks SPA flow, fails WCAG. The `client/CLAUDE.md` rule "Never use `alert()` for errors" is **violated 5 times** in the codebase.
- **Files:**
  - `client/src/pages/RiskDashboard.jsx:79` — `alert(`Save failed: ${...}`)`
  - `client/src/pages/RiskDashboard.jsx:114` — `alert(`Add failed: ...`)`
  - `client/src/pages/RiskDashboard.jsx:132` — `alert(`Remove failed: ...`)`
  - `client/src/pages/RiskDashboard.jsx:161` — `alert(`Add failed: ...`)`
  - `client/src/pages/RiskDashboard.jsx:179` — `alert(`Remove failed: ...`)`
- **Fix:** Introduce a `useBannerError` hook returning `{ error, setError, clearError, banner }` that renders an inline `bg-red-950/20 border-red-800/40` banner with an `AlertTriangle` icon and `role="alert"`. Replace all 5 `alert(...)` sites.
- **Effort:** M
- **Severity:** critical
- **Type:** a11y + bug

### 2.2 Confirmation dialogs for destructive actions

- **Why critical:** Single-click permanent deletion of live bot sessions, market-close of futures positions, mass-cancel of orders. On a live futures account, "Close Position" with no confirm is a one-misclick liability.
- **Files:**
  - `client/src/components/algo/SessionCard.jsx:373-382` — Delete session (no confirm, also no onError)
  - `client/src/pages/AlgoTrading.jsx:59-67` — "Clear stopped" wipes all history (no confirm)
  - `client/src/pages/Trade.jsx:692-708` — Close position, single click
  - `client/src/pages/Trade.jsx:851-857` — "Cancel All" open orders
  - `client/src/pages/Trade.jsx:899-910` — Single order cancel (lower risk)
  - `client/src/pages/AdminPanel.jsx:31-38` — Remove email from whitelist
  - `client/src/pages/RiskDashboard.jsx:336-340` — Delete strategy override
  - `client/src/pages/RiskDashboard.jsx:463-466` — Delete symbol override
- **Fix:** Build a `ConfirmDialog` primitive (`components/ui/confirm-dialog.jsx`) using Radix `AlertDialog`. Title + description + cancel + destructive confirm. Wire to all sites above.
- **Effort:** M
- **Severity:** critical (live trading) / high (rest)
- **Type:** bug + a11y

### 2.3 No `<ErrorBoundary>` anywhere — chart crash white-screens the app

- **Why critical:** `lightweight-charts` and `Recharts` can throw at runtime. One bad candle → entire app unmounts.
- **Files:**
  - `client/src/main.jsx` — no top-level boundary
  - `client/src/App.jsx` — no boundary on routes
  - `client/src/components/charts/EquityCurve.jsx` — wrapped in `<Suspense>` but no error boundary
  - `client/src/pages/Trade.jsx:179-205` — `createChart(...)` no try/catch
- **Fix:**
  1. Create `components/ErrorBoundary.jsx` (class component) with reset, "Reload" CTA, and `componentStack` in dev only.
  2. Wrap `<App />` in `main.jsx`.
  3. Wrap each chart panel in its own boundary so one chart crash doesn't kill the page.
- **Effort:** M
- **Severity:** critical
- **Type:** bug

### 2.4 No 404 / NotFound route

- **Why critical:** Unknown URLs (typo, deep-link breakage) render an empty `<Outlet/>`. Looks broken.
- **Files:** `client/src/App.jsx:45-58`
- **Fix:** Add `<Route path="*" element={<NotFound />} />`. Create `pages/NotFound.jsx` styled with the rest of the app: title, message, "Go to Dashboard" CTA.
- **Effort:** S
- **Severity:** high
- **Type:** bug

### 2.5 Custom modals (TP/SL, Leverage) lack focus trap

- **Why critical:** Keyboard-only and screen-reader users can lose focus and can't submit. WCAG 2.4.3 violation.
- **Files:**
  - `client/src/pages/Trade.jsx:542-672` — `TpSlModal` custom `<div>` overlay
  - `client/src/pages/Trade.jsx:1234-1277` — `LeverageModal` custom overlay
- **Fix:** Convert both to use the existing `components/ui/dialog.jsx` (Radix). Remove the hand-rolled overlay. This also gets Escape-to-close, focus restore, and ARIA semantics for free.
- **Effort:** M
- **Severity:** critical (a11y)
- **Type:** a11y

### 2.6 `text-red-500` in Backtest KPIs violates P&L color rule

- **Why critical:** Project rule is `red-400` for loss, `emerald-400` for profit. `red-500` is a one-off drift in the most-screenshotted page.
- **Files:** `client/src/pages/Backtest.jsx:77, 84, 500, 503, 510, 511`
- **Fix:** `s/text-red-500/text-red-400/g` in Backtest.jsx. Audit the rest of `client/src` for `text-red-500` and `text-green-*` usage.
- **Effort:** S
- **Severity:** medium (cosmetic but loudly off-brand)
- **Type:** drift

### 2.7 `fetch()` in Trade.jsx bypasses axios

- **Why critical:** Project rule: "All API calls go through `src/lib/axios.js`". The trade page silently breaks when an axios interceptor is added (e.g. for auth retries, error normalization) because `fetchKlines` doesn't share the config.
- **Files:** `client/src/pages/Trade.jsx:147` — raw `fetch(${API_BASE}/api/v1/trade/klines?...)`
- **Fix:** Refactor to `api.get('/api/v1/trade/klines', { params: { symbol, interval, limit } })`.
- **Effort:** S
- **Severity:** medium
- **Type:** drift

### 2.8 `Binance Spot` option in NewBacktestWizard with no engine implementation

- **Why critical:** User picks "Binance Spot" → silently no spot path exists → misleading or run fails.
- **Files:** `client/src/features/backtest/NewBacktestWizard.jsx:46, 74, 266, 267`
- **Fix:** Remove the Spot option (engine only supports USD-M futures per `API_CONTRACTS.md`). If Spot is a real roadmap item, add a `Coming soon` disabled state with tooltip.
- **Effort:** S
- **Severity:** high
- **Type:** drift + bug

### 2.9 Failed backtest still renders the success-shaped UI

- **Why critical:** Misleading. User sees metric grid + chart shell on a failed run.
- **Files:** `client/src/pages/Backtest.jsx:457, 484-491`
- **Fix:** When `activeResult.status === 'failed'`, render only the error banner + "Run again" CTA. Hide the metric grid and chart shell.
- **Effort:** S
- **Severity:** medium
- **Type:** bug

### 2.10 Buy/Sell buttons have no `aria-busy` during submission

- **Why critical:** Screen reader users don't know an order is in flight.
- **Files:** `client/src/pages/Trade.jsx:1582-1600`
- **Fix:** Add `aria-busy={isSubmitting}` to both buttons; swap content to a `<Loader2>` spinner + "Placing…" while submitting.
- **Effort:** S
- **Severity:** medium
- **Type:** a11y

### 2.11 No `?jobId=invalid` UX for broken backtest deep-links

- **Why critical:** Dashboard deep-links via `?jobId=`. If the result query errors first, user sees loading → empty state with no message.
- **Files:** `client/src/pages/Backtest.jsx:484` (partial) + `BacktestHistory.jsx:174-177` (no error branch)
- **Fix:** In `BacktestHistory`, branch on `isError` → inline "Couldn't load backtest history" with Retry button. In `Backtest.jsx`, when `jobId` is present and result is `isError`, show "Result not found" + "Browse all runs" link.
- **Effort:** S
- **Severity:** high
- **Type:** bug

### 2.12 Trade.jsx error string "Enter a valid quantityand price" (missing space)

- **Files:** `client/src/pages/Trade.jsx:1387`
- **Fix:** Add a space.
- **Effort:** S
- **Severity:** low
- **Type:** bug

---

## 3. Phase 2 — Structural & Convention Alignment (week 1–2)

These bring the UI back in line with the documented rules. Some are touched by 2 of 2 completed lenses and have high confidence.

### 3.1 Navbar: wrong items, wrong order, contradicts spec

- **Drift:** `client/CLAUDE.md:199-200` and `CURRENT_STATE.md:180-182` specify nav order `Dashboard, Strategies, Backtest, Trade, AlgoTrading, Settings` (6 items, OrderHistory not in navbar, Settings as primary nav item, desktop-only — no mobile hamburger).
- **Reality:** Navbar has 7 visible items in order `Dashboard, Trade, Strategies, Risk Dashboard, Backtest, AlgoTrading, Order History`. Settings is an icon in the user dropdown. There's a mobile hamburger + drawer.
- **Files:** `client/src/components/layout/Navbar.jsx:20-28, 60-66, 184-214`
- **Decision needed (user input required):**
  - **(A) Match the spec exactly:** remove mobile hamburger, remove Order History from nav, promote Settings to a primary nav item, restore the documented order.
  - **(B) Keep current layout, update the spec:** the mobile hamburger is a real improvement; the Risk Dashboard is a 3rd-zone feature that warrants nav access; Order History is useful in the nav. Update `client/CLAUDE.md` and `CURRENT_STATE.md` to match.
  - **Recommended:** (B). The spec is one cycle behind the implementation. The current navbar is more usable.
- **Followups (regardless of choice):**
  - Add `focus-visible:ring-2 focus-visible:ring-emerald-500` to all nav items (currently keyboard-invisible).
  - Add `aria-label="Open menu"` / `"Close menu"` to the hamburger.
  - Add `aria-haspopup="menu" aria-expanded={dropdownOpen} aria-label="User menu"` to the avatar button.
  - Add `border-b-2 border-emerald-400` to active state (or update doc if removed intentionally).
- **Effort:** S
- **Severity:** medium (drift)
- **Type:** drift

### 3.2 Inline `style={{ borderRadius: '50%' }}` in Navbar violates "no inline styles"

- **Files:** `client/src/components/layout/Navbar.jsx:120, 127, 132`
- **Issue:** Project rule says Tailwind only. But the global theme override (`tailwind.config.js`) sets `borderRadius: 0`, so `rounded-full` becomes `border-radius: 0`. The inline style is a workaround.
- **Fix:** Either (a) add a one-off arbitrary class `className="[border-radius:50%]"`, or (b) document the avatar-circle exception in `client/CLAUDE.md`.
- **Effort:** S
- **Severity:** low
- **Type:** drift

### 3.3 Pagination — no First/Last, no page-jump, no `aria-current`

- **Files:**
  - `client/src/pages/OrderHistory.jsx:177-199`
  - `client/src/pages/Backtest.jsx:635-660`
  - `client/src/features/backtest/BacktestHistory.jsx:273-297`
  - `client/src/pages/Trade.jsx` (trades pagination)
- **Issue:** All paginated views have First/Prev/Next/Last only with no jump-to-page input. For >20 pages, this is friction. Screen readers can't tell which page is current.
- **Fix:** Extract a `<Pagination>` primitive (`components/ui/pagination.jsx`) with: First (`|<`), Prev, page numbers (with ellipsis), jump-to-page input, Next, Last (`>|`), `aria-current="page"`, `aria-label="Page X of Y"`.
- **Effort:** M
- **Severity:** medium
- **Type:** a11y + UX

### 3.4 Tables are not sortable, filter state not in URL

- **Files:**
  - `client/src/features/backtest/BacktestHistory.jsx:103-167` (filters local-only)
  - `client/src/pages/OrderHistory.jsx:48, 50-65` (filters local-only)
  - All tables across the app — no column sort, no `aria-sort`
- **Fix:**
  1. Move filter state in `BacktestHistory` and `OrderHistory` into `useSearchParams()` (e.g. `?symbol=BTCUSDT&status=running`).
  2. Add `<SortableHeader>` primitive that toggles `aria-sort="ascending" | "descending" | "none"` and emits `onSort(key, dir)`.
  3. Wire to `RecentActivityTable`, `StrategyLeaderboard`, `CachedCandlesTable`, `BacktestHistory`, `OrderHistory`, positions/orders tables.
- **Effort:** L
- **Severity:** medium
- **Type:** UX + a11y

### 3.5 Inconsistent number formatting across pages

- **Files:** multiple — see UX/A11y audit finding 14.
  - `client/src/pages/Trade.jsx:32-49` (`fmtPrice`), 304/438/783/958-961/1065 (inline `toFixed`)
  - `client/src/utils/formatters.js` (canonical)
  - `client/src/components/algo/SessionCard.jsx:34-40` (`fmtNum`)
- **Issue:** Order book uses 1 dp, positions 2 dp, order history 4 dp. Unrealized PnL renders `+1.23450000` (4 trailing zeros). Large numbers not abbreviated.
- **Fix:**
  1. Add to `client/src/utils/formatters.js`: `formatCompact(value)` (e.g. `$1.2M`), `formatPercent(value, decimals)`.
  2. Pick the canonical `formatPrice` / `formatQty` / `formatPnl` and use them everywhere. Remove inline `toFixed`.
  3. Decide on a single precision policy and document it in `client/CLAUDE.md`.
- **Effort:** M
- **Severity:** medium
- **Type:** polish + drift

### 3.6 Inconsistent date/time formatting

- **Files:** multiple.
  - `client/src/pages/Backtest.jsx:607-611` — `month: 'short', day: 'numeric', ...`
  - `client/src/pages/Trade.jsx:403` — 24h `HH:MM:SS`
  - `client/src/pages/OrderHistory.jsx:170` — `YYYY-MM-DD` UTC, no time
  - `client/src/components/algo/SessionCard.jsx:54, 510` — 24h `HH:MM`
- **Issue:** No convention. No timezone is ever shown. A Tokyo and New York user interpret the same number differently.
- **Fix:**
  1. Add to `client/src/utils/formatters.js`: `formatDateTime(iso, opts)` and `formatDate(iso)`. Use UTC by default, with a `local` opt-in.
  2. Replace all ad-hoc `toLocaleString()` / `toLocaleDateString()` / `toLocaleTimeString()` calls.
  3. Add a small "UTC" indicator in the Trade page header so the user knows which zone timestamps are in.
- **Effort:** M
- **Severity:** medium
- **Type:** polish + drift

### 3.7 Color contrast (`text-slate-500` for body copy)

- **Files:** widespread — UX/A11y audit found 15+ occurrences. Common sites:
  - `client/src/pages/Trade.jsx:443, 1542-1556`
  - `client/src/pages/Settings.jsx:138, 242, 246, 305, 350, 440, 515, 545, 632-636`
  - `client/src/components/algo/SessionCard.jsx:340-347, 507-518`
  - `client/src/components/features/dashboard/CachedCandlesTable.jsx`
  - `client/src/pages/RiskDashboard.jsx` (extensive)
  - `client/src/pages/Strategies.jsx:55-60`
- **Issue:** `text-slate-500` on `#060a0f` is ~3.0:1, below WCAG AA (4.5:1 for body). Used for labels, descriptions, and supporting copy.
- **Fix:** Sweep replace `text-slate-500` → `text-slate-400` for body copy. `text-slate-500` remains valid for purely decorative/muted captions (≥18px). Document the threshold in `client/CLAUDE.md`.
- **Effort:** S
- **Severity:** high (a11y, large surface area)
- **Type:** a11y

### 3.8 Empty states — no CTA, no icon, minimal copy

- **Files:**
  - `client/src/pages/Trade.jsx:738, 874, 950, 998, 1049, 1097` (six empty states)
  - `client/src/pages/OrderHistory.jsx:133-138`
  - `client/src/features/backtest/BacktestHistory.jsx:179-182`
  - `client/src/pages/Strategies.jsx:55-61`
  - `client/src/pages/AdminPanel.jsx:91-92`
- **Issue:** Empty messages are just centered text in a `<td>`. No icon, no CTA pointing the user to the next action.
- **Fix:** Build an `<EmptyState icon={...} title={...} description={...} action={...} />` primitive. Apply to all 12+ sites.
- **Effort:** M
- **Severity:** medium
- **Type:** polish + UX

### 3.9 Toasts — no library, hand-rolled `setTimeout` banners

- **Files:**
  - `client/src/pages/Trade.jsx:1624-1628, 1192-1201, 1158` (OCO toast + banner)
  - `client/src/pages/Settings.jsx:34-39, 64-65`
  - `client/src/pages/Strategies.jsx:14-19, 76-82` (silent success)
  - `client/src/pages/Backtest.jsx` (no success toast)
  - `client/src/components/algo/SessionCard.jsx` (no toast on TP/SL fill events)
- **Issue:** No `react-hot-toast` or `sonner` is installed. All notifications are hand-rolled, inconsistent in duration and position, and disappear during navigation. Success notifications are sometimes missing entirely (Strategies.jsx closes the dialog silently).
- **Fix:**
  1. Add `sonner` to `client/package.json` (lightweight, works with React 18 + Vite, themeable).
  2. Configure dark theme in `lib/toaster.jsx` with `position: top-right` and `duration: 4s` (8s for OCO).
  3. Replace all hand-rolled banners with `toast.success` / `toast.error`.
  4. Add success toasts to: strategy create, backtest run start, session start, settings save.
- **Effort:** M
- **Severity:** medium
- **Type:** polish + UX

### 3.10 ARIA sweep — icon-only buttons + form fields

- **Files:** many — see UX/A11y audit. Common sites:
  - `client/src/components/layout/Navbar.jsx:60-66, 103-114, 116-139` — hamburger, settings icon, avatar dropdown
  - `client/src/components/SymbolSearchBar.jsx:79-86, 107-260` — missing listbox/combobox semantics
  - `client/src/components/features/backtest/BacktestHistory.jsx:69-87, 204-258` — filter, refresh, compare toggle
  - `client/src/pages/Dashboard.jsx:94-101` — "View" button
  - `client/src/components/algo/SessionCard.jsx:373-389` — delete, expand chevron
  - `client/src/pages/Backtest.jsx:640-657` — pagination
  - `client/src/pages/OrderHistory.jsx:183-196` — pagination
  - `client/src/components/RiskParamsFields.jsx:55-65` — label not associated
  - `client/src/components/algo/ParamsForm.jsx:8-25` — label not associated
  - `client/src/pages/Trade.jsx:269-285` — timeframe buttons missing `aria-pressed`
- **Issue:** ~25+ icon-only buttons lack `aria-label`. Form fields lack `htmlFor`/`id` association. Symbol search lacks listbox semantics. Session card header is a clickable `<div>` (not focusable).
- **Fix:** Sweep through every icon-only `<button>` and add `aria-label`. Convert SessionCard header div → button. Add proper listbox/combobox semantics to SymbolSearchBar. Add `aria-pressed` to toggle buttons. Associate labels via `htmlFor`/`id` in RiskParamsFields and ParamsForm.
- **Effort:** L
- **Severity:** high
- **Type:** a11y

### 3.11 Stale data indicators on polling queries

- **Files:**
  - `client/src/hooks/useTrade.js:55, 69, 85` (3s, 10s, 15s polling)
  - `client/src/hooks/useAlgoSessions.js:11` (10s polling)
  - `client/src/pages/Trade.jsx:1131-1138` (8s tab polling)
  - `client/src/pages/Trade.jsx:1184-1189` (no spinner on active tab while refetching)
- **Issue:** `isFetching` is never surfaced in the UI. The user has no idea the data is being re-fetched. Combined with `retry: 1` default, a flaky first hit means the user sees stale data forever.
- **Fix:** Add a small `<RefreshingIndicator isFetching={...}>` in the polling tab headers, and a global "Last updated Xs ago" indicator. Set `retry: 2` and exponential backoff on critical queries (`useTrade`, `useAlgoSessions`).
- **Effort:** M
- **Severity:** medium
- **Type:** UX

### 3.12 Document the auth/risk components

- **Drift:** `client/CLAUDE.md` doesn't list `Login.jsx`, `AdminPanel.jsx`, `RiskDashboard.jsx`, `components/risk/`, `DashboardCalendar.jsx`, `utils/backtest-analytics.js`, `utils/exporters.js`, `hooks/useAuth.js`, `hooks/useRiskSettings.js`. The current branch is `auth` — these all exist but aren't documented.
- **Fix:** Update `client/CLAUDE.md` Folder structure section to add:
  - Pages: `Login`, `AdminPanel`, `RiskDashboard`
  - Components: `components/risk/` (4 files)
  - Features: `features/dashboard/DashboardCalendar.jsx` (and note it's currently unused)
  - Utils: `backtest-analytics.js`, `exporters.js`
  - Hooks: `useAuth.js`, `useRiskSettings.js`
- **Effort:** S
- **Severity:** low
- **Type:** drift

### 3.13 Add missing API contracts to docs

- **Drift:** `workspace/docs/core/API_CONTRACTS.md` is missing:
  - `/api/v1/auth/*` (Google OAuth, `/me`, `/logout`)
  - `/api/v1/admin/*` (allowed emails CRUD)
  - `/api/v1/risk/*` (settings, live metrics, simulation)
  - `tpsl_<uuid>_<sl|tp>` OCO prefix used by F-019
- **Fix:** Add these sections to `API_CONTRACTS.md`. They're implemented (in this branch) but undocumented.
- **Effort:** M
- **Severity:** medium
- **Type:** drift

---

## 4. Phase 3 — Polish & Mobile (week 2+)

### 4.1 Code quality & component patterns

**Status: COMPLETE — agent returned verified findings.**

#### 4.1.1 `useState` for server data (should be TanStack Query)
- `client/src/components/algo/SessionCard.jsx:64, 90-97` — `const [equity, setEquity] = useState([])` populated via `api.get(...)` inside `useEffect`. No query key, no caching, no `staleTime`/`refetchInterval`. Refetches from scratch on every collapse/re-expand. Error is silently `.catch(console.error)`. Convert to `useQuery(['algo','sessions', id, 'equity'], ..., { enabled: expanded })`.
- `useTrade.js` and `useAlgoSessions.js` — clean, no violation.
- **Severity:** medium | **Effort:** S | **Type:** refactor

#### 4.1.2 `useEffect`-based fetching that bypasses TanStack Query
- `client/src/pages/Trade.jsx:145-165, 217-236` — candle history fetched with raw `fetch()` (not the `api` axios instance), not a TanStack Query hook. Violates `client/CLAUDE.md` rule "All API calls go through `src/lib/axios.js` — never raw fetch." Also covered in §2.7.
- `client/src/components/algo/SessionCard.jsx:90-97` — same finding restated: `api.get(...).then(setEquity).catch(console.error)` in `useEffect` with a manual `cancelled` flag, instead of `useQuery` built-in cancellation/caching.
- **Severity:** high (rule violation) | **Effort:** M | **Type:** refactor

#### 4.1.3 Deep prop drilling
- `client/src/pages/Trade.jsx:1655-1658, 1209-1213` — `TradeInner → BottomPanel(ocoBanner, onDismissBanner) → OpenOrdersTable(onOcoBannerEvent)`. Only 2 levels; most sub-components self-fetch via hooks. Not severe enough to block shipping.
- **Severity:** low | **Effort:** S | **Type:** refactor

#### 4.1.4 Missing code splitting
- `client/src/components/algo/ChaosWizard.jsx` — no `lazy`/`Suspense`; eagerly bundled into `AlgoTrading.jsx` even though it's only shown behind a dialog toggle (`client/src/pages/AlgoTrading.jsx:8,15`).
- `client/src/pages/RiskDashboard.jsx:10-13` — eagerly imports `CorrelationHeatmap`, `AggregateMarginGauge`, `NetExposureBar`, `SimulationResults` (all chart/viz components) with no lazy loading.
- `client/src/features/backtest/BacktestCalendar.jsx` — not lazy-loaded from its parent.
- `client/src/components/charts/EquityCurve.jsx` — correctly lazy-loaded in `Backtest.jsx:1,24,531-538`; confirmed good.
- **Severity:** medium | **Effort:** S each | **Type:** refactor

#### 4.1.5 `console.log` / `debugger` statements
- `client/src/components/algo/SessionCard.jsx:95` — `.catch(console.error)` on equity fetch; no user-facing error state.
- `client/src/pages/AlgoTrading.jsx:44-50` — `console.error('Stop failed:', err)` in stop-session catch; failure never surfaced to the user.
- `client/src/utils/exporters.js:100` — `console.warn('No trades to export')`; no user-visible feedback.
- No `debugger` statements found.
- **Severity:** medium (AlgoTrading silent failure) / low (others) | **Effort:** S | **Type:** bug

#### 4.1.6 TODO / FIXME / XXX
- **None found** in `client/src/**`. Clean.

#### 4.1 Other (code quality)
- `client/src/pages/Trade.jsx:31-76` — defines local `fmtPrice`, `fmtQty`, `fmtPct` that duplicate `client/src/utils/formatters.js`. Covered and sequenced in §3.5. **Severity:** medium | **Effort:** M | **Type:** refactor.
- `client/src/pages/Trade.jsx` (1683 lines) and `client/src/pages/RiskDashboard.jsx` (551 lines, 16 `useState` hooks, zero sub-component decomposition) — both exceed the "should be split" threshold. **Severity:** medium (maintainability) | **Effort:** L | **Type:** refactor.
- `client/src/components/algo/ChaosWizard.jsx` (654 lines), `client/src/components/algo/SessionCard.jsx` (582 lines) — large single-file components. **Severity:** low | **Effort:** L | **Type:** refactor.
- Error-handling inconsistency: `ChaosWizard.jsx`, `Settings.jsx`, `AdminPanel.jsx` use inline error banners correctly. `AlgoTrading.jsx:44-50`, `SessionCard.jsx:90-97` silently `console.error` with no user feedback. Should match the inline-banner pattern everywhere. **Severity:** medium | **Effort:** S | **Type:** bug.

**Plan:** build a focused code-quality PR targeting §4.1.5 + §4.1.2 + §4.1.1 in that order (all S/M effort), then §4.1.4 as a follow-up lazy-loading PR. §4.1 L-effort refactors (split Trade.jsx, RiskDashboard) are their own separate tickets.

### 4.2 Design system & visual consistency

**Status: COMPLETE — agent returned findings.**

#### 4.2.1 Card primitive bypassed (10+ files)
- **Finding:** `components/ui/card.jsx` EXISTS and exports `Card`, `CardHeader`, `CardContent`, etc. Despite this, hand-rolled `bg-[#0d1117] border border-slate-700/50 rounded-none` appears across 10+ pages.
- **Files:** `RiskDashboard.jsx:241,278,298,314,332,350,365,432,457` · `Backtest.jsx:459,462,464-491` · `Trade.jsx:382,391` · `OrderHistory.jsx:121` · `AdminPanel.jsx:20,68,82` · `Strategies.jsx:28,30` · `AlgoTrading.jsx:83,92,101` · `BacktestHistory.jsx:228,257,270` · `SessionCard.jsx:200,270,400`
- **Fix:** Systematically replace hand-rolled card `div`s with `<Card>` + `<CardContent>` / `<CardHeader>`.
- **Severity:** medium | **Effort:** L | **Type:** drift

#### 4.2.2 No `<Badge>` component — 15+ ad-hoc badge implementations
- **Finding:** No `components/ui/badge.jsx` exists. Every badge is hand-coded with inconsistent opacity and spacing:
  - Long/short: `Trade.jsx:451` uses `bg-emerald-500/20`; `OrderHistory.jsx:100-110` uses `bg-emerald-400/10` (different opacity)
  - Status: `SessionCard.jsx:239-260` has 6 inline strings for each status (`running`, `stopped`, etc.)
  - Source: `OpenOrdersTable.jsx:101` + `OrderHistoryTable.jsx:85` — `bg-indigo-500/20 text-indigo-400` for bot orders
- **Fix:** Create `components/ui/badge.jsx` with `variant` prop covering `long | short | buy | sell | status | source`. Replace all 15+ sites.
- **Severity:** medium | **Effort:** M | **Type:** drift

#### 4.2.3 P&L color drift — `text-green-*` and `text-red-500` (HIGH priority)
- **Finding:** Project rule: `emerald-400` for profit, `red-400` for loss. Violations:
  - `text-green-400`: `Dashboard.jsx:164` · `SessionCard.jsx:73` · `RecentActivityTable.jsx:67` · `SessionCard.jsx:243` (status badge) · `RiskDashboard.jsx:403`
  - `text-red-500`: `RecentActivityTable.jsx:68` · `SessionCard.jsx:80` (in addition to `Backtest.jsx` already in Phase 1)
- **Fix:** Grep-replace `text-green-400` → `text-emerald-400` and `text-red-500` → `text-red-400` across `client/src`. Verify `bg-green-*` → `bg-emerald-*` in badge backgrounds.
- **Severity:** high | **Effort:** S | **Type:** drift

#### 4.2.4 25+ raw `<button>` elements bypassing the Button primitive
- **Finding:** `components/ui/button.jsx` EXISTS with `default | destructive | outline | secondary | ghost | link` variants. Despite this, raw `<button className="...">` elements appear throughout:
  - `Trade.jsx:269,287-300,1582,1594`
  - `Backtest.jsx:605-607` (pagination)
  - `OrderHistory.jsx:184-197` (pagination)
  - `RiskDashboard.jsx:184,240,253`
  - `SessionCard.jsx:373-382`
  - `AdminPanel.jsx:32,42,57,67`
  - `Settings.jsx:90,100,169`
  - `BacktestHistory.jsx:65,69,74`
- **Fix:** Progressively convert raw buttons to `<Button variant="...">`. Prioritize destructive actions and primary submit buttons. Defer pagination (covered by §3.3).
- **Severity:** medium | **Effort:** L | **Type:** drift

#### 4.2.5 Skeleton backgrounds use wrong palette (`bg-gray-*`)
- **Finding:** Skeletons use `bg-gray-900` / `bg-gray-800` — violates midnight-blue palette rule.
  - `AlgoTrading.jsx:97,101` — `bg-gray-900 animate-pulse`
  - `Dashboard.jsx:32,38,44` — `bg-gray-900`
  - `BacktestHistory.jsx:148,152` — `bg-gray-800`
- **Fix:** Replace with `bg-slate-800/50` or `bg-[#0d1117]` + `animate-pulse`. Optionally extract a `<Skeleton>` primitive.
- **Severity:** low | **Effort:** S | **Type:** drift

#### 4.2.6 No icon drift (only the intentional Enma logo SVG)
- All icon imports come from `lucide-react`. The custom SVG at `Navbar.jsx:55-58` is the Enma logo mark — intentional. No action needed.

**Plan:** Build a "design system sweep" PR targeting §4.2.3 first (S effort, high severity), then §4.2.2 (Badge), then progressively §4.2.1 and §4.2.4.

### 4.3 Responsiveness & mobile

**Status: COMPLETE — agent returned findings.**

#### Mobile readiness by page

| Page | Score | Primary blocker |
|------|-------|----------------|
| `Trade.jsx` | **Broken** | 4-panel desktop-only layout, no breakpoints at all |
| `Backtest.jsx` | **Needs work** | `overflow-hidden` on stacked grid hides results column on mobile |
| `OrderHistory.jsx` | Needs work | Outer `overflow-hidden` may fight table's inner `overflow-auto` |
| `BacktestHistory.jsx` | Needs work | `text-[9px]` meta pills, ~30px touch targets |
| `AlgoTrading.jsx` | Needs work | `grid-cols-4`/`grid-cols-3` in SessionCard, no breakpoints |
| `Settings.jsx` | Needs work | `grid-cols-3` at line 365, tight at 375px |
| `RiskDashboard.jsx` | Needs work | `grid-cols-3` no breakpoints |
| `NewBacktestWizard.jsx` | Needs work | `grid-cols-2` form fields inside dialog, no breakpoints |
| `Dashboard.jsx` | **Ready** | `grid-cols-1 sm:grid-cols-2 lg:grid-cols-4` already responsive |
| `Strategies.jsx` | Ready | `grid-cols-1 md:grid-cols-2 lg:grid-cols-3` collapses correctly |
| `Login.jsx` | Ready | `sm:grid-cols-2` collapses to 1 col |
| `Settings.jsx` | Ready (mostly) | Single-column overall, minor inner grid |
| `AdminPanel.jsx` | Ready | Simple list, low risk |

#### 4.3.1 Trade.jsx — 4-panel desktop-only layout (CRITICAL)
- **File:** `client/src/pages/Trade.jsx:228-240`
- **Issue:** `flex flex-row` with `w-[240px]` order book + auto chart + `min-w-[320px]` form. Total minimum width ~1060px. At 375px the body horizontally scrolls, no panels usable.
- **Fix:** Mobile tab layout — Chart tab, Order Book tab, Recent Trades tab; trade form stays accessible at bottom or in dedicated tab. Requires breaking Trade.jsx into sub-panels.
- **Severity:** critical | **Effort:** L

#### 4.3.2 Dashboard StatCard grid (CRITICAL)
- **File:** `client/src/pages/Dashboard.jsx:59`
- **Issue:** `grid grid-cols-4 gap-4` with no `sm:` / `md:` breakpoints.
- **Fix:** `grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4`
- **Severity:** critical | **Effort:** S

#### 4.3.3 Tables missing `overflow-x-auto` (CRITICAL — 4 tables)
- **Files:**
  - `client/src/components/features/trade/PositionsTable.jsx` — container in `Trade.jsx:738` has no `overflow-x-auto` (9 cols)
  - `client/src/pages/OrderHistory.jsx:121` — no `overflow-x-auto` (8 cols)
  - `client/src/features/backtest/BacktestHistory.jsx:228` — no `overflow-x-auto` (9 cols)
  - `client/src/components/features/dashboard/RecentActivityTable.jsx` — no `overflow-x-auto` (6 cols)
- **Fix:** Wrap each table in `<div className="overflow-x-auto">`. As a follow-up, hide non-essential columns at mobile with `hidden sm:table-cell`.
- **Severity:** critical (3 of 4) / high (1) | **Effort:** S per table

#### 4.3.4 Grid layouts without responsive breakpoints (7 pages)
- `Dashboard.jsx:115,141` — `grid-cols-3` + `grid-cols-2` bottom panels
- `AlgoTrading.jsx:106` — `grid-cols-3` session grid
- `Backtest.jsx:462-491` — `grid-cols-4` KPI cards + `grid-cols-2` secondary
- `RiskDashboard.jsx:241` — `grid-cols-3`
- **Fix:** Add `grid-cols-1 sm:grid-cols-2 lg:grid-cols-N` to each. All are `S` effort individually.
- **Severity:** high | **Effort:** S per page

#### 4.3.5 Touch targets < 44px
- `Trade.jsx:269-287` — timeframe pill buttons `px-2 py-1 text-xs` → ~28px height
- `Backtest.jsx:605-660` + `OrderHistory.jsx:183-196` — pagination buttons ~32px height
- `OpenOrdersTable.jsx:105` — cancel icon button `w-6 h-6` (24px)
- `PositionsTable.jsx` — close position button ~28px
- `SessionCard.jsx:373-389` — delete/expand icon buttons ~24px icon in ~32px target
- **Fix:** Add `min-h-[44px] min-w-[44px]` or `p-3` to icon-only buttons. Pagination buttons need `h-10 w-10`.
- **Severity:** medium | **Effort:** S

#### 4.3.6 Modals that overflow on 375px
- `ChaosWizard.jsx:~30` — `max-w-4xl` (896px) — definitively overflows 375px. Add `w-full mx-4` for mobile.
- `NewBacktestWizard.jsx:~40` — `max-w-2xl` in a Dialog. Add vertical step indicator for mobile (horizontal 4-step bar is unreadable at 375px). Switch `grid-cols-2` form fields to `grid-cols-1` on mobile.
- `Trade.jsx TpSlModal:542-672` — custom div modal with `max-w-md` but no mobile positioning guarantee (not Radix). Phase 1 (§2.5) converts it to Radix, which fixes this.
- **Severity:** high | **Effort:** M

#### 4.3.7 Chart containers
- `Trade.jsx:179-205` — `createChart()` with `containerRef.current.clientHeight`. If container has no explicit height on mobile (flex collapse), chart renders 0px tall.
- `EquityCurve.jsx` — `h-64` fixed. Fine but wastes vertical space on mobile; consider `h-48 md:h-64`.
- **Fix:** Add explicit `min-h-[200px]` to the Trade chart container. Verify `autoSize: true` is set on the lightweight-charts instance.
- **Severity:** high (Trade chart) / low (EquityCurve) | **Effort:** S

**Plan:** Mobile work in order — (1) S-effort table + grid fixes first (§4.3.2–4.3.4), (2) touch targets + modals, (3) Trade page layout restructure (largest item, warrants its own PR).

### 4.4 Optimistic updates

- **Files:**
  - `client/src/hooks/useTrade.js:127-133` (useCancelOrder — no optimistic update)
  - `client/src/hooks/useAlgoSessions.js:52-61` (useDeleteSession)
  - `client/src/hooks/useAlgoSessions.js:63-72` (useDeleteAllStopped)
  - `client/src/hooks/useExchangeSettings.js` (no optimistic form update)
  - `client/src/hooks/useBacktest.js:87-99` (useCancelBacktest)
- **Issue:** User clicks → order/session stays visible for 3-10s until next poll. Feels broken.
- **Fix:** Add `onMutate` to remove from cache optimistically, `onError` to restore, `onSettled` to invalidate.
- **Effort:** M
- **Severity:** medium
- **Type:** UX

### 4.5 Real-time update animations

- **Files:**
  - `client/src/components/algo/SessionCard.jsx:131-145` (equity chart append — no flash)
  - `client/src/pages/Trade.jsx:411` (recent trades prepend — no animation)
  - `client/src/pages/Trade.jsx:82-91` (ticker price jumps — no interpolation)
  - `client/src/components/algo/SessionCard.jsx:73-80` (PnL silent updates)
- **Fix:** Subtle: briefly highlight the new row/point in `bg-emerald-400/10` for 600ms, then fade. For the ticker, animate the number (count-up animation) over 200ms. Apply only where it doesn't create distracting motion.
- **Effort:** M
- **Severity:** low
- **Type:** polish

### 4.6 Bulk select on order tables

- **Files:**
  - `client/src/components/features/trade/PositionsTable.jsx` (positions)
  - `client/src/components/features/trade/OpenOrdersTable.jsx` (open orders)
  - `client/src/components/features/trade/OrderHistoryTable.jsx`
- **Issue:** Cancel-All is single-action. No way to select 3 of 5 orders to cancel.
- **Fix:** Add `<BulkActionBar>` with a checkbox column, select-all-in-page, and a "Cancel selected (N)" action (already a confirmation dialog from Phase 1).
- **Effort:** L
- **Severity:** low (nice-to-have)
- **Type:** UX

### 4.7 Network error UX

- **Files:** `client/src/lib/axios.js:1-7` (no interceptors)
- **Issue:** No global "Backend unreachable" banner. Each page handles errors independently. Some pages have no error branch at all.
- **Fix:**
  1. Add an axios response interceptor in `lib/axios.js` that, on 5xx or network error, raises a global "Backend unreachable — retrying" banner.
  2. Add `navigator.onLine` check + "You're offline" banner.
  3. Add Retry buttons to all error states (`OrderHistory.jsx:94-100`, `BacktestHistory.jsx`, `Dashboard.jsx:191-194`).
- **Effort:** M
- **Severity:** medium
- **Type:** UX + bug

### 4.8 Lazy-load heavy components

- **Files:** `client/src/components/charts/EquityCurve.jsx`, `client/src/components/charts/DrawdownSparkline.jsx`, `client/src/components/charts/EquitySparkline.jsx`, `client/src/components/algo/ChaosWizard.jsx`, `client/src/features/backtest/BacktestCalendar.jsx`
- **Issue:** No `React.lazy` + `<Suspense>` anywhere. The whole 1.5MB+ chart bundle is in the initial chunk.
- **Fix:** `const EquityCurve = React.lazy(() => import('./EquityCurve'))` in each consumer; wrap with `<Suspense fallback={<Skeleton .../>}>`. Move RiskDashboard charts to lazy too.
- **Effort:** M
- **Severity:** medium (perf)
- **Type:** refactor

### 4.9 Form validation & required-field markers

- **Files:** widespread (UX/A11y audit found ~10 sites)
  - `client/src/components/RiskParamsFields.jsx:55-65`
  - `client/src/components/algo/ParamsForm.jsx:8-25`
  - `client/src/pages/Trade.jsx:1386-1444, 519-606`
  - `client/src/pages/Settings.jsx:438-447, 439-544`
  - `client/src/features/strategies/StrategyCreateDialog.jsx:46-72, 107-111`
  - `client/src/features/backtest/NewBacktestWizard.jsx:341-370`
- **Issue:** No `aria-required` markers. No `*` in labels. No on-blur validation. No `aria-invalid` + `aria-describedby` for errors. Screen-reader users get no feedback.
- **Fix:**
  1. Add a `<FormField label="..." required error="..." hint="...">` primitive.
  2. Add `*` next to required labels (red-400) and `aria-required="true"`.
  3. Validate on blur, not just on submit.
  4. Wire `aria-invalid` and `aria-describedby` to error messages.
- **Effort:** L
- **Severity:** medium (a11y)
- **Type:** a11y

---

## 5. Decision points (need user input)

Before Phase 1 ships, these need your call. Each has a default I'll proceed with if you don't reply, but I want to surface the trade-off.

### 5.1 Spec vs. current navbar

The spec says 6 nav items, no mobile hamburger. The code has 7 items, mobile hamburger, Risk Dashboard as a nav item. Two choices:

- **(A) Match the spec** — remove mobile hamburger, restore order, remove Order History from nav, promote Settings. (Effort: 2h. Loses recent improvements.)
- **(B) Update the spec** — keep current code, document it. (Effort: 30min. Recommended.)
- **Default: B.** The current code is more usable. Update `client/CLAUDE.md` and `CURRENT_STATE.md`.

### 5.2 Toast library

- **sonner** — lightweight (5kb), themeable, works with Vite, React 18. (Recommended.)
- **react-hot-toast** — more popular, slightly more weight, fewer dark-theme defaults.
- **Hand-roll** — keep current, just fix the inconsistencies. (Cheapest, lowest quality.)
- **Default: sonner.**

### 5.3 Avatar circle

- The global `borderRadius: 0` Tailwind override means `rounded-full` doesn't work. The current code uses inline `style={{ borderRadius: '50%' }}` 3 times.
- **(A) Add `[border-radius:50%]` arbitrary class.** (Recommended.)
- **(B) Add `rounded-full` exception to `tailwind.config.js`.**
- **(C) Document the inline-style exception in `client/CLAUDE.md`.**
- **Default: A.**

### 5.4 Mobile scope

The user said "major mobile mode". Three options:

- **(A) Mobile-friendly (375px readable, no horizontal scroll, all primary actions reachable).** 1 week.
- **(B) Mobile-first redesign (375px native, 768px tablet-optimized).** 3 weeks.
- **(C) Mobile-readable (works on phone but trades aren't optimized for touch).** 3 days.
- **Default: A.** Triggers a follow-up conversation if you want B.

### 5.5 Sortable tables

- **(A) Client-side sort** for tables that already have all rows in memory (Dashboard tables, history ≤100 rows). 4h.
- **(B) Server-side sort** for OrderHistory and BacktestHistory (paginated). 1d + contract change.
- **Default: A for now. B as a separate ticket.**

---

## 6. Sequencing (proposed sprint order)

| Week | Focus | Ship criteria |
|---|---|---|
| **W1 day 1** | Phase 1 (12 items) | All `alert()` gone, all destructive actions confirmed, ErrorBoundary in place, 404 page, 2 modals converted, color drift fixed, fetch→axios, spot option removed, failed backtest UX fixed, aria-busy on Buy/Sell, deep-link error UX, typo fixed. |
| **W1 day 2-3** | Phase 2.1-2.3 (Navbar, pagination, color contrast, sort+filter URL state) | Navbar spec-aligned, pagination primitive, all `text-slate-500` → `text-slate-400` for body, filter state in URL. |
| **W1 day 4-5** | Phase 2.4-2.6 (formatters, dates, empty states) | `formatCompact`, `formatDateTime` in formatters.js; all ad-hoc format calls replaced; `<EmptyState>` primitive; all 12+ sites updated. |
| **W2** | Phase 2.7-2.10 (toasts, ARIA sweep, stale indicators, docs) | sonner installed, all hand-rolled banners replaced, ~25 icon-only buttons labeled, form fields associated, doc updates. |
| **W2-W3** | Phase 3.1-3.3 (code quality, design system, mobile) | Once the 3 remaining agents return. |

---

## 7. Verification (how to know it's done)

After each phase, verify with these checks:

### Per-page checklist
- [ ] **Mobile 375px** — no horizontal scroll, primary action reachable, text ≥14px, touch targets ≥44px.
- [ ] **Tablet 768px** — layout uses available space, no awkward 1-column collapse where 2 fits.
- [ ] **Desktop 1440px** — content uses width without becoming stretched.
- [ ] **Loading state** — skeleton or spinner on every async view.
- [ ] **Empty state** — icon + message + CTA on every list.
- [ ] **Error state** — inline banner with retry on every list.
- [ ] **A11y** — axe-core scan returns 0 critical violations.
- [ ] **Keyboard** — every interactive element reachable via Tab, focus visible, modals trap focus.
- [ ] **Color contrast** — manual spot-check of all `text-slate-*` against panel bg.
- [ ] **Color rule** — only `emerald-400` for profit, `red-400` for loss, no `green-*` or `red-500`.

### Global
- [ ] No `alert(` in `client/src/`
- [ ] No `console.log` / `debugger` / `TODO` / `FIXME` in `client/src/`
- [ ] All queries have `isError` + retry
- [ ] All mutations have `onError` (or a global error boundary)
- [ ] All icon-only buttons have `aria-label`
- [ ] No raw `fetch(...)` (only axios)
- [ ] `client/CLAUDE.md` matches the actual structure
- [ ] `API_CONTRACTS.md` lists all client-callable endpoints
- [ ] Golden master still passes (no engine changes expected, but verify)

### Tools
- Lighthouse: a11y score ≥95, perf score ≥90.
- axe-core: 0 critical, ≤3 serious.
- Manual: keyboard-only walkthrough of every page.
- Manual: 375px, 768px, 1440px walkthrough of every page.

---

## 8. Open questions / followups

- **Skipped pending agents:** §4.1 (code quality), §4.2 (design system), §4.3 (mobile) will be filled in once the 3 remaining audit agents return. The final plan will have those sections integrated.
- **Golden master:** No engine code is touched in this plan, so the golden master should remain valid. Run it after the W1 day-1 PR just to be safe.
- **Bundle size:** The lazy-loading PR (§4.8) should be measured before/after with `vite-bundle-visualizer` to confirm impact.
- **Toast duration:** 4s default, 8s for OCO dual-notification. The OCO rule (CORE RULES 5) needs dual toast + banner — so a single toast is *not* sufficient. Plan §3.9 keeps the OCO banner + adds a toast.

---

## Appendix A — Verified findings (already in code, not just agent reports)

The UX/A11y and drift agents returned real evidence. I spot-checked these before writing the plan:

- `client/src/components/layout/Navbar.jsx:20-28` — confirmed: 7 nav items, Order History is in nav, Risk Dashboard is in nav, mobile hamburger exists. Spec says 6 items, no mobile hamburger, no Order History in nav.
- `client/src/components/layout/Navbar.jsx:120, 127, 132` — confirmed: 3× `style={{ borderRadius: '50%' }}` (inline style, violates "Tailwind only").
- `client/src/components/layout/Navbar.jsx:60-66` — confirmed: hamburger button has no `aria-label`, no `aria-expanded`, `focus:outline-none` (no focus ring).
- `client/src/pages/RiskDashboard.jsx:79, 114, 132, 161, 179` — confirmed: 5× `alert(...)` calls.

These are real, not hallucinated. The other items are reported by the agents with `file:line` and are high-confidence.

---

## Appendix B — Counts

| Lens | Agent | Status | Findings |
|---|---|---|---|
| UX & A11y | claude-1 | ✅ Complete | ~60 |
| Drift (6 vectors) | drift-reviewer | ✅ Complete | 20 |
| Code quality | claude-2 | ✅ Complete | 14 |
| Design system | claude-3 | ✅ Complete | 6 |
| Responsiveness | claude-4 | ✅ Complete | 10+ |

All 5 lenses complete. Plan is ready to execute.
