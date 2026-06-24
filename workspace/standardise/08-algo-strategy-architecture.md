# 08 — Algorithm vs. Strategy: architecture, separation, execution format

> Companion analysis doc (written after the `00`–`07` map and after Phase 1 shipped). Answers a
> direct question: **is Enma's strategy/algorithm separation correct, and can the *algorithm* (the
> execution engine, not the strategies) be optimised to freqtrade / nautilus standards?**
> **References:** freqtrade `freqtrade/strategy/interface.py`, `freqtrade/freqtradebot.py`;
> nautilus `Strategy`/`Actor`, `RiskEngine`, `ExecutionEngine`, `NautilusKernel`.
> **Verdict up front:** the *decision* separation is correct and partly ahead of freqtrade. The one
> structural gap is that Enma runs **two execution loops** (backtest vs live) where both references
> run **one engine for both modes**. That two-loop split is the driver-level root of RC-1. → **F-024**.

---

## The axis that explains all three: how much power does the "strategy" hold?

All three draw a strategy↔algorithm line; they differ on *how much the strategy is allowed to do*.

```
LEAST strategy power ───────────────────────────────► MOST strategy power
   freqtrade                    Enma                      nautilus
 (signal only)        (alpha-signal + bound models)   (submits its own orders)
```

| Dimension | freqtrade | **Enma** | nautilus |
|---|---|---|---|
| What "strategy" *is* | DataFrame signal generator (`IStrategy`) | **Alpha Model only** (`forecast() → Signal`) | an `Actor` subclass with order mgmt |
| Strategy output | signal columns (`enter_long`, `exit_long`…) | a `Signal(direction, conviction, magnitude)` | calls `self.submit_order(order)` |
| Can strategy place orders? | No — bot reads signals | **No — `test_boundaries.py` forbids writing `buy/sell/stop_loss`** | Yes — `OrderFactory` + `submit_order()` |
| Who sizes? | `Wallets` (strategy only *suggests* via `custom_stake_amount`) | `PortfolioModel.construct()` | the strategy itself (`make_qty`) |
| Who does risk? | `FreqtradeBot` + `ProtectionManager` | `RiskModel.assess()` in-pipeline | a separate **`RiskEngine`** (pre-trade gate, emits `OrderDenied`) |
| Who executes? | `execute_entry/exit()` in the bot | `ExecutionModel.route()` + the runner loop | `ExecutionEngine` + venue adapters |
| Data model | **vectorized** (whole dataframe at once) | **sequential** per-candle (`forecast()` each bar) | **event-driven** per tick/bar (`on_bar`) |
| Backtest↔live parity | shared strategy + shared `create_order()` | shared model classes + shared `evaluate()` | **one `NautilusKernel`** for all modes |

---

## Are we correct? — Yes, and on the *decision* side ahead of freqtrade

1. **Separation by role, not just by phase.** freqtrade splits "signals now, execute later" inside one
   monolithic `IStrategy` with a pile of optional callbacks (`custom_stoploss`, `custom_stake_amount`,
   `confirm_trade_entry`…). Enma splits into five distinct objects (Alpha / Risk / Cost / Portfolio /
   Execution), each with one contract (`engine/core/models/base.py`). Stronger separation of concerns.

2. **The boundary is *enforced*, not conventional.** This is the real differentiator. freqtrade *trusts*
   you; nautilus *lets* the strategy submit orders and catches bad ones downstream in `RiskEngine`.
   Enma **fails a test** (`engine/tests/test_boundaries.py`) if a strategy reads `self.equity` or writes
   `self.stop_loss`. Enforced > documented boundaries — neither reference does this as strictly.

3. **Format choice (sequential `forecast()`) is the safe one.** freqtrade is vectorized — fast, but
   lookahead bias is a constant footgun. Enma and nautilus are sequential / event-driven, lookahead-safe
   by construction (engine CLAUDE.md: "strictly sequential — no lookahead"). Enma matches the safer model.

**Do NOT migrate toward nautilus's "strategy submits its own orders" model.** Enma's enforced alpha-only
boundary is better for a single-user platform: strategies are trivially safe to write and cannot corrupt
risk/execution state. nautilus needs a `RiskEngine` *because* it permits dangerous strategies. Enma
designed that danger out — keep it.

---

## Where the *algorithm* can be optimised — uncomfortable truth first

**The biggest gap is not the five-MODEL split (excellent) — it is that Enma runs two execution LOOPS.**
`engine/services/backtest_runner.py:run_backtest_simulation` is a candle-replay loop;
`engine/core/live_bot_manager.py:_run_symbol_loop` is a separate websocket-driven loop. **Both call
`evaluate()`** (so *decide* is unified) and both share `DefaultExecution`/`Backtest`/`LiveExecution`
fill mechanics — but each orchestrates fills, margin, bracket arming and reconciliation **independently**.

This two-loop split is the **driver-level root of RC-1** (backtest↔live asymmetry). freqtrade avoids it by
routing both modes through one `create_order()`; nautilus avoids it harder — **one `NautilusKernel` runs
backtest, sandbox, and live with identical code**, achieving "backtest-live parity" structurally rather
than by hand. Phase 1 closed RC-1's *symptom* (shared `clamp_and_round_qty()` / `round_price()` and the
F-013/F-014 guards, added inline to **both** loops). It did **not** close the *cause*: the two loops are
still separate code that must be kept in sync by discipline. **Every future edit to one loop and not the
other re-opens an RC-1-class asymmetry.** That is the structural finding this doc adds. → **F-024**.

### Gap inventory (against the references)

| # | Gap vs reference | Borrow from | Tracked as |
|---|---|---|---|
| 1 | **Two execution loops** — unify the driver, not just the models | nautilus `NautilusKernel`; freqtrade single `create_order`/`process` | **F-024 (new — this doc, Phase 3)** |
| 2 | **Execution model is market-fill only** — no TWAP/VWAP/iceberg | nautilus `ExecAlgorithm` | **A-016 (new — this doc, Phase 3)** |
| 3 | Risk is in-pipeline, not a central pre-submit gate that can deny + rate-limit | nautilus `RiskEngine`; freqtrade `ProtectionManager` | A-001 / A-002 / A-003 (Phase 4) |
| 4 | Poll-based fill detection, not event-driven | nautilus MessageBus; user-data-stream | F-020 (Phase 5) |
| 5 | No DCA / position adjustment | freqtrade `adjust_trade_position` | A-014 (Phase 9) |
| 6 | No contingent / emulated orders (OCO hand-rolled) | nautilus `OrderEmulator` / contingency | F-018 / F-019 (Phase 6) |

Only #1 and #2 are new; #3–#6 were already in the backlog. Phase 3 captures the two new ones.

---

## Findings

| ID | Area | Severity | One-line | Enma file(s) a fix would touch | Reference |
|----|------|----------|----------|--------------------------------|-----------|
| F-024 | pipeline | HIGH | Two separate execution loops (backtest replay vs live websocket) orchestrate fills/margin/bracket/reconcile independently though both call `evaluate()` → RC-1-class asymmetry recurs at the driver level; Phase 1 fixed the symptom (shared guards) not the cause (shared driver) | `engine/services/backtest_runner.py:run_backtest_simulation`, `engine/core/live_bot_manager.py:_run_symbol_loop` | nautilus `NautilusKernel` (one kernel: backtest/sandbox/live); freqtrade single `create_order()`/`process()` |

| ID | Value | Status | One-line | Enma seam | Reference |
|----|-------|--------|----------|-----------|-----------|
| A-016 | ★★ | MISSING | Pluggable **execution algorithms** (TWAP / VWAP / iceberg) so large orders can be sliced instead of single market fills; only possible cleanly once the driver is unified (F-024) | `engine/core/models/execution.py` (new `ExecAlgorithm` seam on the Execution model) | nautilus `ExecAlgorithm` (order flows strategy → ExecAlgorithm → RiskEngine → ExecutionEngine) |

---

## Why this is one phase, sequenced after metrics (Phase 2)

F-024 is a driver-level refactor of the backtest **and** live loops — exactly the "large rework, do it on
its own" class the playbook warns about. It must come **after** Phase 2 (metrics) because Phase 2 is
adding fields to `run_backtest_simulation`'s metrics block; unifying the loop on top of an in-flight
metrics change would collide. A-016 is the natural follow-on once one driver exists. See `tracker.md`
Phase 3 for the implementer-awareness note (preserve Phase 1 parity guards + Phase 2 metrics; re-baseline
golden master against the post-Phase-2 state).

---

## Note on method

freqtrade behaviour read from source (`strategy/interface.py`, `freqtradebot.py`); nautilus behaviour
read from the docs site (`concepts/strategies`, `concepts/architecture`) — GitHub MCP PAT still expired.
Verify exact `ExecAlgorithm` / `RiskEngine` field names against nautilus source before implementing A-016.
