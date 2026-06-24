# Plan — Finish Dashboard KPI Restructure (Seq #3)

**Status:** Implementation in flight in working tree (uncommitted, 2026-06-24). Docs-only refinement of `dashboardPage_restructure.md`.
**Goal:** Get seq #3 to a verified, committed state, then unblock seq #4.
**Author confidence:** `[Certain]` on file states and engine math; `[Likely]` on perf claim (see §6).

---

## 1. Reality Check (vs. the original plan)

`dashboardPage_restructure.md` proposed 8 KPI cards + 2 sparklines + a performance-calendar heatmap + a new `/dashboard/performance-calendar` endpoint. Inspecting the working tree on 2026-06-24:

| Plan item | Where it lives today | State |
|-----------|----------------------|-------|
| 8 KPI cards (Total Runs, Best Strategy, Avg Win Rate, Profit Factor, Avg Sharpe, Avg Sortino, Max Drawdown, Expectancy) | `client/src/pages/Dashboard.jsx:175-225` | ✅ Wired (uses `DEFAULT_STATS` fallbacks for all new fields) |
| `latestRunId` extended onto `/stats` response | `engine/routers/dashboard.py:46` (default `None`), `:110` (computed via `max(updatedAt)`) | ✅ Extended |
| `avgProfitFactor`, `avgSharpe`, `avgSortino`, `worstDrawdown`, `avgExpectancy` | `engine/routers/dashboard.py:103-109` | ✅ Computed |
| `EquitySparkline.jsx` | `client/src/components/charts/EquitySparkline.jsx` (untracked, new) | ⚠️ Created, **not yet audited** |
| `DrawdownSparkline.jsx` | `client/src/components/charts/DrawdownSparkline.jsx` (untracked, new) | ⚠️ Created, **not yet audited** |
| `DashboardCalendar.jsx` | `client/src/features/dashboard/DashboardCalendar.jsx` (untracked, new) | ⚠️ Created, **not yet audited** |
| `GET /dashboard/performance-calendar` endpoint | `engine/routers/dashboard.py:134-178` | ✅ Implemented (full scan over `backtestTrades`) |
| Server proxy `getPerformanceCalendar` + route | `server/src/controllers/dashboard.controller.js:14`, `server/src/routes/dashboard.routes.js:6` | ✅ Implemented |
| Client hook `useDashboardCalendar` | `client/src/hooks/useDashboard.js:24` | ✅ Implemented |
| Layout wiring (8-card grid, sparkline row, calendar, leaderboard, candles) | `client/src/pages/Dashboard.jsx:174-292` | ✅ Wired |

**Verdict:** Implementation is feature-complete on the page side. The remaining work is **verify, audit, fix, and commit**, not "write more code."

---

## 2. Issues Already Spotted (working tree, 2026-06-24)

These are flagged **before** we run anything — auditing the new code:

### Issue 3-A — `useBacktestResult(undefined)` returns nothing useful
**File:** `client/src/pages/Dashboard.jsx:127`
**Symptom:** `useBacktestResult(stats.latestRunId || undefined)` is called even when `latestRunId` is `null`. TanStack Query still issues a request to `/api/v1/backtest/undefined` which the server rejects as an invalid ObjectId — wasted network round-trip + console noise on first load when no runs exist yet.
**Severity:** Low (cosmetic noise; no user-visible bug because the sparklines correctly handle empty `equityCurve`).
**Fix:** Gate the query with `useBacktestResult(latestRunId)` and `enabled: Boolean(latestRunId)`. The hook signature already takes `id` — need to verify it accepts an `enabled` option (the underlying `useQuery` does, but the wrapper may not surface it).

### Issue 3-B — `/dashboard/performance-calendar` full-collection scan on every page load
**File:** `engine/routers/dashboard.py:142-147`
**Symptom:** `cursor.to_list(length=100_000)` reads **every** trade in `backtestTrades` on every Dashboard mount. At ~10K trades per 100K-candle backtest and 10+ completed runs, this is the slowest part of the Dashboard load by a wide margin. Worse: the hook uses `staleTime: 60_000`, so the first Dashboard render after refresh blocks on it.
**Severity:** Medium (perf, not correctness).
**Fix options:**
1. **MongoDB aggregation pipeline** — `$group` server-side by `exitAt` substring, project `{ pnl, count }`. Faster (single round-trip, no Python loop) and scales. ~10 lines.
2. **Time-bounded query** — accept `?since=YYYY-MM-DD`, default to last 365 days. Caps the data volume; the client already filters by 30/90/all. Cleaner but moves the limit choice server-side.
3. **Cache to MongoDB** — `dashboard_day_aggregates` collection, refreshed on backtest completion. Most invasive; revisit only if scans become a real problem.

**Recommendation:** Option 1 (aggregation pipeline). Lowest-effort, biggest win, doesn't change the contract.

### Issue 3-C — `worstDrawdown` semantics ambiguity (client vs. server)
**File:** `engine/routers/dashboard.py:108`, `client/src/pages/Dashboard.jsx:215`
**Symptom:** Server stores `maxDrawdown` as a **non-positive** number (e.g. `-14.16` meaning -14.16% from peak). The engine does `min(drawdowns)` which returns the deepest trough (most negative) — that *is* the worst drawdown, but the field name "worst" is a bit redundant with `maxDrawdown`. The client renders `${parseFloat(stats.worstDrawdown).toFixed(2)}%` — note it **doesn't** prepend a `-` sign because `toFixed(2)` on `-14.16` already includes the sign. Good — no bug, just naming clarity. The card label "Max Drawdown" with subtext "Worst peak-to-trough" is consistent with the Backtest Overview tab label ("Max Drawdown: actual / allowed").
**Severity:** None (no fix needed; flagging because the duplicate concept — `maxDrawdown` per run vs. `worstDrawdown` across runs — could confuse future readers).

### Issue 3-D — `expectancy` sign and formatting
**File:** `client/src/pages/Dashboard.jsx:221`
**Symptom:** `signed(stats.avgExpectancy)` prepends `+`/`-` correctly. But `expectancy` is in **dollar units** (avg $ P&L per trade), not a percentage. The card subtext says "Avg P&L per trade" — accurate. The icon `Target` is fine. No bug; documenting because `formatPnl` would also work and is more visually consistent with the rest of the app (it adds `$`).
**Recommendation:** Switch to `formatPnl(stats.avgExpectancy)` for visual consistency with the Recent Runs P&L column. Minor polish.

### Issue 3-E — Sparkline components unverified
**Files:** `client/src/components/charts/{EquitySparkline,DrawdownSparkline}.jsx` (new, untracked)
**Symptom:** Not yet read. Need to verify:
- Recharts config matches `client/CLAUDE.md` Chart rules (axis colors, baseline dasharray, line colors `#34d399`/`#f87171`).
- No axes, no tooltip per the original spec.
- Responsive container sizing ~300×90.
- `emerald-400`/`red-400` color rule per Aesthetics Invariant.
- `gap-0`, no rounded corners (per layout rules).

### Issue 3-F — `DashboardCalendar.jsx` unverified
**File:** `client/src/features/dashboard/DashboardCalendar.jsx` (new, untracked)
**Symptom:** Not yet read. Need to verify:
- Filters client-side by `timeframe` prop.
- Color logic matches `BacktestCalendar.jsx` (emerald for profit, red for loss).
- No tab UI (day view only per the original spec).
- Empty state when `days` is empty.
- Does not import `backtest-analytics.js` (data is already pre-aggregated).

---

## 3. Step-by-Step Plan (Finish & Verify)

### Phase A — Audit (no code changes)
1. Read the three untracked files (`EquitySparkline.jsx`, `DrawdownSparkline.jsx`, `DashboardCalendar.jsx`) against §2 Issues 3-E/3-F.
2. Read `useBacktest.js` to confirm whether `useBacktestResult` accepts an `enabled` option (for Issue 3-A).

### Phase B — Fixes (small)
1. **Issue 3-A:** Add `enabled: Boolean(stats.latestRunId)` to the sparkline query, or split into two branches. Pick the option that requires fewer hook changes.
2. **Issue 3-B:** Convert `/dashboard/performance-calendar` from Python loop to MongoDB aggregation pipeline (`$group` by date-substring of `exitAt`). Add a quick perf comparison: count of returned days, wall-clock time before/after.
3. **Issue 3-D:** Change `signed(stats.avgExpectancy)` → `formatPnl(stats.avgExpectancy).value` (and use `.isPositive` for color class).

### Phase C — Verify
1. `docker compose exec client npm run build` — must pass clean (no new errors). Pre-existing chunk-size warning is fine.
2. `docker compose exec server npm test` (if present) or smoke-test: `curl localhost:8000/api/v1/dashboard/stats` → confirm all 9 fields present, `latestRunId` populated for a known completed run.
3. `curl localhost:8000/api/v1/dashboard/performance-calendar` → confirm `{days: [...]}` shape, dates ascending, pnl rounded to 2 dp.
4. Visual: load `/` in browser; confirm 8 cards, sparkline, calendar, leaderboard all render with data. Empty-state copy correct if `totalRuns === 0`.
5. `docker compose exec engine python -m pytest tests/test_boundaries.py -q` — sanity check no engine boundary regression (no engine *logic* changed, but MongoDB queries were added).

### Phase D — Commit & Docs
1. `git add` the 7 modified + 3 new files. Commit with body citing this plan.
2. Update `workspace/docs/state/CURRENT_STATE.md` "Dashboard" subsection — remove "In Progress", promote to "Implemented".
3. Update `workspace/plan/INDEX.md` — mark seq #3 done, archive `dashboardPage_restructure.md` (it's the predecessor; this doc is the canonical record).
4. Update `workspace/plan/STATUS.md` + `workspace/plan/handoff.md` — append a dated entry.

---

## 4. Risks & Rollback

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Aggregation pipeline changes `days` shape | Low | Pure refactor; preserve sort + 2-dp rounding. Verify by comparing curl output before/after. |
| Sparkline color breaks Aesthetics Invariant | Low | Already enforced via `EquityCurve.jsx` precedent (emerald for profit, red for loss). |
| Calendar import regresses when `days` empty | Low | Empty-state branch should already exist; verify visually. |
| `useBacktestResult(enabled:false)` doesn't accept the option | Low | If the wrapper doesn't expose `enabled`, fall back to a conditional render or split the hook. |
| Breaking the `/stats` response shape (cliens depend on `stats.X`) | Low | Adding fields is non-breaking; removing or renaming would be. We're only adding. |

Rollback is a single `git reset --soft HEAD~1` followed by `git restore --staged .` — **only on user instruction** (Rule H). Not done automatically.

---

## 5. Integration with the Platform

Where this lands in the wider system:

### Touches
- **Engine `routers/dashboard.py`** — pure read aggregation; no schema change; no write path. Engine remains sole writer of `backtestResults`/`backtestTrades` (unchanged).
- **Server `controllers/dashboard.controller.js`** — pure proxy; no validation logic added (none needed; engine returns 200 + `{success:true,data:{...}}`).
- **Client `useDashboard.js`** — adds one query hook; query key `['dashboard','performance-calendar']` follows the existing `['resource', id, filters]` pattern.
- **Navbar / routes** — no change. `/` route stays `/`; Dashboard component enhanced in place.

### Doesn't touch
- MongoDB schema (no fields added to `backtestResults` or `backtestTrades`).
- TimescaleDB (still engine-only).
- Backtest worker (`backtest.worker.js`), live bot manager, or any strategy.
- Settings / risk model / order history.
- The Risk Dashboard work (seq #4) — that page will read from these endpoints, but its work is independent.

### Contract surface
- `GET /api/v1/dashboard/stats` — response gains 5 fields + `latestRunId`. Documented in `workspace/docs/core/API_CONTRACTS.md` (needs an update entry as part of Phase D).
- `GET /api/v1/dashboard/performance-calendar` — **new** endpoint. Document shape: `{ success, data: { days: [{ date: 'YYYY-MM-DD', pnl: number, trades: number }] } }`. Sort: `date` ASC. Pagination: none (designed to fit in one response).

### Data freshness
- `useDashboardStats()` — no `staleTime` set → defaults to 0, refetches on remount. Acceptable for a landing page.
- `useDashboardCalendar()` — `staleTime: 60_000` → 1 min cache. Good for a heatmap that doesn't change candle-by-candle.
- `useBacktestResult(latestRunId)` — when used for sparklines, also no explicit staleTime. A completed-run equity curve never changes, so a `staleTime: Infinity` + `gcTime: Infinity` could cache forever. **Not changing in this plan** — premature optimization; revisit if Dashboard becomes the bottleneck.

---

## 6. Open Questions for the User

1. **Issue 3-B fix scope.** Convert the Python loop to a MongoDB aggregation pipeline (recommended), or accept the full-scan perf cost and revisit later? `[Likely]` the user wants it fixed now — but I haven't been told.
2. **Issue 3-D formatting polish** — `formatPnl` swap. Cosmetic. Default to **applying** unless user objects.
3. **Should this plan commit phase-by-phase (one commit per issue) or as a single "finish dashboard" commit?** `[Guessing]` single commit is cleaner for a self-contained feature landing.
4. **When done, archive `dashboardPage_restructure.md` to `archive/`?** `[Likely]` yes — this doc supersedes it.

---

## 7. Done = When

- All 3 issues in §2 fixed (or explicitly deferred with rationale).
- Phase C verification passes (build clean, both endpoints return expected shape, visual check OK).
- Commit landed.
- `CURRENT_STATE.md`, `INDEX.md`, `STATUS.md`, `handoff.md`, `API_CONTRACTS.md` updated.
- `dashboardPage_restructure.md` archived.
- Handoff prompt appended to `handoff.md` for the next session to start on seq #4.