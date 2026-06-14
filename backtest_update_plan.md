# Backtest Report Update Plan — Closing the Gap to TradingView

**Status:** Proposed
**Author:** AI session, 2026-06-14
**Scope:** `engine/services/backtest_runner.py`, `server/` backtest passthrough, `client/src/features/backtest/*`, `client/src/components/charts/*`
**Goal:** Bring Enma's backtest report to feature parity with TradingView's Strategy Tester — the metrics it computes, the way it splits Long/Short, and how it presents results visually — without violating any platform invariant.

---

## 0. Why

Enma already runs a realistic isolated-margin futures simulation and persists a solid metric set. But compared to TradingView's Strategy Tester, the **report** (not the engine) is thin:

- No **Profit Factor**, **Gross Profit/Loss**, **Expectancy**, or **payoff ratio** — the metrics traders reach for first.
- No **Long vs Short breakdown** — directional bias is invisible.
- No **Buy & Hold benchmark** — can't tell if the strategy beats just holding.
- No **per-trade MFE/MAE (run-up/drawdown)** — can't tune stops/targets.
- The equity chart plots **balance only**; no drawdown overlay, no benchmark, no trade markers.
- The results panel is a flat stack of 6 KPI cards + one chart + a trades table. TradingView organizes into **Overview / Performance / Trades Analysis / Risk Ratios / List of Trades** tabs.

This plan is **additive**. Every existing field stays. We extend the engine's metric computation, widen the trade record, and rebuild the client results panel into a tabbed report.

---

## 1. Reference: What TradingView Shows

Distilled from the official TradingView Strategy Tester docs and the Equity Chart spec.

### Tabs
| Tab | Contents |
|-----|----------|
| **Overview** | Equity curve (cumulative P&L) + Buy & Hold line + drawdown; headline KPIs (Net Profit, Total Trades, Profit Factor, % Profitable, Max Drawdown) |
| **Performance Summary** | All / Long / Short columns: Net Profit, Gross Profit, Gross Loss, Max Run-up, Max Drawdown, Buy & Hold Return, Profit Factor, Max Contracts Held, Open P&L, Commission Paid |
| **Trades Analysis** | All / Long / Short: Total/Winning/Losing trades, Percent Profitable, Avg P&L, Avg Win, Avg Loss, Ratio Avg Win/Avg Loss, Largest Win/Loss, Avg # Bars in Trades (and in winners/losers), Max consecutive wins/losses |
| **Risk/Performance Ratios** | Sharpe, Sortino, Profit Factor, Margin Calls (per All/Long/Short) |
| **List of Trades** | Per-trade ledger: entry/exit time, type, price, qty, P&L, **run-up (MFE)**, **drawdown (MAE)**, cumulative P&L |

### Equity chart components
- **Cumulative P&L** line (per closed trade).
- **Buy & Hold** benchmark line.
- **Drawdown** (distance from running peak).
- **Trade Excursions** — MFE (favorable) / MAE (adverse) bars per trade.

### On-chart (price chart) overlay
- Entry/exit markers with signal labels.
- **Entry→exit connector lines colored green (win) / red (loss).**
- Click a trade row → chart jumps to and highlights that trade.

*Sources:*
- [TradingView — Strategy Report: How to start](https://www.tradingview.com/support/solutions/43000764138-tradingview-strategy-report-how-to-start/)
- [TradingView — Equity Chart](https://www.tradingview.com/support/solutions/43000681735-equity-chart/)
- [TradingView — Max equity drawdown](https://www.tradingview.com/support/solutions/43000681690-performance-summary-max-drawdown/)
- [Sharpe and Sortino Ratios (TradingView)](https://www.tradingview.com/script/Mi5DL7bi-Sharpe-and-Sortino-Ratios/)

---

## 2. Gap Analysis — Enma Today vs Target

### 2a. Metrics (`backtest_runner.py` → `metrics` dict)

| Metric | Enma now | TradingView | Action |
|--------|----------|-------------|--------|
| Total trades | ✅ `totalTrades` | ✅ | keep |
| Win rate / % profitable | ✅ `winRate` (0–1) | ✅ | keep |
| Net profit (+%) | ✅ `netProfit`, `netProfitPct` | ✅ | keep |
| Max drawdown | ✅ `maxDrawdown` | ✅ | keep |
| Sharpe / Sortino / Calmar | ✅ | ✅ (no Calmar in TV) | keep |
| Avg win / avg loss | ✅ `averageWin`, `averageLoss` | ✅ | keep |
| Largest win / loss | ✅ `largestWin`, `largestLoss` | ✅ | keep |
| Fees / funding / liquidations | ✅ | ✅ (commission, margin calls) | keep |
| Avg holding period | ✅ seconds | ✅ as **# bars** | extend (add bars) |
| **Gross profit / gross loss** | ❌ | ✅ | **add** |
| **Profit factor** | ❌ | ✅ | **add** |
| **Expectancy** (avg P&L/trade) | ❌ | ✅ Avg P&L | **add** |
| **Payoff ratio** (avg win/avg loss) | ❌ | ✅ | **add** |
| **Max run-up** | ❌ | ✅ | **add** |
| **Buy & Hold return** | ❌ | ✅ | **add** |
| **Max consecutive wins/losses** | ❌ | ✅ | **add** |
| **Long/Short split** of all above | ❌ (combined only) | ✅ | **add** |
| **Max contracts held / peak exposure** | ❌ | ✅ | optional |

### 2b. Per-trade record (`backtestTrades`)

| Field | Enma now | TradingView | Action |
|-------|----------|-------------|--------|
| type, qty, entry/exit price, times, reason, pnl, pnlPct, leverage, liqPrice | ✅ | ✅ | keep |
| **Run-up (MFE)** | ❌ | ✅ | **add** |
| **Drawdown (MAE)** | ❌ | ✅ | **add** |
| **Cumulative P&L** | ❌ (derivable) | ✅ | add (compute client-side or store) |
| **Bars held** | ❌ | ✅ | **add** |

### 2c. Client UI

| Element | Enma now | Target |
|---------|----------|--------|
| Layout | Flat: 6 cards + chart + table | Tabbed: Overview / Performance / Trades Analysis / List of Trades |
| Equity chart | Balance line only (Recharts) | + Buy & Hold line + drawdown area |
| Long/Short split | none | side-by-side columns |
| Profit factor / expectancy cards | none | headline cards |
| Per-trade MFE/MAE | none | columns in List of Trades |
| Trade markers on price | none | (stretch) entry→exit connectors on a candle chart |

---

## 3. Implementation Plan

Phased so each phase ships independently and the report improves at every step. **Invariants respected throughout:** engine is the *sole writer* of `backtestResults`/`backtestTrades` (server only proxies); positive P&L uses `emerald-400`; charts use Recharts; no new pip/npm packages without updating CLAUDE.md (none required here).

### Phase 1 — Engine: richer aggregate metrics (no schema break)

**File:** `engine/services/backtest_runner.py`, metrics block (§10, lines ~660–737).

All new values derive from data already in memory (`trades`, `pnl_values`, `balances_arr`, `candles_np`). No new candle reads.

1. **Gross profit / gross loss / profit factor**
   ```python
   gross_profit = float(np.sum(win_pnl))        # win_pnl already computed
   gross_loss   = float(np.sum(loss_pnl))       # ≤ 0
   profit_factor = gross_profit / abs(gross_loss) if gross_loss != 0 else 0.0
   ```
2. **Expectancy & payoff ratio**
   ```python
   expectancy   = float(np.mean(pnl_values)) if pnl_values.size else 0.0
   payoff_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0.0
   ```
3. **Max run-up** — mirror the existing drawdown vectorization:
   ```python
   running_min = np.minimum.accumulate(balances_arr)
   runup_arr   = np.where(running_min > 0, (balances_arr - running_min) / running_min, 0.0)
   max_runup_pct = float(np.max(runup_arr)) * 100.0
   ```
4. **Buy & Hold return** — first vs last close over the tested window:
   ```python
   first_close = candles_np[warmup_period, 2]
   last_close  = candles_np[-1, 2]
   buy_hold_pct = ((last_close - first_close) / first_close) * 100.0 if first_close > 0 else 0.0
   ```
5. **Max consecutive wins/losses** — single pass over `pnl_values` sign:
   ```python
   def _max_streak(vals, positive):
       best = cur = 0
       for v in vals:
           hit = v > 0 if positive else v <= 0
           cur = cur + 1 if hit else 0
           best = max(best, cur)
       return best
   ```
6. **Avg bars in trade** — requires per-trade bar count (Phase 2 stores `barsHeld`); until then derive from `averageHoldingPeriod / seconds_per_bar(timeframe)` using `utils/timeframes.py`.

Append to the `metrics` dict (all string-formatted to 2dp like the rest):
`grossProfit, grossLoss, profitFactor, expectancy, payoffRatio, maxRunup, buyHoldReturnPct, maxConsecutiveWins, maxConsecutiveLosses`.

### Phase 2 — Engine: per-trade MFE/MAE + bars held

Track favorable/adverse excursion **while the position is open** (in the §8 hot loop, the `else:` branch where the position updates P&L each candle, ~line 467).

1. On entry (every place an `active_trade` dict is created), seed:
   ```python
   active_trade["_entry_index"] = t
   active_trade["_mfe"] = 0.0   # max favorable price excursion, in price terms
   active_trade["_mae"] = 0.0   # max adverse
   ```
2. Each open candle, update excursions from `high_t`/`low_t` relative to entry, sign by side:
   ```python
   entry = strategy.position.entry_price
   if strategy.is_long:
       active_trade["_mfe"] = max(active_trade["_mfe"], high_t - entry)
       active_trade["_mae"] = min(active_trade["_mae"], low_t  - entry)
   else:
       active_trade["_mfe"] = max(active_trade["_mfe"], entry - low_t)
       active_trade["_mae"] = min(active_trade["_mae"], entry - high_t)
   ```
3. On close (each exit site that calls `trades.append`), convert to %, P&L, and bars:
   ```python
   active_trade["runUpPct"]   = f"{(mfe / entry) * 100:.2f}"
   active_trade["drawdownPct"]= f"{(mae / entry) * 100:.2f}"
   active_trade["barsHeld"]   = t - active_trade["_entry_index"]
   ```
4. Persist `runUpPct`, `drawdownPct`, `barsHeld` in the `trade_docs` insert (§13, ~line 791). Strip the `_`-prefixed temp keys (already the pattern for `_entry_dt`/`_exit_dt`).

> There are **5 exit sites** that append a trade (flip, strategy_exit, SL/TP/liquidation, force_close). Factor the MFE/MAE→percent conversion into one small helper so all five stay consistent — this is the main correctness risk in the phase.

### Phase 3 — Engine: Long/Short split

Compute the same block three ways. Cleanest approach: a pure helper that takes a `pnl` array (+ optional bars/excursion arrays) and returns a metric sub-dict.

```python
def _side_metrics(pnls: np.ndarray) -> dict:
    n = pnls.size
    wins = pnls[pnls > 0]; losses = pnls[pnls <= 0]
    return {
        "trades": int(n),
        "winningTrades": int(wins.size),
        "losingTrades": int(losses.size),
        "winRate": f"{(wins.size / n):.2f}" if n else "0.00",
        "netProfit": f"{float(np.sum(pnls)):.2f}",
        "grossProfit": f"{float(np.sum(wins)):.2f}",
        "grossLoss": f"{float(np.sum(losses)):.2f}",
        "profitFactor": f"{(float(np.sum(wins)) / abs(float(np.sum(losses)))):.2f}" if losses.size and np.sum(losses) != 0 else "0.00",
        "avgWin": f"{float(np.mean(wins)):.2f}" if wins.size else "0.00",
        "avgLoss": f"{float(np.mean(losses)):.2f}" if losses.size else "0.00",
    }
```

Build long/short masks from each trade's `type`, then add a nested block to `metrics`:
```python
long_mask  = np.array([tr["type"] == "long"  for tr in trades])
short_mask = np.array([tr["type"] == "short" for tr in trades])
metrics["bySide"] = {
    "all":   _side_metrics(pnl_values),
    "long":  _side_metrics(pnl_values[long_mask])  if long_mask.size  else _side_metrics(np.array([])),
    "short": _side_metrics(pnl_values[short_mask]) if short_mask.size else _side_metrics(np.array([])),
}
```

Nesting under `bySide` keeps the top-level metric keys (used by the Dashboard leaderboard and `/dashboard/stats`) untouched — **important**, the leaderboard reads `metrics.winRate`, `metrics.netProfit`, `metrics.sharpeRatio` directly.

### Phase 4 — Server passthrough (verify, likely zero-change)

The Node server only proxies engine results to Mongo/client. Confirm:
- The backtest result GET route returns `metrics` and `equityCurve` **as-is** (no field whitelist that would drop `bySide`, `profitFactor`, etc.).
- The trades route returns the new `runUpPct`/`drawdownPct`/`barsHeld` fields verbatim.

If any route hand-picks fields, widen it. No new endpoints needed.

### Phase 5 — Client: tabbed report + new cards

**Files:** `client/src/pages/Backtest.jsx`, new `client/src/features/backtest/` components. Use the existing Radix `@radix-ui/react-tabs` (already a dependency).

1. **Restructure** the results region (currently `Backtest.jsx` lines ~238–471) into tabs:
   - `Overview` — headline cards + equity chart.
   - `Performance` — All/Long/Short table from `metrics.bySide`.
   - `Trades Analysis` — win/loss stats, streaks, payoff, expectancy.
   - `List of Trades` — existing table + new MFE/MAE/bars columns.
2. **New headline cards** (reuse `BacktestMetricCard`): Profit Factor, Expectancy, Buy & Hold Δ (net profit % minus buy&hold %), plus the existing six. Profit factor > 1 → `emerald-400`, < 1 → `red-400`.
3. **New component `PerformanceTable.jsx`** — a 3-column (All/Long/Short) table reading `metrics.bySide`. Follow the existing dark table styling; positive values `emerald-400`.
4. **Extend the List of Trades table** with `Run-up`, `Drawdown`, `Bars` columns. Run-up `emerald-400`, drawdown `red-400`.
5. Guard every new field with optional chaining + fallback (`?? '-'`) so **old backtest documents** (pre-migration, no `bySide`/MFE) still render.

### Phase 6 — Client: richer equity chart

**File:** `client/src/components/charts/EquityCurve.jsx` (Recharts — invariant).

1. Add a **Buy & Hold** line. The engine stores only the strategy `equityCurve`; derive the benchmark client-side from `buyHoldReturnPct` as a straight line from start capital to `capital * (1 + buyHoldReturnPct/100)`, OR (better, optional) have the engine emit a downsampled buy&hold series alongside `equityCurve`.
2. Add a **drawdown area** below the line (`AreaChart` with negative fill, per client chart rules) — compute drawdown from the equity series in the component.
3. Keep ≤1,000 points (already enforced by engine downsampling).

### Phase 7 (Stretch) — Trade markers on a price chart

Highest-effort, highest-payoff visual. The Trade page already uses `lightweight-charts`; reuse that layer.
- Render entry/exit markers per trade with `series.setMarkers()`.
- Draw entry→exit connector lines colored by `pnl` sign (green win / red loss).
- Click a row in List of Trades → pan/highlight that trade.

Defer unless Phases 1–6 land cleanly; it needs candle data on the results page (a new lightweight kline fetch through the existing `/trade/klines` proxy).

---

## 4. Migration & Compatibility

- **Old documents:** Every new metric is additive and namespaced (`bySide`, new top-level keys). Old `backtestResults` lack them — the client must treat all new fields as optional. No backfill job; new runs get the full report, old runs degrade gracefully.
- **Dashboard leaderboard:** unaffected — it reads only `metrics.winRate`, `metrics.netProfit`, `metrics.sharpeRatio`, all still top-level.
- **No interface change to `BaseStrategy`** — this is reporting only, so no DECISIONS.md entry required. (If we later add MFE/MAE hooks to live trading, that *would* need one.)
- **No new dependencies** — Recharts, Radix Tabs, lightweight-charts are all already in `package.json`.

---

## 5. Validation

1. **Unit:** add an engine test asserting `profitFactor == grossProfit / |grossLoss|`, and that `bySide.long.trades + bySide.short.trades == totalTrades`.
2. **Invariant:** `sum(bySide.{long,short}.netProfit) ≈ metrics.netProfit` (within float tolerance).
3. **MFE/MAE sanity:** for any trade, `runUpPct ≥ pnlPct ≥ drawdownPct` (the realized P&L lies between the best and worst excursion). Assert in a test.
4. **Manual:** run a known strategy (e.g. `MicroMacroRSIDivergence`) over a fixed window before/after; confirm existing metrics are byte-identical and new ones populate.
5. **UI:** load an *old* result (no `bySide`) and a *new* result; both must render without errors.

---

## 6. Effort Estimate

| Phase | Area | Size |
|-------|------|------|
| 1 — Aggregate metrics | engine | S |
| 2 — MFE/MAE + bars | engine | M (5 exit sites) |
| 3 — Long/Short split | engine | S |
| 4 — Server passthrough | server | XS (verify) |
| 5 — Tabbed report + cards | client | M |
| 6 — Richer equity chart | client | M |
| 7 — Trade markers (stretch) | client | L |

**Recommended first slice:** Phases 1 + 3 + 5 (profit factor, gross P/L, long/short split, and the tabbed UI to surface them). That delivers the biggest perceived jump toward TradingView parity with the least risk, since none of it touches the hot loop. Phase 2 (MFE/MAE) is the only change inside the simulation inner loop and should be reviewed carefully against all five exit sites.

---

## 7. Open Questions

- **Buy & Hold series:** straight-line approximation from `buyHoldReturnPct` (cheap, client-only) vs a real per-bar benchmark series emitted by the engine (accurate, +1 stored array)? Recommend straight-line for v1, upgrade later.
- **Max contracts held / peak exposure:** include now or defer? Low value for a single-position engine; defer.
- **Avg # bars split by win/loss:** TradingView splits it; worth the extra two aggregations? Recommend yes once `barsHeld` exists (Phase 2 makes it free).
