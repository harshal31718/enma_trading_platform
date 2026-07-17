# Feature: Risk Intelligence Dashboard

**Status:** Implemented
**Last updated:** 2026-07-02 — new SPEC, written from `CURRENT_STATE.md` + `API_CONTRACTS.md` +
`server/CLAUDE.md`; this feature previously had no dedicated SPEC despite clearing the
`.claude/GOVERNANCE.md` Feature Documentation Threshold (multi-step cross-service data flow,
non-obvious cascading-override invariant, 3 zones each with 5+ config parameters).

---

## What It Does

A centralized risk page (`/risk-dashboard`, in the header bar between Strategies and Backtest) with
three zones: live real-time portfolio risk visualization, hierarchical risk-limit configuration, and
historical leverage/Monte Carlo simulation. Config set here is enforced across manual trading, bot
sessions, Chaos Mode runs, and backtests via a cascading override resolver — this is the single
source of truth for risk limits, not just a dashboard.

---

## Data Flow

```
Client navigates to /risk-dashboard
        ↓
Zone 1 (Real-Time Portfolio Risk):
GET /api/v1/risk/live-metrics  (requires Binance headers via requireBinanceCredentials)
        ↓
Server checks Redis cache (risk:live-metrics:{userId}, 10s TTL)
        ↓ (miss)
Server proxies → engine GET /risk/live-metrics
        ↓
Engine computes: locked initial margin, free wallet balance, net portfolio leverage,
net Long/Short stacked notional exposure, live 1-day VaR/CVaR (95%/99%), 30-day Pearson
correlation heatmap over rolling close returns
        ↓
Server caches result 10s in Redis, returns to client
        ↓
AggregateMarginGauge / NetExposureBar / CorrelationHeatmap render

Zone 2 (Hierarchical Settings Overrides):
GET /api/v1/risk/settings
        ↓
Server reads per-user Settings doc (upserted on first access) — no engine proxy
        ↓
Returns: { globalHardLimits, strategyOverrides: {[strategyName]: ...}, symbolOverrides: {[symbol]: ...} }
        ↓
User edits and saves → PUT /api/v1/risk/settings
        ↓
Server validates ranges per field (400 VALIDATION_ERROR with field detail on violation);
strategyOverrides keys must match an existing Strategy.name; overrides keyed by name/symbol
are replaced wholesale, not merged
        ↓
Cascading resolver (used by live bot start, Chaos Mode, backtest launch — NOT this dashboard
itself) applies: symbolOverride > strategyOverride > globalHardLimits > hardcoded default

Zone 3 (Historical Simulations):
GET /api/v1/risk/backtest/:id/simulation
        ↓
Server: 404 if backtest not found, 400 if status != "completed"
        ↓
Server proxies → engine POST /backtest/run/leverage-sensitivity
        ↓
Engine re-runs the backtest under leverage scenarios [1, 2, 5, 10, 20] using cached candles,
then Monte Carlo bootstrap-resamples the trade sequence (N=2000 paths) for ruin-probability
and drawdown-exceedance curves
        ↓
Results persisted to MongoDB backtestLeverageScenarios (engine-owned, server reads only)
        ↓
SimulationResults renders leverage-scenario table + Monte Carlo curves
```

---

## Service Responsibilities

| Layer | Owns | Does NOT own |
|-------|------|-------------|
| Client | Zone 1/2/3 rendering, settings form, gauge/heatmap/chart visualizations | Any risk computation |
| Node server | Risk Settings MongoDB doc (Zone 2), 10s Redis cache for live-metrics (Zone 1), route proxy + validation | VaR/CVaR math, Monte Carlo, leverage-scenario simulation |
| Python engine | All Zone 1 risk math (VaR/CVaR, correlation), all Zone 3 simulation (leverage scenarios, Monte Carlo), writes `backtestLeverageScenarios` | Storing user-editable settings |

---

## Key Invariants

- **Cascading resolver, not just a dashboard.** `globalHardLimits` → `strategyOverrides[name]` →
  `symbolOverrides[symbol]` is evaluated by live bot session start, Chaos Mode launch, and backtest
  launch — not only read here. Changing Zone 2 settings changes trading behavior elsewhere.
- **Zone 2 writes replace wholesale, not merge.** A `PUT` with a new `strategyOverrides.MicroScalper`
  object replaces that strategy's entire override object — it does not deep-merge with the existing one.
- **`strategyOverrides` keys must reference a real strategy.** Server-side validation rejects a key
  that doesn't match an existing `Strategy.name`.
- **Zone 1 is cached, not live-polled aggressively.** `GET /risk/live-metrics` is Redis-cached 10s
  server-side per user to protect Binance Testnet rate limits — repeated client refreshes within the
  window return the cached value, not a fresh engine call.
- **Zone 3 only operates on completed backtests.** `GET /risk/backtest/:id/simulation` 400s if the
  target backtest isn't `status: "completed"`; it reuses that run's cached candles, it does not
  re-fetch.
- **`backtestLeverageScenarios` is engine-owned.** Same ownership pattern as `backtestResults`/
  `backtestTrades` — server has a read-only Mongoose model (`BacktestLeverageScenario.js`), engine is
  the sole writer (`engine/services/leverage_sensitivity_runner.py`).
- **Per-user, not per-session.** Risk Settings (Zone 2) live on the per-user `Settings` doc, same as
  Exchange Settings — not scoped per bot session or per backtest run.

---

## REST Endpoints

| Method | Path | Description |
|--------|------|--------------|
| GET | `/api/v1/risk/settings` | Global hard limits + strategy/symbol overrides (per-user, upserted on first access) |
| PUT | `/api/v1/risk/settings` | Update overrides (partial; keyed overrides replaced wholesale) |
| GET | `/api/v1/risk/live-metrics` | Zone 1 real-time portfolio risk (requires Binance headers, 10s server cache) |
| GET | `/api/v1/risk/backtest/:id/simulation` | Zone 3 leverage-scenario + Monte Carlo simulation for a completed backtest |

---

## Related Files

| File | Role |
|------|------|
| `client/src/pages/RiskDashboard.jsx` | Route `/risk-dashboard` — Zone 1/2/3 layout |
| `client/src/components/risk/AggregateMarginGauge.jsx` | Zone 1: locked margin / free balance / leverage gauge |
| `client/src/components/risk/CorrelationHeatmap.jsx` | Zone 1: rolling 30-day close-return correlation heatmap |
| `client/src/components/risk/NetExposureBar.jsx` | Zone 1: stacked long/short notional exposure bar |
| `client/src/components/risk/SimulationResults.jsx` | Zone 3: Monte Carlo / leverage-scenario results |
| `client/src/hooks/useRiskSettings.js` | TanStack Query hooks: settings, live metrics, simulation, overrides |
| `server/src/routes/risk.routes.js` | Route definitions |
| `server/src/controllers/risk.controller.js` | Settings CRUD, live-metrics proxy + Redis cache, simulation proxy |
| `server/src/models/Settings.js` | `globalHardLimits`, `strategyOverrides`, `symbolOverrides` fields |
| `server/src/models/BacktestLeverageScenario.js` | Read-only model for engine-written Zone 3 results |
| `engine/routers/risk.py` | `GET /risk/live-metrics` — VaR/CVaR + correlation computation |
| `engine/routers/leverage_sensitivity.py` | `POST /backtest/run/leverage-sensitivity` — Zone 3 simulation trigger |
| `engine/services/monte_carlo.py` | Monte Carlo bootstrap resampling (N=2000 paths) |
| `engine/services/leverage_sensitivity_runner.py` | Runs leverage-scenario sweeps, writes `BacktestLeverageScenario` docs |
