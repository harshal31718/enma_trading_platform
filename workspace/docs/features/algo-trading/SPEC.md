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
  3. Subscribe to Binance mainnet public Kline WS: {symbol}@kline_{timeframe} (per symbol —
     Plan 21 A-12, shipped 2026-07-17: signal/indicator candles are mainnet-sourced, matching
     warmup/HTF; order execution below still goes to Testnet)
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
- **Case 2 requires a CONFIRMED-flat query, not just a failed one (Plan 21.5, A-15, shipped
  2026-07-17)**: before this fix, Case 2 ("engine has a position, exchange doesn't → close
  locally") fired whenever `positionRisk` reported zero exposure — including when the query itself
  had just *failed* (network error, timeout, missing credentials, or a deliberate A-9 backpressure
  defer), since a failure defaulted to the same "no position found" state as a genuine flat. A new
  `position_query_ok` flag now gates Case 2 to only the confirmed-flat case; an unconfirmed query
  leaves local state untouched and retries next candle instead of fabricating a close on a position
  that may still be open on Binance.
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
- **Weight budgeting + 429/418 backpressure (Plan 21.5, A-9, shipped 2026-07-17 — partial)**:
  `send_signed_request` (`engine/services/binance_testnet.py`) tracks `X-MBX-USED-WEIGHT-1M` per
  base_url and defers any non-order-critical call (`BinanceBackpressureError`) once the last-seen
  weight is at/above a 1800 (75% of the shared 2400/min) soft limit, as long as that reading is
  still inside its 60s freshness window. On an actual 429/418 it reads `Retry-After` (60s default
  if absent) and pauses all non-order-critical calls on that base_url until it expires.
  `/fapi/v1/order` and `/fapi/v1/algoOrder` (entries, exits, SL/TP placement/cancel) are exempt
  from both guards — never deferred, since a skipped stop-loss is worse than a rate-limit warning.
  **Not yet shipped**: batching `positionRisk`/`openAlgoOrders` into one call per session per
  candle wave instead of one per symbol — the big weight win for large Chaos runs — deferred as a
  larger `_run_symbol_loop` concurrency restructure.
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
- **Risk-inflation + slippage observability (Plan 21.7, A-11 + A-14, shipped 2026-07-17)**:
  `clamp_and_round_qty` (`utils/symbols.py`) can bump a sized quantity up (by up to +30%, F-013)
  to satisfy Binance's minNotional filter — SL distance is unchanged, so a bump silently inflates
  realized risk-per-trade by the same factor. It now logs a `warning` with the effective
  multiplier whenever a genuine bump occurs (A-11). Separately, `execute_entry` now measures
  `|fill_price - ref_price| / ref_price` on every entry and logs it — routine `info` below 1%,
  `warning` + a session `log` notification at/above it (A-14). Both are logging-only: neither
  changes a returned quantity, rejects an entry, or alters backtest output. Tests:
  `engine/tests/test_clamp_qty_risk_inflation_log.py`, `engine/tests/test_execute_entry_slippage_log.py`.
- **Engine wick-check defers to a confirmed-armed exchange bracket (Plan 21.7, A-13, shipped
  2026-07-17)**: `ExecutionKernel.check_exits` (`engine/core/kernel.py`) previously always ran its
  own candle high/low wick-check for SL/TP on every live symbol, racing the exchange's own
  MARK_PRICE-triggered conditional order — mostly benign (reconcile wins the race, a lost race just
  produces a safely-handled failed reduceOnly close) but produced duplicate-execution semantics and
  could book `exit_reason="stop_loss"` for a fill that actually happened on the exchange at a
  different price. `check_exits` gained an optional `armed_legs: dict | None = None` param
  (`{"sl": bool, "tp": bool}`); a `True` leg skips the local wick-check for that leg entirely
  (exchange + reconcile handle it, same as always); a `False`/missing leg falls back to the local
  wick-check exactly as before — the A-7 naked-position fallback made explicit. The live per-candle
  loop (`live_bot_manager.py`) builds this straight from `open_positions[symbol]["algo_ids"]`,
  read right after `_reconcile_exchange_state` (which is where A-7 re-arms a missing SL). Backtest
  never passes this param, so its default `None` keeps every backtest call byte-identical — no
  golden master impact. Tests: `engine/tests/test_armed_legs_wick_check_skip.py` (7 cases,
  **actually run with real pytest** — `core/kernel.py` has no TA-Lib/numpy/motor dependency chain).
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
   other symbol showed `CLOSED`. **Investigated by code read 2026-07-18**: `stop_session()`'s close
   loop and `_close_position_on_stop()` are correct by inspection — they query live Binance
   `positionRisk` and force-close every session symbol regardless of local state, so a genuinely
   stuck-open report from that path implies either an exception during the close call (now
   diagnosable via `_binance_error_detail`) or the entry itself was a phantom local-only position.
   **One real gap of the right shape found and fixed**: `execute_entry()`'s market-order fill check
   treated Binance's `"0.00000000"` avgPrice string as a truthy real fill, silently opening a local
   position on an unconfirmed entry — the one order-placement site that didn't follow the ENG-2
   "never fall back to an estimate silently" contract already applied to every close path. Fixed to
   re-query by clientOrderId and reject the entry (no local position) if still unconfirmed. See
   `engine/tests/test_entry_unconfirmed_fill.py` and `0_fixes-queue.md`'s F7 2026-07-18 entry for
   detail. **Not confirmed as the actual FXSUSDT cause** — that needs either the original session's
   retained logs or a fresh reproduction; this is a defensible hardening fix for a real gap found by
   code read, not a verified root-cause match.

**Status: not yet re-run with the improved error logging or the entry-confirmation fix — needs a
live Testnet reproduction (Docker access) before F7 can close.** See `handoff.md`'s most recent
entry for the full session trace and next steps.

---

## Session Risk Governor (Plan 22 Step 22.1 — shipped code-side 2026-07-17)

A new session-scoped risk component, separate from the per-symbol five-model pipeline's
`AtrBracketRiskModel`/protections stack — it sees the whole session's aggregate equity/margin,
which per-symbol models structurally cannot (Plan 21 finding A-10). One instance per live
session, stored in `session["risk_governor"]` (`engine/core/models/governor.py`,
`SessionRiskGovernor`/`GovernorVerdict`), instantiated in `start_session` from
`risk_params.max_session_dd` (existing knob, reused) plus a new `risk_params.governor` sub-object
(`max_daily_loss_pct`, `max_margin_utilization`, `breach_action`, `auto_flatten_on_halt`).

**Two evaluation points:**
- **Pre-trade** (`execute_entry`, after A-001/A-002/A-003): `check_pre_trade()` — can veto the
  entry. Checks aggregate session drawdown, daily realized loss limit, and margin utilization
  ceiling (pre-trade only).
- **Periodic** (`_push_stats`, every stats tick): `check_periodic()` — checks drawdown + daily
  loss only (margin is pre-trade-only). Edge-triggered: only fires `_apply_governor_breach()` when
  `trading_state` is currently `"active"`, so a breach doesn't re-fire every tick. A breach
  auto-transitions `trading_state` to `breach_action` (`"reducing"` default, or `"halted"`), logs,
  and notifies Node with a `risk_breach` event (`{checkName, reason, newState}`). If the new state
  is `"halted"` and `auto_flatten_on_halt` is set (opt-in, default off — `DECISIONS.md` #23), every
  open position is force-closed via the existing `_close_position_on_stop`.

**Three hard checks, all fail-closed** (cannot compute the metric → block, never silently pass):
1. **Aggregate session drawdown** — tracks a session equity high-water mark; breach when current
   equity has drawn down more than `max_session_dd` (default 0.20) from it. Supersedes Plan 21
   step 21.6 (`Merged→22.1`).
2. **Daily realized loss limit** — off by default (`max_daily_loss_pct=None`). UTC-midnight
   anchor (`DECISIONS.md` #23). A loss *limit*, not a net-PnL floor — winning trades never offset
   an already-accumulated daily loss (freqtrade `max_daily_loss` semantics). Fed by
   `record_realized_pnl()`, called at all four PnL-booking sites: the F-018 emergency-exit path,
   `execute_exit`, `_close_position_on_stop`, and `_reconcile_exchange_state`'s Case 2.
3. **Margin utilization ceiling** — pre-trade only; vetoes an entry that would push total margin
   committed past `max_margin_utilization` (default 0.8) of equity. Fails closed (blocks) if
   equity ≤ 0.

`_compute_session_equity_and_margin()` (static method on `LiveBotManager`) derives session-level
`equity`/`used_margin` from `session["open_positions"]` for both call sites — `_push_stats` also
reuses it to derive `total_pnl` (replacing the old inline per-symbol sum).

**Capital integrity gate (B-11/B-12)** — two independent layers, both start-time only:
- **Server** (`server/src/utils/capitalGate.js`, wired into `startSession`/`startChaos` in
  `algo.controller.js`): `validateCapitalValue()` hard-rejects non-numeric/zero/negative capital
  unconditionally (400). `checkCapitalAgainstBalance()` compares
  `requestedCapital + Σ this user's running sessions' capital` (Chaos: `capital × strategyCount`,
  summed not sampled) against the real testnet available balance (`/trade/account`); over-commit
  returns 409 unless the request carries `confirmOverCommit: true` (warn-and-confirm, per
  `DECISIONS.md` #23 Part F Q5 — mainnet would hard-reject with no confirm path, not yet relevant
  since trading stays testnet-pinned).
- **Engine** (`_fetch_available_balance()` + a clamp block in `start_session`,
  `live_bot_manager.py`): best-effort defensive backstop, independent of whatever the server-side
  gate did or didn't catch. If configured capital exceeds the real fetched balance, clamps
  `capital_to_use` down to it, logs a warning, and notifies the session log. A failed balance
  fetch never blocks session start — this is the backstop, not the primary UX.

**Webhook**: `risk_breach` added to `Settings.webhook.events` enum (opt-in by default alongside
`exit_fill`/`liquidation`/`session_error`). `handleEngineStats`'s new `risk_breach` branch persists
`LiveSession.tradingState`, emits `algo:session:update` + `algo:session:log`, and dispatches the
webhook with `{sessionId, strategy, checkName, reason, newState}`.

**Portfolio open-risk budget + liquidation buffer (Plan 22 Step 22.2, shipped 2026-07-17):**
`SessionRiskGovernor.check_portfolio_risk()` computes the TRUE cross-symbol aggregate —
Σ `|entry − stop| × qty` across every open position plus the candidate entry, over session
equity — vetoing past `max_portfolio_risk` (default 0.06, same field name `core/models/
portfolio.py`'s per-symbol check already used, kept for config compat and cascaded from
`risk_params` the same way as `max_session_dd`). This supersedes that per-symbol check for live
sessions (a Plan 21 audit finding: despite the name, it never saw other open symbols); the
per-symbol check itself is untouched for backtest. New `LiveBotManager.
_compute_open_risk_breakdown()` reads each open symbol's live `strategy.stop_loss` (reflects
trailing tightening immediately). Wired into `execute_entry` right after the M-5 SL/TP validity
check — vetoes with a log naming every contributing symbol and its risk amount, applies to DCA
scale-ins too. The same call site also wires `respects_liq_buffer()` (`core/models/risk.py`,
previously decorative — zero pipeline call sites) — computes the actual liquidation price via
`core/margin.py` for the veto log (not just the bool), fails *open* on an unexpected exception in
the check itself (distinct from an actual computed violation, which vetoes).

**Protections parity + risk-integrity events (Plan 22 Step 22.3, shipped 2026-07-17):** new
`MaxDrawdownProtection` (global halt on realized-PnL equity-curve drawdown over a rolling window
— distinct from the governor's own live-equity drawdown check) and `LowProfitPairsProtection`
(per-pair halt on summed realized profit below a threshold), both freqtrade-inspired, both
opt-in/default-off in `risk_params.protections`. `ProtectionManager.record_trade_close` now
dispatches to both on every close (win or loss), and — a real gap found and fixed while wiring
this in — now actually gets CALLED from all four close paths instead of just `execute_exit`: the
F-018 emergency-exit path, `_close_position_on_stop`, and `_reconcile_exchange_state`'s Case 2
were silently never feeding the protections stack at all. Since A-13 made exchange brackets the
sole trigger while armed, Case 2 is now the dominant real-world stoploss path, so `StoplossGuard`
was structurally blind to most real stoplosses before this fix. Case 2's outward notification
still books the generic `exitReason="exchange_sync"` (Binance's raw trade history carries no
reason label); a new `_classify_exchange_sync_exit_reason()` helper does a best-effort proximity
classification (fill near the tracked SL/TP price) for the protections' internal bookkeeping only.
Chaos sessions were traced end-to-end and confirmed to already have full protections coverage —
`startChaos` launches through the exact same `start_session` engine path as regular sessions, so
there's no separate Chaos code path lacking this (the plan's own "live-only wiring" caution was a
stale assumption, corrected rather than duplicated). New `risk_check` event type
(`services/event_log.py`'s `EVENT_TYPES`) — `execute_entry` appends one to `executionEvents` for
every entry that actually places (not a rejected one), recording resolved risk limits and computed
sizing including the minNotional inflation factor; a session-visible warning fires when that
factor exceeds 1.1×.

**Live VaR/CVaR enforcement (Plan 22 Step 22.4, shipped 2026-07-17):** new `engine/services/
portfolio_risk.py` is the one shared computation path for account-wide VaR/CVaR — both the Zone 1
dashboard endpoint (`routers/risk.py`, rewritten as a thin formatter over it) and the governor's
new `check_var()` call the same `compute_var_cvar()` function (wrapping the pre-existing
`utils/risk_math.calculate_portfolio_var`, itself unchanged). Deliberately account-wide, not
session-scoped: Binance's real margin/liquidation risk is account-wide, shared across every
session running on one API key (Chaos runs dozens per key) — scoping to "this session's positions
only" would produce a number that diverges from the dashboard's and understates real risk when
sessions share a key. 10s account-fetch / 60s price-history in-memory caching (per this step's own
acceptance criterion) bounds the REST/DB weight of frequent governor polling across many
concurrent sessions — independent of the Node-side 10s Redis cache the dashboard route already had
(that one only helps the dashboard's own browser polling, not the engine-internal governor calls).
`SessionRiskGovernor.check_var(var_amount, cvar_amount, equity)` adds `var_limit_pct`/
`cvar_limit_pct` config, both defaulting to `None` (off — fully opt-in, unlike the other governor
checks' "0 disables" convention, since an account with no trading history has undefined VaR).
Evaluated pre-trade (`execute_entry`, right after the 22.2 checks — opt-in gated, so sessions that
never configure either limit never pay the extra Binance/TimescaleDB round trip) and periodically
(`_push_stats`, alongside `check_periodic`); a breach reuses the existing `risk_breach` webhook
(`_apply_governor_breach`, no new webhook plumbing). Fails **open** on a fetch/compute exception —
same precedent as 22.2's liquidation-buffer check, since a transient Binance outage must not
silently halt live trading. Zone 2 schema/UI for `varLimitPct`/`cvarLimitPct` deliberately deferred
to 22.7 (that step's own scope explicitly batches "all new fields" including `varLimitPct` into one
UI pass) — the engine-side config keys are live now via `risk_params.governor.var_limit_pct`/
`.cvar_limit_pct`, same reuse pattern as `max_session_dd`/`max_portfolio_risk`.

**Correlation-aware concentration cap (Plan 22 Step 22.5, shipped 2026-07-17):** pre-trade only,
off by default (`risk_params.governor.correlation_cap.rho = None`). `SessionRiskGovernor.
check_correlation_concentration()` does transitive-closure clustering over pairwise
`|correlation| > rho` among currently-open symbols + the candidate entry (BFS graph walk on the
caller-supplied correlation matrix — the governor never fetches data itself, same separation as
`check_var`), vetoing when the resulting cluster's combined notional exceeds
`max_cluster_exposure_pct` (default 0.4) of session equity. New `services/portfolio_risk.
fetch_correlation_matrix(symbols)` reuses `fetch_close_prices`'s existing 60s cache — no new
TimescaleDB load beyond what 22.4 already introduced. Wired into `execute_entry` right after the
22.4 VaR/CVaR block, opt-in gated (skips the fetch entirely when `correlation_rho` is unset), fails
**open** on a fetch/compute exception (same precedent as every other governor check that reaches
an external data source). Zone 2 schema/UI deferred to 22.7, same batching precedent as
`varLimitPct`.

**Portfolio allocation layer (Plan 22 Step 22.6, shipped 2026-07-17, golden-master-gated):** new
`InverseVolatilityPortfolio`/`compute_realized_volatility()` (`core/models/portfolio.py`) — weights
∝ 1/realized-vol (stdev of log returns), an iterative clamp-and-renormalize enforcing a per-symbol
floor/cap (0.05/0.5 default), missing-data symbols fall back to the mean known weight not zero.
Config-gated via `risk_params["allocation"] == "inverse_vol"` (default `"equal"`) in both
`backtest_runner.py` (recomputes `capital_splits` once warmup candles are loaded — the default
path's original pre-candle-load equal-split call is left completely untouched) and
`live_bot_manager.py`'s `start_session` (fetches recent closes via the shared `portfolio_risk.py`
cache; falls back to equal split on any failure, logs the resolved split at session start).
**Golden-master confirmed byte-identical for the default case**:
`docker exec enma_trading_platform-engine-1 python -m scripts.golden_master compare --a pre_22_6
--b post_22_6_v2` → `GOLDEN-MASTER OK` (5/5 seeded strategies, tol 1e-6).

**Zone 2 platform surface + critical fix (Plan 22 Step 22.7, shipped 2026-07-17) — Plan 22 is now
fully shipped (22.1–22.7):** Zone 2 UI (new "Session Risk Governor" form section in
`RiskDashboard.jsx`), server schema/validation (`Settings.js`, `risk.controller.js`), and the
resolver (`resolveStrategyRiskParams()` in `utils/risk.js`) now cover every governor field
accumulated across 22.1–22.6 (`maxDailyLossPct`, `maxMarginUtilization`, `varLimitPct`,
`cvarLimitPct`, `correlationCap`, `allocation`, `breachAction`, `autoFlattenOnHalt`); the New Bot
wizard gained an allocation dropdown (multi-symbol only) and `SessionCard.jsx` gained a governor
state badge (Reducing/Halted, fed live via the `algo:session:update` socket handler — which itself
needed a fix, see below).

**Critical bug found and fixed while wiring this in:** `risk_params` as sent by Node is shaped
`{symbol: {...}, "default": {...}}` (one `resolveStrategyRiskParams()` call per symbol), but
`live_bot_manager.py`'s `start_session` governor_cfg cascade (added 22.1, extended every step
since) read `risk_params.get("max_session_dd")` etc. directly on that wrapper dict — those keys
never exist at that level, so EVERY governor knob had silently fallen through to `None` since 22.1
shipped, regardless of what Zone 2 configured. Fixed via a new `default_risk_params =
risk_params.get("default") or {}`, mirroring the pattern `_setup_strategy_instance` already used
correctly elsewhere. Proven with `test_start_session_risk_params_shape.py` (7 cases) driving the
real `start_session()` against the actual Node-shaped payload.

**Second gap found and fixed:** `AlgoTrading.jsx`'s `algo:session:update` socket handler merged
`status`/`pnl`/`openPositions`/`symbolStats` but silently dropped `tradingState` — so even with the
new SessionCard badge, a real-time governor breach would never have updated it live, only on the
next full refetch. Fixed with the same merge-if-present pattern.

**Third gap found and fixed:** `server/src/utils/webhook.js`'s `VALID_EVENTS` (used to validate a
webhook-config PUT) was missing `risk_breach` — present in `Settings.js`'s schema enum and
dispatched since 22.1, but never added to this separate list, so saving it via the UI 400'd
silently. Fixed.

**Container/Jest-verified 2026-07-17** — `docker exec enma_trading_platform-engine-1 pytest
/app/tests/`: **330/330 passed** (up from 323/323 pre-22.7), covering every Plan 21/22 test file
including the new `test_start_session_risk_params_shape.py`. `docker exec
enma_trading_platform-server-1 npx jest`: **88/88 passed** (up from 79/79) — this also confirms
`capitalGate.test.js`, flagged unverified since 22.1 (no `node_modules` in the earlier dev
sandbox), genuinely passes with 100% coverage. **Live-verified in-browser via Claude in Chrome**
against the user's own running `docker compose watch` stack: Dashboard/Risk Dashboard/Algo Trading
all load with zero console errors; the new governor form section's save→reload round-trip
genuinely persists through MongoDB; the wizard's allocation dropdown renders correctly for 2+
symbols. **Pending: real live Testnet re-verification only** — no behavioral claim above (governor
vetoes, protections locks, capital gate rejects, VaR/CVaR breach, correlation-cluster veto, a real
governor breach flipping the SessionCard badge) has been exercised against an actual running
Binance Testnet session yet.

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
