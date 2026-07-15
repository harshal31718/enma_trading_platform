# Plan 11 — Current-State Reconciliation (audit, 2026-06-25)

**Status:** Ready (V0 gate) · **Priority:** P2 · **Phase:** 9 · **Depends on:** — · **Related:** 12-19

**Why this exists:** the old `workspace/plan/INDEX.md` (since deleted — git history) claimed #3/#4/#5 were "remaining." A direct code
audit found them **already implemented**. This file is the corrected record. Every claim below is
backed by a real file path that exists in the repo today.

---

## Verdict

| INDEX seq | Item | Doc claimed | Audited reality | Action |
|-----------|------|-------------|-----------------|--------|
| #3 | Dashboard restructure | "endpoints missing, page does not exist" | **Built & wired** | → V0 verify only |
| #4 | Risk Dashboard | "page does not exist" | **Built & wired** | → V0 verify only |
| #5 | Monte Carlo / MCPT | "research, not implemented" | **Engine built** (UI surface TBD) | → V0 verify + confirm UI |

The dashboards are no longer "to build." They are "to verify and harden." Net-new effort moves
entirely to the freqtrade/nautilus gaps (S1–S8).

---

## Evidence — Seq #3 Dashboard restructure (DONE)

- `engine/routers/dashboard.py` — `GET /stats` already returns the extended fields
  (`avgProfitFactor`, `avgSharpe`, `avgSortino`, `worstDrawdown`, `avgExpectancy`, `latestRunId`)
  **and** `GET /performance-calendar` (day-level pnl aggregation over `backtestTrades`). This is
  exactly what the (now-deleted) dashboard-restructure plan specified — recoverable from git history.
- `server/src/controllers/dashboard.controller.js`, `server/src/routes/dashboard.routes.js` — present.
- Client: `client/src/components/charts/EquitySparkline.jsx`, `.../DrawdownSparkline.jsx`,
  `client/src/features/dashboard/DashboardCalendar.jsx`, and `useDashboardCalendar()` in
  `client/src/hooks/useDashboard.js` — all present.

**What V0 must still check:** that `client/src/pages/Dashboard.jsx` actually renders the 8-card grid
+ sparkline row + calendar (components existing ≠ page composed), and that the engine `/stats`
numbers are non-zero against seeded backtests.

## Evidence — Seq #4 Risk Dashboard (DONE)

- `engine/routers/risk.py` — `GET /live-metrics` (Binance account → margin, net leverage, exposures,
  VaR95/99 + CVaR, correlation matrix).
- `engine/utils/risk_math.py` — `calculate_portfolio_var()`, `calculate_correlation_matrix()`
  (historical-simulation VaR + Pearson correlation) — the math is in code; the deleted Risk Dashboard
  plan §6 (git history) was the spec.
- `server/src/controllers/risk.controller.js`, `server/src/routes/risk.routes.js` — present.
- `server/src/models/Settings.js` — `globalHardLimits`, `strategyOverrides`, `symbolOverrides`
  (the hierarchical schema from §4) — present at lines 54/63/78.
- Client: `client/src/pages/RiskDashboard.jsx`, `client/src/components/risk/*`,
  `client/src/hooks/useRiskSettings.js`; `App.jsx:29` route `/risk-dashboard`;
  `Navbar.jsx:18` nav entry — all present.

**What V0 must still check:** the param resolver (`resolveStrategyRiskParams`) precedence/clamping
actually runs in `backtest.controller.js` + `algo.controller.js` (the resolver-integration step),
and the engine wiring of `volatility_multiplier` / `max_exposure_notional` / `custom_atr_mult` is live
(`live_bot_manager.py`). If those injections are absent, that is the only real remaining #4 work.

## Evidence — Seq #5 Monte Carlo / leverage sensitivity (ENGINE DONE)

- `engine/services/monte_carlo.py` — `run_monte_carlo_simulation(job_id)`: trade-level bootstrap,
  equity-based returns (correctly divides pnl by starting capital, **not** ROE), ruin probability +
  drawdown distribution. Matches the deleted Risk Dashboard plan §7B intent (git history).
- `engine/routers/leverage_sensitivity.py` + `engine/services/leverage_sensitivity_runner.py` —
  re-run scenarios across leverage `[1,2,5,10,20]`.
- **MCPT (permutation tests, `ref_mcpt-research.md`) is NOT the same as the bootstrap Monte Carlo
  above** and is still unbuilt. It remains research; not pulled into S1–S8. Promote later if wanted.

**What V0 must still check:** whether Monte Carlo / leverage sensitivity have a **client surface**
(a Risk Dashboard Zone-3 tab or a Backtest report tab). The engine math exists; the UI may not.

---

## V0 — Verification checklist (do this before S1)

Run inside the engine container (`docker compose exec engine ...`) and the client/server as noted.

1. **Golden master baseline still green** (everything below builds on this):
   ```
   docker compose exec engine python -m scripts.golden_master run --label v0_baseline
   docker compose exec engine python -m scripts.golden_master compare --a baseline --b v0_baseline
   docker compose exec engine python -m pytest tests/test_boundaries.py -q
   ```
2. **Dashboard** — hit `GET /api/v1/dashboard/stats` and `/performance-calendar`; confirm non-zero
   fields after a seeded backtest; load `/` in the UI and confirm 8 cards + sparklines + calendar render.
3. **Risk Dashboard** — load `/risk-dashboard`; confirm Settings overrides round-trip
   (`GET`/`PUT /api/v1/risk/settings`); confirm `live-metrics` returns (or degrades cleanly with no
   active session).
4. **Monte Carlo / leverage** — call the engine endpoints for a completed `jobId`; confirm a ruin
   probability + distribution come back. Note whether a UI surface exists.
5. **Record findings** in `workspace/plan/handoff.md`. Any gap found here (e.g. resolver not wired,
   no MC UI) becomes a small punch-list item — **not** a reason to rebuild the trio.

> If V0 surfaces that a piece is genuinely missing (not just unpolished), add a short `S0-*.md`
> punch-list spec rather than reopening the original plan docs.
