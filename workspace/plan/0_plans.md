# 0 — Plans Index

Master catalog for everything we intend to build in Enma. This folder is a **planning
workspace only** — nothing here is implemented by writing it here. Implementation happens
in a separate session against a chosen plan.

Companion file: [`0_tracker.md`](0_tracker.md) — the live status board (one row per plan).

---

## How this folder works

One flat folder, four file families (the former `refinements/` subfolder was dissolved into
these on 2026-07-14 — mapping below):

- **`0_*.md`** — meta: **`0_plans.md`** (this file — the catalog: what each plan is, one
  paragraph each, plus how plans relate), **`0_tracker.md`** (the board: ID, status, priority,
  dependencies, phase), **`0_roadmap.md`** (the phased execution blueprint: Phases 0–8 over
  the plans, with per-step objective/implementation/verification), **`0_fixes-queue.md`** (the
  punch-list: the small, independent, ship-any-time items pulled out of the plans and sequenced to
  close one by one — with an explicit "not small, stays in the roadmap" carve-out).
- **`N_<slug>.md`** — one plan per file. Numbered by creation order, not priority.
  Priority lives in the tracker, so a plan can be reprioritised without renaming the file.
- **`audit_*.md`** — evidence: issue catalogs with IDs, severities, confidence tags. Plans
  cite these; they are never edited to match a plan (fix the plan instead).
- **`research_*.md`** — reference: descriptive baseline + external research that informed the
  plans. Read-mostly.

### Plan file naming

`N_<kebab-slug>.md` — e.g. `1_public-access-admin-gating.md`. The number is a stable ID; it
never changes once assigned (even if the plan is deprecated). Slugs may be refined.

### Reference shelf (audits & research)

| File | Was (pre-2026-07-14) | Contents |
|------|----------------------|----------|
| [`audit_1_system-design.md`](audit_1_system-design.md) | `issues.md` | System/SOLID/security audit — SEC-1..10, ENG-1..18, SRV-1..5, CLI-1..3, SYS-1..7. Feeds plans 2–8. |
| [`audit_2_quant-core.md`](audit_2_quant-core.md) | `refinements/05_algotrading_deep_dive.md` | Quant-core audit — QNT-1..17 + methods research. Feeds plans 9–10. |
| [`research_1_project-outline.md`](research_1_project-outline.md) | `refinements/01_project_outline.md` | Descriptive architecture baseline (what exists, mapped). |
| [`research_2_market-survey.md`](research_2_market-survey.md) | `refinements/02_market_research.md` | How NautilusTrader/Hummingbot/Freqtrade + industry build each component. |
| [`research_3_gap-analysis.md`](research_3_gap-analysis.md) | `refinements/03_better_options.md` | Gap analysis + evaluated options (incl. the §0 multi-tenant reframing decision). |
| [`0_roadmap.md`](0_roadmap.md) | `refinements/04_improvement_roadmap.md` | Phased blueprint, rewritten to cover plans 1–10 (Phases 0–8). |

Shorthand references inside these docs (e.g. "02 §10") refer to the old series numbers per
this mapping. The number inside the prefix (`audit_1_`, `research_2_`, …) is **reading order
within that shelf**, not implementation order — implementation order lives only in
`0_tracker.md`/`0_roadmap.md`.

### Plan lifecycle / statuses

| Status | Meaning |
|--------|---------|
| `Draft` | Rough idea captured, not yet fleshed out. |
| `Ready` | Scoped enough to hand to an implementation session. |
| `Blocked` | Waiting on a dependency or a decision. |
| `Shipped` | Implemented and merged. Kept for reference. |
| `Verify` | Believed implemented but not confirmed against the running stack. |
| `Merged→N` | Folded into plan N; this file is a stub pointer. |
| `Split→N,M` | Broke into plans N and M; this file is a stub pointer. |
| `Dropped` | Decided against. Kept so we don't re-propose it. |

### My standing job in this folder

Arrange, rearrange, merge, and split plans as they accumulate. Concretely:
- Keep `0_tracker.md` in sync whenever a plan is added, restatused, merged, or split.
- When two plans overlap, merge them (winner keeps its number; loser becomes a `Merged→N` stub).
- When one plan grows two independent halves, split it (`Split→N,M` stub + two new files).
- Surface conflicts and ordering (dependencies) rather than letting plans drift.

---

## Catalog

### 1 — Public access + admin-gated algo/testnet-start
[`1_public-access-admin-gating.md`](1_public-access-admin-gating.md) · **Shipped**

Open login to anyone with a Google account. Everyone can view the Algo Trading page, Chaos
Mode, and the new-bots UI, enter testnet API keys, and place manual Trade orders. Only the
**start** actions (start a testnet algo session / Chaos) are gated to admin-granted users;
non-granted users hit an "invited users only / request admin access" message.

> Shipped via commits `ddce1c1` / `efa8cd5` (open login + per-user `requireAlgoAccess` +
> admin user table + Settings request flow). Kept for reference.

---

## Remediation program (plans 2–8)

Plans 2–8 are the remediation of the audit captured in [`audit_1_system-design.md`](audit_1_system-design.md). They are one
program, ordered by **dependency, not severity**, and meant to be implemented by separate
sessions in numeric order. Each plan file is self-contained (context, why-now, numbered steps
with per-step acceptance checks, phase acceptance criteria, open questions, handoff template).
The live board is [`0_tracker.md`](0_tracker.md).

### 2 — Safety net & guardrails
[`2_safety-net-and-guardrails.md`](2_safety-net-and-guardrails.md) · **Shipped 2026-07-15** · P0

Behaviour-neutral scaffolding every later plan needs: server + client test harnesses (there
are none today), fail-closed & versioned encryption (SEC-3), correlation IDs + structured
redacted logging (SYS-6), a CI gate that runs tests + golden-master (SYS-5), and a `/health`
that stops lying when a DB is down (ENG-13). Nothing else should start before this lands.

### 3 — Service-to-service trust
[`3_service-to-service-trust.md`](3_service-to-service-trust.md) · **Shipped 2026-07-15** · P0

Flips the inverted trust topology (SYS-1). Authenticates the `/internal/*` order routes
(SEC-1), closes the strategy-code RCE path (SEC-2 — carries a product decision), moves secrets
off custom headers (SEC-6), adds real tiered rate limiting (SEC-5), constant-time compares.

### 4 — Credential & config topology
[`4_credential-and-config-topology.md`](4_credential-and-config-topology.md) · **Mostly Shipped 2026-07-15 — residual: Redis `requirepass` (fixes-queue F8)** · P1

Implements the ".env → per-user Settings" directive: removes personal Binance credentials from
env/files (SEC-9), stops injecting the shared `.env` into every container incl. the client
(SEC-4), makes infra secrets rotatable, pins images and authenticates Redis (SEC-7).

### 5 — Live-trading state integrity
[`5_live-trading-state-integrity.md`](5_live-trading-state-integrity.md) · **In progress — 5.1 (scoped)/5.2/5.3/5.4 Shipped; 5.5 (Decimal) + 5.6 (restart recovery) remain** · P0

The deepest fix. Makes the exchange the single source of truth via an append-only event log
(SYS-2, SRV-3), books real fills instead of fabricated exit prices (ENG-2), adds order
idempotency (ENG-10), serializes per-symbol state to kill the reconcile/candle race (ENG-3),
and moves money math to Decimal (ENG-11). Mainnet must stay gated until this is Shipped.

### 6 — Engine decomposition & exchange abstraction
[`6_engine-decomposition-and-exchange-abstraction.md`](6_engine-decomposition-and-exchange-abstraction.md) · **Ready** · P2

Breaks up the 2,000-line `LiveBotManager` god class (ENG-1), introduces a real testnet/mainnet
`Exchange` abstraction to replace scattered `mode="testnet"` literals (ENG-4), a typed
strategy↔engine contract (ENG-6), fixes the leaky adapter (ENG-5), a reliable ordered Node
transport (ENG-16), and proper packaging without symlink/`sys.path` hacks (ENG-12). Behaviour-
preserving — golden-master is the contract.

### 7 — Server & client structure
[`7_server-and-client-structure.md`](7_server-and-client-structure.md) · **Ready** · P2

Structural cleanup of Node/React: controllers stop being 1,000-line god functions, long engine
calls become a job (BullMQ) instead of an hour-long HTTP hang, page components stop being
1,700-line monsters with 29 `useState` calls. Depends on 2 (test harness must exist first) and
5 (renders the new live-state model 5 introduces).

### 8 — Governance, correctness & cleanup
[`8_governance-correctness-and-cleanup.md`](8_governance-correctness-and-cleanup.md) · **Ready** · P3

Trailing correctness fixes (ENG-8/14/15/18, SEC-8 remainder/10) plus a doc-reconciliation pass
so `workspace/docs/` matches the shipped architecture instead of the "server only proxies"
fiction. Last in the hardening program — only makes sense once 3/5/6 have landed.

---

## Quant-core program (plans 9-10)

Plans 9-10 fix and extend the *simulation and research* half of the platform - backtest
correctness, the optimizer, and Monte Carlo robustness testing. Unlike 2-8 they don't depend on
the trust/state remediation program; Plan 9's P0 steps (9.1-9.3) run immediately and in
parallel with anything else. Source audit: [`audit_2_quant-core.md`](audit_2_quant-core.md).

### 9 — Backtest & optimizer correctness (quant core)
[`9_backtest-and-optimizer-correctness.md`](9_backtest-and-optimizer-correctness.md) · **Ready (9.1-9.3, 9.4, 9.5, QNT-15 Shipped)** · P0 (9.1-9.3) / P1 (rest)

Fixes shipped-behavior bugs invalidating results users act on today (QNT-1 multi-symbol exits
never firing, QNT-2 exec-algo erasing close/flip intents, QNT-17 leverage-sensitivity ignoring
the parent run's real params — all **Shipped 2026-07-15**), then a research-integrity tail:
entry-candle exits, a lookahead sentinel wired into CI, funding-ledger honesty, intrabar
simulation, fill-model realism. **9.6** (optimizer walk-forward/DSR/PBO/Optuna) is absorbed by
Plan 10 Phase 3 rather than built twice; **9.9**'s Monte Carlo portion is absorbed by Plan 10
Phase 1 (its statistics-honesty portion stays here).

### 10 — Monte Carlo Optimiser & Strategy Lab
[`10_monte-carlo-strategy-lab.md`](10_monte-carlo-strategy-lab.md) · **Ready (Phase 1a Shipped)** · P1

Rebuilds the currently-broken Monte Carlo/leverage feature into a job-based "Strategy Lab":
a vectorized block-bootstrap MC engine (**Phase 1a core math Shipped 2026-07-15**), job
plumbing (`labResults`, `simulationQueue`) to fix the synchronous-multi-minute-`GET`
anti-pattern (Phase 1b), a dedicated UI (Phase 2), and an honest optimizer surface — walk-
forward + Deflated Sharpe/PBO + Optuna TPE (Phase 3, absorbs Plan 9's 9.6) — plus MC-scored
parameter/sizing/leverage selection (Phase 4). Depends on Plan 9 steps 9.1/9.3 (both Shipped).

---

## Feature-gap program (plans 11-19)

Plans 11-19 port high-value features from freqtrade/nautilus_trader that Enma is missing -
identified in a parallel audit (`ref_gap-matrix-freqtrade-nautilus.md`) and originally staged in
a second spec directory (`workspace/next_phase/`), folded into this numbering on 2026-07-15
(see [`mergeContext.md`](mergeContext.md) for the mechanical move; **no re-plan** happened in
that move — the entries below are the first pass reconciling this program against plans 1-10
and shipped work). Ordering rule: **risk primitives first, validation tooling next, optimization
last.** Independent of the hardening program (2-8); can start any time after 11's V0 check.

### 11 — Current-state reconciliation (V0)
[`11_current-state-reconciliation.md`](11_current-state-reconciliation.md) · **Verified 2026-07-15 (complete — it was a verify-only gate)** · P2

A verify-only audit (2026-06-25): the Dashboard, Risk Dashboard, and Monte Carlo/leverage
features that an old, deleted `INDEX.md` claimed were "missing" turned out to already be built.
Run its checklist (golden master, dashboard/risk-dashboard rendering, MC endpoint smoke) before
starting 12-19 — it's the gate, not a build item.

### 12 — Max position per asset
[`12_max-position-per-asset.md`](12_max-position-per-asset.md) · **Shipped 2026-07-15 — 1a already shipped** · P2

Caps exposure per symbol (notional) and per session (concurrent open-position count), mirroring
freqtrade's `max_open_trades` / nautilus's per-instrument risk-engine caps. **Confirmed
2026-07-15: sub-item 1a (per-asset notional cap) is already live** —
`engine/core/strategy.py:353`'s `max_qty()` already clamps against `max_exposure_notional`,
wired from both `backtest_runner.py` and `live_bot_manager.py`. **1b** (session-level
`max_open_positions` count gate in `live_bot_manager.py`) shipped the same day.

### 13 — Informative / multi-timeframe contract
[`13_informative-multi-timeframe.md`](13_informative-multi-timeframe.md) · **Ready** · P2

Lets a strategy reference a higher timeframe (e.g. 1h trend filtering 5m entries) without
lookahead — an as-of-aligned, forward-filled `self.htf(timeframe)` helper built on the existing
`prepare()`/`before()` two-phase contract (porting freqtrade's `@informative` decorator idea,
Enma-native). Gate any strategy that uses it through Plan 9.5's lookahead sentinel.

### 14 — Webhook notifications
[`14_webhook-notifications.md`](14_webhook-notifications.md) · **Shipped 2026-07-16 (fixes-queue F3)** · P2

POSTs a JSON payload to a per-user-configured URL on trade lifecycle events (entry/exit/
liquidation/session start-stop-error) — Discord/Slack/IFTTT integration, freqtrade-payload-
shape-compatible. Server-only, no engine/pipeline touch, no golden master. Scoped per-user via
`Settings` (its original single-global-config premise predates multi-user auth and was revised).

### 15 — Data conversion CLI
[`15_data-conversion-cli.md`](15_data-conversion-cli.md) · **Shipped 2026-07-16 (fixes-queue F4)** · P3

A thin `engine/scripts/enma_cli.py` (stdlib-only) to export/import candles and backtest trades
between TimescaleDB/Mongo and CSV/JSON flat files, plus a `list-data` inventory command — for
offline analysis and reproducible datasets. Must run inside Docker (Rule B); never calls Binance
directly (local-data tool only).

### 16 — Lookahead-bias analysis
[`16_lookahead-analysis.md`](16_lookahead-analysis.md) · **Merged→9**

Proposed a per-trade truncated-array diff to detect future-leaking strategies. **Superseded by
Plan 9 step 9.5** (Shipped 2026-07-15), which already implements the same core technique —
expanding-window `prepare()` recompute diffed against the full-array run — as a whole-strategy
CI gate covering all 5 seeded strategies. This file's narrower per-trade, per-indicator-column
bias report is still useful as a **diagnostic** if the 9.5 sentinel ever flags a strategy (it
localizes *which* column leaked); keep it as reference, don't build it as new work now.

### 17 — Recursive-formula analysis
[`17_recursive-analysis.md`](17_recursive-analysis.md) · **Ready** · P2

Distinct from 16: detects indicators whose value drifts with warmup length (EMA/RSI/SuperTrend —
recursive formulas), answering "is the live rolling 500-candle window long enough?" This is a
real, unaddressed gap (not covered by anything shipped this session) and the most likely tool to
catch an actual live/backtest divergence given the live path's rolling-window replay design.

### 18 — Walk-forward analysis
[`18_walk-forward-analysis.md`](18_walk-forward-analysis.md) · **Merged→10**

Proposed a standalone fold-based train/test orchestration layer with its own synchronous
`POST /optimize/walk-forward` endpoint and a new `walkForwardResults` collection. **Conflicts
architecturally with Plan 10 Phase 3**, which already scopes walk-forward as part of the
job-based Strategy Lab (`labResults`, `/api/v1/lab/optimizations`) — building this file's
standalone sync endpoint would create a surface Phase 3 immediately has to retire. Keep this
file's fold-math design (train/test split, anchored-vs-rolling, OOS-stitching) as **input to
Plan 10 Phase 3's implementation**, not a separate build.

### 19 — Bayesian hyperopt (Optuna)
[`19_bayesian-hyperopt.md`](19_bayesian-hyperopt.md) · **Merged→10**

Proposed replacing grid search with Optuna TPE sampling directly in `optimizer.py`, gated behind
a `method` param on the existing sync `/optimize` endpoint. **Same conflict as 18**: Plan 10
Phase 3 already specifies Optuna as the Strategy Lab's search engine. Keep this file's
search-space adapter design (`trial.suggest_*` mapping from the existing `param_grid` spec) and
ask/tell-vs-executor async note as **input to Plan 10 Phase 3**, not a separate build.

### 20 — Binance precision/notional parity (DCA scale-out)
[`20_binance-precision-notional-parity.md`](20_binance-precision-notional-parity.md) · **Shipped 2026-07-15**

Not part of the original 11–19 catalog — opened and shipped same-day from a user-requested audit
(Binance UI vs Enma precision/min-notional handling). Found one real gap: DCA scale-out
(`execute_reduce`) never floored quantity to the symbol's `stepSize`, unlike every other
order-placement path — closed by adding a `reduce_only` mode to `clamp_and_round_qty()`. Also
closed a related Plan 5 Step 5.3 (ENG-10) gap found in the same pass: `execute_entry` had no
order-idempotency handling and never booked the real fill price on success.

### 21 — Live algo industry-standard audit (fill path, brackets, kill-switch)
[`21_live-algo-industry-standard-audit.md`](21_live-algo-industry-standard-audit.md) · **Draft (audit complete 2026-07-16, fixes unstarted)**

Full read-through audit of the live trading path (signals → orders → SL/TP → fill detection →
reconciliation → stop) against industry-standard failproof expectations. 14 findings (A-1…A-14),
headlined by three `[Certain]` critical/high defects that are the likely root causes of F7 item 1:
the `userTrades` real-exit reconstruction call is missing its credential arguments (dead since
Plan 5.2 shipped), the user-data-stream `_on_fill` callback crashes with `AttributeError` on
every FILLED frame (event-driven reconcile is dead code), and `LISTEN_KEY_EXPIRED` permanently
kills the stream. Plus: no close path cancels resting `closePosition:true` SL/TP conditionals
(live wrong-money hazard on symbol re-entry), emergency-exit fabricates its close and can leave
a naked position, no naked-position detector, `ACCOUNT_UPDATE` ignored, no 429/weight handling,
no automatic session-level drawdown kill-switch. 7-step remediation plan (21.1–21.7), all
live-adapter-only, no golden-master impact; 21.1/21.2 are the designated F7 follow-up work.

### 22 — Industry-standard risk management (Session Risk Governor)
[`22_risk-management-industry-standard.md`](22_risk-management-industry-standard.md) · **Ready (scope decided 2026-07-16, unstarted)**

Consolidates and refines the scattered risk-management plans (`ref_gap-matrix` §1.6,
`ref_future-paths` Track D + forks #2/#3, Plan 12 continuation, Plan 21's A-10/A-11) into one
architecture: an engine-side **Session Risk Governor** with pre-trade + periodic checks —
aggregate session drawdown auto-kill-switch, daily loss limit, true cross-symbol open-risk budget
(the existing `max_portfolio_risk` is per-symbol despite its name), margin-utilization ceiling,
**enforced** live VaR/CVaR limits (user decision — Zone 1 graduates from display-only),
correlation-aware concentration caps, and a config-gated inverse-volatility allocation layer
(fork #3 = yes; fork #2 = rule-based only, no GARCH/ML). Also found: `liq_buffer_pct` is
decorative today (`respects_liq_buffer()` has no pipeline call site). 7 steps; 22.1 absorbs Plan
21's step 21.6; depends on Plan 21's 21.1–21.4 fill-path fixes landing first. Only 22.6
(allocation) is golden-master-gated (config default `equal` keeps backtests byte-identical).
**2026-07-16 addendum:** Plan 21 gained Part A2 — a five-model pipeline audit (M-1…M-6):
the "default-on" cost gate has never fired (injected onto `cost_model`, read from
`portfolio_model` — M-1), its formula is dimensionally inconsistent (M-2), `Signal.magnitude`
is dead (M-3), trailing stops never amend the exchange SL order (M-4), and entries proceed with
invalid brackets (M-5). Fixes routed: M-1/M-2/M-3 → new Plan 9 step 9.11 (Step A inert, Step B
re-baselined); M-4/M-5 → 21.4; M-6 → 22.6. `CURRENT_STATE.md`'s false "cost gate active" claim
corrected same day.

### 23 — New strategy: high-risk/high-leverage breakout scalper ("MarginSurge")
[`23_high-risk-leverage-strategy.md`](23_high-risk-leverage-strategy.md) · **Draft (design only, 2026-07-16)**

User-requested high-risk strategy plan. Reframes the "fixed high returns" ask honestly (leverage
scales both tails; the plan's §6 gates are allowed to kill the strategy). Design: 5m/15m
volatility-compression Donchian breakout with ADX/MFI/EMA-200 confirmation and the AtrBracket
ATR-percentile filter; 0.75×ATR stop, 2R take-profit, breakeven at 1R, 1×ATR trail, 24-candle
time stop; leverage (20–50x) selected by leverage-sensitivity + Monte Carlo ruin curves, not
assumed; sizing `risk_pct` 3–5%; margin-heavy = max concurrent positions + high utilization
under the (future) 22.1 governor ceiling. Uses only existing models/indicators. Backtest gates
startable now; live phase hard-gated on 21.1–21.4 (fill path + M-4 trailing) and soft-gated on
22.2 (liq-buffer wiring — currently decorative, B-1).

### 24 — BestSupertrend fixes (never trades at defaults)
[`24_bestsupertrend-fixes.md`](24_bestsupertrend-fixes.md) · **Ready (audited 2026-07-16)** · P1

User-reported "never generates trades" — confirmed and root-caused: at the platform's own
defaults (`defaultLeverage: 1`, strategy `position_size_pct: 1.0`), required margin =
equity×(1+slippage) > balance, so `EntryFill.affordable()` rejects **every** entry in backtest
(one hidden log line) and Binance rejects with `-2019` in live. Four more `[Certain]` flaws:
live HTF supertrend is one full HTF bar staler than backtest (`tsl[-2]` on an array that
already excludes the open bar); unsatisfiable tf/timeframe combos (weekly/monthly on ≤4h base,
or any HTF-fetch failure on sub-1h base) silently produce zero trades forever instead of
failing loud; the `order_type` param name collides with `OrderPlan.order_type` via
`DefaultExecution.route()`'s getattr; docs claim `SignalExitRiskModel` while code binds
`AtrBracketRiskModel`. Fix order S-1→S-5; S-1/S-2 need a (cheap) BestSupertrend golden
re-baseline; live verification gated on 21.1–21.2.
