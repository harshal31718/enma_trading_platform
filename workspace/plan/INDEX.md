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

Verified against code on 2026-06-24: **neither item below is implemented yet** — `prepare()` does not exist in the engine, `min_edge_mult` still defaults to 0.0, `max_portfolio_risk` absent. The large golden-master-gated refactor runs as one workstream; risk improvements follow it.

| Seq | Item | Plan doc | Scope | Effort | Risk | Gate |
|-----|------|----------|-------|--------|------|------|
| **1** | Strategy performance refactor — **workstream** (see below) | `plans/strategy_precompute_architecture.md`, `plans/per_strategy_migration.md`, `plans/migration_checklist.md` | engine (11 files) | L (~12h) | Med–High | Golden-master byte-equivalence mandatory after each strategy (Rule C) |
| **2** | Risk model improvements (5 additive changes) | `plans/strategy_precompute_architecture.md` §2 | engine `risk.py`, `portfolio.py` | M | Med | **Behavior-changing** → re-baseline golden master. Sequence after #1 to avoid double churn |

### Workstream #1 — internal order (per `plans/migration_checklist.md`)
1. **Phase 1** — `BaseStrategy.prepare()` (no-op default) + `backtest_runner.py` wiring. Golden master unchanged (no-op).
2. **Phases 2–6** — migrate the 5 strategies to `prepare()`/`before()` index-only (MicroMacroRSIDivergence → MultiDivergence → MicroScalper → BestSupertrend → AdaptiveTrend). Golden master byte-identical after each.
3. **Phase 7** — live bot parity (`LiveBotManager._run_symbol_loop()` + `append_candle()`).
4. **Phase 8** — full golden master, boundary tests, lint, docs, handoff, commit.

> #2 (risk improvements) should follow #1 (the refactor) because it changes trade decisions and forces a golden-master re-baseline; doing it after the byte-equivalent refactor avoids double churn.

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
