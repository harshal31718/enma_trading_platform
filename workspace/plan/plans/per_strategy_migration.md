# Plan: Per-Strategy Migration

Originally from `workspace/issues_and_solutions/solutions/per_strategy_migration.md` (merged into `plan/` 2026-06-24).

> **Behavioral correctness note:** All migrations must produce identical trade decisions vs the originals. The refactored `before()` computes the same values — just via O(1) index lookups instead of O(N) TA-Lib recomputes. Golden master comparison is mandatory after each strategy.

---

## MicroMacroRSIDivergence (Critical — worst O(N²))

**File:** `engine/strategies/MicroMacroRSIDivergence/__init__.py`

### Move to `prepare()`
- `ta.rsi(..., sequential=True)` → `self._rsi_seq`
- `ta.atr(...)` → `self._atr`
- `ta.pivot_high/low()` (4 calls: micro/macro × high/low) → `self._micro_low/high`, `self._macro_low/high`
- `_smoothed_rsi()` → compute in `prepare()`, not `before()`. **Key change:** pre-allocate output array once and fill at valid positions, instead of allocating `np.full(rsi_seq.shape, np.nan)` every tick (line 222)
- `_eval_bull` / `_eval_bear` → unify into `_eval_divergence(direction=±1)`. ~85% duplicate code (40 lines each → ~20 unified). Direction parameter controls price/RSI comparison polarity
- `win = self.candles[off:]` slicing → remove from hot path (pre-computed arrays eliminate need for window slicing)

### Simplify `before()`
- Only index into `self._*` arrays, populate `self.vars`
- Warmup check using class constant
- Zero TA-Lib calls

### Verification
- Golden master: signals identical
- Runtime improvement ≥50%

---

## MultiDivergence (Critical — 9 oscillator sources)

**File:** `engine/strategies/MultiDivergence/__init__.py`

### Move to `prepare()`
- Price pivots → `self._ph`, `self._pl`
- ATR → `self._atr`
- Each enabled oscillator → `self._enabled_oscillators` dict
- Oscillator pivot arrays → `self._osc_pivots` dict
- Swing amplitude pre-computation → `self._swing_up`, `self._swing_down`. In `prepare()`: find pivot pairs via `np.where(~np.isnan(ph))[0]`, iterate to compute swing between consecutive highs/lows, store as full arrays. Eliminates O(N) oscillation per tick

### Simplify `before()`
- Check new pivot confirmation, tally votes from pre-computed arrays
- 9× O(N) calls eliminated from hot loop

### Verification
- Same trade decisions (pivot timing unchanged)
- Runtime: 9× O(N) → 1× O(N) in prepare

---

## MicroScalper (Medium)

**File:** `engine/strategies/MicroScalper/__init__.py`

### Move to `prepare()`
- EMAs (4×: fast/slow × current/prev-1) → `self._fast_ema_seq`, `self._slow_ema_seq`
- ATR scalar + sequential → `self._atr`, `self._atr_seq`, `self._atr_baseline`

### Simplify `before()`
- Index into EMAs at `i` and `i-1` for crossover detection. **Worst original pattern:** lines 118-119 compute EMA on `self.candles[:-1]` (a view only 1 shorter than full array) — equivalent to computing full EMA and discarding last value
- Compute crossovers with scalar math (no TA-Lib): `crossed_above = fast_prev <= slow_prev and fast_curr > slow_curr`
- ATR stops from pre-computed scalar. `_atr_baseline` pre-computed from `valid_atr[-window_len:]` mean in `prepare()`
- **No changes needed** to `_is_volatile()` or `_crossed_above()/below()` — they already read from `self.vars` which `before()` populates

### Verification
- Crossover signals identical
- ATR stop prices identical
- 6 O(N) calls eliminated

---

## BestSupertrend (Medium-High — pandas resample in hot loop)

**File:** `engine/strategies/BestSupertrend/__init__.py`

### Move to `prepare()`
- Pandas resample → `self._resampled`
- `_calculate_supertrend()` → `self._tsl`
- SMA arrays → `self._sma_fast_seq`, `self._sma_slow_seq`
- Crossover arrays → `self._last_cross_up`, `self._last_cross_down`

### Simplify `_evaluate_signals()`
- Replace backward loop with `_check_cross_up(index)` / `_check_cross_down(index)` — O(1) lookups from pre-computed `self._last_cross_up/down` arrays
- **Behavioral note:** The original backward loop searched from current index backward and returned the *first* crossover found (not necessarily the most recent). The pre-computed arrays track the *most recent* crossover. Combined with a `f_curr > s_curr` check, this should match — but must be verified with golden master
- Index into pre-computed supertrend. In backtest: `st_idx = min(i, len(self._tsl) - 1)`, read `self._tsl[max(0, st_idx - 2)]` (2-bar delay to match original `tsl[-2]`)

### Verification
- Cross-buy/cross-sell timing matches original backward loop
- Supertrend values match
- Pandas resample eliminated from hot loop

---

## AdaptiveTrend (Low — closest to target pattern)

Already partially refactored per its docstring ("All indicators computed once in before(), stored in self.vars. Zero TA-Lib calls in any other hook"). But `before()` still calls TA-Lib on growing array — needs the same `prepare()` extraction as the others.

**File:** `engine/strategies/AdaptiveTrend/__init__.py`

### Move to `prepare()`
- EMAs (6×: trend, fast, slow × various offsets) → `self._trend_ema_seq`, `self._fast_ema_seq`, `self._slow_ema_seq`
- ATR scalar + sequential → `self._atr`, `self._atr_seq`, `self._atr_baseline`

### Simplify `before()`
- Replace O(N) EMAs on slices with O(1) index into pre-computed arrays
- Remove ATR sequential call

### Verification
- Same trend detection, same crossover signals
- 8 O(N) calls eliminated
