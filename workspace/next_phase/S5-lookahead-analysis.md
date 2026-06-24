# S5 — Lookahead-Bias Analysis

**Goal:** Automatically detect when a strategy "sees the future" — i.e. its entry/exit decisions or
indicator values change when later candles are withheld. This is the #1 source of fake backtest alpha.

---

## Current state (audited)

- **Nothing exists** — no `lookahead`/`recursive`/`walk` scripts in `engine/`.
- We have the seam to do it cleanly: workstream #1 made indicators compute in `prepare(candles)` over
  an explicit array, and the backtest is strictly sequential (orders fill at next-candle open, per
  engine `CLAUDE.md`). So "withhold future candles" = "call `prepare()` on a truncated array."

## Upstream reference (freqtrade `LookaheadAnalysis`)

From `freqtrade/optimize/analysis/lookahead.py`:
1. Run a **full backtest** over the whole range; record every trade's entry/exit candle.
2. For **each trade**, run two shortened backtests:
   - `entry_varHolder`: data truncated to **start … entry candle** (future excluded).
   - `exit_varHolder`: data truncated to **start … exit candle**.
3. Compare indicator columns (full vs cut) at the decision candle via a `.compare()`-style diff; any
   column that differs is flagged as biased.
4. Also re-check that the **entry/exit signal still fires** in the shortened run. If the open/close
   signal is missing when future data is withheld → **false signal** (lookahead).
5. Output: list of biased indicator names, false entry signals, false exit signals, overall verdict.

Key insight: bias = **a decision that depends on candles after the decision candle.**

## Design (Enma-native)

A standalone analysis script (read-only, no DB writes to results) reusing the real backtest path so
it tests the *actual* engine behavior, not a reimplementation.

### `engine/scripts/lookahead.py`
1. **Full run:** execute `run_backtest_simulation` (or a thin wrapper exposing per-candle signals) over
   the full range; capture the trade list with entry/exit indices and the `prepare()`-computed indicator
   arrays (`strategy.vars`).
2. **Truncated re-runs per trade (sampled):** for trade entering at index `e`, build
   `candles_np[:e+1]`, re-instantiate the strategy, call `prepare()`, and read the indicator values +
   the would-be signal **at index `e`**.
3. **Diff:** compare each `strategy.vars[col][e]` full-vs-truncated. Any non-NaN difference beyond a
   float tolerance (`1e-9`) → flag column. Compare the `forecast()` direction at `e` full-vs-truncated;
   a change → false signal.
4. **Sampling:** for large trade counts, sample up to K trades (default 50) + always include the first
   few — full per-trade re-runs are O(trades × N). Log the sample size (no silent truncation).
5. **Report:** print a table (strategy, biased columns, # false entries/exits, verdict) and exit
   non-zero if any bias found (CI-friendly).

### Why it's accurate for Enma
Because indicators are isolated in `prepare(array)`, truncating the array is the exact, faithful way
to withhold the future — no need to instrument every indicator. The as-of multi-TF helper from **S2**
is the most likely bias source, so S5 is its safety net.

## Files to create / modify

| Action | File | Change |
|--------|------|--------|
| Create | `engine/scripts/lookahead.py` | full vs per-trade-truncated diff of indicators + signals |
| Modify | `engine/services/backtest_runner.py` | (if needed) expose a "capture signals/vars" hook for analysis without persisting results |
| Create | `engine/tests/test_lookahead.py` | a deliberately leaky test strategy (reads `candles[-1]` future) is flagged; a clean one is not |

## Verification gate

- **Self-test:** a synthetic strategy that peeks at a future candle (`vars["x"] = close[i+1]`) MUST be
  flagged; the 5 seeded strategies (post-workstream-#1, no lookahead) MUST pass clean.
- Determinism: same input → same verdict (no RNG).

## Sequencing & risks

- After **S2** — its primary job is to validate the multi-TF alignment. Run it on every strategy that
  uses `htf()`.
- Risk: cost. Per-trade re-runs are expensive; the sampling cap keeps it bounded. Document the cap in
  output so a "clean" verdict isn't mistaken for exhaustive.
- Risk: NaN handling in the diff (warmup region). Compare only where both runs are non-NaN.
