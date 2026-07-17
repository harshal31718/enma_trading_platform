# MCPT Repo Analysis — neurotrader888/mcpt

**Source:** https://github.com/neurotrader888/mcpt  
**License:** MIT  
**Language:** Python 100%  
**Core Concept:** Monte Carlo Permutation Tests (MCPT) for trading strategy validation

---

## 1. Overview

The repo implements a **permutation-based statistical test** to answer the question: *"Is my strategy's performance significantly better than what would be expected by chance on data with the same statistical properties?"*

Instead of bootstrapping (sampling with replacement), it **shuffles relative price movements** across time bars to create synthetic price series that preserve:

- Mean, variance, skewness, kurtosis of returns
- Volatility clustering (to some extent)
- Cross-market correlation structure
- Intra-bar structure (open→high→low→close relationships)

Then it runs the same strategy on the permuted data and compares the real performance against the distribution of permuted performances to compute a **p-value**.

---

## 2. File-by-File Analysis

### 2.1 `bar_permute.py` — Core Permutation Engine

**Purpose:** The foundation of the entire repo. Generates a synthetic OHLC series by permuting the *relative* price movements of the original data.

**How it works (step-by-step):**

1. **Convert to log space** — All prices are log-transformed so that relative movements become additive.
2. **Extract relative values:**
   - `relative_open`: `log(open) - log(prev_close)` — the gap from previous close to current open
   - `relative_high`: `log(high) - log(open)` — intra-bar upward movement
   - `relative_low`: `log(low) - log(open)` — intra-bar downward movement
   - `relative_close`: `log(close) - log(open)` — intra-bar close relative to open
3. **Independent shuffle:**
   - `relative_high`, `relative_low`, `relative_close` are shuffled together (same permutation) — preserves intra-bar patterns
   - `relative_open` is shuffled independently — breaks serial dependence in gap structure
4. **Rebuild bars sequentially:** Starting from the real start bar, each synthetic bar is built:
   - `open[i] = close[i-1] + shuffled_relative_open[i]`
   - `high[i] = open[i] + shuffled_relative_high[i]`
   - `low[i] = open[i] + shuffled_relative_low[i]`
   - `close[i] = open[i] + shuffled_relative_close[i]`
5. **Convert back** from log space via `exp()`.

**Key insight:** The permutation preserves the *unconditional* distribution of price movements but destroys *serial dependence* (autocorrelation, regime changes, trend structure). If a strategy performs well on permuted data, it's likely exploiting randomness rather than real structure.

**Multi-market support:** Accepts a list of DataFrames, permutes each independently, but the `start_index` is aligned. Cross-market correlation is preserved because the original correlation structure is embedded in how the relative values co-move.

```python
# Core signature
def get_permutation(
    ohlc: Union[pd.DataFrame, List[pd.DataFrame]],
    start_index: int = 0,
    seed=None
) -> Union[pd.DataFrame, List[pd.DataFrame]]:
```

**Enma relevance:** HIGH. This is the primary thing to port. It should live in `engine/` as a statistical utility available to any strategy or backtest pipeline.

---

### 2.2 `donchian.py` — Donchian Breakout Strategy

**Purpose:** Classic Donchian channel breakout strategy with in-sample optimization and walkforward variants.

**Components:**

#### `donchian_breakout(ohlc, lookback)`
- Upper channel: `rolling(lookback-1).max().shift(1)` — highest close over lookback, excluding current bar
- Lower channel: `rolling(lookback-1).min().shift(1)` — lowest close over lookback, excluding current bar
- Signal: `1` when close > upper, `-1` when close < lower, forward-filled

```python
upper = ohlc['close'].rolling(lookback - 1).max().shift(1)
lower = ohlc['close'].rolling(lookback - 1).min().shift(1)
signal = pd.Series(np.full(len(ohlc), np.nan), index=ohlc.index)
signal.loc[ohlc['close'] > upper] = 1
signal.loc[ohlc['close'] < lower] = -1
signal = signal.ffill()
```

#### `optimize_donchian(ohlc)`
- Iterates lookback from 12 to 168 bars
- Computes profit factor for each: `sum(positive returns) / sum(|negative returns|)`
- Returns `(best_lookback, best_pf)`

```python
r = np.log(ohlc['close']).diff().shift(-1)
for lookback in range(12, 169):
    signal = donchian_breakout(ohlc, lookback)
    sig_rets = signal * r
    sig_pf = sig_rets[sig_rets > 0].sum() / sig_rets[sig_rets < 0].abs().sum()
```

#### `walkforward_donch(ohlc, train_lookback, train_step)`
- Trains on a rolling window, re-optimizes every `train_step` bars
- Default: 4 years training (`24*365*4`), 1 month step (`24*30`)

**Enma relevance:** HIGH. Donchian is a classic trend-following strategy. Could be added as a built-in strategy in the engine's strategy registry.

---

### 2.3 `moving_average.py` — MA Crossover (Reference)

**Purpose:** Simple 10/30-period moving average crossover. Used as a baseline/example strategy.

```python
fast_ma = df['close'].rolling(10).mean()
slow_ma = df['close'].rolling(30).mean()
df['signal'] = np.where(fast_ma > slow_ma, 1, 0)
df['return'] = np.log(df['close']).diff().shift(-1)
df['strategy_return'] = df['signal'] * df['return']
```

**Enma relevance:** LOW — trivial example. The pattern of `signal * forward_returns` is useful as a consistent return-calculation pattern.

---

### 2.4 `tree_strat.py` — Decision Tree Strategy

**Purpose:** A DecisionTreeClassifier-based strategy using price change features.

**Features:**
- `diff6` = log price change over 6 hours
- `diff24` = log price change over 24 hours
- `diff168` = log price change over 168 hours (7 days)

**Target:** Sign of next 24-hour forward return, binarized to {0, 1}.

**Model:** `DecisionTreeClassifier(min_samples_leaf=5, random_state=69)`

The `tree_strategy()` function applies the trained model and computes profit factor.

**Warning in the code:** `# This is trash :)` — The author considers it a toy. However, the pattern of replacing it with a real ML model is the key takeaway.

**Enma relevance:** MEDIUM. The ML strategy pattern (feature extraction → model → signal → pf) is useful. The `tree_strat.py` style of separating `train_tree()` and `tree_strategy()` is a good pattern to follow for ML-based strategies.

---

### 2.5 `insample_donchian_mcpt.py` — In-Sample Donchian MCPT

**Purpose:** Apply MCPT to the in-sample Donchian optimization. The real workflow:

1. Optimize Donchian on real training data → get `best_real_pf`
2. For N=1000 permutations:
   a. Generate permuted OHLC via `get_permutation(train_df)`
   b. Re-run `optimize_donchian` on permuted data
   c. Record the best profit factor
3. Compute p-value: `count(perm_pf >= real_pf) / N`

```python
n_permutations = 1000
perm_better_count = 1  # +1 for the real data itself
for perm_i in tqdm(range(1, n_permutations)):
    train_perm = get_permutation(train_df)
    _, best_perm_pf = optimize_donchian(train_perm)
    if best_perm_pf >= best_real_pf:
        perm_better_count += 1
    permuted_pfs.append(best_perm_pf)

insample_mcpt_pval = perm_better_count / n_permutations
```

**Critical insight:** This tests whether the optimization process itself finds patterns. Even if a strategy has no edge, optimization over many parameters will find the one with the best PF by luck. MCPT measures how often similar luck occurs on permuted data.

**Enma relevance:** VERY HIGH. This is the most important workflow to integrate. It validates the *entire strategy optimization pipeline*, not just a fixed strategy.

---

### 2.6 `insample_tree_mcpt.py` — In-Sample ML Tree MCPT

**Purpose:** Same as above, but for the decision tree strategy. Tests whether the trained tree's PF is statistically significant.

```python
real_tree = train_tree(train_df)
real_is_signal, real_is_pf = tree_strategy(train_df, real_tree)

for perm_i in range(1, n_permutations):
    train_perm = get_permutation(train_df)
    perm_nn = train_tree(train_perm)
    _, perm_pf = tree_strategy(train_perm, perm_nn)
    if perm_pf >= real_is_pf:
        perm_better_count += 1
```

**Enma relevance:** VERY HIGH. This is the template for validating ANY ML-based strategy in Enma. The pipeline is:
1. Train model on real data → get performance
2. Permute data → retrain same model → get performance
3. Compare — if real doesn't beat permuted distribution, the model is overfitting

---

### 2.7 `walkforward_donchian_mcpt.py` — Walkforward MCPT

**Purpose:** The most realistic variant — applies MCPT to a walkforward optimization, not in-sample.

**Key difference from in-sample:** The permutation must respect the walkforward train/test split. The `start_index` parameter in `get_permutation` keeps the first `train_window` bars intact (for initial training) and only permutes from that point onward.

```python
df['donch_wf_signal'] = walkforward_donch(df, train_lookback=train_window)
donch_rets = df['donch_wf_signal'] * df['r']
real_wf_pf = donch_rets[donch_rets > 0].sum() / donch_rets[donch_rets < 0].abs().sum()

for perm_i in range(1, n_permutations):
    wf_perm = get_permutation(df, start_index=train_window)
    wf_perm_sig = walkforward_donch(wf_perm, train_lookback=train_window)
    perm_pf = ...
```

**Enma relevance:** VERY HIGH. Walkforward MCPT is the gold standard for strategy validation. It tests whether the **entire walkforward process** (periodic re-optimization) generates real alpha.

---

## 3. Key Statistical Concepts

### 3.1 MCPT vs Bootstrap

| Method | Approach | Preserves | Destroys |
|--------|----------|-----------|----------|
| **Bootstrap** | Sample bars with replacement | Empirical distribution | Temporal order, volatility clustering |
| **MCPT** | Shuffle relative movements within bars | Return distribution, intra-bar structure, cross-market correlation | Serial dependence, autocorrelation, trends |

MCPT is superior for trading strategies because it preserves more realistic microstructure while still breaking the signal a strategy exploits.

### 3.2 P-Value Interpretation

- **p < 0.01:** Strong evidence the strategy finds real structure
- **p < 0.05:** Moderate evidence
- **p > 0.05:** Strategy may be overfitting to noise
- **p ≈ 0.5:** Strategy is indistinguishable from random

### 3.3 Why 1000 Permutations?

The repo uses 1000 permutations in-sample and 200 for walkforward (computational cost). With 1000 permutations, the minimum non-zero p-value is 0.001.

---

## 4. Integration Roadmap for Enma

### Phase 1: Port Core Permutation Engine

**File:** `engine/app/core/permutation.py` (or similar)

```python
# Pseudocode for Enma integration
class BarPermuter:
    def __init__(self, ohlc: pd.DataFrame):
        self.ohlc = ohlc
        
    def get_permutation(self, start_index: int = 0, seed: int = None) -> pd.DataFrame:
        """Returns a permuted OHLC DataFrame."""
        # Port bar_permute.py logic exactly
        
    def get_multi_permutation(self, ohlc_list: List[pd.DataFrame], ...) -> List[pd.DataFrame]:
        """Multi-market permutation preserving cross-correlation."""
```

**Considerations:**
- Must use NumPy for performance (not pure Python loops)
- Should accept the same column naming conventions Enma uses
- Add a `numba` JIT decorator if the loop becomes a bottleneck
- The `start_index` parameter is critical for walkforward MCPT

### Phase 2: MCPT Test Harness

**File:** `engine/app/core/mcpt.py`

```python
class MCPTester:
    def __init__(
        self,
        strategy_fn: Callable,  # Function that takes OHLC, returns (signals, performance)
        ohlc: pd.DataFrame,
        n_permutations: int = 1000,
        start_index: int = 0,
        walkforward: bool = False
    ):
        ...
    
    def run(self) -> MCPTResult:
        """Returns p-value, permuted distribution, real performance."""
```

**This should be generic enough to work with any Enma strategy.** The strategy function should have a standard interface.

### Phase 3: API Endpoint

**Location:** `server/` → routes a request to `engine/`

```json
POST /api/backtest/mcpt
{
    "strategy_id": "donchian_breakout",
    "parameters": { "lookback": 20 },
    "symbols": ["BTCUSDT"],
    "timeframe": "1h",
    "start": "2020-01-01",
    "end": "2023-01-01",
    "n_permutations": 500,
    "walkforward": true,
    "walkforward_params": { "train_lookback": 35040, "train_step": 720 }
}
```

**Response:**
```json
{
    "real_profit_factor": 1.42,
    "mcpt_p_value": 0.023,
    "permuted_performance_distribution": [0.89, 0.92, ..., 1.15],
    "percentile": 97.7,
    "significant": true
}
```

### Phase 4: UI Visualization

**Location:** `client/` — new page/section

- Histogram of permuted PFs with real PF as vertical line (exactly as the matplotlib charts do)
- P-value display with color coding (green if significant, red if not)
- Strategy parameter sensitivity: run MCPT across different parameter sets
- Multi-strategy comparison table with MCPT p-values

---

## 5. Specific Code Patterns to Adopt

### 5.1 Return Calculation Convention

```python
r = np.log(close).diff().shift(-1)  # Forward-looking log returns
```

Shifted forward so that `signal * r` aligns signal at bar `t` with the return from `t` to `t+1`. This is essential for correct backtesting.

### 5.2 Profit Factor Definition

```python
profit_factor = rets[rets > 0].sum() / rets[rets < 0].abs().sum()
```

Clean, handles NaN implicitly. Could be extracted as a utility function.

### 5.3 Walkforward Structure

```python
next_train = train_lookback
for i in range(next_train, n):
    if i == next_train:
        # Re-optimize
        best_lookback, _ = optimize_donchian(ohlc.iloc[i-train_lookback:i])
        next_train += train_step
    # Apply current optimal parameters
    wf_signal[i] = tmp_signal.iloc[i]
```

This is a clean walkforward pattern. Enma's engine already has walkforward capability (`walkforward_optimization` in CURRENT_STATE.md?), but this pattern is worth reviewing.

### 5.4 Histogram + Vertical Line Visualization

```python
pd.Series(permuted_pfs).hist(color='blue', label='Permutations')
plt.axvline(best_real_pf, color='red', label='Real')
```

Simple, effective. The client should replicate this with Chart.js or Recharts.

---

## 6. Potential Adaptations for Enma

### 6.1 Multi-Timeframe MCPT

The current MCPT works on a single timeframe. Enma could extend this to:
- Permute different timeframes independently for multi-timeframe strategies
- Check whether the strategy's edge is robust across aggregation levels

### 6.2 Strategy-Agnostic MCPT Interface

Design a generic MCPT that accepts any strategy with a standard interface:

```python
# Standard strategy interface for MCPT
class MCPTCompatibleStrategy:
    def generate_signals(self, ohlc: pd.DataFrame) -> pd.Series:
        """Returns signal series (-1, 0, 1)"""
        ...
    
    def get_performance_metric(self, ohlc: pd.DataFrame) -> float:
        """Returns a single performance metric (e.g., profit factor, Sharpe)"""
        ...
```

### 6.3 Alternative Metrics Beyond Profit Factor

The repo uses only profit factor. Enma could extend to:
- Sharpe ratio
- Sortino ratio
- Calmar ratio
- Maximum drawdown
- Win rate
- Return per unit of turnover
- Combined multi-metric p-value

### 6.4 Permutation of Feature Matrices for ML Strategies

For ML strategies, an alternative approach: instead of permuting OHLC then regenerating features, you could permute the feature matrix directly (shuffle rows independently). This is statistically weaker but computationally cheaper.

### 6.5 Sequential Permutation for High-Frequency Data

For tick or 1-minute data, the current bar-level permutation might not be sufficient. Consider:
- Permute within volatility regimes
- Use a block permutation to preserve microstructure patterns at small scales

---

## 7. Risks and Limitations

| Limitation | Impact | Mitigation |
|-----------|--------|------------|
| Permutation destroys autocorrelation but also genuine patterns | May falsely reject strategies that exploit autocorrelation | Use multiple null hypotheses (iid shuffle, GARCH residuals, etc.) |
| Cross-market correlation is only preserved if you permute all markets with the same indexing | The algorithm reorders all markets identically per column type | Verify the multi-market path works for Enma's data formats |
| P-value granularity is limited by permutation count | With 200 permutations, p-value can only be multiples of 0.005 | Default to 1000+ permutations; allow user config |
| The permutation assumes relative movements are i.i.d. | Some market regimes have different distributions of relative movements | Consider regime-aware permutation |
| No transaction costs or slippage in the original code | Strategies may look good on permuted data but be unprofitable with costs | Enma already handles these in its backtesting engine — just ensure costs are applied before computing PF |

---

## 8. Summary: What to Take

| Component | Priority | Effort | Location in Enma |
|-----------|----------|--------|-------------------|
| Bar permutation engine (`bar_permute.py`) | **P0 — Critical** | ~1 day | `engine/app/core/permutation.py` |
| In-sample MCPT workflow | **P0 — Critical** | ~0.5 day | `engine/app/core/mcpt.py` |
| Walkforward MCPT workflow | **P0 — Critical** | ~1 day | `engine/app/core/mcpt.py` |
| Donchian breakout strategy | P1 — High | ~0.5 day | `engine/app/strategies/builtin/donchian.py` |
| MCPT API endpoint | P1 — High | ~1 day | `server/` routes → `engine/` |
| MCPT UI (histogram + p-value) | P2 — Medium | ~1 day | `client/` new page |
| Recommendation tree strategy | P3 — Low | N/A | Already have better ML via transformers |
| MA crossover | P3 — Low | N/A | Trivial reference example |

---

## 9. Directory Structure Proposal for Enma

```
engine/
  app/
    core/
      permutation.py          # BarPermuter class (port of bar_permute.py)
      mcpt.py                 # MCPTester class (generic MCPT framework)
    strategies/
      builtin/
        donchian.py           # Donchian breakout + optimization
        # ... existing Enma strategies
    api/
      routes/
        mcpt.py               # MCPT API endpoint
      schemas/
        mcpt_schema.py         # Request/response models

server/
  src/
    routes/
      mcptRoutes.ts           # Proxy to engine MCPT endpoint
    controllers/
      mcptController.ts

client/
  src/
    pages/
      MCPTResults.tsx          # MCPT results display page
    components/
      mcpt/
        PermutationHistogram.tsx
        MCPTReport.tsx
```

---

## 10. Quick Start Code to Port

### `bar_permute.py` → `engine/app/core/permutation.py`

The core function is self-contained and only depends on `numpy` and `pandas` — both already available in Enma's engine. The port is straightforward:

```python
import numpy as np
import pandas as pd
from typing import List, Union, Optional

class BarPermuter:
    """Generates synthetic OHLC data by permuting relative price movements."""
    
    def __init__(self, seed: Optional[int] = None):
        self.seed = seed
        
    def permute(
        self,
        ohlc: Union[pd.DataFrame, List[pd.DataFrame]],
        start_index: int = 0
    ) -> Union[pd.DataFrame, List[pd.DataFrame]]:
        """Returns permuted OHLC preserving stat properties."""
        np.random.seed(self.seed)
        # ... exact logic from bar_permute.py
```

### `mcpt.py` — Generic Test Harness

```python
class MCPTResult(BaseModel):
    real_performance: float
    p_value: float
    permuted_performances: List[float]
    n_permutations: int
    is_significant: bool
    confidence_level: float = 0.95

class MCPTester:
    def __init__(
        self,
        strategy: Any,  # Strategy object with run() method
        ohlc: pd.DataFrame,
        n_permutations: int = 1000,
        start_index: int = 0,
        walkforward_params: Optional[dict] = None
    ):
        ...
    
    def execute(self) -> MCPTResult:
        real_pf = self._compute_performance(self.ohlc)
        
        better_count = 1
        perm_performances = []
        
        for _ in range(self.n_permutations - 1):
            perm_ohlc = BarPermuter().permute(self.ohlc, self.start_index)
            perm_pf = self._compute_performance(perm_ohlc)
            if perm_pf >= real_pf:
                better_count += 1
            perm_performances.append(perm_pf)
        
        p_value = better_count / self.n_permutations
        return MCPTResult(
            real_performance=real_pf,
            p_value=p_value,
            permuted_performances=perm_performances,
            n_permutations=self.n_permutations,
            is_significant=p_value < 0.05
        )
```

---

## 11. Conclusion

This repo provides a **statistically rigorous framework for strategy validation** that Enma currently lacks. The core idea is simple but powerful: compare your strategy's performance against its performance on shuffled data to detect overfitting.

**The top priorities are:**
1. Port `bar_permute.py` → Enma's engine core
2. Build a generic `MCPTester` that works with any Enma strategy
3. Expose as an API endpoint
4. Build the UI visualization

This feature would be a **major differentiator** for Enma — most backtesting platforms only report absolute performance metrics without any statistical significance test.
