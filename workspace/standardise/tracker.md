# Standardise — Implementation Tracker

> Live status board for all 38 items (23 corrections `F-xxx` + 15 additions `A-xxx`).
> **Workflow:** see `CLAUDE.md`. Work **top-to-bottom, one phase at a time, one item at a time.**
> Update each row's **Status** + **Commit/Note** the moment an item is finished. Do not batch.

**Status values:** `TODO` · `IN PROGRESS` · `BLOCKED` · `DONE` · `DROPPED`

## Progress

| | Total | TODO | IN PROGRESS | BLOCKED | DONE | DROPPED |
|---|---|---|---|---|---|---|
| Corrections (F) | 23 | 17 | 0 | 0 | 6 | 0 |
| Additions (A) | 15 | 15 | 0 | 0 | 0 | 0 |
| **All** | **38** | **32** | **0** | **0** | **6** | **0** |

> Update this table whenever a row changes status.

---

## Phase 1 — Backtest↔live parity (root cause RC-1). Ship first; de-risks live.

| Step | ID | Item | Doc | Sev | Status | Commit / Note |
|---|---|---|---|---|---|---|
| 1.1 | F-005 | Route backtest entry through `clamp_and_round_qty()` (stepSize/minQty/minNotional) | 05 | CRITICAL | DONE | Backtest entries/flips routed through clamp_and_round_qty() |
| 1.2 | F-006 | Round backtest SL/TP prices to tickSize via `round_price()` | 05 | CRITICAL | DONE | SL/TP prices rounded to exchange tickSize in backtests |
| 1.3 | F-007 | Make `round_price()` direction-aware (ROUND_DOWN long / ROUND_UP short for stops) | 05 | HIGH | DONE | Stops price rounding now uses ROUND_DOWN for long / ROUND_UP for short |
| 1.4 | F-013 | Skip-or-tolerance gate when min-notional bump would exceed `risk_pct` budget | 02 | HIGH | DONE | Skips trade if minNotional bump exceeds target qty by >30% |
| 1.5 | F-008 | Add margin/stoploss reserve to the min-notional bump | 05 | MEDIUM | DONE | 5% margin + stoploss reserve buffer added to minNotional quantity calculations |
| 1.6 | F-014 | Re-assert global risk hard-limits inside the engine (defensive floor) | 02 | MEDIUM | DONE | risk_pct <= 0.20, max_session_dd <= 0.90, leverage <= 125 defensive clamps enforced |

## Phase 2 — Metrics & analysis (cheap, high-value; data already stored).

| Step | ID | Item | Doc | Val/Sev | Status | Commit / Note |
|---|---|---|---|---|---|---|
| 2.1 | A-007 | Add CAGR, Calmar, SQN, profit factor, expectancy(+ratio), consecutive win/loss, drawdown duration, market change | 07 | ★★★ | TODO | |
| 2.2 | A-012 | Restructure metrics as a pluggable statistic registry (one class per metric) | 07 | ★★ | TODO | |
| 2.3 | A-008 | Per-exit-reason + per-pair/per-tag breakdown tables in backtest results | 07 | ★★ | TODO | |
| 2.4 | A-009 | Underwater / drawdown curve | 07 | ★★ | TODO | |
| 2.5 | A-010 | Returns distribution / per-trade P&L histogram + MFE/MAE scatter | 07 | ★★ | TODO | |
| 2.6 | A-011 | Rolling Sharpe/volatility curve | 07 | ★ | TODO | |
| 2.7 | F-011 | Model gap-through stops in backtest (fill at candle OPEN when range skips the stop) | 01 | HIGH | TODO | |
| 2.8 | F-012 | Replace fixed-% slippage with candle-bounded (or liquidity-scaled) fills | 01 | MEDIUM | TODO | |
| 2.9 | F-017 | Multi-symbol (portfolio) backtest mode | 03 | MEDIUM | TODO | |

## Phase 3 — Risk layers (protections + state machine).

| Step | ID | Item | Doc | Val/Sev | Status | Commit / Note |
|---|---|---|---|---|---|---|
| 3.1 | A-001 | Protections stack: CooldownPeriod + StoplossGuard (then MaxDrawdown window, LowProfitPairs) | 07 | ★★★ | TODO | |
| 3.2 | A-002 | TradingState machine ACTIVE / REDUCING / HALTED session kill-switch | 07 | ★★★ | TODO | |
| 3.3 | A-003 | Order rate-limiting (max submit/modify rate) before orders hit Binance | 07 | ★★ | TODO | |

## Phase 4 — State truth & reconciliation (root cause RC-A/B). Large rework; do on its own.

| Step | ID | Item | Doc | Sev | Status | Commit / Note |
|---|---|---|---|---|---|---|
| 4.1 | F-001 | One exchange-reconciled position record as single source of truth | 00/06 | HIGH | TODO | |
| 4.2 | F-021 | UI reads the reconciled record, not engine in-memory belief | 06 | HIGH | TODO | |
| 4.3 | F-002 | Reconcile open ORDERS (not just open positions) each loop | 00 | HIGH | TODO | |
| 4.4 | F-020 | User-data-stream listener for fills (event-driven, not poll) | 04 | MEDIUM | TODO | |
| 4.5 | F-004 | Reconcile every loop regardless of local position state (self-heal when wrongly flat) | 00 | MEDIUM | TODO | |
| 4.6 | F-022 | Unify startup (Node) + runtime (engine) reconciliation into one owner | 06 | MEDIUM | TODO | |
| 4.7 | F-023 / A-013 | Exchange-truth PnL via mark-price fallback chain (mark→quote→last→close) + missing-price flag | 06/07 | MEDIUM / ★★★ | TODO | |
| 4.8 | F-003 | Reduce/strengthen the engine→Node→engine→Binance placement hop chain | 00 | HIGH | TODO | |

## Phase 5 — SL/TP & OCO robustness.

| Step | ID | Item | Doc | Sev | Status | Commit / Note |
|---|---|---|---|---|---|---|
| 5.1 | F-018 | Emergency market exit if SL placement fails after entry (no naked positions) | 04 | HIGH | TODO | |
| 5.2 | F-019 | Partial-fill quantity propagation between SL/TP legs (OUO semantics) | 04 | HIGH | TODO | |

## Phase 6 — Pair management.

| Step | ID | Item | Doc | Val/Sev | Status | Commit / Note |
|---|---|---|---|---|---|---|
| 6.1 | F-009 | Single source for the symbol list (drop the triple-maintained copies) | 05 | MEDIUM | TODO | |
| 6.2 | A-004 | Dynamic pairlist pipeline: VolumePairList → Spread/Volatility/Precision/Age filters | 07 | ★★★ | TODO | |

## Phase 7 — Parameters & optimization.

| Step | ID | Item | Doc | Val/Sev | Status | Commit / Note |
|---|---|---|---|---|---|---|
| 7.1 | F-015 | Reject (not silently clamp) out-of-range params; surface to user | 03 | MEDIUM | TODO | |
| 7.2 | F-016 | Error (not silently drop) unknown/typo'd param names | 03 | LOW | TODO | |
| 7.3 | A-005 | Typed self-validating parameter classes (IntParameter/DecimalParameter analogues) | 07 | ★★ | TODO | |
| 7.4 | A-006 | Parameter-optimization run mode over the backtester (Sharpe/Sortino/Calmar/multi-metric objectives) | 07 | ★★★ | TODO | |

## Phase 8 — Strategy mechanisms (borrow logic, not strategy files).

| Step | ID | Item | Doc | Val | Status | Commit / Note |
|---|---|---|---|---|---|---|
| 8.1 | A-014 | Position adjustment / DCA (scale in/out) in the execution model | 07 | ★★★ | TODO | |
| 8.2 | A-015 | Entry/exit tagging end-to-end (signal → trade record) feeding per-tag analytics | 07 | ★★ | TODO | |

## Phase 9 — Cleanup.

| Step | ID | Item | Doc | Sev | Status | Commit / Note |
|---|---|---|---|---|---|---|
| 9.1 | F-010 | Remove dead `round_qty()` (or wire it in if needed after Phase 1) | 05 | LOW | TODO | |

---

## Coverage check

All 23 corrections placed: F-001→4.1 · F-002→4.3 · F-003→4.8 · F-004→4.5 · F-005→1.1 · F-006→1.2 ·
F-007→1.3 · F-008→1.5 · F-009→6.1 · F-010→9.1 · F-011→2.7 · F-012→2.8 · F-013→1.4 · F-014→1.6 ·
F-015→7.1 · F-016→7.2 · F-017→2.9 · F-018→5.1 · F-019→5.2 · F-020→4.4 · F-021→4.2 · F-022→4.6 ·
F-023→4.7.
All 15 additions placed: A-001→3.1 · A-002→3.2 · A-003→3.3 · A-004→6.2 · A-005→7.3 · A-006→7.4 ·
A-007→2.1 · A-008→2.3 · A-009→2.4 · A-010→2.5 · A-011→2.6 · A-012→2.2 · A-013→4.7 · A-014→8.1 ·
A-015→8.2.
