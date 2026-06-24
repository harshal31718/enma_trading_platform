# Findings Index — Standardise Study

> Flat, severity-ranked, **independently-shippable** list of every finding across the six topic
> docs. This is the backlog the later fix phase executes from — in **severity order, not file
> order**. Each row is self-contained: a future session can act on one row without reading the rest.
>
> **Status:** map complete — all seven topic docs written; 24 findings (F-001…F-024). F-024 added
> post-Phase-1 from the architecture analysis in `08-algo-strategy-architecture.md`.
> Counts reconcile: total rows here == sum of findings across `00`–`06` + `08` (F-024).

## Legend

`[CRITICAL]` wrong money/state or backtest not reproducible live · `[HIGH]` real correctness/risk
gap · `[MEDIUM]` inconsistency / missing validation / duplication · `[LOW]` cleanup / dead code / docs.

## Severity rollup (fix in this order)

| Severity | Count | IDs |
|---|---|---|
| CRITICAL | 2 | F-005, F-006 |
| HIGH | 10 | F-001, F-002, F-003, F-007, F-011, F-013, F-018, F-019, F-021, F-024 |
| MEDIUM | 10 | F-004, F-008, F-009, F-012, F-014, F-015, F-017, F-020, F-022, F-023 |
| LOW | 2 | F-010, F-016 |

## By area

| Area | Count | Doc |
|---|---|---|
| pipeline | 5 | `00-pipeline-overview.md` + `08` (F-024) |
| boundaries | 6 | `05-boundaries.md` |
| backtesting | 2 | `01-backtesting.md` |
| risk | 2 | `02-risk-management.md` |
| params/portfolio | 3 | `03-params-portfolio.md` |
| sltp-oco | 3 | `04-sltp-oco.md` |
| reconciliation | 3 | `06-reconciliation-uistate.md` |

## The two root causes everything hangs off

- **RC-1 — Backtest↔live guard asymmetry.** Precision/min-notional/risk guards enforced live, skipped
  in backtest. Spawns the only two CRITICALs (F-005, F-006) plus F-011, F-013, F-017. One shared
  validation path fixes the *symptom* cluster (shipped in Phase 1). The *driver-level* root — two
  separate execution loops kept in sync only by discipline — is **F-024** (Phase 3, doc `08`).
- **RC-A/B — Three-way state + partial reconcile.** Position truth split across engine memory / Mongo /
  Binance, reconciled only partially and only when a position is open. Spawns F-001, F-002, F-004,
  F-020, F-021, F-022. One exchange-reconciled record that the UI reads fixes the cluster.

## Findings

| ID | Area | Severity | One-line | Enma file(s) a fix would touch | Reference |
|----|------|----------|----------|--------------------------------|-----------|
| F-001 | pipeline | HIGH | Position truth split across engine memory / Mongo / Binance with no single authoritative record continuously reconciled | `engine/core/live_bot_manager.py`, `server/src/models/LiveSession.js` | freqtrade `Trade` + `update_trade_state()` |
| F-002 | pipeline | HIGH | No reconciliation of pending/open ORDERS (only open positions); partial-fill / reject between loops not detected | `engine/core/live_bot_manager.py:_execute_entry`, `_run_symbol_loop` | freqtrade `manage_open_orders()` → `update_trade_state()` |
| F-003 | pipeline | HIGH | Order placement crosses engine→Node→engine→Binance; position can exist on exchange while engine view fails to update | `engine/core/live_bot_manager.py:_execute_entry`, `server/src/controllers/algo.controller.js:handleAlgoPlaceOrder` | freqtrade in-process `execute_entry()` |
| F-004 | pipeline | MEDIUM | Reconciliation gated on candle-close AND open local position; cannot self-heal when engine wrongly believes it is flat | `engine/core/live_bot_manager.py:_verify_exchange_position_still_open` (gated call site) | freqtrade reconciles every `process()` regardless of state |
| F-005 | boundaries | CRITICAL | Backtest never calls `clamp_and_round_qty()` → fills sub-minNotional/sub-stepSize orders live rejects (JUPUSDT class) | `engine/services/backtest_runner.py:563-564,607-608` | freqtrade `create_order` → `amount_to_precision` / `get_min_pair_stake_amount` |
| F-006 | boundaries | CRITICAL | Backtest SL/TP prices not rounded to tickSize (`round_price` not called) → exits at prices unreachable live | `engine/services/backtest_runner.py:689-725` | freqtrade `create_order` → `price_to_precision` |
| F-007 | boundaries | HIGH | `round_price()` always ROUND_DOWN, not direction-aware; can nudge stop the wrong way | `engine/utils/symbols.py:round_price` (callers `live_bot_manager.py:526-527`) | freqtrade `price_to_precision(rounding_mode)` |
| F-008 | boundaries | MEDIUM | No reserve buffer on min-notional bump → orders a ~5%+stoploss reserve would size correctly get rejected | `engine/utils/symbols.py:clamp_and_round_qty`, `live_bot_manager.py:538-554` | freqtrade `_get_stake_amount_limit` reserve |
| F-009 | boundaries | MEDIUM | Tradable-symbol list maintained in 3 parallel places; drift risk; suspended symbols removed without marker | `engine/core/constants.py:FUTURES_SYMBOLS`, `client/src/utils/symbolLimits.js`, `server/src/constants/top_symbols.js` | freqtrade single market metadata source |
| F-010 | boundaries | LOW | `round_qty()` defined but never called (dead code) | `engine/utils/symbols.py:round_qty` | n/a |
| F-011 | backtesting | HIGH | Backtest fills SL/TP at exact stop/target even on gap-through candles → understates gap loss | `engine/services/backtest_runner.py:688-718`, `core/models/execution.py:exit_fill` | freqtrade `_get_close_rate_for_stoploss` (gap → OPEN) |
| F-012 | backtesting | MEDIUM | Fixed adverse slippage % is symbol/size-agnostic, not liquidity-aware | `engine/core/models/execution.py:entry_fill/exit_fill`, `cost.py:adverse_fill` | freqtrade candle-bounded fills |
| F-013 | risk | HIGH | Min-notional bump raises qty above `risk_pct` budget → silently over-risks (breaks invariant #6) on small-equity/high-minNotional symbols | `engine/utils/symbols.py:clamp_and_round_qty`, `engine/core/live_bot_manager.py:_execute_entry` | freqtrade `validate_stake_amount` (skip below min) |
| F-014 | risk | MEDIUM | Global risk hard-limits enforced only in `risk.js`; engine trusts incoming values → non-`risk.js` paths bypass caps | `server/src/utils/risk.js:resolveStrategyRiskParams`, `engine/services/backtest_runner.py` (~L282-335) | freqtrade single config-validated path |
| F-015 | params | MEDIUM | Out-of-range params silently clamped (not rejected) → backtest runs with different params than entered | `engine/services/backtest_runner.py:282-300`, `engine/core/strategy.py:PARAMS` | freqtrade typed `NumericParameter` bounds validated at construction |
| F-016 | params | LOW | Unknown/typo'd param name silently dropped (`setattr`-if-exists) → runs with default, no error | `engine/services/backtest_runner.py:~295` | freqtrade explicit parameter declaration |
| F-017 | portfolio | MEDIUM | Single-symbol backtest vs multi-symbol live with shared margin → backtest equity unrepresentative; portfolio risk never validated pre-live | `engine/services/backtest_runner.py:run_backtest_simulation`, `engine/core/models/portfolio.py:allocate` | freqtrade shared `wallets` accounting (both modes) |
| F-018 | sltp-oco | HIGH | Entry fills but SL placement fails → position left naked; only logs/notifies, no emergency market exit | `engine/core/live_bot_manager.py:_execute_entry` (~L604-612) | freqtrade `emergency_exit()` |
| F-019 | sltp-oco | HIGH | No partial-fill quantity propagation between SL/TP legs → resting leg can over-close residual position | `engine/core/live_bot_manager.py:_check_exits/_close_position`, `server/src/controllers/trade.controller.js:placeOCOOrder` | nautilus `OUO` peer-quantity reduction |
| F-020 | sltp-oco | MEDIUM | Exit/fill detection poll-based (candle-gated); no user-data-stream listener → stale view between fill and next candle | `engine/core/live_bot_manager.py:_check_exits`, `_verify_exchange_position_still_open` | nautilus event-driven fills |
| F-021 | reconciliation | HIGH | UI position/PnL derives from engine in-memory belief (engine→Mongo→UI), not exchange-reconciled state → UI shows wrong data when desynced | `engine/core/live_bot_manager.py:_notify_node`, `server/src/controllers/algo.controller.js:handleEngineStats`, `server/src/models/LiveSession.js` | freqtrade UI reads reconciled `Trade`; nautilus cache |
| F-022 | reconciliation | MEDIUM | Reconciliation split across Node startup + engine runtime with no shared truth definition | `server/src/services/reconciliation.js`, `engine/core/live_bot_manager.py` | freqtrade single-loop reconcile |
| F-023 | reconciliation | MEDIUM | Live PnL from last price (`qty*price − notional`) diverges from Binance mark-price + funding unrealized PnL | `engine/core/live_bot_manager.py` PnL calc, client live-PnL hook | freqtrade/nautilus exchange-reported values |
| F-024 | pipeline | HIGH | Two separate execution loops (backtest replay vs live websocket) orchestrate fills/margin/bracket/reconcile independently though both call `evaluate()` → RC-1-class asymmetry recurs at the driver level (Phase 1 fixed the symptom, not the cause) | `engine/services/backtest_runner.py:run_backtest_simulation`, `engine/core/live_bot_manager.py:_run_symbol_loop` | nautilus `NautilusKernel` (one kernel: backtest/sandbox/live); freqtrade single `create_order()`/`process()` |

<!--
Row template:
| F-0XX | area | SEVERITY | one-line | enma/file.py:line | upstream reference |
-->

## Next phase (not started)

Phase 2 = fix, in severity order: the two CRITICALs (F-005/F-006) and the RC-1 cluster first via a
single shared backtest/live validation path; then the RC-A/B cluster via one exchange-reconciled
record. Each finding row is self-contained and independently shippable. Requires separate approval.
