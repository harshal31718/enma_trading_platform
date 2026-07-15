# Session Handoff Log

Resume prompts for cross-session continuity (root `CLAUDE.md` Rule G / `AGENTS.md` → Session Handoff).

**Format rules:**
- Newest entry on top: `## <date> — <title> — <status>` with **Goal / Done / Files changed / Open questions**.
- Keep at most the **3 most recent entries**. When adding a new one, delete the oldest — git history is the archive. This file must stay a short resume prompt, not a project log.

---
## 2026-07-15 — Plan 9.1–9.3 shipped (quant P0 bug fixes); autonomous multi-plan session started — IN PROGRESS 🔄

**Goal:** User asked to pick up the prior session and, per standing instruction, to then drive
continuously through the **entire `workspace/plan` catalog** (all plans, all tracks) without
stopping for check-ins — commit at each checkpoint, only surface genuine blockers (destructive
git ops, product decisions like Plan 3.2, secrets/`.env`). This entry covers the first
checkpoint; later checkpoints in this same session will be appended above this one on the next
handoff write (subject to the 3-entry cap) if the session is still running when a new entry is
due — check `git log` for anything shipped after this note.

**Done — Plan 9.1–9.3 (QNT-1, QNT-2, QNT-17), all P0, all Shipped:**
1. **QNT-1** — `services/backtest_runner.py` `_run_shared_portfolio` now calls
   `adapters[sym].record_equity(strategy, time_t)` after `evaluate_and_route` each candle (it
   never called this before — the only place that cleared `_entered_this_candle`, which
   `kernel.check_exits` early-returns on). New test `tests/test_multi_symbol_portfolio_exits.py`
   drives `_run_shared_portfolio` directly with 2 synthetic symbols and asserts both exit via
   `stop_loss` + exact cash conservation. Live-data proof: 2-symbol golden-master run now shows
   real `stop_loss`/`take_profit` exits (previously structurally impossible). Checked
   `backtestResults` for `symbol` containing "," (the migration the audit called for) — none
   exist in this environment, so no stale-flag migration was needed.
2. **QNT-2** — `core/kernel.py` `evaluate_and_route` snapshots `_close_at_open`/`_pending_flip`
   before the exec-algo clear and restores them after. Two new tests in
   `tests/test_exec_algo_slicing.py` confirm a close/flip survives an active TWAP algo and
   actually fires on the next candle.
3. **QNT-17** — `services/backtest_runner.py`'s `backtestResults` write now persists
   `alphaParams`, `riskParams`, `slippagePct`, `fundingEnabled`, `fundingRate` (
   `leverage_sensitivity_runner.py` already read these via `parent.get(...)` — it was written
   against this contract from the start; the fields were simply never being saved).
4. **Verification:** single-symbol golden master byte-identical before/after
   (`pre_qnt1_2_3_baseline` vs `post_qnt1_2_3_fix`, tol=1e-6, 5 strategies) — confirms zero
   regression on the existing shipped path. Full engine test suite: 84/84 green. New
   multi-symbol golden-master baseline captured (`multi_symbol_baseline_post_fix`) for future
   re-baseline diffing on steps 9.4+.
5. Docs updated: `0_tracker.md` (row 9 + Notes section — also **fixed a pre-existing truncation
   bug** from the 2026-07-14 session: the Notes section and plan-9 step descriptions were cut
   off mid-sentence in commit `a5c0bf7`, notes for plans 6–10 were missing entirely; both
   completed), `9_backtest-and-optimizer-correctness.md` (9.1–9.3 marked Shipped with detail).

**Session-wide plan (TaskCreate #1–12, tracked live, not repeated here):** finish 9.1–9.3 →
browser-verify the backtest UI still works end-to-end → hardening track Plan 2 → 3 → 4 → 5 → 6
→ 7 → 8 → quant remainder 9.4–9.10 → Plan 10 (Monte Carlo/Strategy Lab) → full UI polish +
mobile/responsive pass (last, added mid-session per explicit user request). Committing at each
plan/phase checkpoint on `dev`, not pushing to remote without being asked. Also asked to
periodically re-verify via `claude-in-chrome` after each checkpoint that the app still actually
works, not just that tests pass.

**Files changed:** `engine/services/backtest_runner.py`, `engine/core/kernel.py`,
`engine/tests/test_multi_symbol_portfolio_exits.py` (new),
`engine/tests/test_exec_algo_slicing.py`, `workspace/plan/0_tracker.md`,
`workspace/plan/9_backtest-and-optimizer-correctness.md`.

**Open questions (unchanged, still open, deferred to when 9.4/9.7/9.8 are reached):** who signs
off golden-master re-baselines for output-changing steps; keep or delete `IcebergAlgorithm`
(untestable under the constant-slippage fill model until 9.10 lands); Plan 3.2 product decision
(retire vs sandbox UI strategy editing) needs the user's sign-off when Plan 3 is reached.

---
## 2026-07-14 — Quant-Core Deep-Dive Audit (planning only, no code) — COMPLETE ✅

**Goal:** Deep-dive the algotrading core (backtest runner, kernel, fill/margin models, metrics,
optimizer, Monte Carlo, live-loop trading semantics) beyond the existing `audit_1_system-design.md` audit;
web-research current methods; document findings + remediation plan. No implementation (Rule D).

**Done:** 17 new issues **QNT-1..17** documented with code citations in
`workspace/plan/audit_2_quant-core.md`. Two H-severity shipped bugs:
(QNT-1) multi-symbol portfolio backtests never fire SL/TP/liquidation/funding after first entry
(`_entered_this_candle` never cleared — `_run_shared_portfolio` skips `record_equity`);
(QNT-2) exec-algo mode erases `_close_at_open`/`_pending_flip` intents (kernel clears before
re-route; route() returns None for close/flip). Also: leverage-sensitivity re-runs with default
params because run config is never persisted (QNT-17); entry-candle exits impossible in
backtest but live-active (QNT-3); flat/mispriced funding model (QNT-5); in-sample-only
optimizer (QNT-6); i.i.d. Monte Carlo (QNT-7); live/backtest fill-timing + rolling-500-window
parity gaps (QNT-8/9); silent WS candle gaps (QNT-10). Research-backed upgrade paths: walk-forward
+ DSR/PBO + Optuna, detail-timeframe intrabar sim, historical funding ledger, lookahead sentinel,
block-bootstrap MC, fill-model ladder. New **Plan 9** created
(`9_backtest-and-optimizer-correctness.md`, steps 9.1–9.3 = P0 bug fixes, runnable in parallel
with plans 2–8); catalog/tracker/audit_1_system-design.md updated.

**Also done (same session):** detailed **Plan 10 — Monte Carlo Optimiser & Strategy Lab**
(`10_monte-carlo-strategy-lab.md`). Diagnosis of the broken MC feature: Risk Dashboard's
`SimulationResults.jsx` fires a cache-forever `GET /risk/backtest/:id/simulation` that makes
the engine re-run the full backtest 5× + MC synchronously (SRV-5 pattern), with default params
(QNT-17), all failures blanket-wrapped as 503; engine `/optimize` API has **no Node route and
no UI** (dead feature). Plan: job-based (BullMQ/Socket.IO reuse), vectorized block-bootstrap MC
engine, `labResults` collection, dedicated Strategy Lab page (MC tab + Optimizer tab),
MC-scored param selection + drawdown-constrained risk_pct + MC-banded leverage; 4 phases,
absorbs 9.6/9.9; hard-depends on 9.1/9.3.

**Also done (same session): plan-folder restructure.** `workspace/plan/refinements/` dissolved
into the flat plan folder with a file-family taxonomy: `01_project_outline` →
`research_1_project-outline.md` · `02_market_research` → `research_2_market-survey.md` ·
`03_better_options` → `research_3_gap-analysis.md` · `04_improvement_roadmap` → **rewritten as
`0_roadmap.md`** (phased blueprint extended from Phases 1–6 over plans 2–8 to **Phases 0–8
over plans 1–10**, two parallel tracks: hardening + quant) · `05_algotrading_deep_dive` →
`audit_2_quant-core.md` · `issues.md` → `audit_1_system-design.md`. All cross-references updated
across the folder; `0_plans.md` gained the taxonomy + old→new mapping table ("Reference
shelf"); `0_tracker.md` gained a Phase column + two-track session protocol. Old shorthand like
"02 §10" inside research docs refers to the old series numbers via the mapping table.

**Files changed (docs only):** new: `audit_2_quant-core.md`, `9_backtest-and-optimizer-correctness.md`,
`10_monte-carlo-strategy-lab.md`, `0_roadmap.md`; renamed: `research_1_project-outline.md`,
`research_2_market-survey.md`, `research_3_gap-analysis.md`, `audit_1_system-design.md` (ex
`issues.md`); updated: `0_plans.md`, `0_tracker.md`, `handoff.md`; deleted: `refinements/`
(contents relocated, `04_improvement_roadmap.md` superseded by `0_roadmap.md`).

**Open questions:** who signs off golden-master re-baselines for output-changing steps
(9.4/9.7/9.8); flag/migrate existing multi-symbol `backtestResults` as stale now or with 9.1
(**resolved 2026-07-15: none exist, no migration needed**); keep or delete `IcebergAlgorithm`
(untestable under constant-slippage fill model).

---
## 2026-07-03 — UI Fixes: Bot Stopping State, Session List Ranking, Dashboard Section Alignments — COMPLETE ✅

**Goal:** Resolve three user-reported UI issues on the Dashboard and AlgoTrading pages. (1) Stop button disappears during `'stopping'` state, and needs to remain visible displaying "Stopping" until completely stopped. (2) Bot sessions list needs customized ranking/sorting rules: running first (last started first), then stopped (last stopped first). (3) Strategy Leaderboard title is oversized and has inconsistent margin/padding compared to other Dashboard sections. (4) Align "Live Runs", "Recent Live Runs", and "Recent Backtests" into the same row (3 columns if active live runs exist, else 2 columns).

**Done:**
1. **Stop button visibility fix:** Updated `SessionCard.jsx` to render the Stop button when `session.status === 'running' || session.status === 'stopping'`. When `stopping` is true or status is `'stopping'`, the button is disabled and its label changes to "Stopping".
2. **Bot session ranking/sorting:** Wrapped the bot session list map in `AlgoTrading.jsx` with a custom `useMemo` comparator sorting running/starting/stopping sessions first (newest `createdAt` first), followed by stopped/errored sessions (newest `stoppedAt || createdAt` first).
3. **Strategy Leaderboard style alignment:** Stripped the `<Card>`, `<CardHeader>`, `<CardTitle>`, and `<CardContent>` wraps from `StrategyLeaderboard.jsx` to remove the excessive padding/margin and double borders. Wrapped `StrategyLeaderboard` in a `<PanelSection>` component inside `Dashboard.jsx` to match the layout and title text size of other panels.
4. **Three-column layout for active runs:** Refactored the Dashboard layout to group "Live Runs" (active sessions), "Recent Live Runs" (finished sessions), and "Recent Backtests" into a single flex/grid row that dynamically adapts: 3 columns if active live runs exist, 2 columns otherwise.

**Verification done:** Build compilation verified via `npm run build`.

**Files changed:** `client/src/components/algo/SessionCard.jsx`, `client/src/pages/AlgoTrading.jsx`, `client/src/features/dashboard/StrategyLeaderboard.jsx`, `client/src/pages/Dashboard.jsx`.
