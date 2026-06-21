# Add Strategy

Scaffold a new trading strategy inside the Python FastAPI engine.

Arguments: $ARGUMENTS (Format: Name of the strategy, e.g. MACDRSI)

## Step 0 — Check for duplicates FIRST

Read both index files before writing any code:

1. `workspace/docs/strategies/INDEX.md` — all 5 existing strategies, their signal logic, and which
   indicators they use. Confirm your new strategy's signal logic doesn't duplicate an existing one.

2. `workspace/docs/indicators/INDEX.md` — all available `ta.*` indicator functions. Reuse existing
   indicators rather than computing inline where possible.

## Instructions

1. Create a directory named `engine/strategies/$ARGUMENTS/`.

2. Inside that directory, create `__init__.py` declaring a class named `$ARGUMENTS` inheriting from `BaseStrategy`:

   ```python
   from engine.core.strategy import BaseStrategy
   import engine.indicators as ta

   class $ARGUMENTS(BaseStrategy):
       PARAMS = {
           "period": {"type": "int", "default": 14, "min": 2, "max": 200, "label": "Period",
                      "description": "Increasing: fewer signals. Decreasing: more signals."}
       }

       def __init__(self):
           super().__init__()
           self.period: int = self.PARAMS["period"]["default"]

       def before(self) -> None:
           # Compute all indicators once here and store in self.vars
           if len(self.candles) < 20:
               return
           self.vars["my_indicator"] = ta.rsi(self.candles, period=self.period)

       def should_long(self) -> bool:
           return False

       def should_short(self) -> bool:
           return False

       def go_long(self) -> None:
           stop = self.price * 0.98
           qty = self.size_by_risk(stop)
           self.buy = qty, self.price
           self.stop_loss = qty, stop
           self.take_profit = qty, self.rr_target("long", stop, rr=self.rrr)

       def go_short(self) -> None:
           stop = self.price * 1.02
           qty = self.size_by_risk(stop)
           self.sell = qty, self.price
           self.stop_loss = qty, stop
           self.take_profit = qty, self.rr_target("short", stop, rr=self.rrr)
   ```

3. Register the new strategy in `engine/services/strategy_seeder.py`. Append an entry to
   `DEFAULT_STRATEGIES` with the `name` matching `$ARGUMENTS` and a one-line `description`.
   The seeder is idempotent — upserts metadata into MongoDB `strategies` on every startup.

4. Restart the engine container (`docker-compose restart engine`) and verify the strategy
   metadata loads on the UI Strategies page.

5. Update documentation:
   - Create `workspace/docs/strategies/$ARGUMENTS.md` — follow the format of existing strategy docs.
   - Add a row to `workspace/docs/strategies/INDEX.md`.
   - Update `workspace/docs/state/CURRENT_STATE.md` — strategy list.

6. Run `/sync-spec`.

## Rules

- **No lookahead** — only use candle data at or before `self.index`.
- **No direct Binance calls** — only `self.buy`, `self.stop_loss`, `self.take_profit`, `self.liquidate()`.
- **Use `ta.*`** — call `import engine.indicators as ta`; route everything through the indicator layer.
  Inline computation is only acceptable for indicators not yet in the layer (see `workspace/docs/indicators/INDEX.md`).
- **`self.vars`** — for state that must persist across candles within a single bar.
- **Compute once in `before()`** — never call `ta.*` inside `should_long/short`, `go_long/short`,
  or `update_position`. This prevents redundant TA-Lib calls and keeps backtest hot-loop fast.
- **`size_by_risk(stop)`** — default sizing (rule #6). Use `size_by_notional` only when you intentionally
  want a fixed equity fraction and are not setting a stop-loss.
