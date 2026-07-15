# 0 — Plan Tracker

Live status board. One row per plan. Catalog + conventions live in [`0_plans.md`](0_plans.md);
the phase column maps to [`0_roadmap.md`](0_roadmap.md) (Phases 0–9).

Statuses: `Draft` · `Ready` · `Blocked` · `Verify` · `Shipped` · `Merged→N` · `Split→N,M` · `Dropped`
(defined in `0_plans.md`).

| ID | Title | Status | Priority | Phase | Depends on | Related | Updated |
|----|-------|--------|----------|-------|------------|---------|---------|
| 1  | Public access + admin-gated algo/testnet-start | Shipped | — | — | — | — | 2026-07-14 |
| 2  | Safety net & guardrails | Shipped | P0 | 1–2 | — | 3,4,5 | 2026-07-15 |
| 3  | Service-to-service trust | Shipped | P0 | 1–2 | 2 | 4,8 | 2026-07-15 |
| 4  | Credential & config topology | Mostly Shipped (4.5 partial) | P1 | 1 | 2,3 | 8 | 2026-07-15 |
| 5  | Live-trading state integrity | In progress (5.1 scoped, 5.2, 5.4 shipped) | P0 | 3 | 2,3 | 6 | 2026-07-15 |
| 6  | Engine decomposition & exchange abstraction | Ready | P2 | 4, 6.1 | 5 | 7 | 2026-07-14 |
| 7  | Server & client structure | Ready | P2 | 5 | 2,5 | 6 | 2026-07-14 |
| 8  | Governance, correctness & cleanup | Ready | P3 | 6 | 3,5,6 | all | 2026-07-14 |
| 9  | Backtest & optimizer correctness (quant core) | Ready (9.1–9.5, QNT-15 Shipped) | P0 (9.1–9.3 done) / P1 (rest) | 0 + 7 | — (9.1–9.3); 2 (9.5+) | 5,6,8,16 | 2026-07-15 |
| 10 | Monte Carlo Optimiser & Strategy Lab | Ready (Phase 1a shipped) | P1 | 8 | 9 (9.1, 9.3) | 2,7,18,19 | 2026-07-15 |
| 11 | Current-state reconciliation (V0) | Verified | P2 | 9 | — | 12–19 | 2026-07-15 |
| 12 | Max position per asset | Shipped | P2 | 9 | 11 | 6 | 2026-07-15 |
| 13 | Informative / multi-timeframe contract | Ready | P2 | 9 | 11 | 16,17 | 2026-07-15 |
| 14 | Webhook notifications | Ready | P2 | 9 | 11 | — | 2026-07-15 |
| 15 | Data conversion CLI | Ready | P3 | 9 | 11 | — | 2026-07-15 |
| 16 | Lookahead-bias analysis | Merged→9 | — | — | — | 9 (9.5), 13 | 2026-07-15 |
| 17 | Recursive-formula analysis | Ready | P2 | 9 | 11, 13 | 16 | 2026-07-15 |
| 18 | Walk-forward analysis | Merged→10 | — | — | — | 10 (Phase 3) | 2026-07-15 |
| 19 | Bayesian hyperopt (Optuna) | Merged→10 | — | — | — | 10 (Phase 3), 18 | 2026-07-15 |
| 20 | Binance precision/notional parity (DCA scale-out) | Shipped | P1 | 9 | — | 5, 9 | 2026-07-15 |

---

## Execution order

Plans 2–8 are the remediation of the audit in [`audit_1_system-design.md`](audit_1_system-design.md), sequenced by
**dependency, not severity**. Work them in numeric order; a later plan may run in parallel with
an earlier one only where the `Depends on` column allows (e.g. Plan 4 config work and Plan 5
state work touch different files). Rationale for the ordering is in each plan's "Why this is
first / Why now" section, and summarized: verification scaffolding (2) → close the two worst
security holes (3) → move secrets to per-user settings (4) → fix live-trading state integrity
(5) → restructure the engine that implements it (6) → restructure server/client (7) →
reconcile docs and close trailing correctness gaps (8).

The quant track (9, 10) runs **in parallel** with the hardening track — Phase 0 (9.1–9.3)
should start immediately; see `0_roadmap.md` for the two-track sequencing and per-phase gates.

The feature-gap track (11–19) runs **in parallel** with both — it touches neither the trust/
state remediation surface nor the quant simulation core, only additive engine/server features.
Start with 11 (verify-only gate), then 12/13/14/15/17 in any order; 16/18/19 are stubs (see
Notes) and are not separately scheduled.

**Session protocol:** pick the lowest-numbered plan not `Shipped` on your track (hardening:
2→8; quant: 9→10; feature-gap: 11→17, skipping merged stubs 16/18/19), set it to a working
status, follow its Steps in order, meet its Acceptance criteria, then update this row and write
a resume note to `handoff.md` (CLAUDE.md Rule G).
Never mark `Shipped` without the phase Acceptance criteria and (for pipeline-touching steps)
a golden-master check per Rule C.

## Notes

- **1** — Shipped via commits `ddce1c1` / `efa8cd5` (open login, per-user `requireAlgoAccess`,
  admin user table, Settings request flow). Kept for reference.
- **2** — Shipped 2026-07-15. Server/client test harnesses (39 + 11 tests), fail-closed
  encryption (required an unplanned credential migration — see plan file for the shared-
  production-database discovery), correlation IDs + pino logging, honest engine `/health`, CI
  (`.github/workflows/ci.yml` + `docker-compose.ci.yml` + `.env.ci`). Full detail + deviations
  in `2_safety-net-and-guardrails.md`'s "Shipped summary". **Flagged follow-up before Plan 4:**
  local dev shares production's MongoDB Atlas cluster — decide whether to give local dev its
  own database.
- **3** — Shipped 2026-07-15. Closed the RCE strategy-code path (removed, confirmed dead code
  client-side) and authenticated `/internal/*` (distinct shared secret, constant-time compare
  both directions), tiered Redis-backed rate limits. Full detail in
  `3_service-to-service-trust.md`'s "Shipped summary" — includes a self-inflicted crash-loop
  incident during the step, root-caused and fixed before moving on.
- **4** — Mostly shipped 2026-07-15. Headline finding: the ".env → per-user Settings" directive
  was **already fully satisfied** before this plan — every `BINANCE_*` env var was dead code.
  Scoped each container's env (client now gets zero secrets — was getting everything);
  `ENCRYPTION_KEY` rotation window implemented + tested. **Not done: Redis `requirepass`**
  (deferred, see plan file) and **`.env`'s 7 dead `BINANCE_*` lines** (permission system
  blocked autonomous deletion — needs the user's explicit go-ahead in a future turn). Full
  detail in `4_credential-and-config-topology.md`'s "Shipped summary".
- **5** — Highest-value correctness work: exchange as source of truth for live trading state,
  replacing the current three-way-divergent (exchange / engine memory / Mongo) reconciliation
  heuristics. Do not promote to mainnet before this is `Shipped`. 2026-07-15: **5.2 (ENG-2, real
  fills not fabricated closes) and 5.4 (ENG-3, per-symbol state lock) shipped** — both live-
  tested against real testnet sessions; **5.1 (SYS-2, execution event log) shipped in scoped
  form** — append-only `executionEvents` collection, engine writes at every state-mutating site,
  Node-side seq-ordering guard, and a tested `fold_events()` replay function satisfying the
  step's stated acceptance check. Scoped down from the full spec: `LiveSession`/engine memory
  are not yet *pure* derived views of the log (still the live read path) — that projection is
  Step 5.6, now unblocked. See `5_live-trading-state-integrity.md` for full detail. 5.3 (full
  order idempotency), 5.5 (Decimal money), 5.6 (restart recovery) remain — 5.5 in particular
  needs a deliberate golden-master sign-off, not a same-day rush.
- **6** — Structural cleanup of the live engine: `LiveBotManager` stops being a 2,000-line god
  class; live/backtest/mainnet vary behind a real exchange abstraction instead of `is_live`
  flags. Comes after 5 so the correctness model is settled before the code moves.
- **7** — Structural cleanup of Node/React: controllers stop being 1,000-line god functions,
  long engine work becomes a job not an HTTP hang, page components stop being 1,700-line
  monsters. Depends on 2 (tests must exist first) and 5 (render the new state model).
- **8** — Trailing correctness fixes (ENG-8/14/15/18, SEC-8 remainder/10) + doc reconciliation
  to the shipped architecture. Last because it only makes sense once 3/5/6 have landed.
- **9** — Quant-core correctness (see `audit_2_quant-core.md`). Steps 9.1–9.3 (QNT-1 multi-symbol
  exit-check, QNT-2 exec-algo close/flip erasure, QNT-17 run-config persistence for leverage
  sensitivity) **Shipped 2026-07-15** — see `handoff.md`. Steps 9.4–9.10 remain `Ready`; several
  change backtest outputs by design and need a golden-master re-baseline with sign-off (Rule C)
  before landing.
- **10** — Job-based Monte Carlo + Optimizer Strategy Lab. Hard-depends on 9.1/9.3, both
  shipped. 2026-07-15: **MC engine core rewritten** (vectorized block bootstrap, QNT-7/QNT-14
  fixes) — the math is now honest, but it's still behind the old synchronous endpoint (SRV-5 not
  fixed) and nothing else in the plan (job queue, `labResults`, Strategy Lab UI, optimizer
  exposure) has started. See `10_monte-carlo-strategy-lab.md`'s scoped-delivery note. Its
  Phase 3 (optimizer exposure) absorbs 18 and 19 — see those entries below.

- **11–19** — Feature-gap program, ported from `workspace/next_phase/` on 2026-07-15 (mechanical
  move by a separate concurrent session, see `mergeContext.md`; this reconciliation pass against
  0–10 and shipped work is 2026-07-15, same day). Independent of the hardening program; gated
  only by 11's V0 verification checklist. Ordering: 11 → 12/13/14/15/17 (additive, any order
  after 11) → nothing else, since 16/18/19 are merged elsewhere.
- **11 — Verified 2026-07-15**, live via browser against the running stack (real testnet account,
  3 open positions untouched — read-only checks). All 4 checklist items confirmed: (1) Dashboard
  renders live-data stat strip + Recent Live Runs/Backtests/Leaderboard correctly, but
  **confirmed (not new) that `DashboardCalendar.jsx`/`EquitySparkline`/`DrawdownSparkline` are
  NOT composed into `Dashboard.jsx`** — this matches `client/CLAUDE.md`'s own existing note that
  `DashboardCalendar` is "currently unused... candidate for removal or wiring in a future pass";
  not a new gap, just confirmed still true, no action taken (not urgent — the KPI strip already
  covers the numeric content, only the visual sparkline/calendar surface is missing). (2) Risk
  Dashboard loads with real live margin/exposure/correlation data and settings panels render.
  (3) `resolveStrategyRiskParams` confirmed wired into both `algo.controller.js` and
  `backtest.controller.js` (has its own test file too) — the resolver-integration concern Plan 11
  flagged is resolved, it's live. (4) Monte Carlo/leverage-sensitivity **has a real UI surface**
  (Risk Dashboard's "Backtest & Historical Risk Profiler" section) and returns real computed
  numbers when a backtest is selected — confirmed the `N=5000` default from this session's Plan
  10 Phase 1a MC rewrite is live in production. No gaps found worth a punch-list item beyond the
  already-documented sparkline/calendar non-wiring.
- **12 — Shipped 2026-07-15.** 1a confirmed pre-existing (`max_qty()`/`max_exposure_notional`,
  `engine/core/strategy.py:353`). 1b (session-level `max_open_positions` count gate)
  implemented: `execute_entry()` blocks new symbols once the session is at its configured cap
  (only new symbols, never one already counted), wired from Node's `startSession` as an optional
  `maxOpenPositions` field (default unlimited). Chaos sessions not wired (safe default, no clear
  single-cap semantic for chaos yet). No UI control added — out of 1b's scope. See
  `12_max-position-per-asset.md`'s Shipped summary.
- **13** — New `self.htf(timeframe)` strategy contract (as-of aligned, no lookahead by
  construction). Gate any strategy that adopts it through 9.5's already-shipped lookahead
  sentinel — no new CI needed, just run it.
- **14** — Independent, server-only, no golden master. Ship any time.
- **15** — Independent CLI, stdlib-only, no golden master. Ship any time.
- **16 — Merged→9.** Proposed a per-trade truncated-array lookahead diff; **superseded by 9.5**
  (Shipped 2026-07-15), which already does the same core check (expanding-window `prepare()`
  vs full-array, diffed) as a whole-strategy CI gate. Keep 16's per-column bias-report design as
  a diagnostic to build **only if** the 9.5 sentinel ever actually flags a strategy — not new
  work now. Also relevant once 13 ships (validates `htf()` alignment).
- **17** — Distinct from 16 (insufficient warmup, not future leakage). Real, unaddressed gap —
  most likely tool to catch a genuine live/backtest divergence given the live path's rolling
  500-candle replay window. Sequence after 13 (sweeps multi-TF indicators too).
- **18 — Merged→10.** Proposed a standalone synchronous `POST /optimize/walk-forward` +
  new `walkForwardResults` collection. **Architectural conflict** with Plan 10 Phase 3, which
  already scopes walk-forward inside the job-based Strategy Lab (`labResults`,
  `/api/v1/lab/optimizations`) — building 18 as specified would create a surface Phase 3 has to
  retire immediately. Its fold-math design (train/test split, anchored vs rolling, OOS
  stitching) is good input **for** Phase 3's implementation, not a separate build.
- **19 — Merged→10.** Same conflict as 18 — Phase 3 already specifies Optuna TPE as the search
  engine. Keep 19's `trial.suggest_*` search-space adapter design and async ask/tell note as
  input to Phase 3, not a separate build.
- **20 — Shipped 2026-07-15, same day as opened.** Not part of the original 11–19 catalog — a
  user-requested audit (Binance UI precision/min-notional screenshots vs Enma's implementation)
  found one real gap: DCA scale-out (`execute_reduce`) never floored qty to the symbol's
  `stepSize`, a genuine live-order-rejection risk once any strategy implements
  `adjust_trade_position()` (none do yet — confirmed dead code today, hence low urgency despite
  P1). Fixed same session: `clamp_and_round_qty(..., reduce_only=True)` in both adapters. Found
  and fixed a related gap in the same pass: `execute_entry` had no order-idempotency handling
  (Plan 5 Step 5.3, ENG-10) and never booked the real fill price on a normal entry — both fixed.
  See `20_binance-precision-notional-parity.md`'s "Shipped summary".