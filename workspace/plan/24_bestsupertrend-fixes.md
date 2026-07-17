# 24 — BestSupertrend: why it never trades, and the fix set

**Status: ALL SHIPPED 2026-07-17 (S-1 through S-5), container-verified** — pending live Testnet
re-verification only (see the plan's own "Sequencing / verification" section below).
**Priority:** P1 (a seeded strategy that silently can't trade at default settings is a
trust bug, not a feature gap)

## Shipped summary (2026-07-17)

All five findings fixed in sequence (S-1 → S-2 → S-3 → S-4 → S-5), each independently committed,
golden-master-verified where applicable, and container-tested (`docker exec
enma_trading_platform-engine-1 pytest /app/tests/`):

- **S-1** (`engine/core/strategy.py`'s `size_by_notional()` + `position_size_pct` default 1.0→0.9):
  now sizes DOWN to the true affordable notional (accounting for leverage, slippage, taker fee)
  instead of letting the downstream affordability check reject the entry outright. Golden master
  re-baselined — only BestSupertrend diverges (same 61 trades/win-loss structure, PnL scaled by
  the smaller position size); the other 4 seeded strategies are byte-identical (no other caller of
  `size_by_notional`). New `test_size_by_notional_affordability.py` (7 cases) proves entries are
  now affordable at leverage=1/pct=1.0 — the actual bug scenario, which `golden_master.py`'s own
  leverage=3 harness never exercised.
- **S-2** (`prepare()`'s live constant path): read `self._htf_tsl[-2]` when `_fetch_htf_candles`
  already excludes the in-progress bar, making the live path one full HTF bar more stale than
  backtest. Fixed to `[-1]`; golden master confirmed byte-identical (live-only branch, never
  exercised by backtest). New parity test (5 cases) drives the real class through both the live
  constant path and the equivalent bucket-path formula, confirming they agree.
- **S-3** (structurally unsatisfiable tf/timeframe combos): new
  `required_base_candles_for_htf()` (`engine/utils/timeframes.py`) estimates the base-candle count
  needed for `pd+2` completed HTF buckets. Backtest logs an error (log-only, zero simulation-output
  change — golden master confirmed byte-identical) when the loaded window can't satisfy it; live's
  HTF-fetch failure and on-success-but-insufficient-data are both now session-visible errors
  (previously a warning-level log only), plus a new one-time warning once the live rolling
  candle window hits its 500-candle cap with the HTF value still unresolved. 8 new unit tests for
  the shared helper.
- **S-4** (`order_type` param rename): renamed to `direction_filter` — the old name collided with
  `OrderPlan.order_type`, silently overriding it with the filter string instead of `"market"` (decorative
  today, would have detonated the moment any consumer honored `OrderPlan.order_type`). Golden
  master confirmed byte-identical. 3 new tests confirm `BaseStrategy`'s own `order_type="market"`
  default now shows through correctly.
- **S-5** (docs drift): the `SignalExitRiskModel`→`AtrBracketRiskModel`/`NotionalPortfolio` doc
  drift was already fixed in an earlier session (confirmed 2026-07-17 while surveying, before this
  window started). The one remaining item — the weekly-resample (`W-MON`) off-by-one TODO comment
  — is intentionally left as documentation only per this plan's own instruction ("fold into S-3's
  start-time validation rather than fixing resample semantics blind"); S-3's generic warmup-
  sufficiency check now covers it without touching the resample math itself.
  `workspace/docs/strategies/BestSupertrend.md` updated for all of S-1/S-2/S-3/S-4's user-visible
  changes (param rename, new default, tsl[-1] correction, tf/timeframe warmup note).

**Container suite: 353/353 passed** (up from 337/337 baseline at the start of this plan's work).
**Not done:** the live-verification step described in "Sequencing / verification" below (one
1-symbol testnet session at leverage 2–3 confirming ≥1 real entry and HTF-value parity against a
parallel backtest window) — requires a human-observed live session, marked pending same as every
other live-verification item across this codebase's plans.

---
**Source:** full read of `engine/strategies/BestSupertrend/__init__.py` (404 lines) +
`NotionalPortfolio`/`size_by_notional`/`EntryFill.affordable` + `backtest_runner.py`'s entry
rejection path + `Settings.js` defaults. User report: "it has some flaws and never generates
trades" — confirmed, with the primary cause isolated.

---

## S-1 · PRIMARY: `position_size_pct=1.0` default × leverage-1 default = every entry rejected · [Certain]

The arithmetic, at the platform's own defaults (`Settings.js`: `defaultLeverage: 1` for
backtest, `defaultBotLeverage: 1` for live bots; strategy default `position_size_pct: 1.0`):

```
qty       = equity × 1.0 / price                      (size_by_notional)
fill      = price × (1 + slippage)                    (adverse fill, backtest)
notional  = qty × fill = equity × (1 + slippage)      > equity
req_margin= notional / leverage(=1) = equity × 1.0005 > balance
→ EntryFill.affordable(free_balance) is False for EVERY entry, always.
```

`backtest_runner.py:325` then logs `"Entry rejected: margin + fee exceeds free capital"` —
a log line users never see — and returns. **Zero trades, structurally, at default settings.**
Live path at leverage 1: the same order reaches Binance and dies with `-2019 Margin is
insufficient` per entry attempt (resilient-failure path clears the signal, retries next
signal, forever). At leverage ≥ 2 the strategy can trade (margin = notional/lev leaves
headroom) — which is why Chaos runs (default 50x) may show trades while default backtests
show none. The other 4 seeded strategies are unaffected: they size by risk (~1–2% of equity),
never by 100% notional.

**Fix (two parts, both output-changing → needs a BestSupertrend re-baseline, a cheap one since
the current baseline plausibly contains zero trades):**
1. `size_by_notional()` (single owner, `core/strategy.py`) sizes to *affordable* notional:
   `qty = min(equity×pct, (free_balance − est_fee) × leverage / (1+slippage)) / price` — i.e.
   size-down instead of letting the runner reject (freqtrade behavior: stake adjusted to
   available). Keeps 100%-notional configs functional at any leverage.
2. Drop the strategy default `position_size_pct` 1.0 → 0.9 (belt and braces; 1.0 with zero
   headroom is a footgun even after fix 1).

## S-2 · Live HTF supertrend is one full HTF bar more stale than backtest · [Certain]

Live pre-fetches `_htf_candles` with the in-progress HTF bar **already excluded**
(`_fetch_htf_candles` does `raw[:-1]`), so the last array element IS the last completed bar —
but `prepare()`'s constant path takes `tsl[-2]`, skipping one extra bar back. Backtest's bucket
path (`htf_tsl[k-1]`, where `k` is the in-progress bucket) correctly uses the last completed
bar. Net: at the default `tf="daily"`, live trades against the supertrend from **two days ago**
while backtest uses yesterday's. Fix: constant path takes `tsl[-1]`; add a parity unit test
(same data through both paths must produce the same `st_tsl_tf` per candle).

## S-3 · Structurally unsatisfiable tf/timeframe combos fail silent-forever · [Certain]

`_htf_st_at()` returns `None` (→ all signals False → no trades, no log) until `pd+2` = 12
completed HTF buckets exist. Two ways this becomes *permanent*:
- **Live fallback:** if the startup HTF fetch fails, `prepare()` silently falls back to
  resampling the rolling ≤500-candle base window. 500×1m ≈ 8.3h; 500×5m ≈ 41h; 500×15m ≈ 5.2d —
  none can ever form 12 daily buckets. Zero trades forever, one warning log at startup only.
- **Any config:** `tf="weekly"` needs 12 completed weeks ≈ 2,016 hourly candles — impossible
  under the 500-candle live cap on any base ≤ 4h, and silently zero-trade in most backtests.
  `tf="monthly"` is worse.

**Fix:** (a) at session/backtest start, compute
`required_base_candles ≈ (pd+2) × htf_bucket / base_timeframe` and **fail loud** (reject start
or emit a persistent session-log error) when it exceeds the available window; (b) if
`_htf_st_at` is still `None` N candles after warmup completes, emit a one-time warning
notification instead of staying silent; (c) live HTF-fetch failure at startup should be a
session-visible error, not a debug log, given (a).

## S-4 · `order_type` param name collides with the execution-model field · [Certain, latent]

The strategy's direction filter param is named `order_type` ("Longs+Shorts"/"LongsOnly"/
"ShortsOnly"). `DefaultExecution.route()` builds `OrderPlan(order_type=getattr(s, "order_type",
"market"))` — so every BestSupertrend OrderPlan carries `order_type="Longs+Shorts"` instead of
`"market"`. Currently decorative (both adapters hardcode MARKET), but it detonates the moment
any consumer honors `OrderPlan.order_type` (e.g. Plan 6's exchange abstraction or a future
limit-order path). Fix: rename the param to `direction_filter` (PARAMS key change — note it in
the strategy INDEX; saved configs with the old key will be rejected by F-016 unknown-param
validation, which is the desired loud failure).

## S-5 · Docs drift · [Certain, minor] — **docs-drift half already resolved (checked 2026-07-17)**

`engine/CLAUDE.md` ("Built-in strategies" / model-variant notes) and `MODELS`-adjacent docs
describe BestSupertrend as bound to `SignalExitRiskModel`; the code binds `AtrBracketRiskModel`
(+ `NotionalPortfolio`) with signal exits layered via `forecast()` returning 0. Update docs to
match code (code wins). Also carry the code's own TODO: weekly resample (`W-MON`,
right-labeled) has a known off-by-one bucket edge — fold into S-3's start-time validation
rather than fixing resample semantics blind.

**Checked while surveying for decision-free/golden-master-free work (2026-07-17):** grepped the
whole repo for `SignalExitRiskModel` — `workspace/docs/features/strategy-management/SPEC.md`
(row 110) and `workspace/docs/strategies/BestSupertrend.md` ("Risk Model" section) both already
correctly say `AtrBracketRiskModel` + `NotionalPortfolio` and explicitly note "(replaced the
earlier `SignalExitRiskModel`)" — some prior session already fixed this half, not reflected as
struck-through here. `engine/CLAUDE.md` and `workspace/docs/core/MODELS.md` never actually made
the stale binding claim in the first place (both just list model variants generically, no
per-strategy binding assertion). **Remaining under S-5: only the weekly-resample TODO**, which is
correctly scoped to fold into S-3 (needs a golden-master re-baseline this environment can't run —
no Docker access) rather than being fixed standalone.

## Sequencing / verification

- S-1 fix + S-2 fix change BestSupertrend backtest outputs → **one re-baseline for this
  strategy's golden runs** (trivial if the old baseline has zero trades — verify that first:
  `grep totalTrades` on the stored BestSupertrend baseline; if non-zero, someone ran it at
  leverage ≥ 2 and the re-baseline needs actual review).
- S-3/S-4 are behavior-visible but only in configs that currently produce zero trades or dead
  fields — low re-baseline risk, still verify.
- Order: S-1 → S-2 → S-3 (needs S-1 to even observe trades) → S-4/S-5 (any time).
- Live verification after S-1/S-2: one 1-symbol testnet session at leverage 2–3, default params,
  confirm ≥1 entry when signals align and that entry/HTF values match a parallel backtest
  window. Gate on Plan 21.1–21.2 landing first (fill-path correctness) so the verification
  session is trustworthy.
