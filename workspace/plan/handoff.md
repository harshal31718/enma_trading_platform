# Session Handoff Log

Resume prompts for cross-session continuity (root `CLAUDE.md` Rule G / `AGENTS.md` → Session Handoff).

**Format rules:**
- Newest entry on top: `## <date> — <title> — <status>` with **Goal / Done / Files changed / Open questions**.
- Keep at most the **3 most recent entries**. When adding a new one, delete the oldest — git history is the archive. This file must stay a short resume prompt, not a project log.

---
## 2026-07-15 — Autonomous multi-plan session: 9.1–9.3, Plan 2/3/4, 11–19 merge, Plan 5.1/5.2/5.4, Plan 20, Plan 11/12 — SESSION END (context limit) ⏸️

**Goal:** pick up the prior session, then drive continuously through the entire `workspace/plan`
catalog without stopping for check-ins — commit at each plan checkpoint, only surface genuine
blockers. Detail for each shipped plan lives in that plan's own file under a "Shipped summary"
heading — **read those before touching a dependent plan**, this entry is a pointer index, not a
duplicate log. Check `git log` for anything shipped after this note if resuming.

**Shipped this session (chronological):**
- **Plan 9 steps 9.1–9.3** (QNT-1/QNT-2/QNT-17) — multi-symbol portfolio backtests now actually
  fire SL/TP/liquidation (`_run_shared_portfolio` never called `record_equity`); exec-algo mode
  no longer erases close/flip intents; leverage-sensitivity reruns use the parent run's real
  params. Detail: `9_backtest-and-optimizer-correctness.md`. Browser-verified live (user logged
  in) with a real BTCUSDT+ETHUSDT run; user then asked for a symbol column on List of Trades —
  added end-to-end (engine → server schema → client table/CSV), also verified live.
- **Plan 2 (Safety net & guardrails), all 6 steps.** Server (Jest, 39 tests) + client (Vitest, 11
  page smoke tests) harnesses stood up from scratch/half-wired state; encryption fails closed
  with a versioned envelope; correlation IDs (`AsyncLocalStorage` + pino) thread server↔engine;
  engine `/health` now honest; CI added. **Surfaced a standing risk**: local dev shares
  production's MongoDB Atlas cluster — unresolved, flagged for before/during Plan 4 (now
  addressed in 4.1's inventory, still not structurally resolved). Detail:
  `2_safety-net-and-guardrails.md`.
- **Plan 3 (Service-to-service trust), all 5 steps.** `/internal/*` now authenticated
  (`INTERNAL_API_KEY`, constant-time compare both directions); strategy-code-write RCE path
  removed outright (confirmed dead client-side first — 3.2's decision made on the plan's own
  stated default under "proceed on recommended paths" authorization, no sign-off round-trip);
  tiered Redis-backed rate limits. Self-inflicted crash-loop mid-step (stale container + missing
  dependency) surfaced as a repeating browser toast — root-caused and fixed same step. Detail:
  `3_service-to-service-trust.md`.
- **Plan 4 (Credential & config topology), 4.1–4.4 shipped, 4.5 partial.** Full secret inventory
  — headline finding: **every `BINANCE_*` env var was already dead code**, the per-user-Settings
  credential path the user originally asked for was already fully in place. Each container's env
  scoped to only what it reads (client went from "the entire shared `.env`" to two public
  `VITE_*` vars — caught and fixed a real regression this introduced, an empty-string-vs-unset
  `os.getenv` landmine in `candle_importer.py`). `ENCRYPTION_KEY` rotation window implemented +
  tested (6 new tests, v1↔v2 mixed records). TimescaleDB pinned to its exact running version.
  **Not done:** Redis `requirepass` (deferred — real work, wide blast radius, not squeezed into
  an already-long session); `.env`'s 7 dead `BINANCE_*` lines including one real unused testnet
  key/secret (permission system correctly blocked autonomous deletion — needs the user's
  explicit go-ahead). Detail: `4_credential-and-config-topology.md`.

**Operational lesson learned the hard way (twice) this session:** `docker compose up -d` on a
container recreates it **from whatever's baked into the image**, silently discarding anything
that only ever existed via `docker compose watch`'s live file sync. Any source or test file
written since the last `docker compose build` for that service vanishes on recreation — this
already cost two rounds of "why did my test count drop" debugging. **Rule going forward:
`docker compose build <service>` before every `up -d` that could recreate a container**, not
just when you know you changed a dependency.

**Also shipped this session (quant remainder + Plan 10 Phase 1a + UI pass):**
- **Plan 9.4** (QNT-3, opt-in entry-candle SL/TP evaluation) and **9.5** (QNT-12, lookahead-bias
  sentinel — all 5 seeded strategies pass, zero divergence) — both additive, default-off,
  golden-master-safe. Plus the **QNT-15** perf fix (`AtrBracketRiskModel`'s ATR history kept
  sorted incrementally instead of re-sorted every candle). 9.7/9.8/9.9/9.10 (funding ledger,
  intrabar sim, remaining MC/stats work, fill-model ladder) remain — larger, genuinely
  behavior-changing, correctly deferred. Detail: `9_backtest-and-optimizer-correctness.md`.
- **Plan 10 Phase 1a**: rewrote the Monte Carlo engine core (`engine/services/monte_carlo.py`)
  — vectorized block bootstrap replacing an O(n_runs×n_trades) i.i.d. Python loop, `scale_out`
  legs excluded, equity-path compounding bug fixed (was silently mixing additive-computed
  returns with multiplicative application). ~100x faster, response contract preserved. The
  full job-based architecture (queue, `labResults`, Strategy Lab UI, optimizer exposure) is
  **not started** — multi-day scope, explicitly out of reach this session. Detail:
  `10_monte-carlo-strategy-lab.md`'s scoped-delivery note.
- **UI pass**: live-tested the MC rewrite through the actual Risk Dashboard UI and caught a
  real bug it exposed (`SimulationResults.jsx` hardcoded "N=2000" — fixed to read the real
  run count). Desktop visual QA across Dashboard/Settings/Strategies/Trade/RiskDashboard/
  AdminPanel/AlgoTrading — all clean, aesthetics invariant holds, no regressions from any
  container restart this session (the user's live/now-stopped session data survived intact).
  **Could not verify mobile/narrow-viewport rendering** — `resize_window` doesn't actually
  change `window.innerWidth` in this environment (confirmed via JS, window stays maximized
  regardless of the tool call's reported "success"); substituted a code-level audit of
  Tailwind breakpoint usage instead (Navbar has a documented mobile drawer, `SessionCard.jsx`
  has proper `grid-cols-1`→responsive breakpoints, the shared `Table` component wraps in
  `overflow-auto` so wide tables scroll rather than break layout) — reasonable but not a
  substitute for actually seeing it render narrow. Flag this tooling gap to a future session.

**Session-wide plan (TaskCreate #1–13, all resolved except Plan 5):** 9.1–9.3 ✅ → browser
checkpoint ✅ → Plan 2 ✅ → 3 ✅ → 4 ✅ → **Plan 5 — BLOCKED, see below** → 6/7/8 blocked by 5 →
9.4/9.5/QNT-15 ✅ → Plan 10 Phase 1a ✅ → UI pass ✅. Committing at each checkpoint on `dev`, not
pushing to remote without being asked.

**Update — user gave explicit go-ahead on Plan 5 ("Full send, all 6 steps"), work resumed:**
The pause above was real at the time (correct call — no rubber-stamping unsupervised state-
machine rewrites against a live session) but the user then explicitly authorized the full scope
after seeing the reasoning. Shipped since: **5.2** (real fills, not fabricated closes — every
close-booking site now reads the actual exchange fill, failed closes leave the position open
instead of fabricating a close), **5.4** (per-symbol `asyncio.Lock` killing the candle-loop vs
fill-callback race), and **5.1 in scoped form** (append-only `executionEvents` log + Node seq-
ordering guard + a tested `fold_events()` replay — but `LiveSession`/engine memory are NOT yet
pure derived views of the log; that's Step 5.6, now unblocked but not started). Detail for all
three: `5_live-trading-state-integrity.md`. Remaining: 5.3 (entry-order idempotency — partially
covered as a 5.2 side effect), **5.5 (Decimal money — the largest, riskiest piece, needs its own
deliberate golden-master sign-off pass, not a same-day bundle)**, 5.6 (restart recovery).

**Also done (same session): merged plans 11–19 into tracking.** A separate concurrent Claude Code
session had consolidated `workspace/next_phase/` into `workspace/plan/` as new plans 11–19 +
`ref_*.md` (mechanical move only, see `mergeContext.md`) — this session read all 9 new plan files,
cross-referenced them against 0–10 and shipped work, and updated `0_tracker.md`/`0_roadmap.md`
(new Phase 9)/`0_plans.md` to reference them. **Found and fixed two real conflicts**: Plan 16
(lookahead analysis) is superseded by the already-shipped 9.5 sentinel — now `Merged→9`; Plans 18
(walk-forward) + 19 (Bayesian hyperopt) duplicate Plan 10 Phase 3's already-scoped job-based
optimizer design — now `Merged→10`, kept as design reference only. Also **fixed a pre-existing
bug**: `0_plans.md` was truncated mid-word in the last commit, missing catalog entries for plans
7–10 entirely — reconstructed them. Confirmed via grep that Plan 12's "1a" (per-asset notional
cap) is already shipped (`max_qty()`/`max_exposure_notional`), narrowing that plan's scope to
just the position-count gate. The other session's staged renames were left untouched — only
content was added on top. Detail: `0_tracker.md` Notes section, `0_plans.md`'s new sections.

**Further shipped after the above (same 2026-07-15 session, later in the day):**
- **User-requested Binance precision/notional audit** (screenshots comparing Enma's Trade page
  to Binance's own UI) — dispatched a research agent to compare Binance's real `exchangeInfo`
  filter semantics against every Enma order-placement surface. Found everything else consistent;
  **one real gap**: DCA scale-out (`execute_reduce`) never floored qty to the symbol's
  `stepSize` (a live `-4023`/`-1111` rejection risk, currently dead code — no strategy does DCA
  scale-out yet). **Fixed same session**: `clamp_and_round_qty(..., reduce_only=True)` in both
  adapters (`20_binance-precision-notional-parity.md`, Shipped). **Bonus fix found in the same
  pass**: `execute_entry` had zero order-idempotency handling (Plan 5 Step 5.3, ENG-10) and
  always booked the pre-trade price estimate instead of the real fill even on a normal success —
  both fixed.
- **Plan 11 (V0 verification) — Verified live** via browser against the running stack (real
  testnet account, 3 open positions, read-only checks — nothing was touched). Dashboard,
  Risk Dashboard, and MC/leverage-sensitivity UI all confirmed working with real data;
  `resolveStrategyRiskParams` confirmed wired into both controllers. One already-documented,
  non-urgent gap reconfirmed (Dashboard's sparkline/calendar components exist but aren't
  composed into the page — `client/CLAUDE.md` already flagged this before this session).
- **Plan 12 (max position per asset) — Shipped.** 1a was already live; 1b (session-level
  `max_open_positions` concurrent-position cap) implemented in `execute_entry`, wired from Node
  as an optional `maxOpenPositions` field (default unlimited, no behavior change for existing
  sessions). Chaos sessions deliberately not wired (safe default, no UI control added — out of
  1b's minimal scope).
- **Docs drift fix**: found and fixed 3 files (`CURRENT_STATE.md`, `API_CONTRACTS.md`,
  `strategy-management/SPEC.md`) still describing in-app strategy code editing as live — it was
  removed outright by Plan 3 Step 3.2 earlier this session and the docs were never updated for
  it. All three corrected.

**Verification state at session end:** engine suite 127/127 passing (started this session's
final stretch at 108, +19 across 5.1/20/12). Golden master confirmed inert everywhere it
mattered — every touched file this final stretch was either live-adapter-only (zero backtest
overlap, same reasoning as 5.2/5.4) or a default-off/dead-code-path addition. Server files
verified to load/parse cleanly (`node -e "require(...)"` inside the container). **No live
Docker Compose watch was active this session — all container verification was done via
`docker cp` + in-container checks, not a rebuild.** If resuming with `docker compose up -d` or
`build`, remember the standing lesson: rebuild before any recreate, or freshly-written
source/test files vanish (engine has `volumes: []`).

**Next session — pick up in this order:**
1. **Plan 5 remaining: 5.3 (verify `execute_flip`'s idempotency is adequately covered by
   delegating to the now-idempotent `execute_entry`/`execute_exit` — not independently verified;
   `execute_reduce` still has no client id, low priority as it's dead code), 5.5 (Decimal
   money — the largest, riskiest remaining piece, budget real dedicated time, needs a documented
   golden-master re-baseline with sign-off per Rule C, do NOT rush this), 5.6 (restart recovery —
   depends on 5.1, now unblocked, but 5.1 only shipped the log+fold function, not the
   "LiveSession becomes a pure projection" work 5.6 actually needs — that projection work may
   need to happen as part of 5.6 itself, not before it).**
2. **Phase 9 remaining: Plan 13 (informative/multi-timeframe `self.htf()` contract — genuinely
   new feature work, not an audit-fix; scoped in `13_informative-multi-timeframe.md`), 14
   (webhooks), 15 (data CLI), 17 (recursive-formula/warmup analysis, sequence after 13).** All
   independent of Plan 5 and each other — can run in parallel with anything.
3. Plans 6/7/8 remain blocked on Plan 5 fully shipping (not just 5.1/5.2/5.4).

**Open questions (carried forward, see each plan file for full context):** who signs off
golden-master re-baselines for output-changing steps (9.4/9.7/9.8, 5.5); keep or delete
`IcebergAlgorithm`; **local dev vs. production sharing one MongoDB Atlas cluster** — still
unresolved structurally, only worked around per-incident so far; if strategy code-editing is
ever wanted again it needs a fresh sandboxed design (nothing to re-enable, 3.2 removed the
endpoint outright); Redis auth and the dead `.env` `BINANCE_*` lines are explicit follow-ups for
whoever picks up Plan 4 fully or does a dedicated infra-hardening pass; event log store choice
(Mongo, shipped, vs Timescale, considered) — Mongo was used for 5.1, revisit only if volume
becomes a real concern.

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
