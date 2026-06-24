# 00 — Pipeline Overview: Enma vs. freqtrade main loop

> The spine of the whole study. Every `0X` topic doc is a checkpoint hung off this flow.
> Root-cause-forward: structural "why this is wrong" first, then findings.
>
> **Upstream reference:** `freqtrade/freqtradebot.py` `process()` (develop branch).

---

## The two loops, side by side

### freqtrade — one ordered, synchronous loop (`FreqtradeBot.process()`)

One process owns the whole cycle. Order is deterministic and reconcile-before-act is structural:

| # | Step | Method | Purpose |
|---|------|--------|---------|
| 1 | refresh exchange | `exchange.reload_markets()` | markets/filters current |
| 2 | **reconcile closed** | `update_trades_without_assigned_fees()` | backfill exit fees from exchange |
| 3 | open trades + whitelist | `Trade.get_open_trades()`, `_refresh_active_whitelist()` | working set |
| 4 | candles | `dataprovider.refresh()` | fresh OHLCV |
| 5 | signals | `strategy.bot_loop_start()` → `strategy.analyze()` | compute enter/exit signals |
| 6 | **reconcile open orders** | `manage_open_orders()` → `update_trade_state()` | sync fills/timeouts vs exchange |
| 7 | **exits** | `exit_positions()` → `handle_trade()` / `handle_stoploss_on_exchange()` | SL/TP/should_exit |
| 8 | position adjust | `process_open_trade_positions()` | DCA / partial |
| 9 | **entries** | `enter_positions()` → `create_trade()` → `execute_entry()` | new positions |

Entry sub-flow (step 9): `get_entry_signal()` → `wallets.get_trade_stake_amount()` →
`get_valid_enter_price_and_stake()` (price/amount/leverage validated against exchange limits)
→ `exchange.create_order()` → `trade.adjust_stop_loss()`.

**State lives in one place:** the `Trade` object (DB), kept truthful by `update_trade_state()`
fetching from the exchange every loop. The exchange is the authority; the DB is reconciled to it.

### Enma — per-symbol async loops, work split across 3 services

`engine/core/live_bot_manager.py:_run_symbol_loop()`, fired per WebSocket candle-close per symbol:

| # | Step | Location | Purpose |
|---|------|----------|---------|
| 1 | candle close | WS `"x": true` | trigger |
| 2 | HTF candles | `_run_symbol_loop` ~L425-434 (non-blocking) | multi-timeframe refresh |
| 3 | indicators | `strategy.prepare()` / `strategy.before()` | vectorised pre-compute |
| 4a | **reconcile open position** | `_verify_exchange_position_still_open()` (only if position open) | detect off-band SL/TP fills |
| 4b | **exits** | `_check_exits()` | local SL/TP touch detection |
| 5 | signal→size→route | `pipeline.py:evaluate()` (alpha→risk→cost→portfolio→execution) | the 5-model pipeline |
| 6 | **entry** | `_execute_entry()` → `clamp_and_round_qty()` → Node `/place-order` → engine `/trade/order` → Binance | place order |
| 7 | reflect state | `_notify_node()` → `algo.controller.js:handleEngineStats` → Mongo + Socket.IO → client | UI update |

**State lives in THREE places:** engine `strategy.position` (in-memory), Mongo
`LiveSession.positionDetails[symbol]` (persisted), and Binance (authority). Nothing
continuously reconciles all three; `_verify_exchange_position_still_open()` was retrofitted to
patch the worst divergence.

---

## Structural observations (root causes)

### RC-A — Single source of truth vs. three-way state

freqtrade keeps exactly one authoritative record (`Trade`) and reconciles it to the exchange
**every loop iteration** (steps 2 + 6). Enma spreads position truth across engine memory, Mongo,
and Binance, and only reconciles the engine↔Binance pair, only when a position is already open,
only on candle close. The desync commit history (live position verification, session/symbol-lock
reconciliation) is the symptom of this missing single-source design. → **F-001**

### RC-B — Reconcile-before-act is structural in freqtrade, partial in Enma

freqtrade reconciles **open orders** (`manage_open_orders` → `update_trade_state`, step 6)
*before* it ever evaluates exits or entries — so a fill that happened between loops is known
before any new decision. Enma reconciles **open positions** but has no equivalent step for
**pending/open orders**: a partially-filled or exchange-rejected entry isn't reconciled the way
freqtrade does it; the engine assumes its `_execute_entry()` POST reflects reality. → **F-002**

### RC-C — Order placement crosses three services on the hot path

freqtrade: signal→size→`create_order()` is in-process — one failure surface, synchronous result.
Enma: `_execute_entry()` (engine) → HTTP → Node `/place-order` → HTTP → engine `/trade/order` →
HTTPS → Binance. Each hop is a place the position can be created on Binance while the engine's
view fails to update (timeout, crash between hops). This is the structural reason an unprotected
position window exists (entry filled, SL not yet placed). Detailed in `04-sltp-oco.md`. → **F-003**

### RC-D — Exchange limits validated at entry in freqtrade, asymmetrically in Enma

freqtrade validates price/amount/leverage against exchange limits in
`get_valid_enter_price_and_stake()` on the **one** path both live and dry-run share, so its
backtest/dry-run cannot fill what live would reject. Enma validates only on the live path
(`clamp_and_round_qty` in `_execute_entry`); the backtest path skips it entirely. This is the
headline backtest↔live asymmetry — owned by `01-backtesting.md` and `05-boundaries.md`. → see RC-1 (README).

### RC-E — Reconcile granularity: continuous vs. event-gated

freqtrade reconciles on a fixed `process_throttle_secs` cadence regardless of trade activity.
Enma's reconciliation is gated on candle-close *and* an open local position — if the engine's
local state wrongly believes it is flat (the exact failure desync produces), the verification
step is skipped, so the loop cannot self-heal from a "lost" position. → **F-004**

---

## Findings (rolled into findings-index.md)

| ID | Severity | One-line | Enma file(s) | Reference |
|----|----------|----------|--------------|-----------|
| F-001 | HIGH | Position truth split across engine memory / Mongo / Binance with no single authoritative record continuously reconciled | `live_bot_manager.py`, `models/LiveSession.js` | freqtrade `Trade` + `update_trade_state()` |
| F-002 | HIGH | No reconciliation of pending/open ORDERS (only open positions); partial-fill / reject between loops not detected | `live_bot_manager.py:_execute_entry`, `_run_symbol_loop` | freqtrade `manage_open_orders()` → `update_trade_state()` |
| F-003 | HIGH | Order placement crosses engine→Node→engine→Binance; position can exist on exchange while engine view fails to update | `live_bot_manager.py:_execute_entry`, `algo.controller.js:handleAlgoPlaceOrder` | freqtrade in-process `execute_entry()` |
| F-004 | MEDIUM | Reconciliation gated on candle-close AND open local position; cannot self-heal when engine wrongly believes it is flat | `live_bot_manager.py:_verify_exchange_position_still_open` (call site, gated by `if position`) | freqtrade reconciles every `process()` regardless of state |

> RC-D's backtest↔live asymmetry is tracked as RC-1 and its concrete findings live in
> `01-backtesting.md` / `05-boundaries.md` to avoid double-counting here.

---

## What freqtrade does that Enma could adopt (inspiration, not transplant)
 
- **A single reconcile step at the top of every loop** that syncs *both* open orders and open
  positions against the exchange before any exit/entry decision — even when local state says flat.
- **One authoritative trade record** the UI reads from, reconciled to the exchange, instead of
  three views that drift. (Enma's `LiveSession.positionDetails` could become that record if the
  engine treats it as derived-from-exchange, not derived-from-its-own-memory.)
- **One shared entry-validation path** for backtest and live so neither can fill what the other
  rejects (kills RC-1 at the structural level).
