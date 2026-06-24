# Plan: Strategy Performance Refactor

Originally from `workspace/issues_and_solutions/solutions/strategy_precompute_architecture.md` (merged into `plan/` 2026-06-24).

Maps to analysis: `issues/strategy_performance.md`

---

## 1. Two-Phase Architecture (`prepare()` + `before()`)

### Problem
`before()` recomputes full indicator arrays every tick as `strategy.candles` grows by 1 each iteration → O(N²).

### Solution

**Phase A — `prepare(candles)`**: Called **once** before simulation. Computes all indicators in vectorized batch on the full candle array. Stores as typed instance attributes.

**Phase B — `before()`**: Called per-candle. **Only indexes** into pre-computed arrays at `self.index`. Zero TA-Lib or numpy math.

```
load_candles() ──► strategy = StrategyClass()
                           │
                           ▼
                strategy.prepare(full_candles)    ← NEW: one-time vectorized batch
                           │
                           ▼
                for t in range(warmup, total):
                    strategy.candles = candles[:t+1]
                    strategy.index   = t
                    strategy.before()              ← HOT: lookups only
                    evaluate(strategy, ...)
                    strategy.after()
```

### `prepare()` — BaseStrategy Contract

```python
def prepare(self, candles: np.ndarray) -> None:
    """One-time batch indicator pre-computation. Called ONCE by the runner.
    Default: no-op (backward compatible)."""
    pass
```

### `before()` — New Contract

`before()` must NOT call any TA-Lib or pandas-ta function. Index-only:

```python
# BEFORE (O(N²) — DESTROY THIS PATTERN):
def before(self):
    self.vars["rsi"] = ta.rsi(self.candles, period=14, sequential=True)

# AFTER (O(1) — INDEX LOOKUP):
def prepare(self, candles):
    self._rsi = ta.rsi(candles, period=14, sequential=True)

def before(self):
    i = self.index
    self.vars["rsi_val"] = float(self._rsi[i]) if not np.isnan(self._rsi[i]) else 0.0
```

### Typed State Container

Use `@dataclass` (not `NamedTuple`) — arrays are mutated each candle:

```python
@dataclass
class IndicatorState:
    ready: bool = False
    rsi: np.ndarray = field(default_factory=lambda: np.array([]))
    atr: float = 0.0
```

### Runner Changes

Insert `strategy.prepare(candles_np)` after strategy init, before simulation loop:

```python
try:
    strategy.prepare(candles_np)
except Exception as e:
    raise RuntimeError(f"STRATEGY_ERROR: prepare() failed: {e}")
```

### Backward Compatibility

- `prepare()` is a no-op by default → existing strategies work unchanged
- `before()` still has access to `self.candles` (full history up to index)
- `self.vars` still works for dynamic state (temporary flags, counters)
- No changes to `forecast()` signature, `Signal`, model interfaces, or pipeline
- Lint check recommended: verify `before()` has no TA-Lib calls if `prepare()` is overridden

---

## 2. Risk Model Improvements

| # | Change | Priority | File | Detail |
|---|--------|----------|------|--------|
| 1 | Trailing stop on `AtrBracketRiskModel` | HIGH | `risk.py` | Add `trail_atr_mult` param. In the "maintain" path: `candidate = s.price ± trail_mult * atr`; if candidate tightens the stop, update it. Default 0 = static bracket |
| 2 | Partial exit at 1R (breakeven) | MEDIUM | `risk.py` | `if s.price >= entry + risk_per_unit: stop = max(stop, entry_price)` for longs. Move SL to breakeven when price reaches 1× risk |
| 3 | ATR percentile filter | MEDIUM | `risk.py` | `percentile = np.searchsorted(sorted(valid_atr), current_atr) / valid_atr.size`; veto if `percentile < 0.10` |
| 4 | Enable cost gate | LOW | `portfolio.py` | Change `DefaultPortfolioModel.min_edge_mult` from 0.0 → 0.05. Blocks trades where expected edge < 5% of transaction cost. Strategies can override by setting `self.cost_model.min_edge_mult = 0.0` |
| 5 | Portfolio exposure cap | LOW | `portfolio.py` | `max_portfolio_risk` default 6%. If `current_risk + new_risk > equity * max_portfolio_risk`, don't add to exposure. Requires tracking aggregate risk in runner |

All changes are **additive**: existing behavior preserved when new params are at defaults.

---

## 3. Live / Backtest Sync

### Startup
```
LiveBotManager._run_symbol_loop():
    1. Load warmup candles (enough for longest indicator period + pivot buffer)
    2. strategy.prepare(warmup_candles)              ← one-time batch
    3. strategy.candles = warmup_candles
    4. strategy.index = len(warmup_candles) - 1
    5. Enter WS loop
```

### Each New Candle (Resolving the IndexError Gap)
*   **The Gap:** If `prepare()` calculates arrays of length `W` (warmup), then when a new live candle arrives and `strategy.index` is incremented to `W`, indexing into `self._rsi_seq[strategy.index]` will trigger an `IndexError` because the precomputed array is still of length `W`.
*   **The Solution:** Implement a stateful update mechanism for live mode. Instead of simply incrementing `index`, call a specialized `append_candle(candle_row)` method on the strategy. This method updates the candle list, calculates the newest indicator value using a sliding tail of candles (to avoid full recomputations), appends that value to the precomputed arrays, and then increments the index.

```python
# BaseStrategy live update interface
def append_candle(self, candle_row: np.ndarray) -> None:
    # 1. Update candle list
    self.candles = np.vstack([self.candles, candle_row])
    
    # 2. Update each precomputed indicator by running calculations on a sliding tail
    # (Example using RSI with tail = period * 5 to avoid warmup drift)
    tail_len = self.rsi_period * 5
    new_rsi_val = ta.rsi(self.candles[-tail_len:], period=self.rsi_period, sequential=True)[-1]
    self._rsi_seq = np.append(self._rsi_seq, new_rsi_val)
    
    # 3. Increment index safely
    self.index += 1
```

```
     async for kline in ws_stream:
         strategy.append_candle(candle_row)            ← Updates candles, calculates tail indicators, appends to arrays, increments index
         strategy.before()                              ← O(1) — index lookup (same code as backtest!)
         signal = evaluate(strategy, ...)
```

Key requirement: `warmup_candles` length >= longest indicator period + `max_pivot_bars × 2` + buffer. Re-run `prepare()` periodically every 10K candles for long-lived sessions to wipe out any minor float drift from sliding-tail calculations.

### Edge Cases

| Edge Case | Handling |
|-----------|----------|
| Warmup too short for all indicator periods | `LiveBotManager` fetches extra candles: `max_all_periods + max_pivot * 2 + 50` |
| Very long-lived session (RAM growth) | Periodically re-run `prepare()` on truncated history (every 10K candles) |
| Candle gap (WS disconnection) | On reconnect, re-fetch missed candles and re-run `prepare()` over the updated history |
| Strategy param change mid-session | Restart the symbol loop with new `prepare()` call |
| Multi-timeframe (BestSupertrend) | HTF supertrend pre-computed in `prepare()`; live appends need HTF resample on demand |

---

## 4. Updated `/add-strategy` Template

Every new strategy must implement both `prepare()` and `before()`:

```
class {Name}(BaseStrategy):
    def prepare(self, candles: np.ndarray) -> None:
        # Compute ALL indicators here using sequential=True
        self._rsi_seq = ta.rsi(candles, period=self.rsi_period, sequential=True)
        self._atr = float(ta.atr(candles, period=self.atr_period))

    def before(self) -> None:
        # NO TA-Lib calls — index only
        i = self.index
        self.vars["rsi"] = float(self._rsi_seq[i])
        self.vars["atr"] = self._atr
```

Command also enforces: no TA-Lib imports in `before()`, indicator arrays as `self._*`, typed state dataclass.
