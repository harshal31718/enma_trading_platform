# Feature: Algo Trading (Bot Sessions)

**Status:** Implemented
**Last updated:** 2026-07-02 — refreshed for the 2026-07-01 multi-user auth rollout, the trading-state
kill-switch, pairlist preview, and per-symbol leverage clamping; previous version dated 2026-06-05.

---

## What It Does

Runs a Python trading strategy as a live autonomous bot against Binance Testnet. A single session can trade multiple symbols simultaneously. The bot subscribes to Binance Kline WebSocket streams and evaluates strategy logic on each candle close. Session status and PnL stream in real-time via Socket.IO.

---

## Data Flow

```
User opens NewSessionWizard
  → Form pre-filled with defaultBotCapital and defaultBotLeverage from Exchange Settings
        ↓
Selects: strategy, symbols (multi), params, capital, leverage
        ↓
POST /api/v1/algo/sessions  (Node server)
  → Reads Exchange Settings (takerFee) 
  → Injects fee_rate into engine session config
        ↓
Server checks Redis symbol lock for each symbol
        ↓
If free: creates LiveSession doc (status='starting')
        Locks all symbols in Redis (type='bot')
        Calls engine POST /algo/sessions with fee_rate
        ↓
Engine starts session in background task:
  1. Dynamic import of strategy class
  2. Load historical candles for indicator warmup
  3. Subscribe to Binance Kline WS: {symbol}@kline_{timeframe} (per symbol)
  4. Set strategy.fee_rate from session_config (not hardcoded)
        ↓
On each candle close event (per symbol):
  strategy.before()
  pipeline.evaluate(strategy, current_holding)  → Alpha forecast() → Risk → Cost → Portfolio → Execution
  → If the Execution model emits an OrderPlan: place order on Binance Testnet
  → Track position, compute unrealized PnL (uses fee_rate on exit)
  strategy.after()
  → Emit session update to Node server
        ↓
Node server emits algo:session:update to the owning user's room only (io.to('user:' + userId).emit(...))
        ↓
Client updates SessionCard in real-time (status, PnL, open positions)

User clicks "Stop"
        ↓
POST /api/v1/algo/sessions/:id/stop
        ↓
Server updates status to 'stopping', calls engine POST /algo/sessions/{id}/stop
        ↓
Engine gracefully exits loop, closes all open positions, releases symbol locks
        ↓
Socket.IO emits algo:session:stopped → client sets status to 'stopped'
```

---

## Service Responsibilities

| Layer | Owns | Does NOT own |
|-------|------|-------------|
| Client | Session list UI, NewSessionWizard, SessionCard real-time updates | Session logic |
| Node server | LiveSession MongoDB doc lifecycle, symbol lock management, engine proxy | Strategy execution |
| Python engine | Strategy execution loop, Binance WS subscription, order placement | Session persistence |

---

## Key Invariants

- **All sessions target Binance Testnet.** No real money involved.
- **Symbol lock is enforced before session start.** If any symbol is already locked (by another bot or manual trading), the session start is rejected with an error.
- **Fee rate from settings.** `strategy.fee_rate` is injected from Exchange Settings (takerFee) at session start, not hardcoded. Used to compute position exit costs.
- **Bot defaults pre-fill.** NewSessionWizard pre-fills capital and leverage from Exchange Settings one-time on load, user can override.
- **Graceful stop.** When stopped, the engine closes all open positions before exiting the loop. The session does not terminate mid-trade.
- **Candle-driven execution.** Strategy logic runs only on confirmed candle close events (not tick data). This matches backtest behavior.
- **Multi-symbol sessions.** Each symbol gets its own Kline WebSocket stream and its own strategy instance; `pipeline.evaluate()` (Alpha `forecast()` → Risk → Cost → Portfolio → Execution) runs independently per symbol.
- **Indicator warmup.** Historical candles are loaded before the live stream begins, so indicators have sufficient data on the first signal evaluation.
- **Single engine instance.** `LiveBotManager` is a singleton — it manages all active sessions in one process.
- **DCA and entry/exit tagging are shared with backtest, not live-only.** `Strategy.adjust_trade_position()`
  and `Position.add_qty()`/`reduce_qty()` (A-014) plus `Signal`/`OrderPlan` tagging (A-015) are
  evaluated by the same `ExecutionKernel` on both the live and backtest adapters — see
  `workspace/docs/features/backtest-pipeline/SPEC.md` "Execution & Risk Mechanics" for the mechanism;
  this doc doesn't duplicate it.

---

## Exchange State Reconciliation

- **Unified Exchange Reconciliation (F-001/F-002/F-004)**: `_reconcile_exchange_state()` in
  `live_bot_manager.py` queries Binance directly for position AND open orders every loop,
  unconditionally, before any exit/entry decision — self-healing when the engine wrongly believes it
  is flat. Handles 3 cases: restores orphan positions, closes stale local state, updates unrealised
  PnL from exchange mark price.
- **Orphan-position restore (I-07)**: rebuilds a lost-track position with exchange-truth `leverage`
  / `isolatedWallet` / `liquidationPrice` from `positionRisk` (not a bare `leverage=1` guess) and
  re-arms `stop_loss`/`take_profit` + `algo_ids` from the open algo orders, so a restored position is
  protected and OUO peer-cancel (below) can fire for it.
- **Open Orders Reconciliation (F-002)**: fetches both standard `/fapi/v1/openOrders` and conditional
  `/fapi/v1/openAlgoOrders` (SL/TP) each loop. Filled/cancelled orders are also detected between
  candle closes via the Binance User Data Stream (`services/user_data_stream.py` —
  `UserDataStreamManager` singleton, listen-key lifecycle, `wss://fstream.binancefuture.com/ws/{listenKey}`,
  processes `ORDER_TRADE_UPDATE` in real time, auto-reconnect with exponential backoff, 30-min
  keep-alive; per-symbol fill callbacks trigger immediate reconciliation).
- **Exchange-Reconciled Position Record (F-021)**: `LiveSession.positionDetails` is sourced from
  exchange-truth reconciliation. `_push_stats()` sends `mark_price`, `unrealized_pnl`, and
  `price_missing` per symbol; `SessionCard` uses exchange-reported `unrealized_pnl` first, falling
  back to local calc with mark price, then last price.
- **Direct Binance Placement (F-003)**: algo order placement calls `send_signed_request()` directly
  from the engine for entry, exit, and stop-close — no engine→Node→engine→Binance hop chain.
- **Mark-Price PnL Fallback Chain (F-023/A-013)**: primary source is exchange-reported
  `unRealizedProfit`. Mark price is parsed as optional (not coerced to `0`), fallback chain
  `markPrice` → cached 24h last price → engine last close. `price_missing` is set only when no
  source yields a usable price (a legitimate `0.0` PnL is preserved, not dropped — audit I-05).

## SL/TP & OCO Safety

- **Emergency Market Exit on SL Placement Failure (F-018, retry ladder + real-fill booking added
  Plan 21.4 A-6, shipped 2026-07-17)**: in `LiveAdapter.execute_entry()`, if a stop-loss conditional
  order fails to place after a MARKET entry fills, the engine sends a MARKET close order, retrying
  up to 3 attempts with `1s × attempt` backoff on failure. On success, books the trade with the
  **real** fill price (`_extract_fill_price()` → `_query_real_fill_price()` fallback, same ladder
  `execute_exit` uses — never the fabricated entry price) and `exit_reason="emergency_exit"`,
  returns `False` — matches freqtrade's `emergency_exit()` pattern. On total failure across all 3
  attempts, records **nothing** (no fabricated close) and leaves `strategy.position` untouched;
  Binance is left holding a real, unprotected position and a CRITICAL-worded alert fires — the next
  `_reconcile_exchange_state` Case 1 pass restores it, and the naked-position re-arm below takes it
  from there. Tests: `engine/tests/test_execute_entry_bracket_safety.py`.
- **Naked-position detection & re-arm (Plan 21.4, A-7, shipped 2026-07-17)**: `_reconcile_exchange_state`
  Case 3 (both engine and exchange agree a position is open) now checks whether a live SL algo order
  actually rests on the exchange whenever `strategy.stop_loss` is set. If not — orphan restores with
  no open algo orders, a TP-400 that leaves the SL leg fine but a symmetric SL failure, or an A-6
  total-failure survivor — attempts a direction-aware re-arm via the same rounding path
  `execute_entry` uses. After `_NAKED_POSITION_MAX_REARM_ATTEMPTS` (3) consecutive failures across
  separate reconcile passes, force-closes the position via `execute_exit` rather than let it run
  naked indefinitely (mirrors freqtrade's per-iteration missing-stoploss re-placement, bounded).
  Tests: `engine/tests/test_reconcile_naked_position_rearm.py`.
- **Exchange-SL amend-on-tighten (Plan 21.4, M-4, shipped 2026-07-17)**: the risk models' maintain
  path (trailing/breakeven/Chandelier stops, `DefaultExecution.route()` Path 5) tightens
  `strategy.stop_loss` every candle, but previously that only updated the **local** value — the
  resting `closePosition:"true"` STOP_MARKET order on Binance stayed at its original, widest
  trigger for the position's entire life, with only the engine's own candle-close wick check
  enforcing the tightened level (up to one candle late). New
  `LiveBotManager._maybe_amend_exchange_sl()`, wired into `_run_symbol_loop` right after
  `kernel.evaluate_and_route(...)`, cancels+replaces the exchange SL algo order whenever the new
  stop is a genuine tighten (direction-aware); a widening or unchanged stop is a no-op, and a failed
  amend is caught and logged without corrupting the tracked algo id, falling back to the engine wick
  check. Tests: `engine/tests/test_maybe_amend_exchange_sl.py`.
- **Reject entries with an invalid protective stop (Plan 21.4, M-5, shipped 2026-07-17)**: previously
  an SL landing on the wrong side of the fill price (gap between signal close and market fill) was
  silently dropped and the entry proceeded naked on that leg, with the stale invalid tuple left in
  place for the next candle's `check_exits` to misread as instantly triggered. `execute_entry` now
  rejects the entry outright on an invalid SL (`strategy.buy`/`sell`/`stop_loss`/`take_profit` all
  cleared, returns `False`, no order placed) — freqtrade does not enter without its stop. An invalid
  TP stays lower-stakes: dropped, but the entry still proceeds on its valid SL. Tests:
  `engine/tests/test_execute_entry_bracket_safety.py`.
- **OUO Partial-Fill Peer-Cancel (F-019)**: SL/TP algo order IDs are tracked in
  `session["open_positions"][symbol]["algo_ids"]`. Two safety nets: (1) the user-data-stream `_on_fill`
  callback cancels the peer leg (`DELETE /fapi/v1/algoOrder`) immediately when a tracked `tpsl_*`
  order reports `FILLED`/`PARTIALLY_FILLED`; (2) `_reconcile_exchange_state()` cross-checks tracked
  algo IDs against the exchange's open algo orders and cancels the peer if one leg is missing. Mirrors
  nautilus `ContingencyType.OUO` semantics for Binance conditional orders with `closePosition: "true"`.
- **Bracket cleanup on every close path (Plan 21.3, A-4/A-5, shipped 2026-07-17)**: the two OUO
  safety nets above only cover the "one leg fills, cancel the other" case. Every *engine-initiated*
  close (a strategy exit, engine-side wick-check stop/target, a flip, session stop) previously left
  **both** `closePosition:"true"` brackets armed on Binance — a stale trigger would market-close
  whatever position later existed on that symbol (same session re-entering, a different session, a
  user manually trading it). `LiveBotManager._cancel_symbol_algo_orders(session, symbol, algo_ids)`
  closes this gap: cancels the tracked ids directly if known, else discovers and cancels everything
  open via `GET /fapi/v1/openAlgoOrders`, best-effort (a cancel failure never blocks or unwinds the
  close that triggered it). Wired into `execute_exit`'s success path, `_close_position_on_stop`, the
  F-018 emergency-exit path, and reconcile Case 2 (the exchange-side-SL/TP-fired case — the one
  scenario the existing OUO peer-cancels structurally cannot reach, since both are guarded by
  `has_exchange_position`, which is false by definition once Case 2 fires). Not yet live-verified —
  see `CURRENT_STATE.md` / `handoff.md`.

## Dynamic Pairlist & Symbol Management

- **Unified Symbol Source (F-009)**: `GET /candles/symbols` returns `all` — every TRADING symbol
  from cached Binance exchangeInfo, enriched with volume-based tiers (`high`/`mid`/`low` from 24hr
  `quoteVolume`), base/quote asset, status. `load_symbol_volume_tiers()` populates the tier + ticker
  cache at engine startup. `symbolService.js` fetches from the engine on startup (5-min TTL), falling
  back to a static 80-symbol list (`top_symbols.js`) when the engine is unreachable.
- **Dynamic Pairlist Pipeline (A-004)**: `engine/services/pairlist.py` — composable pipeline:
  `VolumePairList` (ranks by 24h `quoteVolume` descending), `SpreadFilter` (drops wide bid/ask spreads
  via the book-ticker cache — the 24hr ticker carries no bid/ask for USDⓈ-M futures), `VolatilityFilter`
  (24h high/low band), `PrecisionFilter` (drops pairs where `tickSize/price` exceeds a threshold),
  `AgeFilter` (drops pairs listed fewer than `min_days_listed` days via exchangeInfo `onboardDate`).
  `pairlist_from_config()` builds a `PairlistPipeline` from session config; if `start_session()` gets
  empty `symbols` and `risk_params.pairlist` is configured, the pipeline generates the list
  dynamically. `POST /algo/pairlist/preview` (proxied via `POST /api/v1/algo/pairlist/preview`) dry-runs
  a config without starting a session.
- **Ticker / Book-Ticker / Listing caches**: `load_symbol_volume_tiers()` populates `_ticker_cache`;
  `load_book_tickers()` populates `_book_ticker_cache` (best bid/ask); both run at engine startup and
  feed the pairlist filters.
- **Per-symbol leverage clamping** (`engine/utils/symbols.py → clamp_leverage()`): applies
  `min(requested, symbol_max)` on every path — live bot (signed `/fapi/v1/leverageBracket` fetch +
  cache, logs when reduced), manual `POST /leverage` (returns `effectiveLeverage`), backtest (offline
  hardcoded fallback map, deterministic for golden master).

## Chaos Mode (testnet-only stress tool)

`POST /api/v1/algo/chaos` accepts custom strategies, manual/auto symbol allocation, and risk
overrides. `GET /api/v1/algo/chaos/symbols` exposes the curated tier-tagged pool (80 symbols,
`high`/`mid`/`low` by volume). The client's 4-step Chaos Wizard supports multi-strategy selection,
manual/auto symbol mapping per strategy with cap enforcement (`chaosMaxManualSymbols` for manual picks;
`Settings.limits.testnet.maxSymbolsPerBot` per strategy and `Settings.chaosMaxTotalSymbols` run-wide,
2026-07-03 — see DECISIONS.md #21) and live allocation previews (manual picks guaranteed, remaining
symbols round-robin partitioned per tier, bounded by both caps — `ChaosWizard.jsx`'s preview mirrors
`server/src/utils/chaosAllocator.js`'s algorithm exactly so the UI never shows an uncapped/stale
allocation), timeframe/capital/leverage defaults (Chaos Settings section on the Settings page), and a
review screen before launch. Auto-select (no `strategies` in the request) now runs **all** known
strategies rather than a `chaosMaxStrategies`-capped subset (that field was removed 2026-07-03); the
run is instead truncated to however many `limits.testnet.maxConcurrentBots` slots the user has left,
with truncated strategies reported in the response's `errors` array rather than a hard rejection.
`engine/scripts/chaos_runner.py` is a thin console client with a live status table and `--stop` teardown.

## Resilience & Stats

- **Resilient order placement**: failed testnet orders in `live_bot_manager._execute_entry()` log the
  error, emit a Socket.IO notification, clear pending `buy`/`sell` signals, and return gracefully —
  no longer propagates as an unhandled exception that could crash the symbol loop.
- **Testnet-invalid symbol blacklist** (2026-07-03, see DECISIONS.md #22): some symbols in
  `demo-fapi.binance.com`'s `exchangeInfo` (status=TRADING, contractType=PERPETUAL) are rejected outright
  by the testnet matching engine — confirmed via a definitive HTTP 400 on the signed leverageBracket
  probe `_run_symbol_loop()` already makes at startup. `utils/symbols.py`'s `is_symbol_invalid()`
  blacklists such symbols in-memory; `get_all_symbols()` excludes them from future pairlist/Chaos pools,
  and the symbol loop aborts immediately (before opening a WS connection) instead of repeatedly
  hammering a doomed entry order every candle close. Self-healing (discovered on first probe), in-memory
  only (reset on engine restart).
- **WS reconnect backoff + jitter** (2026-07-03): `_run_symbol_loop()`'s kline WebSocket reconnect was a
  flat 5s retry — with ~80-150 symbols per Chaos run each running this same loop, a shared gateway blip
  reconnected all of them in lockstep every 5s (thundering herd). Now capped exponential backoff (1s→60s)
  with full jitter, reset on successful connect — mirrors the pattern already used by
  `UserDataStreamManager._run_ws()` in `services/user_data_stream.py`.
- **Exchange-rules cache refresh** (2026-07-03): the tick-size/step-size cache `round_price()`/
  `clamp_and_round_qty()` read from was populated once at engine startup and never refreshed, so a
  symbol relisted (or briefly missing a filter) after startup silently sent unrounded prices to Binance
  — surfacing as TP/SL algoOrder 400s. `main.py` now refreshes it every 30 minutes; `round_price()` also
  logs a warning on a cache miss instead of silently passing the price through unrounded.
- **Session stop no longer orphans positions on timeout** (2026-07-03): `stop_session()`'s position-close
  loop was fully serial (2 signed Binance calls per symbol) inside a 120s timeout — for a 100+ symbol
  Chaos session the loop couldn't finish in time, and on timeout the code unconditionally reported
  `openPositions: []` regardless of what actually got closed, silently orphaning real Binance positions.
  Now runs with bounded concurrency (8 in flight) and only reports a symbol as closed once confirmed;
  `reconciliation.js`'s startup sweep was similarly reordered to close-then-write instead of
  wipe-then-close, and a new periodic (10 min) `reconcileFullAccountPositions()` sweep compares real
  Binance positions against everything tracked and alerts (does not auto-close) on any orphan found.
- **Per-symbol live session stats** (`LiveSession.symbolStats`): on each position close and on session
  stop, the server re-aggregates `tradeRecords` by symbol (`computeSymbolStats` in
  `algo.controller.js`) and pushes it via a partial `algo:session:update` emit. Engine remains sole
  writer of `tradeRecords`; server reads/aggregates only. The engine calls `record_trade()` **before**
  notifying Node on close so the aggregation sees the just-closed trade; `position:open` carries the
  per-symbol clamped `leverage`.
- **SessionCard UI**: collapsed bar shows Started · Capital · Leverage · Trades (open/closed, live) ·
  P&L (realised + live-unrealized). Expanded view: Equity Curve, Session Stats grid (open/closed
  trades, win rate, avg PnL, live PnL, realised PnL, drawdown current/max), Activity Log, and an Open
  Positions panel bucket-ordered Open → Traded → Remaining (side/leverage/live-PnL plus cumulative
  trades/qty/margin/notional/realised PnL from `symbolStats`).

### ⚠️ Open issues found in a live Chaos run (2026-07-16 — fixes-queue F7)

A MicroScalper Chaos session (15 auto-selected symbols, 1m, 50x) was run live against Binance
Testnet specifically to answer the long-standing "does `ORDER_TRADE_UPDATE` fire for algo/
conditional orders" question (see `CURRENT_STATE.md`'s Known Technical Debt). It surfaced one
confirmed answer and two separate, still-open bugs:

1. **F-020's event-driven fill path does not reliably catch algo/conditional TP-SL fills —
   confirmed live, not theoretical.** BSBUSDT opened and was closed by its conditional SL/TP
   4 seconds later (per Binance's own Order History: entry `19:54:04`, conditional sell filled
   `19:54:08`, IST); ESPORTSUSDT the same pattern, 9 seconds. Enma's session UI kept showing both
   as open `LONG` positions for roughly another 50-55 seconds — until the next 1m candle close
   drove `_reconcile_exchange_state()`'s unconditional per-loop poll, which is what actually
   caught and closed them (`14:25:04` UTC "Closed BSBUSDT"/"Closed ESPORTSUSDT" in the activity
   log). **Conclusion: the system is silently running on the ~60s REST-poll fallback, not the
   real-time WS path, for at least some conditional-order fills.** This matches the "if no, it's
   a 60s staleness window, not a correctness bug" framing the fixes-queue anticipated — but it
   means every session currently carries up to ~60s where the UI (and the strategy's own
   in-memory `strategy.position`) says a symbol is open when Binance has already closed it.
   **Root cause isolated and code-fixed 2026-07-17 (Plan 21.1, finding A-2):** the WS frame does
   arrive, but `_on_fill`'s client-id lookup read a non-existent `clientOrderId` key, fell back to
   the numeric `orderId` (an int), and crashed on `.startswith("tpsl_")` — the exception was caught
   by the outer per-callback try/except, so `_reconcile_exchange_state()` at the end of `_on_fill`
   never ran. The event-driven path was dead code on every real fill; the system was always
   running on the ~60s REST-poll fallback. Fixed by reading Binance's real `"c"` field via the new
   `_extract_fill_client_id()` helper (`engine/core/live_bot_manager.py`) and by wrapping the OUO
   peer-cancel block in its own try/except so the reconcile call can no longer be skipped by an
   earlier failure in the callback. Regression tests:
   `engine/tests/test_on_fill_client_id_extraction.py`. **Second, independent backstop shipped the
   same day (Plan 21.2, finding A-8):** a per-symbol `_on_account_update` callback, registered
   alongside `_on_fill`, reconciles immediately on any OPEN<->FLAT disagreement between Binance's
   `ACCOUNT_UPDATE` `P[]` position delta and the local `strategy.position` view — debounced via the
   existing per-symbol lock. Unlike A-2's fix, this path is event-type-agnostic: Binance emits
   `ACCOUNT_UPDATE` for every position change (including algo-order fills) regardless of
   `ORDER_TRADE_UPDATE`/client-id semantics, so it closes the staleness window even if A-2 turns out
   to have gaps for some order shapes. Decision logic in `_account_update_needs_reconcile()`.
   Regression tests: `engine/tests/test_account_update_reconcile_decision.py`. **Not yet
   re-verified live** — needs a fresh Chaos/small-session reproduction with both fixes in place to
   confirm the ~60s staleness is actually gone before this item is closed.

2. **TP placement is failing outright on some symbols with a raw `400 Bad Request`** —
   `BCHUSDT`, then `ETHUSDT`, both hit this in the same run (`TP skipped` in the activity log).
   This looks like the same symptom the 2026-07-03 stale-tick-size-cache bug above was fixed for
   (`round_price()`/`clamp_and_round_qty()` reading from a cache populated once at startup and
   never refreshed for newly-relisted symbols) — but that fix already shipped, so either it has a
   gap (e.g. a symbol entering an active Chaos run's auto-selected pool that wasn't in the
   original tier-cache warm set) or this is a distinct cause. **Genuinely unknown right now**
   because the failure was only ever logged as httpx's generic `"Client error '400 Bad Request'
   for url '...'"` — Binance's actual `{code, msg}` body was discarded, not logged. **Fixed
   2026-07-16**: `_binance_error_detail()` added to `live_bot_manager.py`, wired into the entry,
   SL, and TP placement failure logs, so the *next* reproduction will show the real Binance error
   code instead of a dead end. Root cause still open pending that reproduction.
3. **A position stayed shown as open after the session was fully stopped** — `FXSUSDT SHORT`
   remained in the Positions panel with no live PnL/qty/notional after `Stop` completed and every
   other symbol showed `CLOSED`. Not yet investigated — candidates: the entry itself may have
   failed/never actually filled on Binance (a phantom local-only position, possibly linked to the
   same TP-failure class above if `execute_entry` proceeded without confirming the fill), or
   `stop_session()`'s close loop skipped this one symbol for an unrelated reason. Needs the
   engine logs for this specific symbol/session to diagnose.

**Status: session stopped, not yet re-run with the improved error logging.** See `handoff.md`'s
2026-07-16 entry for the full session trace and next steps.

---

## REST Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/algo/sessions` | Start a new bot session |
| GET | `/api/v1/algo/sessions` | List all sessions |
| DELETE | `/api/v1/algo/sessions` | Delete all stopped/errored sessions |
| GET | `/api/v1/algo/sessions/:id` | Get single session detail |
| GET | `/api/v1/algo/sessions/:id/equity` | Get session equity curve |
| POST | `/api/v1/algo/sessions/:id/stop` | Stop a running session |
| DELETE | `/api/v1/algo/sessions/:id` | Delete a session (only if stopped/errored) |
| GET | `/api/v1/algo/symbols/locked` | Get all currently locked symbols |
| POST | `/api/v1/algo/chaos` | Launch Chaos Mode (testnet-only multi-strategy stress run) |
| GET | `/api/v1/algo/chaos/symbols` | Curated tier-tagged symbol pool for Chaos Mode |
| POST | `/api/v1/algo/sessions/:id/trading-state` | Kill-switch: set `active`/`reducing`/`halted` |
| POST | `/api/v1/algo/pairlist/preview` | Dry-run the dynamic pairlist pipeline without starting a session |

---

## Socket.IO Events

| Event | Direction | Payload |
|-------|-----------|---------|
| `algo:session:update` | Node → Client | **Partial** — clients merge only present fields. Most carry `{ sessionId, status?, pnl?, openPositions? }`; the per-symbol aggregation emit carries `{ sessionId, symbolStats }` only. |
| `algo:position:open` | Node → Client | `{ sessionId, symbol, side, qty, price, leverage, timestamp }` |
| `algo:position:close` | Node → Client | `{ sessionId, symbol, pnl, exitPrice, exitReason, timestamp }` |
| `algo:session:log` | Node → Client | `{ sessionId, type, message, timestamp }` |

> There is no `algo:session:stopped` event — a stop is communicated via `algo:session:update` with `status: "stopped"`.

---

## Session Status Lifecycle

```
starting → running → stopping → stopped
                 ↘ error
```

| Status | Description |
|--------|-------------|
| `starting` | Node created doc; engine not yet confirmed |
| `running` | Engine confirmed active, Kline WS subscribed |
| `stopping` | Stop requested; engine closing positions |
| `stopped` | Session cleanly exited, positions closed |
| `error` | Session crashed; requires manual deletion |

---

## LiveSession Model Fields

| Field | Type | Description |
|-------|------|-------------|
| `strategyId` | ObjectId | Ref to Strategy doc |
| `strategyName` | String | Strategy display name |
| `symbols` | [String] | Traded symbols |
| `timeframe` | String | Candle timeframe (e.g. `1h`) |
| `params` | Object | Strategy-specific parameters |
| `capital` | String | Starting capital (decimal string) |
| `leverage` | Number | Leverage applied |
| `status` | Enum | See lifecycle above |
| `tradingState` | Enum | `active`/`reducing`/`halted` — kill-switch, independent of `status` |
| `riskParams` | Object | Per-session risk-model override (risk %, R:R, drawdown cap, etc.) |
| `mode` | Enum | `paper` (Testnet) or `live` |
| `pnl` | String | Current PnL (decimal string) |
| `openPositions` | [Object] | Currently open positions |
| `positionDetails` | Object | `{ [symbol]: { side, qty, price, leverage } }` — reload-safe PnL snapshots, persisted on `position:open`/cleared on `position:close` (F-021) |
| `symbolStats` | Object | `{ [symbol]: { trades, qty, notional, realisedPnl, leverage } }` — per-symbol aggregation re-derived from `tradeRecords` |
| `totalTrades` | Number | Trade count since session start |
| `tradeHistory` | [Object] | `{ timestamp, balance }` for equity curve |
| `logs` | [Object] | `{ type, message, timestamp }` for session log |

---

## Related Files

| File | Role |
|------|------|
| `client/src/pages/AlgoTrading.jsx` | Session list page |
| `client/src/components/algo/NewSessionWizard.jsx` | Multi-step session creation form, pre-fills from settings |
| `client/src/components/algo/SessionCard.jsx` | Per-session card with status, PnL, stop button |
| `client/src/hooks/useAlgoSessions.js` | TanStack Query hooks for all session operations |
| `client/src/hooks/useExchangeSettings.js` | Fetch exchange settings for pre-fill |
| `client/src/hooks/useSocket.js` | Socket.IO event subscription helper |
| `server/src/routes/algo.routes.js` | Route definitions |
| `server/src/controllers/algo.controller.js` | Reads Exchange Settings (takerFee), injects fee_rate into engine call |
| `server/src/models/Settings.js` | MongoDB Settings doc with exchange configuration |
| `server/src/models/LiveSession.js` | Mongoose model |
| `server/src/services/symbolLock.js` | Redis symbol lock: lock, release, isSymbolFree |
| `engine/routers/algo.py` | POST /sessions (accepts fee_rate), POST /sessions/{id}/stop |
| `engine/core/live_bot_manager.py` | Reads fee_rate from session_config, passes to strategy; Kline WS handler, strategy execution loop |
