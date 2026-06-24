# Risk Dashboard — Open Decisions & Gap-Fill

**Date:** 2026-06-24
**Status:** Proposal — fill the open gaps in `RISK_DASHBOARD_PLAN.MD` before any code is written.
**Authority:** This doc does not override the plan; it resolves the questions the plan leaves unanswered and corrects the items that conflict with current state. Where this doc and the plan disagree, **this doc wins** (last-write-wins, per `.claude/GOVERNANCE.md`).

---

## 0. Dependency check — seq #2 is shipped (verified 2026-06-24)

`workspace/plan/INDEX.md` line 23 marks seq #2 (Risk Model Improvements) as **DONE**. I verified this in the engine:

- `trail_atr_mult`, `breakeven_r`, `atr_percentile_min` all in `engine/core/models/risk.py:116-182` ✅
- `min_edge_mult` default = 0.05 in `backtest_runner.py:310` and `live_bot_manager.py:242` ✅
- `max_portfolio_risk` default = 0.06 in `engine/core/models/portfolio.py:66` ✅

> **`workspace/plan/STATUS.md` line 39 is stale** — it still says #2 is "Proposed — next up". `INDEX.md` is authoritative. Note this drift for the next `/sync-spec` pass.

**Implication:** `custom_atr_mult` and `volatility_multiplier` (the two new fields the plan §6 introduces) are not yet on `strategy`. They are *new* for this work, not part of seq #2. We must add them to the engine risk-injection path ourselves (one-line addition each in `backtest_runner.py:305-310` and `live_bot_manager.py:237-242`).

**Golden master gate:** Adding `min_edge_mult=0.05` (seq #2) already changed defaults. Re-run `golden_master.py` before AND after the §6 engine edits — they should remain byte-equivalent because the new fields default to neutral (`custom_atr_mult=None`, `volatility_multiplier=1.0`). If they break, debug before proceeding (Rule C).

---

## 1. Live metrics data path (Zone 1, "Real-Time Portfolio Risk")

**Gap:** The plan defines the response shape for `/api/v1/risk/live-metrics` but never specifies how the server obtains the data. Three constraints collide:

1. `AGENTS.md` §"Non-Negotiable Constraints": *"Only `engine/` calls Binance. Never from `server/` or `client/`."*
2. Existing `engine/routers/trade.py` already exposes `/trade/account`, `/trade/positions`, `/trade/klines`.
3. We need **720 hours of 1h closes** per active symbol for VaR + correlation — that's ~30 days × N symbols of OHLCV.

**Decision:** **Proxy everything through the engine.** Add a new engine endpoint `GET /risk/live-metrics` that returns the full payload, server-side cached 10s in Redis.

| Step | Component | Behavior |
|------|-----------|----------|
| 1 | `engine/routers/risk.py` (new) | `GET /risk/live-metrics` — calls `binance_testnet` for account + positions, calls TimescaleDB for 720h 1h candles via `candle_manager.ensure_candles_available()` (idempotent — fills gaps if any) |
| 2 | `engine/utils/risk_math.py` (new) | `calculate_portfolio_var`, `calculate_correlation_matrix` over the fetched candles |
| 3 | `engine/main.py` | Mount router at `/risk/*` |
| 4 | `server/src/controllers/risk.controller.js` (new) | Forwards to `engine:8000/risk/live-metrics`, caches result in Redis under key `risk:live-metrics:{hash(activeSymbols, exposures)}` with `EXPIRE 10` |
| 5 | `server/src/routes/risk.routes.js` (new) | `GET /api/v1/risk/live-metrics` |
| 6 | `client/src/hooks/useRiskLiveMetrics.js` (new) | TanStack Query hook, `staleTime: 10s, refetchInterval: 10s` |

**Why engine-side aggregation, not server-side:** the engine already owns Binance + TimescaleDB credentials. Pulling candles into the server would require giving it TimescaleDB credentials (forbidden per `AGENTS.md` §"TimescaleDB isolation").

**Cache key:** hash of `(sorted(activeSymbols), walletBalance-bucket)` — bucket the wallet balance to the nearest $10 so the cache survives minor tick changes. Otherwise the cache invalidates on every account-info call.

---

## 2. Leverage sensitivity (Zone 3)

**Decision (confirmed with user):** Re-run the engine 5× at leverage = 1, 2, 5, 10, 20.

| Item | Decision |
|------|----------|
| Where it runs | Engine, behind a new endpoint `POST /backtest/run/leverage-sensitivity` |
| Input | `jobId` of the completed backtest + array of leverage overrides (default `[1, 2, 5, 10, 20]`) |
| Execution | **Reuses the persisted candles.** For each leverage, re-instantiate the strategy with the original params + the new leverage, replay the same candle sequence, write to a new collection `backtestLeverageScenarios` |
| Storage | New MongoDB collection `backtestLeverageScenarios` keyed by `{sourceJobId, leverage}` |
| Compute budget | ~5× the original backtest time. Default 5 leverage levels = 5× — cap at 7 levels to keep UI responsive. User can opt to fewer |
| Caching | Once scenarios for a given `sourceJobId` exist, return cached result; do not re-run unless `forceRefresh=true` |
| UI | `GET /api/v1/risk/backtest/:id/simulation` returns `{leverageSensitivity: [...], monteCarlo: {...}}` |

**New files:** `engine/routers/leverage_sensitivity.py`, `engine/services/leverage_sensitivity_runner.py`, `engine/models/backtestLeverageScenario.py` (engine side — server reads via Mongoose mirror).

**Golden-master impact:** Zero. We're adding a new computation pipeline, not touching the existing `backtest_runner.py`. Existing golden snapshots remain valid.

---

## 3. Monte Carlo (Zone 3)

**Decision (confirmed with user):** **Trade-level bootstrap** for v1.

| Item | Decision |
|------|----------|
| Source | `backtestTrades` rows for the given `sourceJobId` |
| Method | Resample trade P&L % with replacement, rebuild synthetic equity curve (cumulative product of `(1 + sampled_pnl)`), repeat N=2000 times |
| Output | `ruinProbability` (fraction of paths that hit `maxSessionDrawdown`), `drawdownDistribution` (percentiles 10/25/50/75/90/95 of max-drawdown across paths), `recoveryTimeDistribution` (median + 90th percentile candles-to-recover) |
| Edge case | If `backtestTrades` is empty → return `ruinProbability: null, drawdownDistribution: []` with HTTP 200 |
| Compute budget | ~5–10s per 1000 trades × 2000 paths |
| Determinism | Seed with `sourceJobId`-derived integer so re-runs are byte-identical. Test in `engine/tests/test_monte_carlo.py` |

**Known limitation (acceptable for v1):** Trade-level bootstrap destroys path-dependence — a synthetic run cannot represent margin calls or cascading stops within a session. If the user later wants path-accurate ruin estimation, upgrade to block bootstrap on daily-aggregated returns. **Document this in the engine docstring.**

---

## 4. Resolver key bug (plan §3)

**Bug confirmed.** The plan's resolver (line 144-156) reads from `savedSettings[camelField]` using keys that may not match what the Mongoose schema returns.

**Fix:**

```javascript
// server/src/utils/risk.js — add to existing module, do not replace resolveModelParams
function resolveStrategyRiskParams(strategyName, symbol, savedSettings = {}, wizardOverride = {}) {
  // Mongoose Maps come back as plain objects after .lean() — use bracket access
  const strategyRules = (savedSettings.strategyOverrides || {})[strategyName] || {};
  const symbolRules   = (savedSettings.symbolOverrides   || {})[symbol]       || {};
  const hardLimits    = savedSettings.globalHardLimits   || {};
  
  // Normalise override keys: client may send camelCase OR snake_case
  const normOvr = normaliseKeys(wizardOverride);
  
  const out = {};
  for (const [camelField, rule] of Object.entries(RISK_FIELDS)) {
    let val = normOvr[camelField];
    if (val == null || !isFinite(Number(val))) val = strategyRules[camelField];
    if (val == null || !isFinite(Number(val))) val = symbolRules[camelField];
    if (val == null || !isFinite(Number(val))) val = savedSettings[camelField];
    if (val == null || !isFinite(Number(val))) val = rule.fallback;
    val = Number(val);
    
    // Clamp by Global Hard Limits (only after all sources are checked)
    if (camelField === 'riskPct' && isFinite(hardLimits.maxRiskPctPerTrade)) {
      val = Math.min(val, hardLimits.maxRiskPctPerTrade);
    }
    if (camelField === 'maxSessionDrawdown' && isFinite(hardLimits.maxSessionDrawdown)) {
      val = Math.min(val, hardLimits.maxSessionDrawdown);
    }
    
    out[rule.engineKey] = clamp(val, rule.min, rule.max);
  }
  
  // Leverage: independent resolution path (no RISK_FIELDS entry)
  let lev = Number(normOvr.leverage);
  if (!isFinite(lev)) lev = Number(symbolRules.maxLeverage);
  if (!isFinite(lev)) lev = Number(savedSettings.defaultLeverage);
  if (!isFinite(lev)) lev = 1;
  if (isFinite(hardLimits.maxLeverageAllowed)) lev = Math.min(lev, hardLimits.maxLeverageAllowed);
  out.leverage = clamp(lev, 1, 125);
  
  // Custom settings passed through to engine
  out.volatility_multiplier = Number(symbolRules.volatilityMultiplier ?? 1.0);
  out.max_exposure_notional = Number(symbolRules.maxExposureNotional ?? Infinity);
  out.custom_atr_mult       = strategyRules.customAtrMult != null ? Number(strategyRules.customAtrMult) : null;
  
  return out;
}

function normaliseKeys(obj = {}) {
  // Convert snake_case → camelCase for matching against RISK_FIELDS keys
  const out = {};
  for (const [k, v] of Object.entries(obj)) {
    const camel = k.replace(/_([a-z])/g, (_, c) => c.toUpperCase());
    out[camel] = v;
    out[k] = v; // also keep original in case the loop later wants it
  }
  return out;
}
```

**Coexistence with `resolveModelParams`:** Keep the existing function. `resolveStrategyRiskParams` calls into it for the Tier 2 fields, then layers on the strategy/symbol/hard-limit cascade. Both functions live in `server/src/utils/risk.js`.

**Backwards compatibility:** `resolveModelParams` keeps its current signature. The plan's "Risk Model Improvements" (seq #2) work-in-flight already uses it; don't break that.

---

## 5. Schema additions (plan §4) — corrections

The plan's schema is structurally fine, with these corrections:

1. **`strategyOverrides` and `symbolOverrides` as `Map` types** — confirmed correct. Mongoose Maps require `Map` accessor on read when using `lean()` (returns plain object), so the resolver in §4 above handles both.

2. **Add `updatedAt` audit fields** — already enabled via `{ timestamps: true }` on `settingsSchema` (line 53 of `Settings.js`). No change needed, but the dashboard UI should display `updatedAt` per override.

3. **Add a periodic prune job** (per my §3 challenge in the chat):
   - **Trigger:** daily at 02:00 UTC via existing BullMQ scheduler (no new infrastructure).
   - **Logic:** remove entries in `strategyOverrides` whose `strategyName` is not in the current seeded strategy list AND has zero usages in `liveSessions` or `backtestResults` for the past 90 days.
   - **Same for `symbolOverrides`** keyed against symbols that have no usage in 90 days.
   - **Logged:** every prune operation is logged to `workspace/logs/risk-prune.log` (no new collection).

4. **Validation on save:** reject `PUT /api/v1/risk/settings` payloads whose `strategyOverrides[].strategyName` doesn't exist in the `strategies` collection — fail fast with 400.

---

## 6. Phase plan (concrete, executable)

After seq #2 (Risk Model Improvements) ships, the Risk Dashboard lands in 5 phases. **Each phase is independently shippable** and each refactor-touches-pipeline phase (1, 4, 5) gates on `golden_master.py`.

| Phase | Deliverable | New files | Edits | Gate |
|-------|-------------|-----------|-------|------|
| **R1. Schema + Resolver** | Mongoose schema additions, `resolveStrategyRiskParams`, `PUT /api/v1/risk/settings` | `engine/.../none` | `server/src/models/Settings.js`, `server/src/utils/risk.js`, `server/src/controllers/settings.controller.js`, `server/src/routes/settings.routes.js` | Unit tests for resolver (precedence + clamping) |
| **R2. Engine risk math** | `engine/utils/risk_math.py` with `calculate_portfolio_var` + `calculate_correlation_matrix` | `engine/utils/risk_math.py`, `engine/routers/risk.py`, `engine/tests/test_risk_math.py` | `engine/main.py` | `docker exec ... pytest tests/test_risk_math.py` |
| **R3. Live metrics endpoint** | `GET /risk/live-metrics` engine + server passthrough + 10s Redis cache | `server/src/controllers/risk.controller.js`, `server/src/routes/risk.routes.js`, `client/src/hooks/useRiskLiveMetrics.js` | none | Manual: open Trade page, place orders, watch VaR + correlation update |
| **R4. Leverage sensitivity + Monte Carlo** | Re-run engine 5×, trade-level bootstrap, new Mongo collection | `engine/routers/leverage_sensitivity.py`, `engine/services/leverage_sensitivity_runner.py`, `engine/services/monte_carlo.py`, `engine/tests/test_monte_carlo.py`, `server/src/models/BacktestLeverageScenario.js` | `server/src/controllers/risk.controller.js` (extends), `server/src/routes/risk.routes.js` | Golden master comparison: scenario outputs byte-equal across re-runs (determinism seed) |
| **R5. Frontend** | `/risk-dashboard` route, three zones wired, navbar item | `client/src/pages/RiskDashboard.jsx`, `client/src/components/risk/*` (heatmap, VaR panel, param form, scenarios), `client/src/hooks/*` | `client/src/components/layout/Navbar.jsx`, `client/src/App.jsx` | Manual + golden visual check |

**R1 is purely server-side, R2 purely engine-side — they can run in parallel.** R3 depends on R2. R4 is independent of R3. R5 depends on R1, R3, R4.

**Estimated total:** R1 + R2 in ~1 session; R3 in ~0.5 session; R4 in ~1 session (Monte Carlo determinism is fiddly); R5 in ~1.5 sessions (3 zones × UI work + heatmap styling). Total ~4 sessions.

---

## 7. Open questions deferred to implementation

- **What happens if `strategyOverrides` references a strategy the seeder hasn't seeded yet?** — Plan: lazy-resolve at apply time, silently fall back to global default with a `console.warn`. Won't surface in UI until next save.
- **Live-metrics cache invalidation on position change** — server-side cache means positions that change within the 10s window are stale. Acceptable for v1; revisit if UX feedback demands otherwise.
- **Monte Carlo determinism for clients calling from multiple sessions** — seed with `sourceJobId` only, not per-client. Same jobId → same result. Confirmed acceptable.

---

## 10. Doc drift surfaced (flag for next `/sync-spec`)

`workspace/plan/STATUS.md` line 39 still describes seq #2 (Risk Model Improvements) as "Proposed — next up". The engine code (`risk.py`, `portfolio.py`, `backtest_runner.py:310`, `live_bot_manager.py:242`) confirms #2 is shipped. `INDEX.md` line 23 is correct. Either fix STATUS.md or delete it (per `.claude/GOVERNANCE.md` source-of-truth hierarchy).

---

## 8. What this doc does NOT change

- The plan's §3 precedence diagram (cascade order is correct).
- The plan's §6.1 `calculate_portfolio_var` algorithm (correct, edge cases handled).
- The plan's §6.2 `calculate_correlation_matrix` algorithm (correct).
- The plan's §7 Heatmap styling (correct, conforms to UI guide).
- The plan's API endpoint URLs and shapes (correct, conform to `API_CONTRACTS.md`).

## 9. What this doc DOES change

- §0 → seq #2 is shipped (verified by grep, 2026-06-24). Plan §6's `custom_atr_mult`/`volatility_multiplier` are NEW fields to be added in this workstream, gated on golden master.
- §1 → data path is engine-side, not server-side (correction).
- §2 → leverage sensitivity: re-run engine 5×, cached, new collection (decision).
- §3 → Monte Carlo: trade-level bootstrap, N=2000, deterministic seed (decision).
- §3 plan code → key-normalization helper + finite-number guards (bug fix).
- §4 plan schema → add daily prune job + save-time validation (hardening).
- §10 (this doc) → flag `STATUS.md` line 39 as stale (says #2 still proposed; INDEX.md is correct that it's done).