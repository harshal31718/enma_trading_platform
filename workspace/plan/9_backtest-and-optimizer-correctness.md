# Plan 9 — Backtest & optimizer correctness (quant core)

**Status:** Ready · **Priority:** P0 (steps 9.1–9.3) / P1 (rest) · **Depends on:** — (9.1–9.3); 2 (CI for 9.5+) · **Related:** 5, 6, 8

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

### 9.1 — Multi-symbol exit-check fix (QNT-1) — P0
- Clear `_entered_this_candle` per candle in `_run_shared_portfolio` (minimal), then move the
  flag into the kernel loop as local state (structural). Run `update_pnl`/funding/excursion
  updates in the portfolio path.
- Acceptance: 2-symbol backtest with a bracket strategy produces `stop_loss`/`take_profit`
  exit reasons; cash-conservation property test passes
  (`final == capital + Σpnl − fees − funding`); new multi-symbol golden-master scenario
  captured as baseline.
- Migration note: flag existing multi-symbol `backtestResults` (`symbol` contains ",") as
  stale in the UI or a one-off script.

### 9.2 — Exec-algo close/flip pass-through (QNT-2) — P0
- Snapshot `_close_at_open`/`_pending_flip` before the kernel's exec-algo clear; route exits
  and flips unsliced (per the algos' own contract).
- Acceptance: with TWAP active, `close_position()` closes next open and a flip executes;
  tests added to `test_exec_algo_slicing.py`.

### 9.3 — Persist run config; fix leverage sensitivity (QNT-17) — P0
- `run_backtest_simulation` persists `alphaParams`, `riskParams`, `slippagePct`,
  `fundingEnabled`, `fundingRate` into `backtestResults`; `leverage_sensitivity_runner` reads
  them back.
- Acceptance: leverage scenarios of a parent run with non-default params reproduce the parent's
  trade list at the parent's leverage level.

### 9.4 — Entry-candle exit evaluation (QNT-3)
- Opt-in flag: evaluate SL/TP/liquidation against the entry candle (entry at open → exits
  checked on that candle's range). Golden-master re-baseline with sign-off when made default.

### 9.5 — Lookahead sentinel in CI (QNT-12, detector for QNT-9)
- Harness: full-array `prepare()` vs per-candle expanding-window recompute; assert identical
  trade lists for all seeded strategies. Wire into CI (Plan 2's pipeline).

### 9.6 — Optimizer overhaul (QNT-6) — **absorbed by Plan 10 (Phase 3)**
- Walk-forward split layer over `run_backtest_simulation`; report stitched out-of-sample
  metrics only. Deflated Sharpe + PBO/CSCV on the trial set. Optuna TPE + pruning as the
  search engine; min-trades constraint; candles loaded once per optimization; per-combo
  summaries only (no `backtestResults`/trade dumps per combo).

### 9.7 — Historical funding ledger (QNT-5)
- Import `/fapi/v1/fundingRate` into TimescaleDB (idempotent, candle-importer pattern);
  charge boundary-priced signed funding in backtest; keep flat-rate as explicit fallback.

### 9.8 — Detail-timeframe intrabar simulation (ENG-18, QNT-3 residual)
- Opt-in sub-candle loop (1m detail) inside `check_exits` for SL/TP ordering. Re-baseline.

### 9.9 — Monte Carlo & statistics honesty (QNT-7, QNT-13, QNT-14) — **MC portion absorbed by Plan 10 (Phase 1); statistics portion stays here**
- Block bootstrap, 5–10k runs, percentile bands, configurable ruin threshold, exclude
  scale-out legs; leg-vs-round-trip separation in trade statistics; fail-loud metric registry;
  no `"inf"` strings in persisted metrics.

### 9.10 — Fill-model ladder (QNT-11) + small hardening (QNT-4/15/16)
- Spread half-cost → volatility-scaled slippage → √-impact (cached 24h volume as ADV);
  liquidation fee; incremental ATR-history sort; warmup-insufficiency fail-loud
  (with Plan 8 / ENG-8).

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