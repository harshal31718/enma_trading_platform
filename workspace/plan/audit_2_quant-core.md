# 05 — Algotrading Core Deep-Dive: Quant Correctness Audit

**Shelf:** audit (evidence) · **Date:** 2026-07-14 · **Formerly:** `refinements/05_algotrading_deep_dive.md`
**Scope:** the quant core only — backtest runner, execution kernel, fill/margin/position models,
metrics, optimizer, Monte Carlo, leverage sensitivity, and the live candle loop's *trading*
semantics. Architecture/security issues already live in `audit_1_system-design.md` (SEC/ENG/SRV/SYS) and are
not restated. New issue IDs here use the **QNT-*** prefix.
**Confidence:** [Certain] verified by reading the exact code paths cited · [Likely] strong inference.
**Severity:** H / M / L — for *decision quality* (backtests drive strategy/param/leverage
decisions; a wrong backtest is a wrong trade later).

> Companion plan: [`9_backtest-and-optimizer-correctness.md`](9_backtest-and-optimizer-correctness.md)
> — the remediation plan derived from this audit. This file is the evidence; that file is the work.

---

## 1. Correctness defects (new findings, code-verified)

### QNT-1 (H) [Certain] — Multi-symbol portfolio backtests never fire SL / TP / liquidation / funding

The single worst finding in this audit.

`BacktestAdapter.execute_entry` sets `strategy._entered_this_candle = True` on every entry
(`backtest_runner.py:372`). The flag is cleared in exactly two places: `record_equity()`
(`backtest_runner.py:543-545`) and `execute_flip` (`:534`). `kernel.check_exits` early-returns
whenever the flag is truthy (`kernel.py:204`).

`_run_shared_portfolio()` (the F-017 multi-symbol path) **never calls `record_equity`** — it
records portfolio equity itself. Consequence chain, per symbol, after its first non-flip entry:

- `check_exits` returns early on **every subsequent candle** — stop-loss, take-profit and
  liquidation checks are skipped for the life of the position;
- `position.update_pnl()` (inside `check_exits`, after the early return) never runs — unrealized
  PnL stays 0.0, so `_portfolio_unrealized()` and the portfolio equity curve are wrong;
- `charge_funding()` (also inside `check_exits`) never runs;
- per-trade `_mfe`/`_mae` excursions (updated in `record_equity`) are never updated —
  `runUpPct`, `drawdownPct`, and the MFE/MAE scatter are wrong.

Positions in multi-symbol runs exit only via strategy-driven `close_position()`, flips,
scale-outs, or the end-of-run force-close. Four of the five seeded strategies are
bracket-based (ATR SL/TP) — **every multi-symbol backtest result currently in Mongo is
structurally invalid**, and the equity curves shown for them are fiction.

Why nothing caught it: the golden master (`scripts/golden_master.py`) runs **single-symbol
BTCUSDT only**, and no test exercises multi-symbol exits (`tests/` grep: no multi-symbol
bracket assertions).

*Fix direction:* the flag is per-candle state that belongs to the kernel loop, not to the
strategy object. Clear it in `_run_shared_portfolio` after the three kernel steps (minimal fix),
then relocate it into the kernel as a local (structural fix). Add a 2-symbol golden-master
scenario and a test asserting `exitReason == "stop_loss"` occurs in a portfolio run.

### QNT-2 (H) [Certain] — Exec-algo mode silently destroys strategy close and flip intents

`kernel.evaluate_and_route`, exec-algo branch (`kernel.py:335-340`): when a TWAP/VWAP/Iceberg
algo is configured, the kernel unconditionally clears `strategy.buy`, `strategy.sell`,
`strategy._pending_flip`, **and** `strategy._close_at_open` before re-routing.

But `DefaultExecution.route()` encodes a close as `_close_at_open = True` **and returns
`None`** (Path 2), and a flip as `flip_position()` **and returns `None`** (Path 4). With
`plan == None`, nothing re-creates the intent — it is erased. With any exec-algo enabled:

- `close_position()` never executes — positions exit only via SL/TP;
- flips never execute at all (SignalExit-style strategies like BestSupertrend, which trade by
  flipping, would simply stop reversing);
- the guard inside `TWAPAlgorithm.process_order_plan` that checks `_close_at_open` /
  `_pending_flip` is dead code — the kernel cleared both before calling it.

`tests/test_exec_algo_slicing.py` covers slicing of entries only; no test closes or flips a
position with an exec-algo active. The golden master runs without exec-algos, so this is also
invisible to Rule C.

*Fix direction:* snapshot `_close_at_open` / `_pending_flip` before the clear and pass exits
and flips through unsliced (the algos' own docstrings already say exits should not be sliced).

### QNT-3 (M) [Certain] — Entry-candle exits are impossible in backtest, but happen in live

The same `_entered_this_candle` flag means single-symbol backtests skip exit checks on the
candle a position was entered (entered at open of candle *t* → SL/TP/liquidation not evaluated
against candle *t*'s high/low; first check is candle *t+1*). In live, SL/TP exist as
exchange-side conditional orders that are active immediately after the entry fill.

This is an **optimistic** bias (an adverse move that would stop the trade out in the first
candle is ignored) and a backtest/live parity break — the mirror image of the documented
pessimism in ENG-18 (SL-before-TP), but undocumented. Freqtrade evaluates exits on the entry
candle. On lower timeframes and tight ATR stops (MicroScalper) the effect is material.

### QNT-4 (M) [Certain] — Liquidation modeling gaps

`execute_exit` liquidation branch (`backtest_runner.py:382-387`): books `realized_pnl = -margin`,
`pnl_pct = -100`, no fee. Missing/mismatched vs Binance:

- no **liquidation clearance fee** (Binance charges the liquidation order at taker fee against
  the insurance fund — the wallet loses margin *plus* fee);
- liquidation is triggered on candle **last-price** extremes (`is_liquidated(high, low)`) while
  Binance liquidates on **mark price** — last-price wicks overstate liquidation frequency in
  thin candles and understate it during mark/last divergence;
- the MMR table is the BTC bracket table for every symbol (documented in `margin.py`, fine),
  but note the interaction: alts have higher MMR, so alt liquidations are *understated* while
  wick-triggering *overstates* — two unquantified errors in opposite directions.

### QNT-5 (M) [Certain] — Funding model: flat constant, charged at the wrong price, one-signed

`charge_funding` (`backtest_runner.py:282-291`): uses the **current candle's close** for every
funding boundary crossed since the last charge (not the price at each boundary), a single
constant user-supplied rate (default `0.0` — funding disabled unless the user types a number),
and a sign convention where longs always pay when the rate is positive — real funding flips
sign regime-by-regime and is the *dominant* carry cost for held perp positions. Any strategy
holding across 8h boundaries (AdaptiveTrend, BestSupertrend on 1h+) has a first-order cost
term missing or mis-signed.

Binance publishes complete funding history (`GET /fapi/v1/fundingRate`, spec in repo scope:
[funding-rate history endpoint](https://developers.binance.com/docs/derivatives/coin-margined-futures/market-data/rest-api/Get-Funding-Rate-History-of-Perpetual-Futures)).
The right shape: import funding history into TimescaleDB next to candles (same idempotent
pattern as `candle_importer`), charge at each boundary with the *historical signed rate* at the
*boundary's* mark price (closest candle close is an acceptable proxy).

### QNT-6 (M) [Certain] — Optimizer is pure in-sample selection; its "best" is overfit by construction

`services/optimizer.py` grid/random-subset search scores every combination on the **same full
date range** and reports the max. There is no train/test split, no walk-forward, no penalty for
the number of trials, and **no minimum-trade filter** — a combination with 3 lucky trades can
(and will) rank #1 on Sharpe. The reported best-combo metrics are the maximum of N noisy
estimates: selection bias guarantees they overstate live expectation (this is the textbook
"probability of backtest overfitting" setting — see §3.1).

Operational compounders, same file:

- every combo calls `run_backtest_simulation`, which **persists a full `backtestResults` doc
  and bulk-inserts every trade** into `backtestTrades` — a 50-combo run writes 50 result docs
  + tens of thousands of trade rows of pure noise into the collections the UI lists;
- every combo re-runs `ensure_candles_available` + re-fetches candles from Timescale — the
  data is identical across combos and could be loaded once;
- combos run strictly sequentially inside the engine's event loop (no process pool), and each
  publishes Redis progress on `progress:{combo_job_id}` channels nothing subscribes to.

### QNT-7 (M) [Certain] — Monte Carlo: i.i.d. resampling understates tail risk; "ruin" is mislabeled

`services/monte_carlo.py` resamples per-trade returns independently with replacement. Trade
PnLs from trend/divergence strategies are serially correlated (wins cluster in trends, losses
cluster in chop); shuffling destroys that clustering and **narrows the simulated drawdown
distribution** — the tool's output is biased optimistic exactly where it is consulted (tail
risk). Additionally: "ruin" is hardcoded as a 30% drawdown (not ruin, and not configurable);
returns are computed as `pnl / starting_capital` but compounded multiplicatively (mixing an
additive PnL model with a multiplicative equity path); partial-exit synthetic trades (QNT-14)
enter the resample pool as if they were independent trades; and no percentile bands or
final-equity confidence intervals are surfaced — only threshold breach probabilities.

### QNT-8 (M) [Certain] — Live fills one candle earlier than backtest, systematically

Backtest: signals set at close of candle *t* fill at **open of candle *t+1*** via
`execute_pending`. Live: `evaluate_and_route(is_live=True)` executes entries/flips/closes
immediately at candle-*t* close (`ref_price=strategy.price`, `kernel.py:375-448`) — and the
real market order lands seconds after that, behind the reconcile REST calls. Close(*t*) ≈
open(*t+1*) in continuous markets, but the difference is exactly the gap/volatility component
— i.e. it is *not* mean-zero for momentum entries (which fire when price is moving). This is a
persistent, unmeasured live-vs-backtest bias the golden master cannot see (it is backtest-only).
At minimum document it and measure it (record both prices live and track the spread); the
cleaner fix is aligning live execution to next-open semantics or offering close-fill as an
explicit backtest mode.

### QNT-9 (M) [Certain] — Live indicator state ≠ backtest indicator state (rolling-500 window)

Live `prepare()` recomputes on a rolling **≤500-candle** window (`_append_candle` cap); backtest
`prepare()` runs once on the **full history**. Any indicator with long memory diverges: EMAs
seeded from series start, session-cumulative state, and specifically
`AtrBracketRiskModel._atr_history` — which accumulates *per backtest run* in backtest but *per
live session* in live, so the ATR-percentile veto filters different entries in each mode. Same
strategy, same params, different signals. Interacts with ENG-8 (params > 166 make readiness
unreachable) and ENG-4 (warmup candles come from mainnet REST while the traded stream is
testnet). Parity between the two modes is currently asserted (five-model pipeline) but not true
at the indicator-state level.

### QNT-10 (M) [Certain] — WS reconnect loses candles silently; no gap detection

The per-symbol kline loop (`live_bot_manager.py:1190-1373`) reconnects with jittered backoff
but **never backfills** closed candles missed during the outage — the next arriving candle is
appended after the gap, and `_append_candle` has no timestamp-continuity check. Indicators are
then computed across a discontinuity (an EMA/ATR that never saw the missing move), and nothing
is logged or surfaced. Backtests never contain gaps, so this is another silent live-only
divergence. Standard practice: on reconnect, REST-fetch klines since the last stored timestamp
before resuming, and alert on any `ts[i+1] - ts[i] != timeframe` step.

### QNT-11 (L) [Certain] — No spread or impact model; exec-algos are economically inert in backtest

Slippage is one constant (`0.05%`) applied to every market fill regardless of order size,
symbol depth, or volatility; `impact_cost()` returns 0. Consequences: (a) fills on illiquid
alts in a Chaos pairlist are priced like BTC; (b) TWAP/VWAP/Iceberg slicing produces *bit-wise
identical economics* to a single market order in backtest — every slice gets the same constant
slippage — so the exec-algo feature cannot be evaluated in simulation at all, only its bugs
(QNT-2) can. A minimal upgrade ladder: per-symbol spread half-cost from the ticker cache the
pairlist already maintains → volatility-scaled slippage (k·ATR%) → square-root impact term
using 24h quote volume (already cached) as ADV proxy.

### QNT-12 (L) [Certain] — No lookahead-bias guardrail around `prepare()`

`prepare(candles_np)` receives the **full array including future candles** and trusts every
strategy to only read causally. The seeded strategies handle this correctly (pivot reads are
horizon-shifted by `i - right` in MicroMacroRSIDivergence/MultiDivergence — verified), but the
framework has **no enforcement and no detector**: an operator strategy that indexes a pivot
array at `self.index` directly, or normalizes an indicator over the whole series (z-score,
min-max), silently leaks the future and produces a spectacular fake backtest. Freqtrade ships
[lookahead-analysis](https://www.freqtrade.io/en/stable/lookahead-analysis/) (chained backtests
that diff signals against truncated-data reruns) precisely because this is the most common way
strategies lie. Enma has nothing equivalent; see §3.4.

### QNT-13 (L) [Certain] — Metric-layer defects

- `StatisticRegistry.compute_all` swallows **every exception → "0.00"** — a broken metric is
  indistinguishable from a legitimately zero one (same fail-silent pattern as ENG-13);
- `ProfitFactorStat`/`ExpectancyRatioStat` return the string `"inf"` — not valid JSON-number
  material; any downstream `parseFloat`/chart code gets `Infinity` or `NaN` (UI-dependent);
- Sharpe/Sortino: population `np.std` (ddof=0) over per-candle equity returns including long
  flat stretches; acceptable, but undocumented and not comparable to trade-based Sharpe other
  platforms report;
- no overfitting-aware statistics at all (no PSR/DSR, no trade-count confidence) despite the
  optimizer actively encouraging multiple testing (QNT-6).

### QNT-14 (L) [Certain] — Partial exits are counted as full trades in every trade-level statistic

`execute_reduce` appends a synthetic `"scale_out"` trade record (`backtest_runner.py:252-275`).
All downstream consumers — `totalTrades`, `winRate`, `SQN` (√N term!), expectancy, streaks,
Monte Carlo's resample pool, the returns histogram — treat each partial leg as an independent
round-trip. A DCA strategy that scales out in 3 legs triples its apparent trade count and
mechanically inflates SQN. Either aggregate legs per position (freqtrade model) or key
statistics on completed round-trips with legs attached.

### QNT-15 (L) [Certain] — Quadratic hot-path costs in long backtests

- `AtrBracketRiskModel.assess` runs `sorted(self._atr_history)` **every candle** when the
  percentile filter is on → O(N² log N) over a multi-year 1m run (use `bisect.insort` to keep
  it sorted incrementally);
- `BaseStrategy._atr()` / `trail_stop()` recompute full-series ATR per call → O(N²) for any
  strategy using the helpers in `update_position()`;
- legacy multi-symbol equity merge does `list.index(ts)` per timestamp (O(n²)) — mostly dead
  since F-017 but still the fallback path.

### QNT-16 (L) [Certain] — Warmup/data-sufficiency edges fail silent

`warmup_period = max(strategy.MIN_WARMUP_CANDLES, min(50, len(rows)-2))`
(`backtest_runner.py:907`): if the date range yields fewer candles than `MIN_WARMUP_CANDLES`,
`range(warmup, total)` is empty and the backtest **"completes" with zero trades and no
warning** — indistinguishable from "strategy found no signals". The 50-candle minimum check
upstream doesn't protect strategies that declare larger warmups (AdaptiveTrend: 200). Related
cosmetics: the buy-&-hold overlay fabricates `base_candles[-1,2]` by mutating a copied candle
array (`:1057-1061`) — works, but the metric context then carries a falsified last close into
any future statistic that reads it.

### QNT-17 (M) [Certain] — Leverage-sensitivity scenarios re-run with the WRONG strategy config

`leverage_sensitivity_runner.py` re-runs the parent backtest at 5 leverage levels using
`parent.get("slippagePct")`, `parent.get("alphaParams")`, `parent.get("riskParams")`,
`parent.get("fundingEnabled")` — **none of which `run_backtest_simulation` ever persists** into
`backtestResults` (see the `$set` block, `backtest_runner.py:1127-1156`: it stores `feeRate`,
`capital`, `leverage`… but not alpha/risk params or slippage). Every lookup returns `None`, so
scenarios run with **default strategy parameters and default risk settings** regardless of what
the parent run used. The leverage curve shown in the Risk dashboard describes a *different
strategy configuration* than the backtest it claims to analyze. (Bonus: when `fundingRate` is
absent it substitutes `0.0001` instead of the parent's value — harmless only while
`funding_enabled` stays False.) Fix: persist the full run config in `backtestResults` and read
it back — which also fixes reproducibility in general (today a stored result is not
reproducible because its params were never saved).

---

## 2. Verification coverage gaps (why none of §1 was caught)

The repo's safety net is real but aimed at the wrong quadrant:

- **Golden master** = 1 symbol (BTCUSDT), 1h, funding off, no exec-algo, default risk params,
  single-symbol path. QNT-1, 2, 5, 11, 17 are all structurally invisible to it. It verifies
  *refactors don't change the one blessed path* — it does not verify the paths users actually
  run (multi-symbol Chaos-style runs, exec-algos, funding on).
- **Engine tests** (11 modules) cover slicing math, metrics edge cases, pairlist, reconcile
  helpers — no end-to-end multi-symbol backtest assertion, no "SL fires in portfolio mode"
  test, no cash-conservation invariant (final balance == capital + Σ(realized pnl) − fees −
  funding — this single property test would have caught QNT-1 immediately).
- **No parity harness** between live and backtest indicator state (QNT-8/9) and no lookahead
  detector (QNT-12).

---

## 3. Methods & upgrades (research-backed, July 2026)

### 3.1 Optimizer: walk-forward + overfitting-aware statistics

The consensus toolkit for exactly Enma's optimizer problem (QNT-6):

- **Walk-forward optimization** — optimize on a rolling in-sample window, validate on the next
  out-of-sample slice, roll forward; report the *stitched out-of-sample* equity, never the
  in-sample winner. This is the minimum credible upgrade and fits the existing
  `run_backtest_simulation` signature (it's a scheduling layer on top).
- **Deflated Sharpe Ratio (DSR)** — corrects the reported Sharpe for the number of trials,
  variance across trials, and non-normality; directly applicable since the optimizer knows N
  (its own combination count). ([Bailey & López de Prado](https://www.researchgate.net/publication/286121118_The_Deflated_Sharpe_Ratio_Correcting_for_Selection_Bias_Backtest_Overfitting_and_Non-Normality),
  [practitioner course treatment](https://paperswithbacktest.com/course/deflated-sharpe-ratio))
- **CSCV / Probability of Backtest Overfitting (PBO)** — combinatorial partitioning of the
  return series to estimate the probability that the selected combo is overfit; reported to cut
  false-positive strategy selection from ~68% to ~22% vs naive selection
  ([validation-framework survey](https://arxiv.org/html/2512.12924v1),
  [overfitting-discipline overview](https://blog.pickmytrade.trade/trading-strategy-validation-backtest-overfitting/)).
- **Search engine**: replace exhaustive/random grid with **Optuna TPE + median-pruner** — an
  order of magnitude fewer evaluations for the same optimum quality, native parallelism, and
  early termination of hopeless combos ([Optuna vs grid comparisons](https://www.guvi.in/blog/optuna-for-hyperparameter-optimization/),
  [TPE overview](https://www.emergentmind.com/topics/optuna-optimization-framework)). Add a
  **min-trades constraint** (reject combos below ~30 trades) and load candles **once** per
  optimization, not per combo; persist per-combo *summaries* only (no trade dumps — QNT-6).

### 3.2 Intrabar realism: detail-timeframe simulation

The industry answer to both ENG-18 (SL-vs-TP same-candle ambiguity) and QNT-3 (entry-candle
exits): simulate exit logic on a **lower "detail" timeframe inside each main candle** —
freqtrade's `--timeframe-detail` (e.g. 1h main + 5m/1m detail) evaluates SL/TP/callbacks per
sub-candle, resolving intrabar ordering empirically instead of by embedded policy
([freqtrade backtesting docs](https://www.freqtrade.io/en/stable/backtesting/)). Enma already
has the 1m candles in TimescaleDB (or can import them via the existing `candle_importer`);
the kernel's `check_exits` is already a pure function of a candle window, so a sub-loop over
detail candles inside the exit check is architecturally cheap. Offer it as an opt-in flag —
it changes results (correctly) and needs a golden-master re-baseline.

### 3.3 Funding realism: historical funding-rate ledger

Import `/fapi/v1/fundingRate` history per symbol into a Timescale table (same idempotent
insert pattern as candles), and charge funding at each boundary using the **historical signed
rate** and the boundary-nearest close (QNT-5). Funding is the defining economics of perps —
[exchanges' own docs](https://www.binance.com/en/blog/futures/what-is-futures-funding-rate-and-why-it-matters-421499824684903247)
and [funding-arb research](https://www.sciencedirect.com/science/article/pii/S2096720925000818)
treat it as first-order PnL, not an optional toggle defaulted to zero. This also unlocks a
strategy class (carry/funding-aware filters) the platform currently cannot express.

### 3.4 Lookahead & recursive analysis harness

Adopt the freqtrade pattern ([lookahead-analysis](https://www.freqtrade.io/en/stable/lookahead-analysis/)):
run the backtest normally, then re-run with data truncated at each entry signal's timestamp and
**diff the signals/indicator values** — any difference is a lookahead leak. For Enma
specifically: run `prepare()` once on the full array vs recomputed per-candle on the expanding
window `candles[:t+1]`, and assert identical trade lists. This is a *sentinel in CI* — it
mechanically enforces the causality contract QNT-12 shows is currently trust-based, and it
doubles as the live-parity check for QNT-9 (live's rolling-window `prepare()` is exactly the
truncated-data variant).

### 3.5 Monte Carlo: block bootstrap + honest outputs

Replace i.i.d. trade resampling with **block bootstrap** (resample consecutive-trade blocks;
block length ≈ √N or tuned to the autocorrelation horizon) to preserve win/loss clustering —
the standard fix for exactly this bias ([method comparison](https://quanttradingtools.com/monte-carlo-simulation-trading/),
[block-bootstrap implementation notes](https://opensourcequant.wordpress.com/2016/04/26/block-bootstrapped-mc-function-for-backtest-results-in-r/)).
Raise runs to 5–10k when reporting tail metrics, output equity-percentile bands (5/25/50/75/95)
and final-equity CIs, make the "ruin" threshold explicit and configurable, and exclude
partial-exit legs from the resample pool (QNT-14). Numpy-vectorize the path loop (the current
pure-Python `random.choice` loop is ~100× slower than necessary).

### 3.6 Fill-model ladder (makes exec-algos meaningful)

In order of effort: (1) per-symbol **spread half-cost** from the ticker cache the pairlist
already holds; (2) **volatility-scaled slippage** (k · ATR% of the fill candle) instead of one
global constant; (3) **square-root market-impact** term (`impact ∝ σ·√(order_notional/ADV)`)
using cached 24h quote volume as ADV — at which point TWAP/VWAP slicing finally has a
measurable benefit in backtest (QNT-11) and the `IcebergAlgorithm` can be evaluated or deleted.

### 3.7 Live-loop data integrity

On kline-WS reconnect, REST-backfill from the last stored candle timestamp before processing
new events, and add a timestamp-continuity assertion in `_append_candle` (gap → backfill + log,
not silent append) — QNT-10. Belongs naturally to Plan 6's `Exchange` abstraction work (the
combined-stream refactor already planned there is the right moment: one socket per session with
a gap-aware candle buffer per symbol).

---

## 4. Priority-ordered remediation summary

| # | Item | Closes | Effort | Payoff | Where it belongs |
|---|------|--------|--------|--------|------------------|
| 1 | Fix `_entered_this_candle` in portfolio loop + multi-symbol golden-master scenario + cash-conservation property test | QNT-1 | S | 5 | **Plan 9** (immediate) |
| 2 | Fix exec-algo close/flip destruction + close/flip-under-algo tests | QNT-2 | S | 5 | **Plan 9** (immediate) |
| 3 | Persist full run config in `backtestResults`; leverage-sensitivity reads it back | QNT-17 | S | 4 | **Plan 9** |
| 4 | Entry-candle exit evaluation (opt-in → default after re-baseline) | QNT-3 | S–M | 4 | **Plan 9** |
| 5 | Lookahead sentinel (expanding-window vs full-array prepare diff) in CI | QNT-12, QNT-9 (detector) | M | 4 | **Plan 9**, CI via Plan 2 |
| 6 | Walk-forward + DSR/PBO + Optuna TPE + min-trades + no per-combo trade dumps | QNT-6, QNT-13 (partial) | M | 5 | **Plan 9** |
| 7 | Historical funding ledger + boundary-priced signed funding | QNT-5 | M | 4 | **Plan 9** (data), pairs with Plan 6 |
| 8 | Detail-timeframe intrabar simulation (opt-in) | ENG-18, QNT-3 residual | M | 4 | **Plan 9** |
| 9 | Block-bootstrap Monte Carlo + percentile bands | QNT-7 | S | 3 | **Plan 9** |
| 10 | WS gap backfill + continuity assertion | QNT-10 | S | 4 | **Plan 6** (exchange abstraction) |
| 11 | Fill-model ladder (spread → vol-scaled → impact) | QNT-11 | M | 3 | **Plan 9**, after 1–8 |
| 12 | Trade-vs-leg statistics separation | QNT-14 | S–M | 3 | **Plan 9** |
| 13 | Liquidation fee + mark-price note; metric hardening (`inf`, fail-loud registry) | QNT-4, QNT-13 | S | 2 | **Plan 9** / Plan 8 |
| 14 | Perf: incremental ATR-history sort, O(N) trail-stop ATR | QNT-15 | S | 2 | **Plan 9** (opportunistic) |
| 15 | Warmup sufficiency fail-loud | QNT-16 | S | 2 | Plan 8 (with ENG-8) |

**Sequencing note:** items 1–3 are *bug fixes to already-shipped behavior* and are safe to do
before/parallel to the Plan 2–8 program (they don't depend on the trust/state work). Items 4–8
change backtest outputs by design — each needs a deliberate golden-master re-baseline with
sign-off (Rule C), which is exactly what the golden-master workflow exists for. Do **not**
trust any existing multi-symbol backtest result or leverage-sensitivity chart until items 1
and 3 land; consider a one-off migration flagging affected `backtestResults` docs
(`symbol` contains a comma → stale).

---

## 5. Sources

- Freqtrade backtesting & detail timeframe: https://www.freqtrade.io/en/stable/backtesting/
- Freqtrade lookahead analysis: https://www.freqtrade.io/en/stable/lookahead-analysis/
- Deflated Sharpe Ratio (Bailey & López de Prado): https://www.researchgate.net/publication/286121118_The_Deflated_Sharpe_Ratio_Correcting_for_Selection_Bias_Backtest_Overfitting_and_Non-Normality
- DSR practitioner treatment: https://paperswithbacktest.com/course/deflated-sharpe-ratio
- Walk-forward validation framework (2025): https://arxiv.org/html/2512.12924v1
- Backtest-overfitting discipline overview: https://blog.pickmytrade.trade/trading-strategy-validation-backtest-overfitting/
- Optuna vs grid search: https://www.guvi.in/blog/optuna-for-hyperparameter-optimization/ · https://www.emergentmind.com/topics/optuna-optimization-framework
- Binance funding-rate history API: https://developers.binance.com/docs/derivatives/coin-margined-futures/market-data/rest-api/Get-Funding-Rate-History-of-Perpetual-Futures
- Funding rates & PnL: https://www.binance.com/en/blog/futures/what-is-futures-funding-rate-and-why-it-matters-421499824684903247
- Funding-arbitrage risk/return study: https://www.sciencedirect.com/science/article/pii/S2096720925000818
- Monte Carlo honesty / block bootstrap: https://quanttradingtools.com/monte-carlo-simulation-trading/ · https://opensourcequant.wordpress.com/2016/04/26/block-bootstrapped-mc-function-for-backtest-results-in-r/

---

*Remediation plan for this file: [`9_backtest-and-optimizer-correctness.md`](9_backtest-and-optimizer-correctness.md)
(+ Plan 10 for the MC/optimizer product surface). Companion audit: [`audit_1_system-design.md`](audit_1_system-design.md).*
