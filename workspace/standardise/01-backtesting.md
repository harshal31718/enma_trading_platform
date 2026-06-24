# 01 — Backtesting: Enma vs. freqtrade

> Checkpoint 1 on the pipeline spine. Fill model, fees, slippage, SL/TP-in-backtest, candle handling.
> **Upstream reference:** `freqtrade/optimize/backtesting.py`.
> Inherits the **headline root cause RC-1** (backtest skips live guards) — the concrete order-limit
> findings live in `05-boundaries.md` (F-005/F-006); this doc covers fill realism.

---

## How freqtrade backtests

Per-candle loop `backtest()` → `backtest_loop(row, pair, current_time, ...)`, processed in order:

1. `manage_open_orders()` — reconcile open orders (timeouts/fills) **first**
2. `_enter_trade()` — new entries
3. `_try_close_open_order()` — fill entry orders
4. `_check_trade_exit()` — exits (SL / ROI / signal)
5. `_process_exit_order()` — fill exits

**Entry fill:** signal data is `.shift(1)` — entries fill on the candle **after** the signal. Fill
rate is constrained to the candle: `_get_order_filled()` requires `low <= rate <= high`; price is
clamped (`min(propose_rate, high)` long / `max(propose_rate, low)` short).

**Critically — precision + min-stake are applied IN backtest `_enter_trade()`:**
- `price_to_precision(close_rate, ...)`
- `amount_to_contract_precision(amount, ...)`
- `wallets.validate_stake_amount(min_stake_amount, max_stake_amount, ...)` — rejects sub-min-stake
- via `get_valid_entry_price_and_stake()` — the **same validation live uses**.

**SL fill realism (gap modelling):** `_get_close_rate_for_stoploss()` — if the stop is beyond the
candle (`stoploss_value > high` long / `< low` short), it **fills at the candle OPEN** (models the
gap-through worst case), else at the stop rate clamped to `[low, high]`.

**Fees:** fixed pct, `set_fee()` takes `max(maker, taker)`; applied as `cost = amount * rate * (1 + fee)`
on both entry and exit. **Slippage:** not implicitly modelled — fills bounded by candle range;
strategy supplies slippage via `custom_entry_price` / `custom_exit_price`.

---

## How Enma backtests

`engine/services/backtest_runner.py:run_backtest_simulation()`:

| Concern | Location | Behaviour |
|---|---|---|
| Entry fill | L562-647 | fills at **next-candle OPEN** |
| Entry slippage | `core/models/execution.py:entry_fill` | fixed **adverse %**: `open*(1+slip)` buy / `open*(1-slip)` sell |
| Exit fill | L688-718, `execution.exit_fill` | SL/TP at the **exact** stop/target price |
| Exit priority | L681-718 | LIQUIDATION → STOP-LOSS → TAKE-PROFIT; SL checked before TP same-candle (`not closed` guard) |
| Fees | `core/models/cost.py:fee` (L33-38) | taker `notional * fee_rate` on every fill |
| Funding | L666-674 | charged at 8h UTC boundaries |
| Liquidation | `core/position.py:is_liquidated` (L682), loss capped at margin (L731) | isolated-margin model |
| Candles | `candle_manager.ensure_candles_available` (L213-225), reject < 50 (L242-246) | auto-fetch + warm-up min |
| **Precision / min-stake** | — | **not applied** (see F-005/F-006 in `05-boundaries.md`) |

---

## Gaps & root causes

### RC-1 (inherited) — backtest skips the precision/min-stake guards
freqtrade enforces `price_to_precision` + `amount_to_contract_precision` + `validate_stake_amount`
inside backtest `_enter_trade()`, sharing live's validation. Enma's backtest applies none.
Concrete findings: **F-005, F-006** (`05-boundaries.md`).

### Optimistic stop fills — no gap modelling
Enma fills SL/TP at the **exact** stop/target price even when the candle gapped straight through it.
freqtrade fills a gapped stop at the candle **OPEN** (the realistic worst case). Enma therefore
**understates loss on gap-downs** and overstates SL precision — a direct over-optimism in reported
backtest results. → **F-011**

### Slippage model is a fixed arbitrary % vs. candle-bounded fills
Enma applies a fixed adverse slippage % at fill. freqtrade applies none implicitly and instead
bounds fills to the candle range, leaving slippage to an explicit strategy callback. Enma's fixed %
is at least adverse (conservative direction) but is not order-book / size aware and is uniform
across symbols of very different liquidity. → **F-012**

### Parity-OK (note, not findings)
- Both fill entries on the **next** candle (Enma at open; freqtrade clamped within range) — aligned.
- Enma's SL-before-TP same-candle ordering is the conservative choice — fine.
- Candle auto-fetch + warm-up minimum is a sound pattern freqtrade shares.

---

## Findings

| ID | Severity | One-line | Enma file(s) | Reference |
|----|----------|----------|--------------|-----------|
| F-011 | HIGH | Backtest fills SL/TP at exact stop/target even on gap-through candles → understates gap loss, over-optimistic results | `engine/services/backtest_runner.py:688-718`, `core/models/execution.py:exit_fill` | freqtrade `_get_close_rate_for_stoploss` (gap → fill at OPEN) |
| F-012 | MEDIUM | Fixed adverse slippage % is symbol/size-agnostic; not liquidity-aware | `engine/core/models/execution.py:entry_fill/exit_fill`, `cost.py:adverse_fill` | freqtrade candle-bounded fills + explicit slippage callback |

> The CRITICAL backtest↔live precision findings (F-005/F-006) are owned by `05-boundaries.md` and
> not duplicated here.

---

## What Enma could adopt

- Route backtest entry/exit through the **same** precision + min-stake validation as live
  (kills RC-1). freqtrade proves one shared path is feasible without slowing backtests.
- Model **gap-through stops**: when a candle's range fully skips the stop, fill at the candle OPEN,
  not the stop price.
- Reconsider the fixed-% slippage in favour of candle-bounded fills (or a liquidity-scaled model).
