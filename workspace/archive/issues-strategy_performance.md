# Analysis: Strategy Performance, Risk Limits & Solutions Brainstorming

Originally from `workspace/issues_and_solutions/issues/strategy_performance.md` (merged into `plan/` 2026-06-24). Updated on 2026-06-24 with deep-dive solutions, alternative designs, and trade-off analyses.

---

## 1. O(N²) Indicator Recomputation in All 5 Strategies

**Root cause:** `BaseStrategy.before()` is called inside the backtest simulation loop with `strategy.candles = candles_np[:t+1]` growing by 1 each iteration. Strategies recompute full indicator arrays from scratch every tick instead of computing once and indexing.

| Strategy | Hot Path Indicator Calls per Candle | Complexity |
|----------|-------------------------------------|------------|
| MicroMacroRSIDivergence | `ta.rsi`, `ta.atr`, `ta.pivot_high` (2×), `ta.pivot_low` (2×), `_smoothed_rsi` | O(N²) — worst offender |
| MultiDivergence | `ta.rsi`, `ta.mfi`, `ta.stochastic`, `ta.adx`, `ta.macd`, `ta.obv`, `ta.pivot_high`, `ta.pivot_low` + z-score, swing | O(N²) — 9 oscillator sources |
| MicroScalper | `ta.ema` (4×), `ta.atr` (1 scalar + 1 sequential) | O(N²) — slice EMAs are worst |
| BestSupertrend | `ta.sma` (4×), `ta.atr` (sequential), pandas resample, backward loop for cross detection | O(N²) — pandas resample in hot loop |
| AdaptiveTrend | `ta.ema` (6×), `ta.atr` (1 scalar + 1 sequential) | O(N²) — already has partial fix but still O(N) per tick |

**Impact:** 100K+ candle backtests are unnecessarily slow. Latency grows quadratically with candle count.

### Brainstormed Solutions & Various Ways to Solve

#### Option 1.A: Vectorized Batch Pre-computation (Two-Phase `prepare()` + `before()`) — [RECOMMENDED]
*   **Design:** Compute all indicators for the entire backtest range *once* before the simulation loop starts. Save the result as full-length arrays. During the simulation loop, `before()` acts as a simple index lookup: `self.vars["val"] = self._indicator_array[self.index]`.
*   **Pros:**
    *   Maximum possible performance gain for backtesting. Vectorized library calls (TA-Lib / NumPy) run at C-speed over contiguous memory.
    *   No change to alpha logic structure; only relocates indicator instantiation.
*   **Cons:**
    *   Requires the full candle history up-front.
    *   Cannot react if indicators depend on runtime mutations (which they do not in our standard strategies).
    *   Higher memory usage for very long historical runs (not a bottleneck for our 100k candle runs).

#### Option 1.B: Sliding-Window Recalculation (O(W) complexity)
*   **Design:** Slice a fixed-size window of recent candles (e.g., `self.candles[-200:]`) and run indicators only on that slice.
*   **Pros:**
    *   Caps complexity to O(W) per step, where W is the window size. Keeps calculation size constant regardless of backtest length.
    *   Doesn't require up-front knowledge of the entire dataset, aligning naturally with live WS streams.
*   **Cons:**
    *   Still recalculates indicators on every tick (redundant work).
    *   EMA and other recursive indicators will experience "warmup drift" unless the window is excessively large (often needs 5× the longest period).

#### Option 1.C: Stateful Incremental Updates (O(1) complexity)
*   **Design:** Implement mathematical formulas for incremental updates (e.g., updating an EMA using only the previous tick's EMA and the new candle's close: $EMA_t = (Close_t \times k) + (EMA_{t-1} \times (1 - k))$).
*   **Pros:**
    *   O(1) time complexity. Extremely memory efficient.
    *   Ideal for high-frequency or long-running live sessions.
*   **Cons:**
    *   Requires writing custom, hand-coded incremental formulas for every indicator (cannot use standard TA-Lib out-of-the-box).
    *   High risk of cumulative floating-point precision drift.
    *   Complex indicators (like swing-pivots or resampled pandas klines) are hard to model incrementally.

---

## 2. Risk Model Limitations (6 Issues)

| # | Issue | Severity | File | Detail |
|---|-------|----------|------|--------|
| 1 | Fixed R:R target — static take-profit | HIGH | `risk.py:137-153` | `tp = price ± rrr × |price - stop|` — no adaptation as trade develops |
| 2 | Static bracket on divergence strategies | HIGH | `risk.py:83-168` | Only `ChandelierRiskModel` (AdaptiveTrend) trails; MicroMacroRSI and MultiDivergence use static `AtrBracketRiskModel` |
| 3 | ATR is backward-looking | MEDIUM | `talib_adapter.py:56-61` | ATR(14) = average of last 14 candles; stale during volatility spikes |
| 4 | Max notional can override risk budget | LOW | `portfolio.py:109-115` | Notional cap sizes position below what risk model allows |
| 5 | Cost gate defaults off | MEDIUM | `portfolio.py:30` | `min_edge_mult = 0.0` → always trade, never gate on cost |
| 6 | No portfolio-level exposure tracking | LOW (single) / HIGH (chaos) | `portfolio.py` | Each trade sized independently; no aggregate check |

---

### Brainstormed Solutions & Various Ways to Solve

#### Issue 1: Fixed R:R target — static take-profit
*   **Option 1.A: Time-Decay take profit.**
    *   *Design:* Reduce the take-profit distance dynamically as bars-held increases: `tp_price = entry_price + (initial_tp_distance * exp(-decay_rate * bars_held))`.
    *   *Rationale:* The longer a trade stays open, the lower the probability of hitting a high R:R target, while exposure to tail risk remains constant.
*   **Option 1.B: Volatility-Adjusted dynamic TP.**
    *   *Design:* Re-assess the TP price on each candle based on the current ATR. If ATR compresses, bring the TP closer to secure profits; if ATR expands, let the target stretch.
*   **Option 1.C: Multi-Stage Scale-Outs.**
    *   *Design:* Split target portfolio into portions (e.g., exit 50% at 1.5R, 30% at 2.5R, trail the remaining 20% using Chandelier stop).

#### Issue 2: Static bracket on divergence strategies
*   **Option 2.A: Composable Risk Trailing Decorator.**
    *   *Design:* Implement a trailing stop decorator or mixin that can wrap *any* `RiskModel` (including `AtrBracketRiskModel`). It monitors the peak price since entry and moves the SL up/down by `trail_atr_mult * ATR` only when it tightens the stop.
*   **Option 2.B: Pivot-based Trailing stops.**
    *   *Design:* Re-compute trailing stops based on the most recently confirmed swing high/low instead of a fixed ATR multiple. For a long trade, the stop is moved to the lowest low of the last N candles or the last confirmed swing low.

#### Issue 3: ATR is backward-looking
*   **Option 3.A: Exponential ATR (eATR).**
    *   *Design:* Replace SMA-smoothed ATR with an EMA-smoothed ATR. Recent volatility is weighted more heavily, reacting faster to spikes.
*   **Option 3.B: Bollinger Band Width or Standard Deviation Ratio.**
    *   *Design:* Scale ATR dynamically using a short-term standard deviation normalized by a longer-term standard deviation.
*   **Option 3.C: Kaufman's Efficiency Ratio (ER) Adaptive ATR.**
    *   *Design:* Shorten ATR calculation period when the market is highly direct (momentum) to react instantly, and lengthen it during choppy, sideways markets to avoid noise.

#### Issue 4: Max notional can override risk budget
*   **Option 4.A: Leverage-Affordability Diagnostics.**
    *   *Design:* Sizer detects when the position is clipped by `max_notional` and calculates the "Risk Budget Coverage Pct". If the actual size represents less than 80% of the budgeted size, log a trade-level warning or output diagnostic fields on `backtestResults`.
*   **Option 4.B: Dynamic Leverage Scaling.**
    *   *Design:* If the risk budget allows a larger size but is limited by the current leverage setting, dynamically increase the position's leverage (clamped by symbol maximums) to scale up size while maintaining the same cash margin.

#### Issue 5: Cost gate defaults off
*   **Option 5.A: Active Edge-vs-Cost Hurdle (Veto).**
    *   *Design:* Set default `min_edge_mult = 1.0`. Compare the expected price move (magnitude) against the transaction cost (fee + slippage estimate). Veto entries where `predicted_move * entry_price < cost.total * min_edge_mult`.
*   **Option 5.B: Market Impact Sizing Penalization.**
    *   *Design:* Scale down target position size when trade size is large relative to order book depth, directly factoring expected execution slippage into the sizing equation.

#### Issue 6: No portfolio-level exposure tracking
*   **Option 6.A: Centralized Exposure Manager.**
    *   *Design:* Introduce a `PortfolioExposureManager` service that tracks active sessions. The PCM query interface checks total active margin, net directional beta, and asset correlation. Sizing is scaled down or vetoed if total exposure boundaries are violated.
*   **Option 6.B: Volatility-adjusted Capital Allocation.**
    *   *Design:* Reduce the capital allocated to new sessions in Chaos Mode if overall market volatility (average index ATR) is high, reserving margin capital for drawdowns.

---

## 3. Live / Backtest Synchronization Gap

**Problem:** `LiveBotManager._run_symbol_loop()` loads warmup candles and appends WS data, calling `before()` each tick. Currently `before()` recomputes over the entire growing array (warmup + all live candles).

*   Latency grows linearly with session duration.
*   First iteration after warmup = O(W) where W = warmup size.
*   1000th live iteration = O(W + 1000).
*   Pivot confirmation needs `right` lookback bars — must work identically in live mode.
*   Candle gap on WS disconnection requires re-fetch + re-prepare.

### Brainstormed Solutions & Various Ways to Solve

#### Option 3.A: Dual-Mode Sliding Queue (Buffer Recalculation) — [RECOMMENDED]
*   **Design:** Maintain a fixed sliding queue of length `K = MIN_WARMUP_CANDLES + buffer` (e.g., last 500 candles). In live mode, when a new candle arrives, append to queue, pop the oldest, and run `prepare()` on this constant-sized array.
*   **Pros:**
    *   Time complexity per tick remains O(1) relative to session runtime (strictly capped at O(K) calculations).
    *   Easy to maintain parity with backtest (uses same adaptor/TA-Lib math on the slice).
*   **Cons:**
    *   Still does W-length computations on every tick, which is less optimal than incremental updates but perfectly acceptable for live loops (millisecond range).

#### Option 3.B: State-Caching and Tail Updates
*   **Design:** Retain the full historical candle array in RAM. On each new candle, compute indicators *only* on the new value (or the last few bars for indicators requiring historical window overlaps) and append it to the cached indicator arrays.
*   **Pros:**
    *   True O(1) calculation step on every live candle tick.
*   **Cons:**
    *   Indicators like MACD and EMA depend on historical recursion; appending requires preserving internal state (e.g., previous candle's EMA value).
    *   If a websocket disconnection occurs and candles are missed, the cache must be fully discarded and recomputed from scratch.

#### Option 3.C: Periodic Sync and Gap Reconciliation
*   **Design:** On WS disconnect, query REST API for missed candles, append them to the queue, and run a full `prepare()` pass to catch up. Run a full `prepare()` pass every 1,000 candles to clear any floating-point drift.
