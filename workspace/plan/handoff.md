# Session Handoff Log

Resume prompts for cross-session continuity (root `CLAUDE.md` Rule G / `AGENTS.md` → Session Handoff).

**Format rules:**
- Newest entry on top: `## <date> — <title> — <status>` with **Goal / Done / Files changed / Open questions**.
- Keep at most the **3 most recent entries**. When adding a new one, delete the oldest — git history is the archive. This file must stay a short resume prompt, not a project log.

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
(9.4/9.7/9.8); flag/migrate existing multi-symbol `backtestResults` as stale now or with 9.1;
keep or delete `IcebergAlgorithm` (untestable under constant-slippage fill model).

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

---
## 2026-07-03 — Chaos Mode Diagnosis + Bot Session Caps + Testnet-Invalid Symbol Blacklist — COMPLETE ✅

**Goal:** User reported chaos-mode WS disconnect storms + TP-order 400s, then a 53-real-vs-4-tracked
open-position gap. Diagnosed root causes, fixed them, added configurable per-environment session caps
per the user's exact spec, then fixed a Chaos Wizard UI bug and a distinct testnet-symbol-validity bug
found while verifying against the live stack.

**Done:**
1. **Diagnosis + fixes (DECISIONS.md #21/#22 context, no dedicated decision entry for these — see git
   history for the 6-finding writeup):** WS reconnect thundering herd (no backoff/jitter) → capped
   exponential backoff + full jitter. Stale exchange-rules cache causing TP algoOrder 400s → periodic
   30-min refresh + loud warning on cache-miss. Quarterly/delivery contracts (e.g. `ETHUSDT_260925`)
   reaching TP placement → `contractType` filtering in `get_all_symbols()`. `stop_session()`'s serial
   close loop timing out and silently reporting `openPositions: []` regardless of what actually closed
   → bounded-concurrency (semaphore=8) close loop, only reports confirmed-closed symbols.
   `reconciliation.js` wiping `openPositions` in Mongo before confirming closes → reordered to
   close-then-write. No full-account safety net → new periodic (10 min) `reconcileFullAccountPositions`
   sweep, alert-only (does not auto-close).
2. **Configurable bot session caps (DECISIONS.md #21):** new `Settings.limits.{testnet,mainnet}.
   {maxSymbolsPerBot,maxConcurrentBots}` + `Settings.chaosMaxTotalSymbols`, replacing the removed
   `chaosMaxStrategies` (one unified concurrent-bot cap now governs both manual bots and Chaos Mode).
   Enforced in `algo.controller.js`'s `startSession()`/`startChaos()` (chaos truncates to available
   slots and reports skips via `errors`, not a hard reject); `chaosAllocator.js`'s round-robin bounded
   by both the per-strategy and run-wide caps as running counters (not pool pre-truncation, to preserve
   tier-priority mix); `Settings.jsx` UI added (testnet card live, mainnet card marked "Future" — no
   enforcement path exists for mainnet, added as pure future-proofing per user instruction); engine
   `StartSessionRequest.symbols` got a defensive `max_length=250`. Also hardcoded `_getBinanceHeaders()`
   to `'testnet'` (was reading `Settings.mode`, a latent landmine — harmless today, fixed for
   consistency with every other Binance-header call site).
3. **`ChaosWizard.jsx` fix:** its client-side allocation-preview algorithm was a stale duplicate of the
   OLD unbounded round-robin (from before item 2) and still read the removed `chaosMaxStrategies` field
   — dialog showed 120+ symbols/strategy even though the server now correctly capped and truncated on
   launch ("bots started correctly, dialog box showing wrong" — user-reported). Rewrote the preview to
   mirror `chaosAllocator.js`'s bounded algorithm exactly.
4. **Testnet-invalid-symbol blacklist (DECISIONS.md #22):** ~60 symbols in demo-fapi's `exchangeInfo`
   (status=TRADING, contractType=PERPETUAL) are rejected outright by the testnet matching engine —
   confirmed via a definitive HTTP 400 on both `leverageBracket` and real order placement for the same
   symbols. New `is_symbol_invalid()` in `utils/symbols.py` blacklists on a definitive 400 specifically
   (not 429/5xx/timeout, which stay transient/retryable); `get_all_symbols()` excludes blacklisted
   symbols from future pairlists/Chaos pools; `live_bot_manager.py` aborts a symbol's loop immediately
   (right after the leverage probe, before opening a WS connection) instead of retrying a doomed order
   every candle close forever.

**Verification done:** All Python/Node files import/load-check clean in-container after every change.
Full `docker compose down && up --build -d` cycle run twice. **Environment gotcha worth remembering:**
`engine` and `client` both ha