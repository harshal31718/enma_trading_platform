# 03 — Parameter Handling & Portfolio Management: Enma vs. freqtrade

> Checkpoint 3 on the pipeline spine. Strategy param schema/validation, equity/portfolio accounting,
> multi-symbol behaviour.
> **Upstream reference:** `freqtrade/strategy/parameters.py`, `freqtrade/wallets.py`.

---

## Parameters

### freqtrade — typed parameter objects, bounds enforced at construction
`BaseParameter` → `NumericParameter` → `IntParameter` / `RealParameter` / `DecimalParameter`,
plus `CategoricalParameter` / `BooleanParameter`. Each is declared once as a class attribute:
- Constructor takes `low, high, *, default, space, optimize, load` (or `[low, high]` sequence).
- `NumericParameter` **validates at construction** that a high bound is present.
- `DecimalParameter` enforces precision via its setter; `CategoricalParameter` requires ≥2 categories.
- The **same declaration** drives hyperopt search space (`get_space()`) and the runtime `value`/`range`.
One typed object = one source of bounds, validated when the strategy class loads.

### Enma — dict schema, injected by `setattr`, clamped silently across two services
`engine/core/strategy.py:BaseStrategy.PARAMS` is a dict list `{name, type, default, min, max}`.
Injection (`backtest_runner.py:282-300`): for each incoming param, if in `PARAMS` **clamp to
[min,max]**, else **`setattr` only if the attribute already exists**, then best-effort
`validate_params()`. Risk params take a separate path through `server/src/utils/risk.js` (4-tier
cascade + clamp). Two consequences:
- Out-of-range values are **silently clamped**, not rejected — the user runs a backtest with
  different parameters than they entered, with no signal. → **F-015**
- An unknown / typo'd param name is **silently dropped** (the `setattr`-if-exists branch) — no error,
  the strategy runs with the default. → **F-016**

---

## Portfolio / equity

### freqtrade — continuous wallet accounting
`wallets.py` tracks `free / used / total` continuously; `get_available_stake_amount()` =
`min(total*tradable_balance_ratio − open_stakes, free)`. Multi-pair capital is one shared wallet,
reconciled to the exchange each loop (live) or simulated consistently (backtest) — **the same
accounting object** in both modes.

### Enma — per-symbol allocation, single-symbol backtest vs multi-symbol live
- Live: `DefaultPortfolioModel.allocate(capital, symbols)` splits equity per symbol
  (`live_bot_manager.py`); `strategy.available_margin = balance − position.margin`.
- Backtest: `run_backtest_simulation()` runs **single-symbol**; equity curve is one symbol's path.
- Equity curve downsampled to 1000 points for BSON limits (`backtest_runner.py:972-985`).

Because backtest is single-symbol and live splits capital across symbols with shared margin and
correlated drawdowns, **a backtest equity curve does not represent a live multi-symbol session** —
portfolio-level risk (concurrent positions, aggregate drawdown) is never validated before going
live. → **F-017**

---

## Gaps & root causes

- **Param validation is split, dict-typed, and silent** (F-015, F-016): no single typed schema like
  freqtrade's parameter objects; bounds live partly in engine `PARAMS`, partly in `risk.js`; failures
  are silent clamps/drops rather than explicit rejections. This is the same "validation lives in the
  wrong/duplicated place" theme as F-014.
- **Backtest ≠ live at the portfolio level** (F-017): single-symbol backtest cannot surface the
  aggregate-exposure and correlated-drawdown behaviour the live multi-symbol allocator produces — a
  portfolio-scope cousin of the backtest↔live asymmetry (RC-1).

---

## Findings

| ID | Severity | One-line | Enma file(s) | Reference |
|----|----------|----------|--------------|-----------|
| F-015 | MEDIUM | Out-of-range params silently clamped (not rejected) → backtest runs with different params than entered, no signal to user | `engine/services/backtest_runner.py:282-300`, `engine/core/strategy.py:PARAMS` | freqtrade typed `NumericParameter` bounds validated at construction |
| F-016 | LOW | Unknown/typo'd param name silently dropped (`setattr`-if-exists) → runs with default, no error | `engine/services/backtest_runner.py:~295` | freqtrade explicit parameter declaration |
| F-017 | MEDIUM | Backtest is single-symbol while live splits capital multi-symbol with shared margin → backtest equity curve unrepresentative; portfolio-level risk never validated pre-live | `engine/services/backtest_runner.py:run_backtest_simulation`, `engine/core/models/portfolio.py:allocate` | freqtrade shared `wallets` accounting across pairs (both modes) |

---

## What Enma could adopt

- A **single typed parameter schema** (one declaration with bounds) shared by UI, server, and engine,
  and make out-of-range / unknown params **explicit errors** surfaced to the user, not silent
  clamps/drops.
- Re-assert risk/param bounds inside the engine (ties to F-014) so one validation source governs both.
- Consider a **multi-symbol (portfolio) backtest mode** so aggregate exposure and correlated drawdown
  are validated before live — closing the portfolio-scope half of RC-1.
