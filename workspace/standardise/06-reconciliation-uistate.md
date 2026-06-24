# 06 — Reconciliation & Real-Data-on-UI: Enma vs. freqtrade & nautilus

> Checkpoint 6 — the tail of the pipeline spine: bot↔exchange desync recovery and how *true*
> exchange state reaches the UI. This is the user's "make sure real data is shown" concern.
> **Upstream references:** `freqtrade/freqtradebot.py` reconcile methods; nautilus event-driven cache.

This doc is the convergence point for RC-A (three-way state) and RC-B (reconcile-before-act).
It largely *consolidates* findings F-001/F-002/F-004/F-020 and adds the **UI-truth** findings.

---

## How freqtrade keeps state truthful

Reconciliation is a first-class, every-loop concern, all flowing into one `Trade` record:
- `update_trade_state()` — fetch order from exchange, update amounts/fees, fire `order_filled()`.
- `manage_open_orders()` — sync open orders (fills/timeouts) before any new decision.
- `update_trades_without_assigned_fees()` — backfill exit fees on closed trades.
- `handle_onexchange_order()` — recover a trade whose order exists on the exchange but is missing
  from the DB.
- `startup_update_open_orders()` / `handle_insufficient_funds()` — startup + lost-order recovery.

**UI/RPC reads from the `Trade` DB**, which is continuously reconciled **to the exchange**. The
exchange is the authority; the displayed state is derived from the reconciled record. There is no
separate "bot's belief" that can drift from what the UI shows.

## How nautilus keeps state truthful

Event-driven: an `ExecutionEngine` consumes venue events (`OrderFilled`, `PositionChanged`) and
updates a central `Cache`; everything (risk, portfolio, UI) reads the same cache. State is updated
the instant the venue reports, not on a poll.

---

## How Enma does it

| Concern | Location | Behaviour |
|---|---|---|
| Runtime position reconcile | `live_bot_manager.py:_verify_exchange_position_still_open` | per-candle, only when local position open |
| Startup position sync | `live_bot_manager.py:_sync_open_position` | once per symbol at bot start |
| Startup lock reconcile | `server/src/services/reconciliation.js:reconcileSymbolLocks` | stop orphans, release stale locks, re-lock manual |
| Engine→UI push | `live_bot_manager.py:_notify_node` → `algo.controller.js:handleEngineStats` | PATCH stats/events → Mongo `LiveSession` + Socket.IO |
| UI state source | `LiveSession.positionDetails`, `openPositions`, `pnl` | persisted from engine payloads |
| Live PnL | client/engine: `qty*price − notional` | computed from last price |

**The structural problem:** the UI reads `LiveSession` (Mongo), which is written from the engine's
**in-memory belief** (`_notify_node`). Mongo is therefore derived from the engine, and the engine is
only intermittently reconciled to Binance. So the chain is *engine-belief → Mongo → UI*, **not**
*Binance → UI*. When the engine is desynced, the UI confidently shows the wrong position/PnL.

---

## Gaps & root causes

### UI reflects the engine's belief, not reconciled exchange truth
This is the "real data on the platform" defect stated directly. The displayed position/PnL is
downstream of `strategy.position` (engine memory), not of a record reconciled to Binance. Contrast
freqtrade (UI reads the exchange-reconciled `Trade`) and nautilus (UI reads the event-updated cache).
Until Enma has a single record reconciled **to the exchange** that the UI reads from, the UI is only
as correct as the engine's last belief. → **F-021** (the UI-facing face of F-001).

### Reconciliation is split and uncoordinated across services
Startup reconcile lives in Node (`reconciliation.js`), runtime reconcile in the engine
(`_verify…`, `_sync_open_position`), with different triggers and no shared definition of "truth."
freqtrade runs all reconcile paths inside one loop against one record. Enma's split means a gap one
side assumes the other covers. → **F-022**

### Displayed PnL is a last-price approximation, not the exchange figure
Enma computes live PnL as `qty*price − notional` from **last price**. Binance reports unrealized PnL
from **mark price** and accounts for funding. The number on the UI therefore diverges from the
exchange's own PnL — small in calm markets, material near liquidation or funding boundaries. → **F-023**

---

## Findings

| ID | Severity | One-line | Enma file(s) | Reference |
|----|----------|----------|--------------|-----------|
| F-021 | HIGH | UI position/PnL derives from engine in-memory belief (engine→Mongo→UI), not from exchange-reconciled state → UI shows wrong data when engine is desynced | `engine/core/live_bot_manager.py:_notify_node`, `server/src/controllers/algo.controller.js:handleEngineStats`, `server/src/models/LiveSession.js` | freqtrade UI reads exchange-reconciled `Trade`; nautilus event-updated cache |
| F-022 | MEDIUM | Reconciliation split across Node startup (`reconciliation.js`) and engine runtime (`_verify…`,`_sync_open_position`) with no shared truth definition | `server/src/services/reconciliation.js`, `engine/core/live_bot_manager.py` | freqtrade single-loop reconcile into one `Trade` |
| F-023 | MEDIUM | Live PnL computed from last price (`qty*price − notional`); diverges from Binance mark-price + funding unrealized PnL shown to exchange | `engine/core/live_bot_manager.py` PnL calc, client live-PnL hook | freqtrade/nautilus use exchange-reported values |

> F-001/F-002/F-004/F-020 (state ownership, order reconcile, gated reconcile, poll-based fills) are
> the engine-side roots; this doc adds their UI-facing consequences. Fixing F-001 (single
> exchange-reconciled record) is the lever that resolves F-021 as well.

---

## What Enma could adopt

- **One exchange-reconciled record** (extend `LiveSession.positionDetails` to be *derived from
  Binance*, refreshed by a top-of-loop reconcile) that the UI reads from — collapses F-001 + F-021.
- **Unify reconciliation**: one routine, run at startup and every loop, covering orders *and*
  positions, owned in one place (engine), with Node's lock reconcile feeding it rather than paralleling it.
- **Show the exchange's PnL** (pull unrealized PnL / mark price from `positionRisk`) instead of a
  last-price estimate, at least for the displayed figure.
