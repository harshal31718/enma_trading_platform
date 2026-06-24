# Plans

This directory consolidates forward-looking plans, problem analyses, and execution checklists. It replaces `workspace/issues_and_solutions/` (merged 2026-06-24).

Completed/verified plans have been moved out of the active list to `archive/` (2026-06-24). See [archive/](archive/) for historical record (modular merger, chaos mode, documentation-drift audit + doc fixes).

---

## Done (2026-06-24) — archived

| Item | Plan doc (now in `archive/`) | What shipped |
|------|------------------------------|--------------|
| ✅ Live PnL `—` on reload | `archive/live_pnl_fix_plan.md` | `LiveSession.positionDetails` persisted on open / cleared on close; `SessionCard` seeds from session doc. See `CURRENT_STATE.md` → Algo Trading |
| ✅ Backtest UI layout refactor | `archive/backtest_ui_refactor.md` | 2×7 (14-metric) Overview grid, Max Drawdown actual `/` allowed, Export JSON relocated to tab header (matched to "Run Backtest"), Simulation Config + Export Results blocks removed |

## Proposed Execution Sequence (remaining)

Verified against code on 2026-06-24: `min_edge_mult` still defaults to 0.0, `max_portfolio_risk` absent, dashboard KPI endpoints missing, Risk Dashboard page does not exist.

| Seq | Item | Plan doc | Scope | Effort | Risk | Gate |
|-----|------|----------|-------|--------|------|------|
| ~~**1**~~ ✅ DONE 2026-06-24 | Strategy performance refactor — **workstream** (Phases 1–8 complete, golden-master byte-equivalent, merged to `dev`; see `handoff.md`) | `plans/strategy_precompute_architecture.md`, `plans/per_strategy_migration.md`, `plans/migration_checklist.md` | engine (8 files) | L | Med–High | ✅ Golden-master OK all 5 strategies after each phase |
| ~~**2**~~ ✅ DONE 2026-06-24 | Risk model improvements — 5 steps complete (trailing stop, breakeven move, ATR percentile filter, cost gate injection 0.0→0.05, portfolio exposure cap 6%). Golden master `ws2_final`==`baseline` (no re-baseline needed). See `handoff.md`. | `plans/strategy_precompute_architecture.md` §2 | engine `risk.py`, `portfolio.py`, `backtest_runner.py`, `live_bot_manager.py` | M | Med | ✅ Golden-master OK all 5 strategies; boundary suite 20/20 |
| **3** | Dashboard page restructure (8 KPI cards, equity sparkline, drawdown chart, performance calendar heatmap, timeframe selector) | `dashboardPage_restructure.md` | client + server (new aggregation endpoints) | M | Low | Client-only risk. Independent of #2 and #4 — can run between or after |
| **4** | Risk Dashboard — new nav page (real-time portfolio risk, hierarchical param controls, backtest risk profiler: VaR, correlation heatmap, Monte Carlo, leverage sensitivity) | `RISK_DASHBOARD_PLAN.MD` + `RISK_DASHBOARD_DECISIONS.MD` (gap-fill) | all 3 services (new engine math, new DB schema, new REST endpoints, new React page) | L | Med–High | Phases R1–R5 each independently shippable; pipeline-touching phases (R2, R4) gate on golden master. See decisions doc for open questions resolved |

### Workstream #1 — internal order (per `plans/migration_checklist.md`)
1. **Phase 1** — `BaseStrategy.prepare()` (no-op default) + `backtest_runner.py` wiring. Golden master unchanged (no-op).
2. **Phases 2–6** — migrate the 5 strategies to `prepare()`/`before()` index-only (MicroMacroRSIDivergence → MultiDivergence → MicroScalper → BestSupertrend → AdaptiveTrend). Golden master byte-identical after each.
3. **Phase 7** — live bot parity (`LiveBotManager._run_symbol_loop()` + `append_candle()`).
4. **Phase 8** — full golden master, boundary tests, lint, docs, handoff, commit.

> #2 (risk improvements) must precede #4 (Risk Dashboard) because the dashboard's hierarchical parameter resolution system and custom ATR/exposure overrides assume the risk primitives (`trail_atr_mult`, `min_edge_mult` injection, `max_portfolio_risk`) are stable. #3 (dashboard restructure) is client/server only and may run at any point after #1.

---

## Active Analysis (drives the sequence above)

| Path | What it contains | Status |
|------|-----------------|--------|
| `issues/strategy_performance.md` | **Analysis:** O(N²) indicator recomputation across 5 strategies + 6 risk-model gaps + live/backtest parity, with brainstormed solution options | Active — maps to seq #1 & #2 |

---

## Reference / Backlog (no decisions pending)

| Path | What it contains | Status |
|------|-----------------|--------|
| `future_paths.md` | Long-horizon roadmap (Monte Carlo, Risk Dashboard, vol forecasting, regime detection, equities/ML forks) | Exploration only |
| `research/optimization_ideas.md` | Parking lot: 28 optimization ideas from codebase review — nothing decided or implemented | Reference |
| `open_items.md` | Planning decisions resolved + refactor priority | Updated |
| `handoff.md` | Session resume log | Active log |
| `STATUS.md` | Planning status snapshot | Updated |

---

## Archive (completed & verified — moved out 2026-06-24)

See [`archive/`](archive/): `modular_merger_plan.md`, `chaos_mode_upgrade.md`, `documentation_drift.md`, `doc_fixes_applied.md`, `doc_fixes_pending.md`, `live_pnl_fix_plan.md`, `backtest_ui_refactor.md`.
