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

### 9.7 — Historical funding ledger (QNT-5) — **Shipped 2026-07-17**
- Import `/fapi/v1/fundingRate` into TimescaleDB (idempotent, candle-importer pattern);
  charge boundary-priced signed funding in backtest; keep flat-rate as explicit fallback.
- **Done.** Endpoint verified against official Binance docs first (root `CLAUDE.md` Rule A):
  `GET /fapi/v1/fundingRate`, public/no signing, `symbol`/`startTime`/`endTime`/`limit` (max 1000),
  ascending order, rows `{symbol, fundingRate, fundingTime, markPrice}` — documented in
  `binance-api.md` §2. New TimescaleDB hypertable `funding_rates` (`time`, `exchange`, `symbol`,
  `funding_rate`, `mark_price`; unique index on `(time, exchange, symbol)`) — added to
  `docker/timescale/init.sql` for future fresh deployments AND applied directly to the live
  running database (init.sql only runs on a fresh volume, confirmed via `\dt` before/after).
  New `engine/services/funding_importer.py` (`import_funding_rates`, mirrors
  `candle_importer.py`'s idempotent `ON CONFLICT DO NOTHING` upsert pattern, paginates via
  Binance's own `fundingTime` cursor since — unlike klines — there's no fixed interval to derive
  "next" from) and `engine/services/funding_manager.py` (`ensure_funding_available`, the single
  entry point, mirrors `candle_manager.py`'s contract). **Manually verified end-to-end against
  real Binance mainnet data**: fetched 22 real funding events for BTCUSDT 2024-01-01..08 (3/day,
  matching the expected ~8h cadence), confirmed idempotent re-fetch (second call hits the
  count-based cache, zero duplicate rows).
- **Backtest wiring** (`services/backtest_runner.py`): new `historical_funding: bool = False`
  param. When `True` and `exchange == "Binance Futures"`, fetches funding events for the same date
  range into a numpy array per symbol, passed to `BacktestAdapter(historical_funding_events=...)`.
  `charge_funding()` gained a new branch: when `historical_funding_events is not None`, walks
  forward event-by-event (not boundary-by-boundary) charging each event's OWN signed
  `funding_rate` against its OWN `mark_price` (falling back to the candle's `close_t` when
  Binance omitted `markPrice`) — genuinely more realistic than the flat-rate fallback in three
  ways: (1) real signed rates instead of one constant for the whole backtest, (2) Binance's own
  irregular event timestamps instead of an assumed-fixed 00:00/08:00/16:00 UTC boundary schedule,
  (3) each event's own mark price instead of the candle's last-trade close. Default `None`
  (unchanged) reproduces the exact pre-9.7 flat-rate/fixed-boundary code path — same condition
  structure, same walk logic, verified byte-identical.
- **Verification:** golden master confirmed byte-identical (Rule C; the default golden-master
  config also has `funding_enabled=False`, so this is doubly inert by default). New
  `engine/tests/test_historical_funding.py` (8 cases): default path unaffected by the new
  constructor param; funding-disabled short-circuits regardless of events; a real event charges
  its own rate AND mark price (not the candle's close); missing `mark_price` falls back to
  `close_t`; short positions receive when the rate is positive (sign convention matches the
  flat-rate branch); multiple events in one window are each charged exactly once with the cursor
  advancing correctly across two separate `charge_funding()` calls (no double-charge); no events
  in the window charges nothing and leaves the cursor untouched; an empty (non-`None`) events
  array is historical-mode-charging-nothing, distinct from `None`'s flat-rate fallback. Container
  suite: 415/415 passed (up from 407). `binance-api.md` and `engine/CLAUDE.md` (services listing,
  DB schema table, Binance-call-site allowlist) updated.
- **Not implemented — deliberately deferred:** no server/API surface to actually SET
  `historical_funding=True` from a backtest request (same "mechanism only, not the
  user-facing feature" scoping as 9.4's `entry_candle_exits` and every other opt-in flag shipped
  this session) — reachable only by calling `run_backtest_simulation` directly with the kwarg.
  Making it user-facing (a UI toggle, wired through the same path as `funding_enabled`) is a
  separate, smaller follow-up whenever someone wants to actually use this.

### 9.8 — Detail-timeframe intrabar simulation (ENG-18, QNT-3 residual) — **Shipped 2026-07-17**
- Opt-in sub-candle loop (1m detail) inside `check_exits` for SL/TP ordering. Re-baseline.
- **Done.** `ExecutionKernel.__init__` gained `intrabar_detail: bool = False`,
  `detail_candles_by_symbol: dict | None = None`, `base_timeframe_ms: int | None = None`, and a
  new `_resolve_intrabar_winner()` method. `check_exits()`'s long/short branches now compute
  `sl_hit`/`tp_hit` candidates first; when BOTH are true within one base candle (the genuinely
  ambiguous case — previously always resolved SL-first by code-order alone), the ambiguity is
  resolved via `_resolve_intrabar_winner()` (opt-in) — scans 1m sub-candles within that base
  candle's `[open, open+timeframe)` window in chronological order, returning whichever level's
  wick genuinely triggers first, falling back to the SL-first default when detail data isn't
  available/doesn't cover the window (a gap in 1m history is never a hard failure). Refactor is
  behavior-preserving by construction for the default path (`intrabar_detail=False`):
  `_resolve_intrabar_winner()` short-circuits to `None` immediately, so `winner = None or
  "stop_loss"` reproduces the exact prior structural bias.
- **Wiring** (`services/backtest_runner.py`): new `intrabar_detail: bool = False` param on
  `run_backtest_simulation`. When `True` and the base timeframe isn't already `1m`, fetches 1m
  candles for the same date range via the existing `ensure_candles_available()` single entry
  point (same pattern as Plan 13's HTF fetch) into a new `detail_candles_by_sym` dict, passed to
  each symbol's `ExecutionKernel` alongside `base_timeframe_ms = utils.timeframes.to_ms(timeframe)`.
  Default `False` means this fetch never runs at all — zero cost, not just zero behavior change.
  **Not implemented: 1m-fetch cost/size guardrails** — a long multi-year backtest opting into this
  would fetch a very large 1m candle set (e.g. a 1-year 1h backtest needs ~525k 1m candles); no
  warning or cap was added this session, left as a known limitation for whoever activates this in
  practice.
- **Verification:** golden master confirmed byte-identical (Rule C — both the refactored
  `kernel.py` exit-check logic and the new backtest_runner.py wiring, default settings). New
  `engine/tests/test_intrabar_detail_resolution.py` (10 cases): default-off preserves the
  SL-first bias; opt-in correctly resolves TP-hit-first and SL-hit-first from synthetic 1m data;
  graceful fallback when detail data is missing for the symbol, doesn't cover the window, or
  (defensively) doesn't actually confirm either level; the non-ambiguous single-level case is
  unaffected by the flag either way; short-side resolution; `_resolve_intrabar_winner()`'s own
  None-returning guards (flag off, `base_timeframe_ms` unset). Container suite: 407/407 passed
  (up from 397).

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
- **Fill-model ladder — Shipped 2026-07-17.** New `LadderedTransactionCostModel`
  (`core/models/cost.py`, exported from `core/models/__init__.py`) — layers volatility-scaled
  slippage (`vol_slip_mult * ATR%`, via the strategy's own `_atr()` helper) and a square-root
  market-impact term (`impact_mult * sqrt(notional / ADV)`, ADV approximated as trailing ~24h
  `sum(volume * close)` from the strategy's own candle window — the numpy candles array only
  carries base-asset `volume`, not the DB's separate `quote_volume` column) on top of the base
  `slippage_pct`. **Spread half-cost (the ladder's first rung) deliberately NOT modeled** —
  backtesting has zero historical bid/ask spread data (TimescaleDB's `candles` table is
  OHLCV-only, unlike live's ticker cache); inventing spread data would be worse than omitting it.
  Required widening `DefaultTransactionCostModel.adverse_fill()`'s signature with an optional
  `qty: float | None = None` param (both `execution.py` call sites — `entry_fill`/`exit_fill` —
  already had `qty` in scope, now pass it through; the base model ignores it, byte-identical).
  **Opt-in only**: a strategy assigns `self.cost_model = LadderedTransactionCostModel()` in its
  own `__init__` — none of the 5 seeded strategies do, so this is golden-master-safe by
  construction, not merely by a default-off flag. Golden master confirmed byte-identical anyway
  (Rule C). New `engine/tests/test_laddered_cost_model.py` (11 cases): base model unaffected by
  the new `qty` param; zero ATR + zero qty reduces to base-slippage-only; higher ATR widens the
  fill; ATR-read failures/zero-price degrade to 0.0 (never crash); no impact term when `qty` isn't
  passed; larger `qty` produces larger impact; zero ADV disables impact (no divide-by-zero); ADV
  window sizing for an hourly timeframe; empty-candles ADV degrades to 0.0; sell side widens
  downward symmetrically. Container suite: 397/397 passed (up from 386).
- **Liquidation fee (QNT-4) — Shipped as opt-in 2026-07-18, resolving the product-call left open
  below.** User's decision: keep `engine/CLAUDE.md`'s documented margin-only-loss contract as the
  default (unchanged), make an extra clearance-style fee available as an explicit opt-in for
  users who want closer-to-real-Binance modeling. New `BacktestAdapter.liquidation_fee_pct`
  (`services/backtest_runner.py`), threaded through as a `run_backtest_simulation` kwarg
  (default `0.0`, same not-yet-router-exposed pattern as `historical_funding`/`round_trip_stats`/
  `intrabar_detail` — internal-only until a UI control exists). When `> 0`, charges
  `liquidation_fee_pct * notional_at_entry` on top of the forfeited margin in `execute_exit`'s
  `"liquidation"` branch, added to both the realized loss and `total_fees`; `trade_pnl_pct` now
  computes as `realized_pnl / margin * 100` instead of a hardcoded `-100.0` literal — exactly
  `-100.00` when the fee is `0.0` (division identity: `-margin/margin` is exactly `-1.0` in
  IEEE754 for any nonzero margin, so the formatted string is byte-identical), more negative when
  opted in. **Documented as an approximation, not a bankruptcy-price simulation** — real Binance's
  clearance fee depends on the liquidation engine's actual fill vs. the bankruptcy price, which
  isn't reconstructable from OHLCV candles alone; a fixed fraction of notional is the closest
  honest approximation without fabricating exchange internals.
  **Verified:** 6 new tests (`engine/tests/test_liquidation_fee.py`) — default `0.0` reproduces
  the exact pre-QNT-4 loss/pct/fees, opted-in fee adds the correct extra loss for both long and
  short (notional-scaled), a non-liquidation exit (`take_profit`) is provably unaffected by the
  param regardless of its value. Container suite 421 → **427/427 passed**. Golden master not run
  via the script (a `git stash`-equivalent file swap to get a true before/after was denied by the
  session's safety classifier per root CLAUDE.md Rule H's spirit) — relied instead on the
  division-identity proof above plus the full container suite showing zero regressions, which
  covers the same guarantee for every seeded strategy (none of which opt into this param).
- **Warmup-insufficiency fail-loud (QNT-16) — Shipped 2026-07-24.** Was deliberately deferred
  pending Plan 8/ENG-8 coordination; Plan 8 shipped in full 2026-07-21, unblocking this. New
  `check_warmup_sufficient(sym, warmup_period, num_rows, min_warmup_candles)`
  (`services/backtest_runner.py`) — a pure, directly-unit-testable extraction — raises
  `RuntimeError("WARMUP_INSUFFICIENT: ...")` when `warmup_period >= len(rows)`, the exact condition
  that previously made `range(warmup_period, total_candles)` empty and let the simulation loop
  "complete" with zero trades and no warning, indistinguishable from a strategy that legitimately
  found no signals. The raise propagates through `routers/backtest.py`'s existing
  `except Exception` handler, which already sets `backtestResults.status="failed"` +
  `error=str(e)` for any raised exception (same path `STRATEGY_ERROR: prepare() failed` uses) — no
  new error-surfacing plumbing needed. Fires only when the date range genuinely can't support the
  strategy's declared warmup, so every existing passing backtest is unaffected by construction.
  **Verified:** new `engine/tests/test_warmup_sufficient.py` (5 cases: sufficient candles passes,
  exact boundary passes, `warmup==num_rows` raises, `warmup>num_rows` raises, error message names
  the symbol + both counts). Container suite 670 → **675/675 passed**, golden-master `MultiDivergence`
  byte-identical (`trades=55 netProfit=-1784.02 winRate=0.36 cagr=-71.32 sqn=-2.08`) — expected,
  since no seeded strategy's default config/date-range combination trips the new check.

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