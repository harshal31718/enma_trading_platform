# Plan: Migration Checklist — Execution Order

Originally from `workspace/issues_and_solutions/solutions/migration_checklist.md` (merged into `plan/` 2026-06-24).

Maps to analysis: `issues/strategy_performance.md`

---

## Phase 0: Preparation
- [ ] Read all refactor plan documents in order
- [ ] Create git branch: `refactor/precompute-strategies`
- [ ] Run golden master baseline: `python -m scripts.golden_master run --label baseline`
- [ ] Record baseline runtime for each strategy

## Phase 1: BaseStrategy + Runner Changes
- [ ] Add `prepare(candles: np.ndarray) -> None` to `BaseStrategy` (default no-op)
- [ ] Add `self._indicators: dict | None = None` and `self.index: int = 0` to `BaseStrategy.__init__`
- [ ] In `backtest_runner.py`, insert `strategy.prepare(candles_np)` after strategy init
- [ ] Verify `strategy.index` is set before `before()` call
- [ ] Run boundary tests, golden master unchanged (prepare() is no-op)

## Phase 2: MicroMacroRSIDivergence
- [ ] Move all TA-Lib calls to `prepare()` (RSI, ATR, 4 pivot calls, smoothed RSI)
- [ ] Simplify `before()` to index-only
- [ ] Unify `_eval_bull`/`_eval_bear` into `_eval_divergence(direction=±1)`
- [ ] Golden master: signals identical; runtime ≥50% improvement

## Phase 3: MultiDivergence
- [ ] Move oscillator pre-computation to `prepare()` (price pivots, ATR, each enabled oscillator, oscillator pivots, swing amplitudes)
- [ ] Simplify `before()` to check new pivots + tally votes
- [ ] Golden master: same trade decisions; 9× O(N) eliminated

## Phase 4: MicroScalper
- [ ] Move EMAs + ATR to `prepare()`
- [ ] Simplify `before()`: index at `i` and `i-1`, scalar crossover math
- [ ] Golden master: crossover signals identical; 6 O(N) eliminated

## Phase 5: BestSupertrend
- [ ] Move pandas resample + supertrend calc to `prepare()`
- [ ] Pre-compute crossover arrays; replace backward loop with O(1) lookups
- [ ] Golden master: supertrend values, cross-buy/sell timing match

## Phase 6: AdaptiveTrend
- [ ] Move EMAs + ATR to `prepare()` (6→8 calls eliminated)
- [ ] Replace candle-slice EMA pattern with index shift
- [ ] Golden master: same trend detection, same crossovers

## Phase 7: Live Bot Parity
- [ ] Update `LiveBotManager._run_symbol_loop()`: fetch sufficient warmup, call `prepare()`, set `strategy.index`
- [ ] Verify `before()` works in live mode (no TA-Lib calls)
- [ ] Test pivot confirmation in live mode

## Phase 8: Cleanup & Final Verification
- [ ] Run full golden master comparison (baseline vs refactored)
- [ ] Run boundary tests, lint (`ruff check engine/`)
- [ ] Update `CURRENT_STATE.md` + `DEPRECATED.md`
- [ ] Write handoff to `workspace/plan/handoff.md`
- [ ] Commit

## Estimated Effort: ~12 hours (11 files changed)
