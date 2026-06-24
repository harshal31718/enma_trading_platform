# 05 — Minimum-Requirement Boundaries: Enma vs. freqtrade

> Checkpoint 5 on the pipeline spine. Exchange filters: minNotional, LOT_SIZE / MARKET_LOT_SIZE,
> PRICE_FILTER tickSize, stepSize, precision rounding.
> **Upstream reference:** `freqtrade/exchange/exchange.py`.

This doc carries the **headline root cause (RC-1)**: precision / min-notional guards run live and
are skipped in backtest.

---

## How freqtrade handles it

| Concern | Method | Behaviour |
|---|---|---|
| Qty → step size | `amount_to_precision(pair, amount)` | rounds quantity to exchange precision via market metadata |
| Contract qty | `amount_to_contract_precision(pair, amount)` | precision + contract-size conversion |
| Price → tick size | `price_to_precision(pair, price, rounding_mode=ROUND)` | **direction-aware**: stoploss must use `ROUND_DOWN` for longs, `ROUND_UP` for shorts (conservative) |
| Min stake/notional | `get_min_pair_stake_amount(pair, price, stoploss, leverage)` → `_get_stake_amount_limit(limit="min")` | `max(cost_min, amount_min)` then a **reserve buffer**: `margin_reserve = 1 + amount_reserve_percent (5% default)`, `stoploss_reserve = margin_reserve / (1 - abs(stoploss))` |
| Max stake | `get_max_pair_stake_amount(...)` → `_get_stake_amount_limit(limit="max")` | `min` across cost/amount limits |
| Application point | `exchange.create_order()` | `amount_to_precision()` + `price_to_precision()` applied **inside create_order** |

**The structural property that matters:** `create_order()` is the **single path** for live *and*
dry-run/backtest. Precision and min-stake are applied where the order is created, so neither mode
can fill what the other rejects. Min-stake also includes a **reserve** so a bumped order stays
affordable after fees/stop buffer.

---

## How Enma handles it

| Concern | Location | Behaviour |
|---|---|---|
| Filter fetch/cache | `engine/utils/symbols.py:load_exchange_rules()` | parses PRICE_FILTER, LOT_SIZE, MARKET_LOT_SIZE, MIN_NOTIONAL into `_rules_cache`; called at `main.py:lifespan()` |
| Qty round + min enforce | `engine/utils/symbols.py:clamp_and_round_qty()` | round↓ to stepSize → ensure ≥ minQty → bump↑ to minNotional → re-verify minQty |
| Price round | `engine/utils/symbols.py:round_price()` | round to tickSize, **ROUND_DOWN only** (not direction-aware) |
| Orphan | `engine/utils/symbols.py:round_qty()` | defined, **never called** |
| Live application | `engine/core/live_bot_manager.py:_execute_entry()` L523 (`clamp_and_round_qty`), L526-527 (`round_price` for SL/TP), L538-554 (notional vs buying power) | enforced |
| **Backtest application** | `engine/services/backtest_runner.py` L563-564, 607-608 (qty raw), L689-725 (SL/TP raw) | **NOT enforced** |
| Symbol list | `engine/core/constants.py:FUTURES_SYMBOLS` (50) | duplicated in `client/src/utils/symbolLimits.js`, `server/src/constants/top_symbols.js` |
| Max leverage | `engine/utils/symbols.py:get_max_leverage()` / `clamp_leverage()` | fetch/cache, offline fallback map |

---

## Gaps & root causes

### RC-1 (here) — Backtest skips the guards live enforces

freqtrade applies precision + min-stake inside the one `create_order()` both modes share. Enma
applies `clamp_and_round_qty()` and `round_price()` **only** in `_execute_entry()` (live). The
backtest reads `strategy.buy/sell` quantity and `strategy.stop_loss/take_profit` prices raw. So:
- Backtest fills sub-minNotional / sub-stepSize quantities the exchange rejects (JUPUSDT: $6 sized
  fill in backtest vs $50 min-notional reject live).
- Backtest SL/TP exits trigger at prices off the tick grid — unreachable live.

Backtest performance is therefore structurally optimistic and not reproducible. The fix shape
freqtrade points to: a **single shared validation path** both backtest and live route through.

### Direction-unaware price rounding

freqtrade rounds stop prices **conservatively by side** (`ROUND_DOWN` long, `ROUND_UP` short) so
rounding never makes a stop easier to skip. Enma's `round_price()` is always `ROUND_DOWN`
regardless of side or whether it's an SL or TP — for some side/level combinations this nudges the
stop the wrong way (wider risk or a TP that rounds away from fill).

### No reserve buffer on the min-notional bump

freqtrade's min-stake includes a margin/stoploss reserve (~5% + stoploss) so a bumped order is
still affordable after fees and stop distance. Enma bumps to the exact minNotional then checks
buying power and may **reject** — an order that a small reserve would have sized correctly.

### Symbol list maintained in three places

`FUTURES_SYMBOLS` (engine), `symbolLimits.js` (client), `top_symbols.js` (server) are parallel
hand-maintained lists. Drift between them is a latent source of "symbol tradable here, not there"
bugs. Suspended symbols (FTMUSDT, WAVESUSDT) were removed by deletion with no explicit marker.

---

## Findings

| ID | Severity | One-line | Enma file(s) | Reference |
|----|----------|----------|--------------|-----------|
| F-005 | CRITICAL | Backtest never calls `clamp_and_round_qty()` → fills sub-minNotional/sub-stepSize orders live rejects (JUPUSDT class) | `engine/services/backtest_runner.py:563-564,607-608` | freqtrade `create_order` → `amount_to_precision` / `get_min_pair_stake_amount` |
| F-006 | CRITICAL | Backtest SL/TP prices not rounded to tickSize (`round_price` not called) → exits at prices unreachable live | `engine/services/backtest_runner.py:689-725` | freqtrade `create_order` → `price_to_precision` |
| F-007 | HIGH | `round_price()` always ROUND_DOWN, not direction-aware; can nudge stop the wrong way | `engine/utils/symbols.py:round_price` (callers in `live_bot_manager.py:526-527`) | freqtrade `price_to_precision(rounding_mode)` ROUND_DOWN long / ROUND_UP short |
| F-008 | MEDIUM | No reserve buffer on min-notional bump → orders that a ~5%+stoploss reserve would size correctly get rejected at buying-power check | `engine/utils/symbols.py:clamp_and_round_qty`, `live_bot_manager.py:538-554` | freqtrade `_get_stake_amount_limit` margin/stoploss reserve |
| F-009 | MEDIUM | Tradable-symbol list maintained in 3 parallel places; drift risk; suspended symbols removed without explicit marker | `engine/core/constants.py:FUTURES_SYMBOLS`, `client/src/utils/symbolLimits.js`, `server/src/constants/top_symbols.js` | freqtrade single market metadata source |
| F-010 | LOW | `round_qty()` defined but never called (dead code) | `engine/utils/symbols.py:round_qty` | n/a |

---

## What Enma could adopt

- Route backtest entry/exit through the **same** `clamp_and_round_qty()` + `round_price()` the live
  path uses (single shared validation path) — kills F-005/F-006 and RC-1 structurally.
- Make `round_price()` **direction-aware** (side + SL/TP) like `price_to_precision`'s rounding mode.
- Add a small reserve to the min-notional bump so a bumped order stays affordable.
- Derive the three symbol lists from one source (engine `exchangeInfo`) instead of hand-syncing.
