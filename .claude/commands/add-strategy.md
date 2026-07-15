# Add Strategy

Scaffold a new trading strategy inside the Python FastAPI engine, in the **five-model
(Narang Black-Box) style** — the strategy is a pure Alpha Model. The former
`go_long`/`go_short`/`should_long` template is retired: it writes order state from the
strategy, which `/check-boundaries` and `engine/tests/test_boundaries.py` reject.

Arguments: $ARGUMENTS (Format: Name of the strategy, e.g. MACDRSI)

## Step 0 — Check for duplicates FIRST

Read both index files before writing any code:

1. `workspace/docs/strategies/INDEX.md` — all existing strategies, their signal logic, and which
   indicators they use. Confirm your new strategy's signal logic doesn't duplicate an existing one.
2. `workspace/docs/indicators/INDEX.md` — all available `ta.*` indicator functions. Reuse existing
   indicators rather than computing inline where possible.

Also skim one seeded reference implementation (`engine/strategies/MicroScalper/__init__.py`) —
the template below mirrors it.

## Instructions

1. Create a directory named `engine/strategies/$ARGUMENTS/`.

2. Inside it, create `__init__.py` declaring a class named `$ARGUMENTS`:

   ```python
   import numpy as np

   from engine.core.strategy import BaseStrategy
   import engine.indicators as ta

   try:  # dual import root (engine package vs top-level) — mirror the seeded strategies
       from engine.core.models import AtrBracketRiskModel, RiskBudgetPortfolio, Signal
   except ImportError:
       from core.models import AtrBracketRiskModel, RiskBudgetPortfolio, Signal


   class $ARGUMENTS(BaseStrategy):
       """One-paragraph description: signal logic, intended timeframe/symbols."""

       # ≥ the largest indicator lookback (+ buffer). The runner warms up
       # max(50, MIN_WARMUP_CANDLES) candles before the first signal.
       MIN_WARMUP_CANDLES: int = 50

       PARAMS = {
           "period": {"type": "int", "default": 14, "min": 2, "max": 200, "label": "Period",
                      "description": "Increasing: fewer signals. Decreasing: more signals."},
       }

       def __init__(self):
           super().__init__()
           self.period: int = self.PARAMS["period"]["default"]

           # Bind the risk + portfolio models (stops/TP and sizing live THERE,
           # never in the strategy):
           #   AtrBracketRiskModel  — ATR SL/TP bracket (+ optional trailing/breakeven)
           #   ChandelierRiskModel  — chandelier trailing stop
           #   SignalExitRiskModel  — no bracket; exits are signal-driven (flips)
           #   RiskBudgetPortfolio  — size by risk budget (default choice)
           #   NotionalPortfolio    — fixed equity-fraction sizing
           self.risk_model      = AtrBracketRiskModel()
           self.portfolio_model = RiskBudgetPortfolio()

       def validate_params(self) -> None:
           # Raise ValueError for invalid cross-param combinations (rejected, not clamped).
           pass

       # ── Phase A: one-time vectorized pre-computation over the FULL array ──
       def prepare(self, candles: np.ndarray) -> None:
           if len(candles) == 0:
               self._ind_seq = np.array([])
               return
           self._ind_seq = np.asarray(
               ta.rsi(candles, period=self.period, sequential=True), dtype=float)

       # ── Phase B: pure index lookup per candle (NO ta.* calls here) ────────
       def before(self) -> None:
           i = self.index
           if (i + 1) < self.MIN_WARMUP_CANDLES:
               return
           self.vars["ind"] = float(self._ind_seq[i])
           # If the risk model should use precomputed levels, set:
           #   self.vars["atr"], self.vars["atr_stop_long"], self.vars["atr_stop_short"],
           #   self.vars["atr_tp_long"], self.vars["atr_tp_short"]

       # ── Alpha Model: predict only ─────────────────────────────────────────
       def forecast(self) -> Signal:
           if self.vars.get("ind", 50.0) < 30.0:
               return Signal(direction=1, conviction=1.0, ref_price=self.price)
           if self.vars.get("ind", 50.0) > 70.0:
               return Signal(direction=-1, conviction=1.0, ref_price=self.price)
           return Signal(direction=0, conviction=0.0, ref_price=self.price)
   ```

3. Register the new strategy in `engine/services/strategy_seeder.py`. Append an entry to
   `DEFAULT_STRATEGIES` with the `name` matching `$ARGUMENTS` and a one-line `description`.
   The seeder is idempotent — upserts metadata into MongoDB `strategies` on every startup.

4. Restart the engine container (`docker-compose restart engine`) and verify the strategy
   metadata loads on the UI Strategies page.

5. **Gate:** run `/check-boundaries $ARGUMENTS` and
   `docker compose exec engine python -m pytest engine/tests/test_boundaries.py -q` — both must
   be clean. A strategy that reads position/balance state or writes order state is rejected
   here regardless of its backtest results.

6. Run a smoke backtest (any symbol/timeframe with candles) and confirm it completes with
   plausible trades.

7. Update documentation:
   - Create `workspace/docs/strategies/$ARGUMENTS.md` — follow the format of existing strategy docs.
   - Add a row to `workspace/docs/strategies/INDEX.md`.
   - Update `workspace/docs/state/CURRENT_STATE.md` — strategy list.

8. Run `/sync-spec`.

## Rules

- **Alpha predicts, nothing else** — `forecast()` returns a `Signal`; the strategy must never
  read `self.balance` / `self.equity` / `self.position` or write
  `self.buy` / `self.sell` / `self.stop_loss` / `self.take_profit` / `_pending_flip` /
  `_close_at_open`. Sizing → portfolio model; stops/TP/trailing → risk model; orders/flips →
  execution model. (`/check-boundaries` is the enforcement arm.)
- **No lookahead** — `prepare()` receives the FULL candle array including the future. Only use
  causal indicators indexed at `self.index`. For confirmation-lagged indicators (swing pivots
  with `right` bars, anything centered), read at the visibility horizon `i - right`, never at
  `i` — see how `MicroMacroRSIDivergence._last_two_visible` does it. A z-score/min-max over the
  whole series is lookahead. (Audit context: `workspace/plan/audit_2_quant-core.md` QNT-12.)
- **Compute once in `prepare()`, look up in `before()`** — never call `ta.*` per candle.
- **`MIN_WARMUP_CANDLES`** must cover the largest lookback any indicator needs (including
  derived windows like `atr_period * 2`); live readiness also depends on it (ENG-8: history is
  capped at 500 candles — a param that needs more than that will never become ready live).
- **Use `ta.*`** — route indicators through the provider layer; inline computation only for
  indicators not in the layer (then consider `/add-indicator`).
- **PARAMS descriptions** must state the effect of increasing/decreasing — the UI renders them.
