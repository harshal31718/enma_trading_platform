# Plan 9 — Backtest & optimizer correctness (quant core)

**Status:** Ready (9.1–9.3 Shipped 2026-07-15) · **Priority:** P0 (steps 9.1–9.3, done) / P1 (rest) · **Depends on:** — (9.1–9.3); 2 (CI for 9.5+) · **Related:** 5, 6, 8

> Source audit: [`audit_2_quant-core.md`](audit_2_quant-core.md)
> (issues QNT-1..17). This plan fixes the *simulation and research* half of the platform the
> way Plan 5 fixes the *live execution* half. Unlike plans 2–8 it does not depend on the
> trust/state remediation program — steps 9.1–9.3 are shipped-behavior bug fixes and can run
> immediately and in parallel with any other plan.

## The uncomfortable part

Every multi-symbol backtest result currently stored is structurally invalid (QNT-1: SL/TP/
liquidation/funding never fire after the first entry), and every leverage-sensitivity chart
was computed with default strategy params, not the parent run's (QNT-17). Users are making
strategy and leverage decisions from these numbers today. That makes 9.1–9.3 P0 even though
no live money path is touched.

## Goal

Backtest results are correct on all shipped paths (multi-symbol, exec-algo, funding),
reproducible (full config persisted), and honest (out-of-sample optimizer reporting,
overfitting-aware statistics, tail-preserving Monte Carlo). Live and backtest produce the same
signals from the same data, verified mechanically, not by assertion.

## Steps

### 9.1 — Multi-symbol exit-check fix (QNT-1) — P0 — **Shipped 2026-07-15**
- Clear `_entered_this_candle` per candle in `_run_shared_portfolio` (minimal), then move the
  flag into the kernel loop as local state (structural). Run `update_pnl`/funding/excursion
  updates in the portfolio path.
- Done: `_run_shared_portfolio` now calls `adapters[sym].record_equity(strategy, time_t)` after
  `evaluate_and_route` each candle (`services/backtest_runner.py`) — the minimal fix (structural
  move deferred, not required for correctness). Acceptance verified: new deterministic kernel-
  level test `tests/test_multi_symbol_portfolio_exits.py` drives `_run_shared_portfolio` with 2
  synthetic symbols and asserts both exit via `stop_loss` and the cash-conservation invariant
  (`final == capital + Σ trade pnl`, fees/slippage/funding zeroed for a clean assertion) holds
  exactly. Live-data confirmation: a 2-symbol (BTCUSDT+ETHUSDT) golden-master run
  (`multi_symbol_baseline_post_fix`) now shows real `stop_loss`/`take_profit` exit reasons
  (previously impossible). Single-symbol golden master (`pre_qnt1_2_3_baseline` vs
  `post_qnt1_2_3_fix`) is byte-identical — confirms no behavior change on the existing path.
- Migration note: checked `backtestResults` for `symbol` containing "," — **none exist** in
  this environment, so no stale-flagging migration was needed. Re-check before any production
  data migration.

### 9.2 — Exec-algo close/flip pass-through (QNT-2) — P0 — **Shipped 2026-07-15**
- Snapshot `_close_at_open`/`_pending_flip` before the kernel's exec-algo clear; route exits
  and flips unsliced (per the algos' own contract).
- Done: `core/kernel.py` `evaluate_and_route` snapshots both attributes before the exec-algo
  clear and restores them right after `process_order_plan`/`step` runs. Two new regression
  tests in `tests/test_exec_algo_slicing.py`
  (`test_twap_close_at_open_survives_exec_algo_clear`,
  `test_twap_pending_flip_survives_exec_algo_clear`) assert the intent survives the clear and
  `execute_exit`/`execute_flip` actually fire on the next candle. Existing TWAP/Iceberg
  full-fill tests still pass (full suite: 84/84 green).

### 9.3 — Persist run config; fix leverage sensitivity (QNT-17) — P0 — **Shipped 2026-07-15**
- `run_backtest_simulation` persists `alphaParams`, `riskParams`, `slippagePct`,
  `fundingEnabled`, `fundingRate` into `backtestResults`; `leverage_sensitivity_runner` reads
  them back.
- Done: `services/backtest_runner.py`'s `backtestResults` write now includes all five fields
  (`leverage_sensitivity_runner.py` already read them via `parent.get(...)` — it was written
  against this contract from the start, the fields were simply never persisted). No runner
  change needed.

### 9.4 — Entry-candle exit evaluation (QNT-3) — **Shipped (opt-in) 2026-07-15**
- Opt-in flag: evaluate SL/TP/liquidation against the entry candle (entry at open → exits
  checked on that candle's range). Golden-master re-baseline with sign-off when made default.
- Done: `ExecutionKernel.__init__` gained `entry_candle_exits: bool = False`; `check_exits`'s
  `_entered_this_candle` early-return now also requires `not self.entry_candle_exits`. Threaded
  through `run_backtest_simulation`'s new `entry_candle_exits` parameter (default False, wired
  into the kernel construction site). 4 new kernel-level tests
  (`tests/test_entry_candle_exits.py`) cover: default-off preserves the existing skip, opt-in
  evaluates and fires SL on the entry candle, no-op when the candle isn't actually the entry
  candle, and live is never affected regardless of the flag. Full suite 88/88. Golden-master
  default-path determinism re-confirmed (two same-container runs byte-identical) — **not** a
  true before/after diff against the pre-9.4 code, because the pre-9.4 baseline file was lost to
  the container-recreation issue noted under 9.5; the change is provably a default-off additive
  parameter by inspection, and the dedicated kernel tests cover the actual logic.
- **Still not done, and this is the real remaining work**: this ships the mechanism only, not
  the feature. Nothing sets `entry_candle_exits=True` anywhere (no Settings field, no API
  parameter, no UI toggle) — it's reachable only by calling `run_backtest_simulation` directly
  with the kwarg, same as `_reprep_every_candle`. **Making it a real user-facing default requires
  the golden-master re-baseline + sign-off this step was always going to need** — that hasn't
  happened, and shouldn't happen casually; it changes every backtest's numbers.

### 9.5 — Lookahead sentinel in CI (QNT-12, detector for QNT-9) — **Shipped 2026-07-15**
- Harness: full-array `prepare()` vs per-candle expanding-window recompute; assert identical
  trade lists for all seeded strategies. Wire into CI (Plan 2's pipeline).
- Done: `services/backtest_runner.py`'s `run_backtest_simulation` gained a test-only
  `_reprep_every_candle: bool = False` parameter (default False is byte-identical to the
  pre-9.5 path — the new branch is unreachable unless a caller explicitly opts in). When True,
  `prepare()` is re-invoked every candle on `candles_np[:t+1]` instead of once upfront.
  `engine/scripts/lookahead_sentinel.py` (new, same pattern as `golden_master.py`) runs each of
  the 5 seeded strategies both ways over a 3-month BTCUSDT window and diffs trade lists.
  **Result: all 5 strategies pass, zero divergence** — confirms the audit's finding that the
  seeded strategies were already causal, only the framework lacked a detector. Wired into CI as
  its own best-effort step (`continue-on-error`, same external-Binance-network caveat as the
  golden-master step).
- **Note for future sessions:** the engine container has `volumes: []` — `scripts/golden/*.json`
  baseline files written by `golden_master.py` do NOT survive a container recreation (only what
  `docker compose build` bakes into the image persists). A baseline captured in one container
  lifetime is unrecoverable after any `docker compose up -d`/`build`/restart of `engine`. This
  session lost its `pre_qnt1_2_3_baseline.json` this way partway through 9.5 — worked around
  with a determinism check (two fresh runs compared to each other) instead of a true before/after
  diff, which was sufficient here (the code change is a default-off additive parameter) but
  won't be for a real output-changing step like 9.4/9.7/9.8. For those, either capture both
  baseline and post-change snapshots **within the same uninterrupted container session**, or
  `docker cp` the JSON out to the host between rebuilds.
- **2026-07-15 note:** `16_lookahead-analysis.md` (a per-trade, per-column lookahead diff)
  proposed independently in the feature-gap program (plans 11-19) is now `Merged→9` — this
  step's sentinel already covers the same failure mode as a whole-strategy CI gate. Reopen 16
  only if this sentinel ever flags a strategy and the failure needs per-column localization.

### 9.6 — Optimizer overhaul (QNT-6) — **absorbed by Plan 10 (Phase 3)**
- Walk-forward split layer over `run_backtest_simulation`; report stitched out-of-sample
  metrics only. Deflated Sharpe + PBO/CSCV on the trial set. Optuna TPE + pruning as the
  search engine; min-trades constraint; candles loaded once per optimization; per-combo
  summaries only (no `backtestResults`/trade dumps per combo).
- **2026-07-15 note:** the feature-gap program (plans 11-19) independently proposed this same
  scope as `18_walk-forward-analysis.md` + `19_bayesian-hyperopt.md`. Both are now `Merged→10`
  — their fold-split math and Optuna adapter design are folded into Plan 10 Phase 3 as
  implementation reference, not built as their originally-specified standalone endpoints.

### 9.7 — Historical funding ledger (QNT-5)
- Import `/fapi/v1/fundingRate` into TimescaleDB (idempotent, candle-importer pattern);
  charge boundary-priced signed funding in backtest; keep flat-rate as explicit fallback.

### 9.8 — Detail-timeframe intrabar simulation (ENG-18, QNT-3 residual)
- Opt-in sub-candle loop (1m detail) inside `check_exits` for SL/TP ordering. Re-baseline.

### 9.9 — Monte Carlo & statistics honesty (QNT-7, QNT-13, QNT-14) — **MC portion absorbed by Plan 10 (Phase 1); statistics portion stays here**
- Block bootstrap, 5–10k runs, percentile bands, configurable ruin threshold, exclude
  scale-out legs; leg-vs-round-trip separation in trade statistics; fail-loud metric registry;
  no `"inf"` strings in persisted metrics.
- **Fail-loud metric registry — Shipped 2026-07-17.** `StatisticRegistry.compute_all()`
  (`engine/services/metrics.py`) previously swallowed EVERY exception from ANY registered
  `Statistic.compute()` into a silent `"0.00"` fallback — a genuinely broken metric (a coding bug,
  an unexpected data shape) was indistinguishable from a legitimately-zero one. Now logs
  `logger.error(..., exc_info=True)` on the failing stat's name + exception before falling back —
  the fallback VALUE is unchanged (never poison the result doc; a broken stat still shouldn't fail
  the whole backtest), only the failure is now diagnosable. Golden master confirmed byte-identical
  (none of the 5 seeded strategies' stats currently throw — this is purely an observability
  addition on a path the default baseline never exercises). New tests in
  `engine/tests/test_metrics_fixes.py` (+3): fallback value unchanged on a simulated broken stat,
  the failure is logged with the stat name + message, a healthy stat produces zero log noise.
  Container suite: 377/377 passed (up from 374).
- **Leg-vs-round-trip separation (QNT-14) — Shipped 2026-07-17.** New
  `services.metrics.aggregate_legs_to_round_trips(trades)` groups a DCA/scale-out position's
  partial `"scale_out"` legs (each recorded as an independent trade by `execute_reduce`) + its
  final closing leg into ONE synthetic round-trip record — `pnl` summed across legs, `qty`
  reconstructed as the position's original total size, all descriptive fields
  (`exitReason`/`exitTag`/`barsHeld`/`runUpPct`/`drawdownPct`) taken from the FINAL leg. Grouping
  key is `(symbol, entryAt)` — every leg of one position shares the same `entryAt`, copied
  verbatim by `execute_reduce` from `active_trade`; a backtest is strictly sequential so no two
  distinct positions on one symbol ever share an `entryAt`. **Opt-in** via
  `run_backtest_simulation(round_trip_stats=True)` (default `False`) — a new `stats_trades`
  variable (`services/backtest_runner.py`) feeds `MetricContext.trades`, the `bySide` breakdown,
  `returnsHistogram`, and the MFE/MAE scatter; **persisted `backtestTrades` documents and
  `tradeCount` are unchanged either way** — always the raw per-leg list, since per-leg
  analytics/UI need the individual legs, only STATISTICS get the round-trip view. Golden master
  confirmed byte-identical (default `False`). New `engine/tests/test_round_trip_aggregation.py`
  (9 cases): single-leg passthrough, multi-leg aggregation (pnl sum, qty reconstruction, final-leg
  descriptive fields), pnlPct recomputed from aggregate pnl vs. original margin, distinct
  same-symbol positions never merge, different symbols never merge even with a coincidentally
  shared `entryAt`, insertion-order preservation, empty input, and non-mutation of the input list
  (both single- and multi-leg). Container suite: 386/386 passed (up from 377).
- **Still open**: `"inf"`-string persistence (re-audited 2026-07-17 — still zero client-side
  `parseFloat`/`Number()` consumption of `profitFactor`/`expectancyRatio`/`payoffRatio` found
  anywhere in `client/src` or `server/src`; real per the audit but genuinely dormant, deliberately
  not fixed speculatively — see root `CLAUDE.md`'s "don't add validation for scenarios that can't
  happen") and the block-bootstrap Monte Carlo work (absorbed by Plan 10 Phase 1, not this plan's
  scope). **9.9 is otherwise complete within this plan's own scope.**

### 9.10 — Fill-model ladder (QNT-11) + small hardening (QNT-4/15/16)
- Spread half-cost → volatility-scaled slippage → √-impact (cached 24h volume as ADV);
  liquidation fee; ~~incremental ATR-history sort~~; warmup-insufficiency fail-loud
  (with Plan 8 / ENG-8).
- **Incremental ATR-history sort (QNT-15) — Shipped 2026-07-15, pulled forward out of this
  step.** `AtrBracketRiskModel._atr_history` (`core/models/risk.py`) now stays sorted via
  `bisect.insort` on every append instead of calling `sorted()` fresh on every percentile-filter
  lookup — O(N) insert vs O(N log N) full re-sort per candle, which was O(N² log N) over a
  multi-year 1m run. Pure data-structure refactor, mathematically equivalent (verified: a
  `bisect.insort`-maintained list and a freshly-`sorted()` copy of the same multiset produce
  identical `bisect_left` ranks — spot-checked directly, and by construction). `atr_percentile_min`
  defaults to `0.0` (filter disabled) for every seeded strategy, so this path doesn't execute in
  the default golden-master run at all — zero risk to the existing baseline; full suite 88/88.
  Fill-model ladder + liquidation fee + warmup fail-loud remain undone.

### 9.11 — Cost-gate resurrection: rewire, fix dimensions, wire-or-delete `magnitude` (M-1/M-2/M-3, added 2026-07-16) — **Step A Shipped 2026-07-17**
- **Source:** Plan 21's five-model audit addendum (`21_live-algo-industry-standard-audit.md`
  Part A2). Three `[Certain]` findings: **M-1** — the "default-on" cost gate never fires because
  `live_bot_manager.py:1262`/`backtest_runner.py:905` inject `min_edge_mult=0.05` onto
  `cost_model` while the live gate (`DefaultPortfolioModel._edge_beats_cost`) reads
  `portfolio_model.min_edge_mult` (0.0); **M-2** — the gate's formula compares a per-unit price
  distance (`conviction × risk_per_unit × rrr`) against a whole-position quote cost
  (`cost.total`), making any activated gate a function of the symbol's absolute price level
  (always-pass on BTC-priced, always-veto on sub-cent symbols); **M-3** — `Signal.magnitude` is
  documented as feeding this gate but is read by nothing.
- **Step A (golden-master-inert):** route the injected value to the object the gate actually
  reads; fix the formula to quote-vs-quote (`edge_total = |conviction| × risk_per_unit ×
  qty_est × rrr`, same `qty_est` as `estimate()`); wire `magnitude` in as the edge term where
  provided (fallback conviction) or delete the field; **default `min_edge_mult` to 0.0
  everywhere** (both injection sites) so behavior stays byte-identical. Unit-test the gate's
  veto boundary on a high-priced and a sub-cent symbol.
- **Step B (separate, re-baselined):** decide whether to activate at 0.05 by default —
  golden-master re-baseline + sign-off, per this plan's standing protocol. Do not bundle with
  Step A. `CURRENT_STATE.md`'s Risk-Model bullet already carries the 2026-07-16 correction;
  update it again when A/B land.
- **Step A shipped 2026-07-17.** `DefaultPortfolioModel._edge_beats_cost()`
  (`core/models/portfolio.py`) now reads a `min_edge_mult` that's actually set on the right
  object: both injection sites (`backtest_runner.py`, `live_bot_manager.py`) write
  `strategy.portfolio_model.min_edge_mult` instead of the dead `strategy.cost_model.min_edge_mult`
  (M-1), and both now default to `0.0` (was `0.05` — but since the old value never reached the
  gate, this is a no-op change, not a behavior change). The gate formula is now quote-vs-quote:
  `edge_total = edge_frac × risk_per_unit × qty_est × rrr` where `qty_est =
  min(budget/risk_per_unit, max_notional/price)` — the same quantity the Cost Model used to
  produce `cost.total` — instead of comparing a bare per-unit price distance against a
  whole-position quote cost (M-2). `edge_frac` uses `sig.magnitude` when the alpha model provides
  one (nonzero), falling back to `abs(sig.conviction)` (M-3) — `Signal.magnitude`'s docstring was
  already accurate, it was simply unread until now. New `engine/tests/test_edge_beats_cost_gate.py`
  (5 cases) proves: gate-off passes regardless of cost; a scaled-edge boundary case flips on
  cost; the veto boundary is **price-level invariant** (identical relative setup on a BTC-priced
  and a sub-cent symbol gives the identical verdict — the concrete regression test for M-2);
  magnitude overrides conviction when provided; the alpha-level veto still short-circuits.
  **Golden master re-run before/after per root CLAUDE.md Rule C**: `compare --a pre_9_11_stepA
  --b post_9_11_stepA` → `GOLDEN-MASTER OK` (5/5 seeded strategies, tol 1e-6) — confirms the
  default-off gate produces byte-identical output. Container suite: 358/358 passed (up from 353).
  Step B (deciding whether to activate the gate at 0.05 by default) is untouched — genuinely a
  product decision needing its own re-baseline + sign-off, not bundled here.

## Acceptance criteria (phase)

- All shipped backtest paths (single, multi, exec-algo, funding-on) covered by golden-master
  scenarios and at least one behavioral test each.
- Cash-conservation invariant test green across all scenarios.
- Optimizer reports out-of-sample metrics + DSR; in-sample-only reporting removed.
- Lookahead sentinel green in CI for all seeded strategies.

## Open questions

- When 9.4/9.8 change defaults, who signs off the re-baseline? (Same owner as Rule C.)
- Keep or delete `IcebergAlgorithm` once the fill model makes it evaluable? (It is currently
  untestable in sim — QNT-11.)
- Funding history import depth (full history vs rolling 2 years) and storage budget.

## Handoff template

```
Next session: Pla