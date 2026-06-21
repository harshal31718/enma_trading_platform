# Session Handoff

_Written at the end of each completed phase so any AI session can resume exactly where the
previous one stopped. Keep it current — stale handoffs are worse than none._

---

## Last Updated

2026-06-21 — **Symbol lock bug fixed + Phase 1 reporting merger completed.**

Next session: Phase 2 strategy lab work is underway. Implemented a new Strategy Lab create/clone workflow:
- Engine routes: `POST /strategies`, `PUT /strategies/{name}/code`.
- Server proxies: `POST /api/v1/strategies`, `PUT /api/v1/strategies/:id/code`.
- Client UI: Strategies page new strategy button, clone button on strategy cards, and a create dialog with blank/template selection and param preview.
Files changed: `engine/routers/strategies.py`, `server/src/controllers/strategy.controller.js`, `server/src/routes/strategy.routes.js`, `client/src/hooks/useStrategies.js`, `client/src/pages/Strategies.jsx`, `client/src/features/strategies/StrategyCard.jsx`, `client/src/features/strategies/StrategyCreateDialog.jsx`, `workspace/docs/core/API_CONTRACTS.md`, `workspace/docs/features/strategy-management/SPEC.md`, `workspace/docs/state/CURRENT_STATE.md`.
Open questions: Next step is code edit/save UX and strategy boundary/lint guidance before backtest live execution.

---

### Prior 2026-06-21 — **Implementation: Narang strict Black-Box merger — ALL PHASES COMPLETE (code written; golden master pending).**

### What was done
Full implementation of `workspace/plan/modular_merger_plan.md` — every file listed in the Appendix A
file-by-file change map has been written:

**Phase 1 — Data types + ABCs**
- `engine/core/models/base.py` — `Signal` (+ asset/magnitude/timeframe), `RiskConstraints` (was `RiskFrame` + max_drawdown_hit), `CostEstimate` (was `Cost`), `TargetPortfolio` (was `Target` + asset), `OrderPlan`, backward-compat aliases; `RiskModel.assess()` abstract, `TransactionCostModel.estimate()` new sig, `PortfolioModel.construct()` abstract, `ExecutionModel.route()` abstract.

**Phase 2 — Risk Model variants**
- `engine/core/models/risk.py` — `DefaultRiskModel.assess()` replaces `frame()` (shim kept); `AtrBracketRiskModel` (static bracket, maintain reads stored stop/TP); `ChandelierRiskModel` (per-trade state: _extreme/_entry_price/_initial_risk/_current_stop; initializes from s.position.entry_price on first holding candle via _signal_price); `SignalExitRiskModel` (no bracket).

**Phase 3 — TCM**
- `engine/core/models/cost.py` — `DefaultTransactionCostModel` (was `DefaultCostModel`, alias kept); `estimate(s, sig, constraints)` new signature estimates notional from budget/risk_per_unit.

**Phase 4 — Portfolio variants**
- `engine/core/models/portfolio.py` — `DefaultPortfolioModel.construct()` (veto/maintain/size with _edge_beats_cost); `RiskBudgetPortfolio._size()` (min(budget/rpu, max_notional/price)×conviction); `NotionalPortfolio._size()` (size_by_notional×conviction).

**Phase 5 — Execution**
- `engine/core/models/execution.py` — `DefaultExecution.route()` implements 5 paths (flat→flat, hold→flat close, flat→enter, flip, maintain bracket); `plan()` shim kept.

**Phase 5 — Pipeline**
- `engine/core/pipeline.py` — `evaluate(s, current_holding=0.0)` unconditional every-candle flow; no early return for open positions.

**Phase 5 — Strategy base**
- `engine/core/strategy.py` — `should_long/short/go_long/go_short` no longer `@abstractmethod` (defaults: False/pass); `self.alpha_model = self` added.

**Phase 5 — Runner wiring**
- `engine/services/backtest_runner.py` step C — `current_holding` computed and passed to `evaluate()`.
- `engine/core/live_bot_manager.py` — unified every-candle block with `current_holding` + `_close_at_open` handling.

**Phase 6 — Strategy ports (all 5)**
- `MicroScalper` — `AtrBracketRiskModel` + `RiskBudgetPortfolio`; `forecast()` handles is_open (flip on crossover).
- `AdaptiveTrend` — `ChandelierRiskModel` + `RiskBudgetPortfolio`; `forecast()` maintains while holding.
- `BestSupertrend` — `SignalExitRiskModel` + `NotionalPortfolio`; `forecast()` handles is_open; **known golden master drift** (liquidate→_close_at_open fill price).
- `MicroMacroRSIDivergence` — `AtrBracketRiskModel` + `RiskBudgetPortfolio`; `forecast()` handles exit_on_opposite close.
- `MultiDivergence` — `AtrBracketRiskModel` + `RiskBudgetPortfolio`; `forecast()` returns vars["signal"].

**Phase 6 — Tests + docs**
- `engine/tests/test_boundaries.py` — boundary regression test (defines forecast, no forbidden methods, no forbidden refs, model bindings).
- `.claude/commands/check-boundaries.md` — removed deleted `newGuide.md` reference.

### What's STILL NEEDED (golden master gate — must run in Docker)

1. **Capture baseline BEFORE this PR is considered done:**
   ```
   docker compose exec engine python -m scripts.golden_master run --label baseline
   ```
   (Only needed if no baseline exists yet from a previous session.)

2. **Run golden master AFTER:**
   ```
   docker compose exec engine python -m scripts.golden_master run --label modular_merger
   docker compose exec engine python -m scripts.golden_master compare --a baseline --b modular_merger
   ```
   - Exit 0 = metrics identical for all 5 strategies (except possibly BestSupertrend — see known drift).
   - BestSupertrend drift is **intentional** (liquidate→_close_at_open behavioral change). If it drifts,
     snapshot a new BestSupertrend-specific baseline and document in `workspace/docs/core/DECISIONS.md`.

3. **Run boundary tests:**
   ```
   docker compose exec engine python -m pytest engine/tests/test_boundaries.py -q
   ```

### Open questions / known risks
- `ChandelierRiskModel._signal_price` init is correct for standard flow; verify on BTC 2024 1h golden master.
- `RiskBudgetPortfolio` for `AdaptiveTrend` uses `constraints.max_notional = equity * min(max_leverage, leverage)`. Verify this triple-min is exactly the old `_position_qty` formula.
- `engine/tests/test_boundaries.py` `test_model_bindings` does partial __init__ — may need adjustment if strategy __init__ depends on full BaseStrategy setup. Run inside Docker to confirm.

### Files changed
```
engine/core/models/base.py           ← REWRITTEN
engine/core/models/risk.py           ← REWRITTEN
engine/core/models/cost.py           ← REWRITTEN
engine/core/models/portfolio.py      ← REWRITTEN
engine/core/models/execution.py      ← REWRITTEN
engine/core/models/__init__.py       ← UPDATED
engine/core/pipeline.py              ← REWRITTEN
engine/core/strategy.py              ← EDITED (remove abstractmethods, add alpha_model)
engine/services/backtest_runner.py   ← EDITED (step C: current_holding)
engine/core/live_bot_manager.py      ← EDITED (unified every-candle block)
engine/strategies/MicroScalper/      ← REWRITTEN (forecast + model bindings)
engine/strategies/AdaptiveTrend/     ← REWRITTEN (forecast + model bindings)
engine/strategies/BestSupertrend/    ← REWRITTEN (forecast + model bindings)
engine/strategies/MicroMacroRSIDivergence/ ← REWRITTEN (forecast + model bindings)
engine/strategies/MultiDivergence/   ← REWRITTEN (forecast + model bindings)
engine/tests/test_boundaries.py      ← CREATED
engine/tests/__init__.py             ← CREATED
.claude/commands/check-boundaries.md ← UPDATED
workspace/plan/handoff.md            ← THIS FILE
```

---

### (prior) 2026-06-20 — Two back-to-back tasks: (1) workspace/memory audit + cleanup, (2) ruthless `.claude/` cut-down. Both complete.

---

## Task 1 — Workspace/memory audit + approved cleanup

**Drift fixed (D1–D7), all applied & verified:**
- **D1 (HIGH):** docs claimed JWT `/api/v1/auth/*` register/login + middleware exist. **They don't** — no routes/controller/middleware/User model; `bcryptjs`/`jsonwebtoken` unused; `client/src/store/useAuthStore.js` orphaned. Fixed `CURRENT_STATE.md`, `auth-settings/SPEC.md`, `DECISIONS.md`. Now consistent with `DEPRECATED.md` + code.
- **D2:** removed non-existent `engine/utils/validators.py` from `engine/CLAUDE.md`.
- **D3:** no `.pine` files in repo — fixed "(root of repo)" refs (`strategies/INDEX.md`, two strategy docs).
- **D4:** `CURRENT_STATE.md` "5 pages" → "6 pages".
- **D5:** skills count stale.
- **D6:** `settings.local.json` prune — **BLOCKED by harness permission-file guardrail**; not applied. Pruned content was handed to the user to paste manually.
- **D7:** `workspace/` now git-tracked (anchored `/docs/` `/plan/`). NB: the `.gitignore` spec-block was externally removed mid-session; restored as local-only for `.claude/`/`CLAUDE.md`/`AGENTS.md`/`.mcp.json`.

**Bloat removed:** deleted `workspace/docs/archive/` (4 files); trimmed `workspace/archive/research/` 15 numbered deep-dives; kept `TASK/OPTIMIZATION_PLAN/NEXT_STEPS`. Single archive root = `workspace/archive/`.

## Task 2 — `.claude/` ruthless cut-down (3 agents/13 commands/3 root docs → 1/6/1)

**Final `.claude/` tree:**
```
agents/    drift-reviewer.md
commands/  add-strategy · add-indicator · add-endpoint · sync-spec · security-review · verify
GOVERNANCE.md   (= governance + AI-infrastructure inventory; the sole root doc)
settings.json · settings.local.json   (untouched)
```
- **Agents:** kept `drift-reviewer`; deleted `doc-syncer` (→ folded into `/sync-spec`), `spec-explorer` (→ built-in Explore).
- **Commands:** deleted `review-drift` (→ drift-reviewer agent), `new-feature` (gate → `/sync-spec`), `setup` (→ merged into `/verify`), and domain primers `client-ui`/`server-api`/`engine-algo`/`binance-api` (redundant with service `CLAUDE.md` + core binance doc). Fixed `add-endpoint` drift (removed fictional JWT/express-validator step).
- **Root docs:** `BOOTSTRAP.md` folded into `AGENTS.md`; `AI_INFRASTRUCTURE.md` folded into `GOVERNANCE.md` Part 2.
- **Cross-refs updated:** `CLAUDE.md` (bootstrap pointer + Rule F), `AGENTS.md` (read-order, skills pointer → GOVERNANCE, subagent table), `skills/README.md`, `archive/README.md`, `DEPRECATED.md`. Final dangling-ref sweep clean (only the user's prompt file + an unrelated `vite.config.js setup.js` remain).

## What's Next
- No active feature work. Optimization backlog: `workspace/archive/research/OPTIMIZATION_PLAN.md` (28 items).
- **User to apply manually:** the pruned `settings.local.json` (D6, guardrail-blocked).
- **Open decision:** delete orphaned `client/src/store/useAuthStore.js` + unused `bcryptjs`/`jsonwebtoken` deps (code change, not done).
- Committing is left to the user: `git add -A && git commit` (workspace/ is now tracked).

## Open Questions
- The `.gitignore` spec-block was externally removed mid-session; restored as local-only. Confirm whether `.claude/`/`CLAUDE.md` were intended to become git-tracked too.
