# 07 — Additive Features: what to borrow from freqtrade & nautilus

> Companion to the findings docs. Findings (`F-xxx`) fix what is **wrong**; this catalog (`A-xxx`)
> adds what is **missing**. Inspiration, not architecture transplant — each item names the Enma
> seam it would attach to.
> **References:** freqtrade plugins (protections/pairlists), hyperopt, backtest metrics;
> nautilus RiskEngine + PortfolioAnalyzer.

**Status tags:** `[HAVE]` already in Enma · `[PARTIAL]` exists but thin · `[MISSING]` not present.
**Value:** ★★★ high leverage · ★★ useful · ★ nice-to-have.

---

## 1. Layers of risk management

Enma today: one session-drawdown circuit breaker (`DefaultRiskModel.can_trade`) + per-trade
`max_portfolio_risk` veto + leverage clamp + notional-vs-buying-power check. That is **one layer**.
freqtrade and nautilus both run a *stack* of independent guards.

### From freqtrade — Protections (post-trade, time-based lockouts)
A protection layer that **halts trading** based on recent outcomes — orthogonal to per-trade sizing:

| Protection | Behaviour | Enma status |
|---|---|---|
| `StoplossGuard` | halt (global or per-pair) when stoploss count > `trade_limit` within `lookback_period` | `[MISSING]` |
| `MaxDrawdown` | pause when account drawdown > `max_allowed_drawdown` over a lookback | `[PARTIAL]` — Enma has session DD but no lookback window / auto-resume |
| `LowProfitPairs` | lock a pair that fails `required_profit` over a window | `[MISSING]` |
| `CooldownPeriod` | block re-entry into a pair for `stop_duration` after exit | `[MISSING]` — Enma re-enters next candle |

- **A-001 ★★★** — Add a **protections stack** (StoplossGuard + CooldownPeriod first) to the risk
  model. CooldownPeriod alone kills the "re-enter the same losing pair immediately" failure. Attach
  at `engine/core/models/risk.py` (gate inside `can_trade()`), config via `server/src/utils/risk.js`.

### From nautilus — pre-trade RiskEngine + trading-state machine
A **pre-trade gate** every order passes before it leaves the engine:

- Pre-trade checks: price/qty precision, positive price, qty min/max bounds, `max_notional_per_order`,
  reduce-only semantics, cash-balance impact, **submit/modify rate limits**, GTD expiry.
- `TradingState` machine: **`ACTIVE`** (normal) · **`HALTED`** (deny new submit/modify, allow cancels)
  · **`REDUCING`** (only exposure-reducing orders). Failed checks emit `OrderDenied` — the order
  never reaches the venue.

- **A-002 ★★★** — Add a **`TradingState` switch** (ACTIVE/REDUCING/HALTED) at the session level.
  HALTED = stop opening, allow closing; REDUCING = only let SL/TP/flatten through. This is the
  manual kill-switch Enma lacks for a live session going wrong. Attach at
  `engine/core/live_bot_manager.py` (`_execute_entry` consults state) + a server control endpoint.
- **A-003 ★★** — Add **order rate-limiting** (`max_order_submit_rate` equivalent) so a strategy bug
  can't machine-gun Binance into a ban. Attach where `_call_node_internal` posts orders.

---

## 2. Pair management logic

Enma today: a **static** hand-maintained `FUTURES_SYMBOLS` list (`engine/core/constants.py`),
triple-duplicated (F-009). freqtrade runs a **dynamic pairlist pipeline** — a generator + chained
filters re-evaluated each loop. This is the single biggest *capability* gap.

| Handler | Selects/filters on | Value for Enma |
|---|---|---|
| `VolumePairList` | rank by 24h volume (generator) | ★★★ trade only liquid pairs, auto-refreshed |
| `PercentChangePairList` | sort by % change over window | ★★ momentum universe |
| `MarketCapPairList` | CoinGecko marketcap rank | ★ universe sanity bound |
| `AgeFilter` | drop newly-listed / near-delist | ★★ avoids thin new listings |
| `SpreadFilter` | drop wide bid/ask spread (`max_spread_ratio`) | ★★★ directly cuts slippage cost |
| `RangeStabilityFilter` | drop pairs with too-small/large range | ★★ regime filter |
| `VolatilityFilter` | keep pairs within a volatility band | ★★★ pairs Enma's ATR sizing assumes |
| `PrecisionFilter` | drop pairs where rounding breaks the stop | ★★★ exactly your JUPUSDT class |
| `PriceFilter` | bounds on price / min-tick value | ★★ |
| `PerformanceFilter` | rank by realized profit | ★★ feedback loop from live results |
| `FullTradesFilter` | shrink to in-trade pairs when slots full | ★ |
| `ShuffleFilter` | randomize order (anti-bias) | ★ |
| `StaticPairList` | manual whitelist/blacklist w/ regex | `[HAVE]` (your current list) |

- **A-004 ★★★** — Introduce a **pairlist pipeline**: a generator (`VolumePairList`) + filter chain
  (`SpreadFilter` → `VolatilityFilter` → `PrecisionFilter` → `AgeFilter`) feeding the live session's
  symbol set, replacing the static list. `PrecisionFilter` + `SpreadFilter` alone would have
  pre-empted several of your symbol-specific bugs. New module `engine/services/pairlist.py`, sourced
  from the rules already cached in `engine/utils/symbols.py:load_exchange_rules`.

---

## 3. Stricter parameters & optimization

Enma today: dict `PARAMS` with `min/max`, injected via `setattr` with silent clamp (F-015/F-016).
No optimization. freqtrade's hyperopt system is both **stricter typing** and a **tuning engine**.

- **Typed parameters:** `IntParameter`, `DecimalParameter` (bounded decimals — preferred),
  `RealParameter`, `CategoricalParameter`, `BooleanParameter`, each with `optimize`/`load` flags.
- **Optimizable spaces:** `buy/enter`, `sell/exit`, `roi`, `stoploss`, `trailing`, **`protection`**,
  `trades` — i.e. risk and protection params are tunable too, not just signals.
- **Loss functions** (what "better" means): `SharpeHyperOptLoss`, `SharpeHyperOptLossDaily`,
  `SortinoHyperOptLoss(Daily)`, `CalmarHyperOptLoss`, `MaxDrawDownHyperOptLoss`,
  `MaxDrawDownRelativeHyperOptLoss`, `ProfitDrawDownHyperOptLoss`, `OnlyProfitHyperOptLoss`,
  `MultiMetricHyperOptLoss` (profit + drawdown + profit factor + expectancy + win rate).

- **A-005 ★★** — Adopt **typed, self-validating parameters** (a small class hierarchy mirroring
  `IntParameter`/`DecimalParameter`) so bounds live in one declaration and out-of-range = explicit
  error (also resolves F-015/F-016). Attach at `engine/core/strategy.py`.
- **A-006 ★★★** — Add a **parameter-optimization run mode** over your existing backtest engine, with
  selectable objective (Sharpe / Sortino / Calmar / drawdown / multi-metric). Enma already computes
  most of these metrics — wiring an optimizer loop over `run_backtest_simulation` is the gap, not the
  math. High leverage: turns your backtester into a tuner.

---

## 4. Analysis methods, curves, and metrics

Enma reports: netProfit, winRate, Sharpe, Sortino, maxDrawdown, leverage, liquidations, totalFees,
totalFunding, plus per-trade `_mfe`/`_mae`. Solid base, but missing several standard measures.

### Missing metrics (freqtrade reports these; cheap to add — vectorized like your existing ones)
| Metric | Why it matters | Enma status |
|---|---|---|
| **CAGR %** | annualized return, comparable across run lengths | `[MISSING]` |
| **Calmar ratio** | return per unit max drawdown | `[MISSING]` |
| **SQN** (Van Tharp) | system quality / consistency | `[MISSING]` |
| **Profit factor** | gross win / gross loss | `[MISSING]` |
| **Expectancy + Expectancy ratio** | avg $ per trade, edge per trade | `[MISSING]` |
| **Max consecutive wins/losses** | streak / ruin risk | `[MISSING]` |
| **Drawdown duration** (time underwater) | recovery pain, not just depth | `[MISSING]` |
| **Market change / benchmark** | strategy vs buy-and-hold | `[MISSING]` |
| **Per-exit-reason breakdown** (SL vs TP vs flip vs liq) | where P&L actually comes from | `[MISSING]` (data exists in trades, not aggregated) |
| **Per-pair / per-entry-tag tables** | which symbols/signals carry the strategy | `[PARTIAL]` (live `symbolStats` only) |

- **A-007 ★★★** — Add the metric block above to `backtest_runner.py` metrics (L847-970). All derivable
  from trades you already store; this is the cheapest high-value add in the whole catalog.
- **A-008 ★★** — Add an **exit-reason aggregation** and **per-pair/per-tag tables** to backtest
  results (freqtrade's breakdown tables) — answers "is my edge the TP or just avoided liquidation."

### New curves (charts Enma doesn't draw)
- **A-009 ★★** — **Underwater / drawdown curve** (equity below running peak over time) alongside the
  equity curve you already downsample.
- **A-010 ★★** — **Returns distribution / per-trade P&L histogram** and **MFE/MAE scatter** (you
  already capture `_mfe`/`_mae` per trade — currently unused for visualization).
- **A-011 ★** — **Rolling Sharpe/volatility curve** to show edge stability over the run.

### From nautilus — PortfolioAnalyzer pattern
A registry where statistics are pluggable: subclass `PortfolioStatistic`, implement
`calculate_from_realized_pnls()`, register via `analyzer.register_statistic(stat)`. Also: equity via
**mark-to-market with a fallback chain** (mark → quote → last → bar close) and **missing-price
flagging** so valuation never silently goes stale.

- **A-012 ★★** — Restructure metrics as a **pluggable statistic registry** (one class per metric)
  instead of a monolithic metrics function — makes A-007 additions trivial and testable.
- **A-013 ★★★** — Adopt the **mark-price fallback chain + missing-price flag** for equity/PnL
  valuation. Directly addresses F-023 (last-price PnL diverging from exchange) with a principled
  pricing source order.

---

## 5. Strategies — borrow mechanisms, not files

Uncomfortable truth: don't copy strategy files. freqtrade's core ships only **templates**; the
community `freqtrade-strategies` repo is largely educational/overfit; nautilus ships **example**
strategies (EMACross, OrderbookImbalance, VolatilityMarketMaker). Lifting a specific strategy is how
you import someone else's curve-fit. What's worth importing is the **mechanisms** Enma's strategies
can't currently express:

| Mechanism | What it adds | Enma status |
|---|---|---|
| **Position adjustment / DCA** (`adjust_trade_position`) | scale into/out of a position, grid/pyramid | `[MISSING]` — Enma is one-shot entry |
| **Informative pairs / multi-timeframe** | use HTF/other-pair data in signals | `[PARTIAL]` — Enma fetches HTF candles but no formal informative API |
| **`custom_exit` / `custom_stoploss`** | per-trade dynamic exit logic | `[PARTIAL]` — ATR/Chandelier trailing exists; no arbitrary callback |
| **Entry/exit tagging** | label why each trade fired, for per-tag analytics | `[MISSING]` — feeds A-008 |
| **Order-book imbalance signal** (nautilus) | microstructure entry on book pressure | `[MISSING]` |

- **A-014 ★★★** — Add **position adjustment (DCA / scale-in-out)** to the execution model — the single
  most impactful *strategy capability* gap; turns every strategy into a family. Attach at
  `engine/core/models/execution.py` + position tracking in `engine/core/position.py`.
- **A-015 ★★** — Add **entry/exit tagging** end-to-end (signal → trade record) to unlock per-tag
  analytics (pairs with A-008). Cheap, high analytical payoff.

---

## Priority shortlist (where to start)

| Rank | Item | Value | Effort |
|---|---|---|---|
| 1 | **A-007** add CAGR/Calmar/SQN/profit-factor/expectancy/streaks to backtest metrics | ★★★ | low |
| 2 | **A-001** protections stack (CooldownPeriod + StoplossGuard) | ★★★ | low-med |
| 3 | **A-002** TradingState ACTIVE/REDUCING/HALTED kill-switch | ★★★ | med |
| 4 | **A-004** dynamic pairlist pipeline (Spread/Volatility/Precision filters) | ★★★ | med-high |
| 5 | **A-013** mark-price fallback chain for PnL (also fixes F-023) | ★★★ | med |
| 6 | **A-014** position adjustment / DCA | ★★★ | high |
| 7 | **A-006** parameter-optimization run mode | ★★★ | high |

Lower-effort ★★★ first (metrics, protections) — they ship fast and de-risk the live system before
the larger capability builds (pairlists, DCA, optimizer).

---

## Note on method

GitHub MCP auth is currently broken (expired PAT), so upstream behaviour here was read via WebFetch
on the freqtrade/nautilus docs sites, not source line-cites. Names of handlers, parameters, loss
functions, states, and metrics are quoted from those docs. Verify exact config field names against
source before implementing any specific item.
