# 04 — SL/TP Placement & OCO Mutual-Cancel: Enma vs. freqtrade & nautilus

> Checkpoint 4 on the pipeline spine. Stop-loss / take-profit placement, OCO mutual-cancel, and the
> unprotected-position window.
> **Upstream references:** `nautilus_trader` advanced orders (contingency model — primary here),
> `freqtrade/freqtradebot.py` stoploss-on-exchange (failure handling).

This is the checkpoint where **nautilus is the better teacher** — it models contingent orders
natively; freqtrade is the teacher for **what to do when stop placement fails**.

---

## How nautilus models it (the gold standard for contingency)

- **Bracket** = entry + stop-loss (`STOP_MARKET`) + take-profit (`LIMIT`), built via
  `order_factory().bracket()`, returned ordered `[entry, stop-loss, take-profit]`.
- Children are **`reduce_only`** and linked with **`OUO`** contingency.
- `ContingencyType`:
  - **OTO** (one-triggers-other): parent fill auto-places children.
  - **OCO** (one-cancels-other): any fill — **full _or partial_** — best-effort cancels the rest.
  - **OUO** (one-updates-other): any partial execution **proportionally reduces the remaining
    quantity** of the peer leg.
- Linking fields: all legs share `order_list_id`; children reference parent via `parent_order_id`.
- **The key property Enma lacks:** under OUO, a **partial** TP fill immediately and proportionally
  reduces the SL quantity (and vice-versa), so the protective leg never covers more than the open
  position.

## How freqtrade handles stop placement + failure

- SL is placed **on-exchange** after entry (`create_stoploss_order`); TP/ROI is handled
  **internally** (freqtrade exits with a market order — it does not use native exchange OCO).
- `handle_stoploss_on_exchange()` polls the stop order; on `closed`/`triggered` it records the exit.
- Trailing = **cancel + replace** (`handle_trailing_stoploss_on_exchange` →
  `cancel_stoploss_on_exchange` → `create_stoploss_order`), throttled by `stoploss_on_exchange_interval`.
- **Failure path is explicit:** if `create_stoploss_order()` fails after entry —
  `InvalidOrderException` → **`emergency_exit()`** (market force-exit) so the position is never left
  naked; `InsufficientFundsError` → `handle_insufficient_funds()` recovery first.

---

## How Enma does it

From `engine/core/live_bot_manager.py` + `server/src/controllers/trade.controller.js`:

- Entry `MARKET` + conditional SL (`STOP_MARKET`) + TP (`TAKE_PROFIT`) sent via Node
  `/internal/algo/sessions/{id}/place-order`; OCO grouping via `placeOCOOrder()` →
  engine `/trade/order/oco_futures`, legs sharing clientOrderId prefix `oco_<uuid>_` (CLAUDE.md #5).
- Binance natively cancels the linked leg when one fills.
- Exits detected by **polling** `_check_exits()` each candle; `_close_position()` clears both legs,
  records the trade, emits dual notification (toast + banner).
- **Failure handling after entry:** per the pipeline map, if entry fills but SL placement fails, the
  code **logs the error, emits a notification, and clears pending signals** — there is **no
  emergency market exit**.

---

## Gaps & root causes

### Unprotected-position window has no emergency exit (RC-C made concrete)
Entry and its protective SL are **separate** Binance orders placed across the engine→Node→engine→
Binance hop chain (RC-C). If the entry fills and SL placement then fails, Enma leaves the position
**naked** and only logs/notifies. freqtrade treats this exact case as an emergency:
`emergency_exit()` force-closes at market. This is a direct money-risk gap. → **F-018**

### No partial-fill quantity propagation between legs (no OUO equivalent)
Enma relies on Binance's native OCO **full** cancel. nautilus's **OUO** proportionally reduces the
peer leg on **partial** fills. If Enma's TP (or SL) partial-fills, the still-resting leg can cover
**more than the remaining position**, risking an over-close / unintended reversal on the residual.
Enma has no logic to reduce the linked leg's quantity on partial fill. → **F-019**

### Exit detection is poll-based, not event-driven (ties to F-002)
Enma learns about SL/TP fills by **polling** `_check_exits()` / `_verify_exchange_position_still_open()`
on candle close. There is no Binance **user-data-stream** listener for order/fill events. Between a
real fill and the next candle, the engine's view is stale — the same desync window F-002 describes,
now on the exit side. nautilus is fully event-driven; freqtrade polls but reconciles every loop. → **F-020**

---

## Findings

| ID | Severity | One-line | Enma file(s) | Reference |
|----|----------|----------|--------------|-----------|
| F-018 | HIGH | Entry fills but SL placement fails → position left naked; only logs/notifies, no emergency market exit | `engine/core/live_bot_manager.py:_execute_entry` (failure branch ~L604-612) | freqtrade `emergency_exit()` on stop-placement failure |
| F-019 | HIGH | No partial-fill quantity propagation between SL/TP legs; relies on Binance full-cancel → resting leg can over-close residual position | `engine/core/live_bot_manager.py:_check_exits/_close_position`, `server/src/controllers/trade.controller.js:placeOCOOrder` | nautilus `OUO` proportional peer-quantity reduction |
| F-020 | MEDIUM | Exit/fill detection is poll-based (candle-gated); no Binance user-data-stream listener → stale view between fill and next candle (exit-side of F-002) | `engine/core/live_bot_manager.py:_check_exits`, `_verify_exchange_position_still_open` | nautilus event-driven fills; freqtrade per-loop reconcile |

---

## What Enma could adopt

- **Emergency exit on stop-placement failure** — if the SL doesn't confirm shortly after entry,
  force-close at market rather than running naked (freqtrade `emergency_exit`). Highest-value fix here.
- **Partial-fill aware OCO** — on a partial fill of one leg, reduce the peer leg's quantity to match
  the remaining position (nautilus OUO semantics), instead of trusting Binance full-cancel.
- **User-data-stream listener** for order/fill events so exits are known immediately, not on the next
  candle — collapses both the exit-side desync (F-020) and feeds the single-source-of-truth fix (F-001).
