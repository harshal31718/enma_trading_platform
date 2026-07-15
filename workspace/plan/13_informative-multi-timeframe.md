# Plan 13 — Informative / Multi-Timeframe Contract

**Status:** Ready · **Priority:** P2 · **Phase:** 9 · **Depends on:** 11 · **Related:** 16, 17

**Goal:** Let a strategy reference a higher timeframe (e.g. 1h trend filtering 5m entries) without
lookahead, using the existing two-phase `prepare()`/`before()` contract from workstream #1.

---

## Current state (audited)

- `engine/core/strategy.py` has **no** informative/multi-timeframe support — grep for
  `informative|get_candles|htf|multi.?tf` returns nothing in that file. (engine `CLAUDE.md` mentions a
  `self.get_candles(exchange, symbol, '1D')` helper, but it is not present in code — aspirational.)
- Workstream #1 (done) gave us the right seam: `BaseStrategy.prepare(candles)` runs once over the full
  array before the sim loop; `before()` is index-only. A higher-TF series must be **precomputed and
  aligned in `prepare()`**, then read by index in `before()`/`forecast()`.
- Candle access is centralized: `engine/services/candle_manager.py → ensure_candles_available()` is the
  sole entry point. Multi-TF fetch must go through it.

## Upstream reference (freqtrade `@informative`)

From `freqtrade/strategy/informative_decorator.py`:
- A strategy declares an informative timeframe declaratively; freqtrade captures `InformativeData
  {asset, timeframe, fmt, ffill, candle_type}`.
- Columns are renamed `"{column}_{timeframe}"` (e.g. `ema_1h`) then merged into the base dataframe via
  `merge_informative_pair()`.
- **Lookahead safety = `ffill=True` after an as-of merge**: each base candle sees only the *last
  closed* higher-TF candle. freqtrade also shifts so the in-progress HTF candle is never visible.

The critical idea to port: **as-of align the HTF series to base-candle timestamps, forward-filled,
shifted by one HTF bar so only closed HTF candles are visible.**

## Design (Enma-native, prepare()-based)

Keep it declarative and backward-compatible. No change to the `forecast()` boundary rules.

### Contract
```python
class MyStrat(BaseStrategy):
    informative_timeframes = ["1h"]            # opt-in; default [] = no behavior change

    def prepare(self, candles):
        super().prepare(candles)
        htf = self.htf("1h")                   # aligned, lookahead-safe OHLCV for the base index
        self.vars["ema_1h"] = ta.ema(htf, period=50, sequential=True)

    def forecast(self):
        if self.close > self.vars["ema_1h"][self.index]:   # index-aligned to base candles
            ...
```

### `BaseStrategy.htf(timeframe)` helper
1. Fetch the HTF candles for `self.symbol` over the **same date range** via `ensure_candles_available()`.
2. **As-of align** HTF rows onto the base timeframe's timestamps: for each base candle at time `t`,
   pick the most recent HTF candle whose **close time ≤ t** (i.e. the last *closed* HTF bar). This is a
   `searchsorted` on HTF close-times — O(N log M).
3. Return a base-length numpy OHLCV array so any `ta.*(..., sequential=True)` indexes cleanly by
   `self.index`.
4. Cache per `(symbol, timeframe)` so multiple indicators on the same HTF fetch once.

### Lookahead guarantee
The as-of rule (`close_time ≤ t`, shifted one bar) is the same guarantee freqtrade's `ffill+shift`
gives. **S5 (lookahead analysis) must be run against any strategy using `htf()`** to prove no leak.

### Live parity
`live_bot_manager.py` already re-runs `prepare()` on the rolling window each closed candle (workstream
#1, P7). `htf()` must work on that rolling window too — fetch HTF for the window's date span. Same code
path = exact parity, as with the base contract.

## Files to create / modify

| Action | File | Change |
|--------|------|--------|
| Modify | `engine/core/strategy.py` | `informative_timeframes` attr + `htf(tf)` helper (as-of align + cache) |
| Modify | `engine/services/backtest_runner.py` | Ensure HTF candles fetched before `prepare()` (it already calls `prepare`); pass through `candle_manager` |
| Modify | `engine/core/live_bot_manager.py` | `htf()` works on rolling window; warmup replay covers HTF |
| Create | `engine/tests/test_informative_alignment.py` | As-of alignment correctness + no-lookahead (last value uses only closed HTF bars) |
| Modify | `workspace/docs/core/DECISIONS.md` | Record the multi-TF contract decision (it extends BaseStrategy) |

## Verification gate

- **Golden master byte-identical** for all 5 seeded strategies (none declare `informative_timeframes`,
  so the default `[]` path is a no-op): `compare --a baseline --b s2` OK.
- Boundary suite 20/20 (the `htf()` helper must not let `forecast()` violate the alpha boundary —
  it only reads precomputed `self.vars`).
- Alignment unit test: a hand-built HTF series aligns to base timestamps with the correct as-of value
  and **never** reveals an HTF candle that closes after the base candle.

## Sequencing & risks

- After V0/S1. It's a contract change, so it precedes the analysis tools that will exercise it (S5/S6).
- Risk: timezone / candle-close-time off-by-one is the classic multi-TF lookahead bug. The as-of
  comparison must use HTF **close** time, not open time. S5 is the safety net.
- Risk: extra Binance fetches for the HTF — reuse `ensure_candles_available()` caching; never bypass it.
