# Check Boundaries

Enforce the Narang Black-Box separation of concerns (see `workspace/docs/core/ARCHITECTURE.md` and
`workspace/plan/modular_merger_plan.md`) on the engine. The **Alpha Model (a strategy) must only
predict** — it may read candles and its own `PARAMS`, but must never read account/position state or
write execution orders. This skill is the enforcement arm of the modular architecture and a guard for
every strategy added via `/add-strategy`.

Arguments: $ARGUMENTS — optional path/strategy name to scope the check (default: all of
`engine/strategies/`).

---

## What the Alpha boundary forbids

A strategy class (and anything it calls in `forecast()`/`before()`/`should_long`/`should_short`) must
**not** reference any of:

- Account/position state: `self.balance`, `self.equity`, `self.position`, `self.available_capital`,
  `self.available_margin`, `self.peak_equity`, `self.session_drawdown`, `self.max_qty`.
- Order-state writes: assigning `self.buy`, `self.sell`, `self.stop_loss`, `self.take_profit`,
  `self._pending_flip`, `self._close_at_open`.
- Execution/sizing/position-management calls: `size_by_risk`, `size_by_notional`, `go_long`,
  `go_short`, `flip_position`, `close_position`, `liquidate`, `trail_stop`, `move_to_breakeven`,
  `update_position`.

Sizing → Portfolio model. Stops/TP/trailing → Risk model. Orders/flips/closes → Execution model.

## 1. Fast static grep (run first)

```
grep -nE 'self\.(balance|equity|position|available_capital|available_margin|peak_equity|session_drawdown|buy|sell|stop_loss|take_profit|_pending_flip|_close_at_open)|self\.(size_by_risk|size_by_notional|go_long|go_short|flip_position|close_position|liquidate|trail_stop|move_to_breakeven|max_qty)\b' engine/strategies/$ARGUMENTS -r
```

Any hit inside a strategy module is a boundary violation — report it `file:line` + which rule.
(Use the Grep tool, not raw shell, so results are clickable.)

## 2. Boundary unit test (authoritative)

```
docker compose exec engine python -m pytest engine/tests/test_boundaries.py -q
```

The test imports each seeded strategy, asserts it defines `forecast()` and **does not** define
`go_long`/`go_short`/`update_position`, and AST-scans each strategy module for the forbidden
references above. Green = boundaries intact.

## 3. Deep audit (when the grep/test is ambiguous, or after a large refactor)

Spawn the `drift-reviewer` subagent to audit the current code against the five model boundaries defined
in `workspace/plan/modular_merger_plan.md` and `workspace/docs/core/ARCHITECTURE.md`.
Report violations `file:line`. Read-only; reports only.

## Report

List every violation as `file:line — <boundary> — <what leaked>`, or state "boundaries intact" with
the grep + pytest both clean. Do not wave through a strategy that reads equity or sets orders, even if
backtests pass — passing metrics do not prove clean boundaries.
