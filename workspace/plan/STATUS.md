# Planning Status

Created 2026-06-24 — consolidates `workspace/issues_and_solutions/` into `plan/`.
Updated 2026-06-24 — completed plans moved to `archive/`; remaining work verified against code and sequenced (see `INDEX.md`).

---

## Verified Implementation Status (2026-06-24)

Checked each remaining plan against the codebase. **All four are unimplemented** — confirmed by absent code markers:

| Item | Marker checked | Status |
|------|----------------|--------|
| Two-phase `prepare()`/`before()` | `def prepare(` in `engine/`, `.prepare()` in `backtest_runner.py` | ❌ not implemented → seq #1 |
| Risk model improvements | `min_edge_mult` default = 0.05, `max_portfolio_risk` | ❌ still 0.0 / absent → seq #2 |
| Live PnL fix | `positionDetails` on server + `SessionCard.jsx` seed | ✅ **shipped 2026-06-24** (archived) |
| Backtest UI refactor | `grid-cols-7`, "Simulation Config" removed | ✅ **shipped 2026-06-24** (archived) |

> Note: the `trail_atr_mult` in `risk.py` is the pre-existing **ChandelierRiskModel** (AdaptiveTrend), NOT the proposed trailing on `AtrBracketRiskModel`.

---

## Analyses Documented

| Analysis | Status |
|----------|--------|
| O(N²) indicator recomputation in 5 strategies | Not yet implemented → seq #3 |
| 6 risk model limitations | Not yet implemented → seq #4 |
| Live/backtest sync gap | Not yet implemented → part of seq #3 (Phase 7) |
| Documentation drift across 10 nodes | **All items 1–18 applied** → archived |

## Plans — Remaining (sequenced in INDEX.md)

| Seq | Plan | Source | Status |
|-----|------|--------|--------|
| ~~1~~ | Two-phase `prepare()`/`before()` architecture | `plans/strategy_precompute_architecture.md` | ✅ Done 2026-06-24 |
| ~~1~~ | Per-strategy migration (5 strategies) | `plans/per_strategy_migration.md` | ✅ Done 2026-06-24 |
| ~~1~~ | Migration checklist (execution runbook) | `plans/migration_checklist.md` | ✅ Done 2026-06-24 |
| 2 | Risk model improvements (5 changes: trailing stop, breakeven, ATR percentile filter, cost gate injection, portfolio cap) | `plans/strategy_precompute_architecture.md` §2 | Proposed — **next up** |
| 3 | Dashboard page restructure (8 KPIs, sparklines, performance calendar heatmap) | `dashboardPage_restructure.md` | Proposed — independent, can run after #2 |
| 4 | Risk Dashboard — new nav page (VaR, correlation, Monte Carlo, hierarchical param controls) | `RISK_DASHBOARD_PLAN.MD` | Proposed — sequence after #2 |

## Plans — Completed (archived)

Moved to `archive/`: Live PnL resolution + Backtest UI refactor (shipped 2026-06-24); Modular merger (Narang five-model pipeline), Chaos Mode configurable wizard, documentation-drift audit, doc fixes items 1–18 (earlier).

## Open Decisions

See `open_items.md`.
