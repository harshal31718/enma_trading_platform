# Plan — Risk Dashboard (Seq #4)

**Status:** Proposed. Sequenced after Dashboard KPI restructure (seq #3). Refines `RISK_DASHBOARD_PLAN.MD` (which is a vision doc) into an executable, gated plan.
**Confidence:** `[Likely]` on feature scope (vision doc is solid); `[Guessing]` on timeline (depends on #3 finishing first and on user's appetite for risk-model surface area).
**Goal:** Add a dedicated `/risk-dashboard` nav page that gives the operator a single pane of glass for portfolio-level risk across backtests and live sessions.

---

## 1. Why this is seq #4, not #3

`workspace/plan/INDEX.md` already sequences it. The reasoning it codifies:

1. **Risk Dashboard reads risk-model primitives.** The hierarchical parameter controls in Zone 2 (`trail_atr_mult`, `min_edge_mult`, `max_portfolio_risk`, `breakeven_r`, `atr_percentile_min`) all live on `AtrBracketRiskModel` from workstream #2. Those need to be **stable** before we build UI on top of them — otherwise the dashboard is showing controls whose effect changes underneath.
2. **Risk Dashboard re-baselines the golden master.** Zone 3 (Leverage Sensitivity, Monte Carlo Ruin Curve) introduces new engine math. Per Rule C (Golden Master), any pipeline refactor >3 files or new engine service must re-baseline. Building it on top of a stable risk model means a single, clean baseline run instead of cascading re-baselines.
3. **Dashboard KPI restructure (seq #3) is independent** — pure client/aggregation work. It can land before, during, or after #4 with no coupling. By the time we start #4, the existing Dashboard will be a familiar design language for the operator.

**Pre-condition:** seq #3 (this doc's sibling) must be merged first. Otherwise the operator has two dashboards with overlapping but inconsistent KPI conventions, which is the worst kind of UX debt.

---

## 2. Scope (refined from `RISK_DASHBOARD_PLAN.MD`)

The vision doc proposes three zones. Refinements after auditing:

### Zone 1 — Real-Time Portfolio Risk (Live Active Sessions)
**Wired:** `GET /api/v1/algo/sessions` (existing) + per-session `positionDetails` (added in seq #1 archive).
**Compute:** all aggregation in `engine/` per the engine-owns-math rule.

| Card / panel | Data source | Engine surface |
|--------------|-------------|----------------|
| Aggregate Margin & Leverage gauge | sum of `positionDetails[*].margin` / sum of `notional` / wallet balance from Binance Testnet | NEW endpoint `GET /risk/portfolio/aggregate` |
| Net Exposure bar (Long vs Short notional) | sum notional by `side` across all live sessions | same endpoint, `exposure: { long, short }` |
| VaR 95% / 99% (1-day) | per-symbol historical volatility × notional, parametric Gaussian | NEW engine service `engine/services/risk_math.py` |
| Rolling correlation matrix (30d, 1h candles) | TimescaleDB `candles` close returns, Pearson correlation | NEW endpoint `GET /risk/portfolio/correlation` |
| Drawdown circuit-breaker status | per-session `session_drawdown` vs `risk_params.max_session_dd` | NEW endpoint `GET /risk/portfolio/breakers` |

### Zone 2 — Hierarchical Parameter Controls
**Wired:** `GET /api/v1/settings/exchange` (existing) + per-strategy overrides stored in MongoDB `riskOverrides` collection.

**Schema (new):**
```
MongoDB: riskOverrides collection
{
  scope: 'global' | 'strategy' | 'symbol',
  scopeKey: null | '<strategyName>' | '<exchange>:<symbol>',
  params: { trail_atr_mult, breakeven_r, atr_percentile_min,
            min_edge_mult, max_portfolio_risk, max_leverage_clamp,
            hard_max_leverage, hard_max_session_dd },
  updatedAt, updatedBy: 'system'
}
```

`engine/core/models/risk.py → AtrBracketRiskModel.__init__` will be extended to accept overrides loaded from this collection (alongside the existing `risk_params` injection). **This is the part that re-baselines golden master** — defaults remain identical, but the construction path now reads from a new collection.

**Resolution order:** run-specific (wizard) → symbol override → strategy override → global defaults → hard limits (circuit breakers).

### Zone 3 — Backtest & Historical Risk Profiler
Pure read aggregation over `backtestResults` + `backtestTrades` (already populated by engine).

| Panel | Source | Notes |
|-------|--------|-------|
| Leverage Sensitivity | sweep leverage × existing trade simulation: requires re-running sims | **Option A:** precompute at backtest completion (cached on doc). **Option B:** on-demand via `POST /risk/sensitivity` with engine re-sim. Option B is more correct but expensive; recommend A + on-demand fallback for the active run. |
| Sharpe / Calmar / Sortino distribution | already on `backtestResults.metrics` | Just a chart of the leaderboard from Dashboard. |
| Monte Carlo Ruin Curve | resample trade P&L sequence, simulate N paths, plot equity percentile bands | NEW endpoint `GET /risk/monte-carlo/:jobId?runs=1000&horizon_days=90`. Reads existing `backtestTrades`. |

---

## 3. File-by-File Plan (proposed)

### Engine (new files)
- `engine/services/risk_math.py` — VaR (parametric + historical), CVaR, Pearson correlation, Monte Carlo bootstrap
- `engine/routers/risk_dashboard.py` — 5 new endpoints (see §2)
- `engine/core/models/risk.py` — extend `AtrBracketRiskModel.__init__` to accept overrides map (defaults = no change → golden-master safe)
- `engine/scripts/golden_master.py` — add a "risk_dashboard_baseline" label after re-baseline

### Server (new files)
- `server/src/models/RiskOverride.js` — Mongoose schema for the overrides collection (server caches + serves; engine is sole writer... **decision point**, see §6)
- `server/src/controllers/risk_dashboard.controller.js` — proxies all 5 endpoints
- `server/src/routes/risk_dashboard.routes.js` — mount `/api/v1/risk/*`
- `server/src/services/overrideResolver.js` — load + merge the cascade (or do this in engine — see §6)

### Client (new files)
- `client/src/pages/RiskDashboard.jsx` — main page, 3 zones, mounting
- `client/src/features/risk/{AggregateGauge,ExposureBar,CorrelationHeatmap,BreakerStatus,ParameterControls,LeverageSensitivity,MonteCarloCurve}.jsx` — 7 components
- `client/src/hooks/useRiskDashboard.js` — 5 query hooks
- `client/src/components/layout/Navbar.jsx` — add `<ShieldAlert /> Risk Dashboard` between Strategies and Backtest
- `client/src/App.jsx` — `<Route path="/risk-dashboard" element={<RiskDashboard />} />`

### Test / docs
- `engine/tests/test_risk_math.py` — unit tests for VaR/CVaR/MC against known analytical cases
- `engine/tests/test_boundaries.py` — extend to assert risk primitives aren't called from `forecast()`
- `workspace/docs/core/API_CONTRACTS.md` — full Risk Dashboard section
- `workspace/docs/core/DECISIONS.md` — append entry for hierarchical override resolution
- `workspace/plan/plans/risk_dashboard_seq4.md` (this doc) → archive on completion

**Total: ~22 new files, ~4 modified. Effort: L (2–3 weeks).** Risk class: Med–High (re-baselines golden master, introduces new writes, exposes override UI).

---

## 4. Phase Plan (gated)

### Phase R0 — Decide ownership of `riskOverrides`
`[Certain]` This blocks all later phases. The two options:

- **A. Server owns, engine reads.** `RiskOverride.js` model in server, settings UI mutates it, engine reads via HTTP at session-startup (one round-trip per session). Pro: matches existing pattern (`Settings` is server-owned, engine reads on demand). Con: engine needs an HTTP client to fetch overrides; adds a startup dep.
- **B. Engine owns directly.** Engine connects to MongoDB and reads `riskOverrides` itself at session-start. Pro: no HTTP round-trip, faster. Con: violates "server is the routing/queue/auth layer" norm from `server/CLAUDE.md` — engine starts looking like a service that also manages config.

**Recommendation: A.** Default it; if user wants B, plan changes are minimal (drop `RiskOverride.js`, move schema to engine `config/mongo.py`).

### Phase R1 — `risk_math.py` + unit tests (pure compute, no I/O)
Write `VaR`, `CVaR`, `correlation_matrix`, `monte_carlo_resample`. All take numpy/pandas inputs and return numpy/pandas. **No DB, no FastAPI.** Tests: known-analytical cases (constant returns → VaR = 0; perfectly correlated → MC std dev = 0; bootstrap preserves mean ± O(1/√N)).

**Gate:** `pytest tests/test_risk_math.py -q` passes.

### Phase R2 — Engine read-only endpoints
Add `GET /risk/portfolio/{aggregate,correlation,breakers}` and `GET /risk/monte-carlo/:jobId`. They call `risk_math.py` against existing collections. **No schema change.**

**Gate:** All 4 endpoints return 200 in Docker smoke test.

### Phase R3 — Re-baseline golden master
Per Rule C. Build out the override-injection code path in `AtrBracketRiskModel` and `live_bot_manager`. Defaults still produce identical sims.

**Gate:** `python -m scripts.golden_master run --label risk_dashboard_baseline` then `compare --a ws2_final --b risk_dashboard_baseline` = OK (all 5 strategies, tol 1e-6).

### Phase R4 — `riskOverrides` collection + server model + settings UI
Add the schema (option A from R0), Settings page gets a "Risk Overrides" section with the 3 scope tabs (Global / Strategy / Symbol).

**Gate:** End-to-end create/edit/delete works; UI reflects changes immediately (TanStack Query invalidation).

### Phase R5 — Engine applies overrides at session start
`live_bot_manager._run_symbol_loop` reads overrides via the agreed mechanism (HTTP or direct Mongo per R0), merges them into the per-symbol strategy instance's risk params. Defaults unchanged.

**Gate:** Boundary test still 20/20. A live testnet session with an override of `trail_atr_mult=2.5` produces visibly different trailing-stop behavior than a session without.

### Phase R6 — Client page (3 zones)
Build all 7 feature components + the 5 query hooks. Wire Navbar + route.

**Gate:** `npm run build` clean. Visual: all 3 zones render with realistic data; empty states work; correlation heatmap is interactive (hover shows symbol pair + r).

### Phase R7 — Docs & archive
Update `CURRENT_STATE.md`, `API_CONTRACTS.md`, `DECISIONS.md`. Archive the vision doc `RISK_DASHBOARD_PLAN.MD` and this plan. Append handoff.

**Gate:** Grep for old plan paths returns zero hits in active `workspace/plan/`.

---

## 5. Issues I Can Already Foresee

### Issue 4-A — Monte Carlo on a single completed run is misleading
A single backtest is one sample path. MC resamples the **trade sequence**, so the resulting distribution tells you "given this trade ordering, how would alternative orderings perform?" — not "what's the strategy's true performance distribution?" The user will want the latter. Two answers:
- **Document the caveat** in the UI: "Resampled trade-ordering distribution, not strategy generalization."
- **Optional add-on:** bootstrap with replacement on the trade P&L (not sequence) — different math, different answer. Phase R1 implements both; Phase R6 surfaces a toggle.

### Issue 4-B — Correlation across 80 Chaos Mode symbols is unreadable
80×80 heatmap = 6,400 cells. The original plan caps at "actively traded symbols" — but a 20-symbol Chaos session is still 400 cells. **Recommend:** client-side filtering, "show top-N by recent volume" selector (default 12). Engine returns all; client filters.

### Issue 4-C — Override resolution is a foot-gun
A new user could set `hard_max_leverage: 2x` globally and break every existing strategy that expects ≥5x. Mitigation: **the override UI must show a diff preview** before save ("This will reduce leverage on 3 live sessions from 5x to 2x"). Phase R4 acceptance criterion.

### Issue 4-D — Golden-master re-baseline creates drift risk
Per Rule C, every engine change between baselines invalidates comparison. While seq #4 is in flight, **no other engine changes allowed** (or, if any, capture as separate baselines: `risk_dashboard_r1`, `risk_dashboard_r2`). The workstream's `handoff.md` entry must state this constraint.

### Issue 4-E — Testnet-only VaR is misleading
VaR computed on Testnet order flow is not representative of mainnet volatility. Document in the UI header: "Computed from Binance Testnet data; mainnet distribution may differ." Same disclaimer pattern as existing "all orders target Testnet" footer.

### Issue 4-F — 7 new client components, each must handle loading/error/empty
Per `client/CLAUDE.md`: "All components must handle loading and error states." Forgetting on even one component (most likely `CorrelationHeatmap`) will surface as a broken state when the engine is down. Add a Playwright smoke test or manual checklist.

---

## 6. Open Questions (Blockers)

These need user answers before implementation:

1. **R0 ownership:** A (server model) or B (engine direct)? Default A.
2. **Leverage sensitivity implementation:** A (cache at backtest completion) or B (on-demand re-sim)? Recommend A for history, B for "what if" on the active run.
3. **MC resampling:** sequence resample or P&L bootstrap or both with a toggle? Recommend both.
4. **Hard limits as live kill-switches?** If user sets `hard_max_session_dd: 5%` and a live session exceeds it, should the platform auto-stop the session, or just visually flag? Auto-stop is the safer default but adds a write path + Socket.IO event + worker cleanup. **Strong recommendation: flag-only for v1**, auto-stop for v2.

---

## 7. Integration with the Platform

### Layer boundary enforcement
- All new math in `engine/services/risk_math.py` — no client math.
- All aggregation over MongoDB stays in `engine/routers/risk_dashboard.py`.
- Server is pure proxy + the override model (per R0 choice).
- Client is read-mostly: pages render, parameter edits trigger `useMutation` → `PUT /api/v1/risk/overrides` → engine next session reads the new value.

### What this enables downstream
- Track D of `future_paths.md` items (Risk Dashboard + Monte Carlo + "Hedge Fund in a Spreadsheet") collapse into this one workstream.
- The "Personal Quant Research Framework" idea (Track D) becomes much more concrete once parameter overrides are first-class.
- Track A Monte Carlo is no longer separate — it ships as part of Zone 3.

### What this blocks
- Any further refactor of `AtrBracketRiskModel` must wait for R3 (re-baseline) to land.
- Any new strategy that wants to consume portfolio-level signals must wait for the override-aware pipeline.

### Coupling with existing work
- seq #3 Dashboard KPI: shares `useDashboardStats` patterns. Different page; no shared state.
- seq #1 archive (`LiveSession.positionDetails`): Zone 1 reads from this directly. Already shipped.
- seq #2 archive (`risk.py` workstream): Zone 2 surfaces the new params. Already shipped.
- Backtest Overview tab's 14-metric grid: Zone 3 panels are richer versions of metrics already shown there. Visual consistency is required (use the same `BacktestMetricCard` component, not a new one).

---

## 8. Done = When

- R0 decision made and recorded in this doc.
- All 7 phases gated and passing.
- Golden master re-baselined to `risk_dashboard_baseline` and committed.
- `boundary tests` still 20/20.
- New endpoints in `API_CONTRACTS.md`.
- New DECISIONS entry for override resolution.
- Visual: `/risk-dashboard` renders all 3 zones with realistic data, empty states work, override UI shows diff preview.
- `RISK_DASHBOARD_PLAN.MD` + this plan archived.
- Handoff prompt appended to `handoff.md` pointing at the next item (likely: a mainnet trading plan, per `future_paths.md` cross-reference, or Track B GARCH vol forecasting per the future-paths shortlist).