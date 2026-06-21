# Modular Merger Plan — Enma Execution Pipeline → Narang Strict Black-Box

**Status:** PROPOSAL — awaiting user approval. No source code has been changed.
**Author:** Claude (planning task, CLAUDE.md Rule D — docs only).
**Inputs:** `currentWorkflow.md` (as-built), `newGuide.md` (target boundaries), live engine source.
**Scope:** `engine/` decision layer only. Server/client/DB untouched except where noted (none required).

---

## 0. TL;DR

Enma **already has** a Five-Model pipeline (`engine/core/pipeline.py` + `engine/core/models/*`), but it
is a **hybrid**: the strategy (Alpha Model) still owns execution state. `go_long()`/`go_short()` compute
the stop, the take-profit, **and** the size, and write `self.buy`/`self.stop_loss`/`self.take_profit`;
`update_position()` owns trailing/breakeven/flip via `self.flip_position()`/`self._pending_flip`. The
Execution Model's `plan()` literally calls `s.go_long()` and reads `s.buy` back — so alpha, risk, sizing
and execution are all entangled inside the strategy class.

This plan refactors that into the **strict Narang boundary**:

- **Alpha** = strategy `forecast()` → emits `Signal(asset, direction, magnitude, conviction, timeframe)`.
  Reads candles + params only. Never touches equity/position/orders.
- **Risk** owns stop **and** take-profit placement, trailing/breakeven, and the drawdown breaker →
  `RiskConstraints`.
- **TCM** is purely descriptive → `CostEstimate` (no veto).
- **PCM** orchestrates: sizes against risk budget/conviction, applies the **edge-vs-friction veto**,
  and emits the signed `TargetPortfolio`.
- **Execution** is the only writer of order state; flips/closes are implicit from `target` vs
  `current_holding`. No `flip_position()`, no `_pending_flip` in strategies.

**Guiding constraint:** every change is gated by `engine/scripts/golden_master.py`. The refactor must be
**metric-identical** (byte-equivalent within `1e-6`) for all 5 seeded strategies on the fixed
2024 BTCUSDT/1h config. Behavior-changing features (continuous conviction, the cost veto) ship **off by
default** behind existing knobs so the golden master stays green.

---

## 1. Current State — Boundary Violations (the "as-is")

Grounded in the actual source (not just `currentWorkflow.md`). The background `drift-reviewer` audit
enumerates these at `file:line`; the structural summary:

| # | Violation | Where | Narang rule broken |
|---|-----------|-------|--------------------|
| V1 | `go_long()/go_short()` set `self.buy/sell`, `self.stop_loss`, `self.take_profit` | all 5 strategies | Alpha sets orders + stops |
| V2 | `go_long()/go_short()` call `size_by_risk()`/`size_by_notional()` → read `self.equity` | all 5 strategies | Alpha reads account / sizes |
| V3 | Stop placement (`atr_stop`, fixed-% SL) computed inside the strategy | MicroScalper, AdaptiveTrend, MicroMacroRSI, MultiDivergence | Risk logic in Alpha |
| V4 | Take-profit (`rr_target`, `tp_atr_mult`) computed inside the strategy | MicroScalper, MicroMacroRSI, MultiDivergence, AdaptiveTrend | Risk logic in Alpha |
| V5 | Trailing stop / breakeven (`trail_stop`, chandelier, `move_to_breakeven`) in `update_position()` | AdaptiveTrend, BaseStrategy helpers | Risk logic in Alpha |
| V6 | Atomic flip via `self.flip_position()` / `self._pending_flip` | MicroScalper, BestSupertrend | Execution logic in Alpha |
| V7 | Early/structural exit via `self.close_position()` / `self.liquidate()` | MicroMacroRSI, BestSupertrend | Alpha mutating execution state |
| V8 | `DefaultExecution.plan()` calls `s.go_long()`/`s.go_short()` and reads `s.buy` | `models/execution.py:75` | Alpha+sizing leak into Execution |
| V9 | `is_worth_it()` (a **decision/veto**) lives in the **Cost** Model | `models/cost.py:80` | TCM must be descriptive only |
| V10 | `evaluate(s)` runs the pipeline **only when flat**; flips come from `update_position()` | `pipeline.py:15` | Pipeline should run every candle; flips implicit |
| V11 | Data types lag the guide: `Signal(direction, conviction, ref_price)`, `RiskFrame`, `Cost`, `Target` | `models/base.py` | Type contract drift |

The pipeline plumbing (`risk_model`/`cost_model`/`portfolio_model`/`execution_model` slots, the value
objects, the `DefaultExecution.entry_fill`/`exit_fill` fill mechanics, the `update_session_risk` drawdown
owner) is **already correct and reusable** — we keep it. The refactor is about **moving logic across the
already-drawn boundaries**, not rebuilding them.

---

## 2. Architectural Decisions & Trade-offs

These are the consequential calls. Each lists the decision, the alternative, and why.

### D1 — The runner stays the "matching engine"; the 5 models stay the "decision layer"

`newGuide.md` §"Decoupled Position Management" suggests `ExecutionModel.route` itself compares price to the
stop and triggers exits. Taken literally that moves the runner's liquidation→SL→TP exit ladder (and the
live `_check_exits`) **into** the Execution Model.

- **Decision:** Do **not** move fill simulation / exit detection into the models. Treat
  `backtest_runner.py` and `live_bot_manager.py` as the **exchange simulant** (the thing that fills orders
  and trips brackets). The 5 models remain the **pre-trade decision layer**. The Execution Model becomes
  the **sole writer** of the order-state fields (`buy/sell/stop_loss/take_profit/_pending_flip/_close_at_open`);
  the runner remains the **sole reader/filler** of them, unchanged.
- **Alternative:** Push SL/TP/liquidation matching into Execution. **Rejected:** it rewrites the proven,
  golden-mastered fill loop (isolated-margin liquidation-before-SL, adverse slippage, funding, MFE/MAE)
  for zero behavioral gain and high regression risk.
- **Trade-off:** A purist could call the runner a "sixth concern." We document it explicitly as the
  execution *venue*, not a model. This is the standard Narang deployment shape (models decide; the
  OMS/exchange fills).

### D2 — Strategy params stay where they are; Risk/Portfolio models **read** them off `s`

`sl_atr_mult`, `tp_atr_mult`, `position_size_pct`, `custom_sl_pct`, `trail_atr_mult`, `breakeven_r`, etc.
are today Alpha `PARAMS` (UI-exposed, clamped, injected by the runner).

- **Decision:** Leave them as `PARAMS` on the strategy instance. The Risk/Portfolio models receive `s` and
  read `s.sl_atr_mult` etc. Reading a volatility/stop **parameter** off the strategy is inside the Risk
  Model's boundary; the violated boundary was the Alpha *computing the stop and writing the order*, which we
  remove. **No UI change, no `PARAMS` migration, no server `risk.js` change.**
- **Alternative:** Relocate every stop/TP param into the `riskParams` dict (server `resolveModelParams`,
  `RiskParamsFields.jsx`, Mongo). **Rejected for now:** large cross-service blast radius (client + server +
  schema) for an internal refactor; can be a later "risk param surfacing" task.
- **Trade-off:** Params are physically declared on the Alpha class but semantically consumed by Risk. We
  annotate each such param `# consumed by <Model>` and add a boundary note. Acceptable.

### D3 — Per-strategy behavior preserved via **paired, configurable model classes** (not one mega-model)

The 5 strategies have genuinely different risk/sizing shapes (ATR stop + RR TP; chandelier trailing;
notional %; fixed-% SL; signal-only exit with no stop). A single `DefaultRiskModel` cannot reproduce all 5
byte-for-byte.

- **Decision:** Provide a **small library of composable model variants** and bind each strategy to the one
  matching its current math. They live in `engine/core/models/` (shared) and are selected by the strategy
  via class attributes (`risk_model_cls` / `portfolio_model_cls`) or by overriding in `__init__`. Proposed
  variants:
  - `AtrBracketRiskModel` — ATR stop (`sl_atr_mult`) + optional RR/ATR take-profit. Covers MicroScalper,
    MicroMacroRSIDivergence, MultiDivergence (with a `fixed_pct` stop mode for `use_custom_sl`).
  - `ChandelierRiskModel` — initial ATR stop + chandelier trailing + breakeven-at-R + optional fixed TP.
    Covers AdaptiveTrend (subsumes `update_position`’s trailing).
  - `SignalExitRiskModel` — no protective stop/TP; exits are alpha-driven (thesis flip). Covers
    BestSupertrend.
  - `RiskBudgetPortfolio` — `size_by_risk(stop) × conviction`, leverage-capped. Default; covers 4 of 5.
  - `NotionalPortfolio` — `size_by_notional(pct)`. Covers BestSupertrend (and AdaptiveTrend's
    `max_leverage` notional cap as an option).
- **Alternative A:** One parametric `DefaultRiskModel` with mode flags. **Rejected:** becomes a god-object
  of `if strategy_is_X` branches — exactly the coupling we're removing.
- **Alternative B:** A risk/portfolio file inside each strategy package. **Rejected:** 10 new files, and the
  variants are 90% shared. Composable shared variants is the Narang-idiomatic "modeler picks a risk module."
- **Trade-off:** ~5 new small classes vs perfect behavior fidelity + clean boundaries. Worth it.

### D4 — Conviction & magnitude are **real but inert** in phase 1

`Signal` gains `magnitude` (predicted move, decimal %) and continuous `conviction`. But:
- **Magnitude** only feeds the PCM **edge-vs-cost veto**, which is gated by `min_edge_mult` (default `0.0` ⇒
  veto off). So magnitude is computed honestly but **changes no metrics** at default settings.
- **Conviction** stays `1.0` for the golden-master phase (continuous conviction would rescale `qty` and
  break metric identity). A documented continuous formula per strategy ships **commented/opt-in** and is
  validated as a separate, explicitly behavior-changing follow-up.
- **Decision:** Ship the *contract* (the fields, the veto wiring) in the refactor; ship the *behavior*
  (continuous conviction, `min_edge_mult>0` tuning) as a later opt-in. Golden master stays green.
- **Trade-off:** The "predictive magnitude/conviction" the prompt asks for is fully *expressed* but
  deliberately not yet *acted upon* in sizing, so the regression gate holds. This is called out loudly so it
  isn't mistaken for a no-op.

### D5 — Flips & closes become implicit from `target` vs `current_holding`

`evaluate(s, current_holding)` runs **every candle**. The Execution Model diffs the desired `TargetPortfolio.qty`
(signed) against `current_holding` and writes exactly one of: a new entry, a flip (`_pending_flip`), a full
close (`_close_at_open`), a stop/TP bracket update, or nothing. Strategies no longer call `flip_position()`,
`close_position()`, or `liquidate()`. The runner's existing A0 (flip) / A1 (close) / A2 (entry) blocks and
the live `_execute_flip`/`_close_position` consume those fields **unchanged** — Execution just becomes their
author instead of the strategy.

- **Trade-off:** This is the highest-risk change for golden-master identity (the *timing* of writes must match
  the old `update_position`/`go_long` ordering exactly). Mitigated by D1 (same fields, same runner) and by a
  per-strategy golden run after each strategy is ported.

---

## 3. Target Data Types — `engine/core/models/base.py`

Rename + extend to match `newGuide.md`. Keep **transitional aliases** so the runner/imports don't break
mid-refactor (removed in the final cleanup phase).

```python
@dataclass
class Signal:                       # Alpha output — candles in, prediction out
    asset: str = ""                 # s.symbol
    direction: int = 0              # +1 / -1 / 0
    magnitude: float = 0.0          # predicted move, decimal % (e.g. 0.02). NEW
    conviction: float = 1.0         # [0,1]; 1.0 == legacy boolean
    timeframe: str = ""             # s.timeframe. NEW
    ref_price: float = 0.0          # kept (entry reference; internal, not in guide)
    @property
    def flat(self) -> bool: return self.direction == 0

@dataclass
class RiskConstraints:              # was RiskFrame
    vetoed: bool = False            # kept: max_drawdown_hit OR invalid stop
    max_drawdown_hit: bool = False  # NEW explicit breaker flag (guide)
    stop_price: float | None = None
    take_profit_price: float | None = None   # NEW — TP now owned by Risk (guide)
    risk_per_unit: float = 0.0
    budget: float = 0.0
    max_notional: float = 0.0       # == max_position_size notional cap

@dataclass
class CostEstimate:                 # was Cost
    fee: float = 0.0
    slippage: float = 0.0
    impact: float = 0.0
    @property
    def total(self) -> float: return self.fee + self.slippage + self.impact

@dataclass
class TargetPortfolio:              # was Target
    asset: str = ""
    qty: float = 0.0                # SIGNED: + long, - short, 0 flat
    weight: float = 0.0

@dataclass
class OrderPlan:                    # unchanged shape; direction now derived from target sign
    direction: int
    qty: float
    entry_price: float
    stop_loss: float | None = None
    take_profit: float | None = None
    order_type: str = "market"
```

Keep `EntryFill`/`ExitFill` as-is (they're fill mechanics, used by the runner). Add module-level aliases for
one phase: `RiskFrame = RiskConstraints`, `Cost = CostEstimate`, `Target = TargetPortfolio`.

**ABC method renames** (to the guide's verbs), with old names kept as thin deprecated shims for one phase:

| Old | New (guide) | Owner |
|-----|-------------|-------|
| `RiskModel.frame(s, sig)` | `RiskModel.assess(s, sig, current_holding)` | Risk |
| `CostModel.estimate(s, target)` | `TransactionCostModel.estimate(s, sig, constraints)` | TCM (descriptive) |
| `CostModel.is_worth_it(...)` | **moves to** `PortfolioModel.construct(...)` | PCM (decision) |
| `PortfolioModel.size(s, sig, rf)` | `PortfolioModel.construct(s, sig, constraints, cost, current_holding)` | PCM |
| `ExecutionModel.plan(s, sig, target, rf)` | `ExecutionModel.route(s, target, current_holding, constraints)` | Execution |

---

## 4. The Pipeline — `engine/core/pipeline.py`

Replace the flat-only branch with the guide's every-candle dataflow:

```python
def evaluate(s, current_holding: float = 0.0) -> OrderPlan | None:
    sig = s.alpha_model.forecast(s)                      # 1 ALPHA  (s.forecast(); see §6)
    constraints = s.risk_model.assess(s, sig, current_holding)   # 2 RISK (stop/TP/trail/breaker)
    if constraints.max_drawdown_hit:
        sig = Signal(asset=sig.asset, direction=0, timeframe=sig.timeframe)  # force flat
    cost = s.tcm_model.estimate(s, sig, constraints)     # 3 TCM   (descriptive only)
    target = s.pcm_model.construct(s, sig, constraints, cost, current_holding)  # 4 PCM (+veto)
    return s.execution_model.route(s, target, current_holding, constraints)     # 5 EXEC
```

- `s.alpha_model` defaults to the strategy itself (`s.alpha_model = self` in `BaseStrategy.__init__`),
  preserving "strategy *is* the Alpha" while giving the pipeline the guide's attribute name.
- `s.tcm_model` is the renamed cost-model slot; `s.pcm_model` the portfolio slot (aliases kept one phase:
  `s.cost_model`, `s.portfolio_model`).
- **Trailing while holding:** `assess()` recomputes the (only-tightening) stop from current price every
  candle and returns it in `constraints.stop_price`; `route()` writes it to `s.stop_loss`. This *is* the old
  `trail_stop`/chandelier, relocated.
- **Drawdown breaker while holding:** `max_drawdown_hit` → `sig` forced flat → PCM targets `0` → Execution
  schedules a close. (Today the breaker only blocks *new* entries; forcing-flat-while-open is a **behavior
  change** — see §8 Risk R3. Default `max_session_dd=0.20`; to stay golden-master-identical we keep the
  *current* semantics, "breaker halts new entries only," in phase 1 and gate force-exit behind an opt-in
  flag.)

---

## 5. Strict Module Implementations — `engine/core/models/`

### 5.1 Risk — `risk.py`

`DefaultRiskModel` keeps the inherited owners (`update_session_risk`, `atr_stop`, `risk_budget_qty`,
`respects_liq_buffer`) and implements `assess()`:

```python
def assess(self, s, sig, current_holding=0.0) -> RiskConstraints:
    breaker = not self.can_trade(s)                 # session_drawdown >= max_session_dd
    if sig.flat and current_holding == 0:
        return RiskConstraints(vetoed=True, max_drawdown_hit=breaker)
    direction = "long" if (current_holding > 0 or sig.direction > 0) else "short"
    stop = self.stop_price(s, direction, current_holding)   # initial OR trailing (only tightens)
    tp   = self.take_profit_price(s, direction, stop)
    rpu  = abs(s.price - stop) if stop is not None else 0.0
    return RiskConstraints(
        vetoed=breaker or rpu <= 0, max_drawdown_hit=breaker,
        stop_price=stop, take_profit_price=tp, risk_per_unit=rpu,
        budget=s.equity * s.risk_pct, max_notional=s.equity * max(s.leverage, 1),
    )
```

- **`AtrBracketRiskModel(DefaultRiskModel)`** — `stop_price` = `entry ∓ sl_atr_mult·ATR` (or `entry·(1±custom_sl_pct/100)`
  when `s.use_custom_sl`); `take_profit_price` = `rr_target(rrr)` or `entry ± tp_atr_mult·ATR` per the
  strategy's current formula. When `current_holding != 0` it returns the **stored** entry-time bracket
  (static), reproducing today's "set once in go_long" behavior.
- **`ChandelierRiskModel(DefaultRiskModel)`** — initial stop = `sl_atr_mult·ATR`; while holding, stop =
  `max(stored, extreme − trail_atr_mult·ATR)` (mirror for short), with breakeven-at-`breakeven_r·R`, and TP
  only if `tp_r_mult>0`. This is AdaptiveTrend's `update_position` relocated verbatim. Per-trade state
  (`_extreme`, `_entry_price`, `_initial_risk`, `_current_stop`) moves onto the model (or a `s.vars` slot
  the model owns), set on the open via `on_open_position`/first holding tick.
- **`SignalExitRiskModel(DefaultRiskModel)`** — `stop_price=None`, `take_profit_price=None`, `vetoed` only on
  the drawdown breaker. BestSupertrend has no bracket; exits are alpha-driven.

### 5.2 TCM — `cost.py` (descriptive only)

Keep `adverse_fill`, `fee`, `impact_cost`, `estimate` (signature → `estimate(s, sig, constraints)`).
**Delete `is_worth_it` from the Cost Model** (V9). Rename class `DefaultCostModel → DefaultTransactionCostModel`
(alias kept). The realized-fill helpers (`adverse_fill`/`fee`) stay — they are the cost *owner* the runner and
Execution compose; that is descriptive, not a decision.

### 5.3 PCM — `portfolio.py` (orchestrator + the veto)

```python
def construct(self, s, sig, constraints, cost, current_holding=0.0) -> TargetPortfolio:
    if constraints.vetoed or sig.flat:
        return TargetPortfolio(asset=s.symbol, qty=0.0, weight=0.0)   # flat target
    qty = self.size(s, sig, constraints)                              # risk-budget or notional
    if not self._edge_beats_cost(s, sig, constraints, cost):          # V9 veto, relocated from TCM
        return TargetPortfolio(asset=s.symbol, qty=0.0, weight=0.0)
    qty *= sig.direction                                              # SIGN the target
    return TargetPortfolio(asset=s.symbol, qty=qty, weight=(abs(qty)*s.price)/s.equity)

def _edge_beats_cost(self, s, sig, constraints, cost) -> bool:
    if s.tcm_model.min_edge_mult <= 0.0:
        return True                                                   # default: no veto (golden-master)
    edge = sig.magnitude * sig.conviction * s.price                   # guide's expected-alpha-return
    return edge >= s.tcm_model.min_edge_mult * cost.total
```

- `RiskBudgetPortfolio.size` = `size_by_risk(constraints.stop_price) × clamp(conviction,0,1)` (default).
- `NotionalPortfolio.size` = `size_by_notional(s.position_size_pct)` (BestSupertrend).
- `allocate()` (cross-symbol split) stays unchanged.
- `min_edge_mult` continues to live on the TCM instance (it's a cost-hurdle knob), but the **comparison/veto
  decision** is now in PCM — boundary corrected.

### 5.4 Execution — `execution.py` (sole order-state writer; flips implicit)

```python
def route(self, s, target, current_holding=0.0, constraints=None) -> OrderPlan | None:
    desired = target.qty                      # signed
    sl = constraints.stop_price if constraints else None
    tp = constraints.take_profit_price if constraints else None

    # 1. Flat → flat: nothing
    if current_holding == 0 and desired == 0:
        return None
    # 2. Flat → open: write entry bracket (replaces go_long/go_short writes)
    if current_holding == 0 and desired != 0:
        d = 1 if desired > 0 else -1
        if d > 0: s.buy = abs(desired), s.price
        else:     s.sell = abs(desired), s.price
        s.stop_loss   = (abs(desired), sl) if sl is not None else None
        s.take_profit = (abs(desired), tp) if tp is not None else None
        return OrderPlan(d, abs(desired), s.price, sl, tp, getattr(s, "order_type", "market"))
    # 3. Holding, target flips sign → atomic flip (replaces flip_position)
    if current_holding != 0 and desired != 0 and (current_holding > 0) != (desired > 0):
        s._pending_flip = {"direction": "long" if desired > 0 else "short",
                           "qty": abs(desired), "stop_loss": sl, "take_profit": tp}
        return None
    # 4. Holding, target → 0 → close (replaces close_position/liquidate)
    if current_holding != 0 and desired == 0:
        s._close_at_open = True
        return None
    # 5. Holding, same side → bracket maintenance (trailing): update stop/TP only
    if sl is not None: s.stop_loss = (abs(current_holding), sl)
    if tp is not None: s.take_profit = (abs(current_holding), tp)
    return None
```

`BacktestExecution`/`LiveExecution` keep their fill helpers (`entry_fill`/`exit_fill`/`exit_fee`) untouched.
`route()` replaces `plan()` (alias kept one phase). **No strategy method is called from Execution anymore**
(V8 fixed).

---

## 6. Decoupling the 5 Strategies (prompt point 3)

Each strategy keeps `before()` (indicator caching — already boundary-clean, reads candles only) and its
internal `should_long/should_short` **as private predicates**. It **gains** a real `forecast()` and **loses**
`go_long`, `go_short`, `update_position`, and every `self.buy/sell/stop_loss/take_profit/flip_position/
close_position/liquidate` write. `BaseStrategy.go_long/go_short` drop their `@abstractmethod` status (kept as
no-op deprecated shims one phase so nothing breaks before all 5 are ported).

Binding pattern per strategy (set in `__init__`):
```python
self.risk_model      = <Variant>RiskModel()
self.pcm_model       = <Variant>Portfolio()      # alias of portfolio_model
self.alpha_model     = self
```

### 6.1 MicroScalper
- **forecast():** `_crossed_above()/_below()` + `_is_volatile()` → direction. **magnitude** =
  `tp_atr_mult·ATR / price`. conviction = 1.0 (opt-in: scale by `atr/atr_baseline`).
- **Risk:** `AtrBracketRiskModel` (stop `sl_atr_mult·ATR`, TP `tp_atr_mult·ATR`). **Portfolio:** `RiskBudgetPortfolio`.
- **Flip:** today `update_position()` flips on opposite crossover. Now `forecast()` simply returns the
  **opposite direction** on that crossover (it already detects it); Execution sees `target` sign flip vs
  `current_holding` → schedules the flip. `update_position` deleted. ✅ stop-and-reverse preserved.

### 6.2 AdaptiveTrend
- **forecast():** 4-layer agreement (`_uptrend/_downtrend`, `_cross_up/_down`, `_is_alive`) → direction;
  `allow_shorts` gate stays. **magnitude** = `(tp_r_mult or trail_atr_mult)·risk_per_unit / price`.
- **Risk:** `ChandelierRiskModel` — absorbs `update_position()`’s chandelier trail + breakeven + optional
  fixed TP, and the `_position_qty` leverage cap (`max_leverage`) moves to the Portfolio model's notional cap.
- **Portfolio:** `RiskBudgetPortfolio` with `max_leverage` cap (the `min(qty, lev_cap, max_qty)` logic).
- **No flip** (trend follower exits via stop); `update_position` deleted, trailing now in Risk.assess every candle.

### 6.3 BestSupertrend
- **forecast():** `_evaluate_signals()` → `bull/bear` for entries; **and** the exit crossovers
  (`long_exit/short_exit`) now map to a **flat-or-flip forecast** while holding: if long and `long_exit` →
  forecast flat (or short if `bear` and shorts allowed) → Execution closes/flips. **magnitude** = small
  fixed proxy (e.g. `0.0`/ATR-based) since the original has no target; conviction 1.0.
- **Risk:** `SignalExitRiskModel` (no bracket). **Portfolio:** `NotionalPortfolio(position_size_pct)`.
- **Replaces:** `flip_position()` and `liquidate()` (V6/V7) with implicit target changes. `update_position` deleted.

### 6.4 MicroMacroRSIDivergence
- **forecast():** `_confluent_long/_short()` → direction; **opposite-divergence early exit**
  (`exit_on_opposite`) becomes: while holding, if opposite confluence fires → forecast flat → Execution
  closes (replaces `close_position()`, V7). **magnitude** = `rrr·sl_atr_mult·ATR / price`. conviction 1.0
  (opt-in: scale by RSI-divergence size).
- **Risk:** `AtrBracketRiskModel` (ATR stop + `rr_target(rrr)` TP). **Portfolio:** `RiskBudgetPortfolio`.

### 6.5 MultiDivergence
- **forecast():** existing `before()` already computes `self.vars["signal"]` ∈ {-1,0,+1} and vote counts;
  `forecast()` returns that direction. **magnitude** = `tp_atr_mult·ATR / price`. **conviction** (natural
  fit, opt-in) = `bull_votes / enabled_sources`. Default 1.0 for golden master.
- **Risk:** `AtrBracketRiskModel` with `fixed_pct` mode when `use_custom_sl` (stop `custom_sl_pct`), TP
  `tp_atr_mult·ATR`. **Portfolio:** `RiskBudgetPortfolio`. No flip/early-exit (static SL/TP) — unchanged.

**Net per strategy:** delete `go_long`/`go_short`/`update_position`; add `forecast()`; bind 2 model classes.
Indicator math, pivots, divergence logic, params — all untouched.

---

## 7. Runner Integration (prompt point 5)

### 7.1 `engine/services/backtest_runner.py`
- **Step C (line ~747-751):** replace the `before(); evaluate(strategy); after()` block. Compute
  `current_holding = strategy.position.qty * (1 if long else -1) if position else 0.0`. Call
  `evaluate(strategy, current_holding)` **every candle** (not only when flat). The returned `OrderPlan` is
  informational; the **side effects** (`route()` writing `buy/sell/stop_loss/take_profit/_pending_flip/
  _close_at_open`) are what the existing A0/A1/A2 blocks on the *next* iteration consume.
- **Step 6 init:** set `strategy.risk_model`/`pcm_model`/`execution_model` (already does the latter via
  `BacktestExecution()`); strategies self-bind their Risk/Portfolio variants in `__init__`, so the runner
  only needs to keep injecting `BacktestExecution` and the risk params.
- **A0/A1/A2/B blocks:** **unchanged** — they already read `_pending_flip`, `_close_at_open`, `buy`, `sell`,
  `stop_loss`, `take_profit`. This is the whole point of D1/D5: same fields, new author.
- **`should_cancel_entry`** (A2): unchanged (still a strategy hook reading candles).

### 7.2 `engine/core/live_bot_manager.py`
- **`_run_symbol_loop` (line ~351-366):** replace the `if position is None: evaluate else update_position`
  branch with a single `current_holding`-aware call:
  ```python
  strategy.before()
  current_holding = (strategy.position.qty * (1 if strategy.is_long else -1)) if strategy.position else 0.0
  if strategy.position is not None:
      strategy.position.update_pnl(strategy.price)
      await self._check_exits(...)                       # unchanged bracket detection
  plan = evaluate(strategy, current_holding)             # every candle
  if strategy.position is None and plan is not None:
      await self._execute_entry(..., plan)
  elif strategy.has_pending_flip:
      await self._execute_flip(...)                      # unchanged
  elif strategy._close_at_open:                          # NEW: honor alpha-driven close live
      strategy._close_at_open = False
      await self._close_position(..., "strategy_exit")
  strategy.after()
  ```
- `_execute_entry`, `_execute_flip`, `_check_exits`, `_close_position` — **unchanged** (read the same
  fields). Trailing-stop updates now arrive via `route()` writing `strategy.stop_loss`, which
  `_execute_entry`/Binance bracket placement already reads. **Note (R4):** live currently places the SL/TP
  bracket on Binance at entry and does not re-arm a trailing stop on the exchange — relocating trailing into
  `assess()` makes the *intent* live, but exchange re-arming of a moved stop is an existing gap, not created
  here; flagged for the live-trailing follow-up.

---

## 8. Risks & Mitigations

| ID | Risk | Mitigation |
|----|------|-----------|
| R1 | Flip/close **write timing** differs from old `update_position`, shifting a fill by one candle → metric drift | Port one strategy at a time; run `golden_master compare` per strategy; the A0/A1/A2 blocks are unchanged so only the *author* of the fields moves, not the consume order |
| R2 | `evaluate` now runs while holding → could place a second entry | `route()` step 2 only fires when `current_holding == 0`; holding paths only update brackets / flip / close |
| R3 | Forcing flat on drawdown breaker while holding is a behavior change | Phase 1 keeps "breaker blocks new entries only" (don't force-exit); force-exit behind opt-in flag, validated separately |
| R4 | Live trailing stop intent not re-armed on Binance | Out of scope for parity; documented as pre-existing; covered by the live-trailing follow-up task |
| R5 | Continuous conviction would rescale qty | Conviction pinned to 1.0 in phase 1; magnitude inert unless `min_edge_mult>0` |
| R6 | Import-root duality (`engine.` vs top-level) for new classes | Mirror the existing dual-import shim used in `strategy.py`/`risk.py` |

---

## 9. Verification (prompt point 6)

Golden master is the gate (CLAUDE.md Rule C — this touches >3 files + the data pipeline).

1. **Baseline (before any change):**
   `docker compose exec engine python -m scripts.golden_master run --label baseline`
   (writes `engine/scripts/golden/baseline.json` for all 5 strategies on fixed 2024 BTCUSDT/1h).
2. **Per phase / per strategy:** after porting strategy X, re-run `--label <phaseN>` and
   `compare --a baseline --b <phaseN>` → **must exit 0** (`tol=1e-6`). A non-zero exit blocks the phase.
3. **Pipeline/contract phases** (data types, pipeline, models — no strategy ported yet): run the existing
   `engine/scripts/_phase_smoke.py` + golden master; both must stay green.
4. **`/verify` skill** (manual end-to-end): after the engine is green, run `/verify` to launch the app and
   confirm a real backtest completes and a live (testnet) session opens/holds/closes a position with the
   same UI numbers (emerald-400 P&L styling intact).
5. **New boundary test** (`engine/tests/test_boundaries.py`, see §10): static assertion that strategy
   modules never reference `self.balance/equity/position/buy/sell/stop_loss/take_profit` and define no
   `go_long/go_short` — a permanent regression guard for the Alpha boundary.
6. **Drift sweep:** `drift-reviewer` subagent re-run at the end; then `/sync-spec` to update
   `currentWorkflow.md`, `CURRENT_STATE.md`, `API_CONTRACTS.md`, `DECISIONS.md`.

**Done = ** golden master byte-identical for all 5 + boundary test green + `/verify` clean + `/sync-spec`
reports zero drift.

---

## 10. New Skills (prompt — "create skills for recurring tasks")

Proposed (created on approval, under `.claude/commands/`):
- **`/golden-check`** — wraps the 3-step golden-master baseline→run→compare loop (the Rule-C ritual we'll run
  dozens of times this refactor and on every future pipeline change). High recurrence → justified.
- **`/check-boundaries`** — runs the §9.5 boundary test + a grep for forbidden Alpha-side references across
  `engine/strategies/*`; the enforcement arm of this whole effort and of every future strategy added via
  `/add-strategy`.

Both are validation tasks (Rule D: no code stubs), so they're shell+assertion wrappers, not scaffolds. Not
created in this planning task — listed for approval.

---

## 11. Phased Rollout (each phase = one golden-master gate + a `handoff.md` write — Rule G)

| Phase | Change | Files | Gate |
|-------|--------|-------|------|
| 0 | Capture golden baseline; add boundary test (currently passes only after ports) | `scripts/golden/`, `tests/` | baseline.json written |
| 1 | Data types: rename+extend, add aliases | `models/base.py`, `models/__init__.py` | smoke + golden green |
| 2 | Models: `assess/route/construct`, move veto to PCM, add 3 Risk + 2 Portfolio variants, drop `is_worth_it` | `models/{risk,cost,portfolio,execution}.py` | smoke green (no strategy ported yet) |
| 3 | Pipeline: `evaluate(s, current_holding)` every candle; `s.alpha_model=self` | `pipeline.py`, `strategy.py` | golden green (strategies still use legacy shims) |
| 4 | Runners: `current_holding` wiring + live `_close_at_open` | `backtest_runner.py`, `live_bot_manager.py` | golden green |
| 5a–5e | Port strategies one-by-one (MicroScalper → MultiDivergence): add `forecast()`, bind models, delete `go_long/go_short/update_position` | `strategies/*/__init__.py` | **golden compare per strategy = exit 0** |
| 6 | Remove transitional aliases + deprecated shims; final drift sweep; `/sync-spec` | `models/*`, `strategy.py`, docs | golden + boundary + `/verify` + zero drift |

---

## 12. Invariants Preserved (explicit checklist)

- **Single-user:** no `user_id` introduced anywhere. ✅ (engine-internal only)
- **Testnet-only / no `ccxt`:** no Binance call paths touched; `binance_testnet.py` untouched. ✅
- **P&L colors `emerald-400`/`red-400`:** no client changes. ✅
- **`ENMA_INDICATOR_LIBRARY`:** strategies still import `engine.indicators` only; no direct TA-Lib. ✅
- **Candle layout `[ts,open,close,high,low,vol]`, next-open fills, liq-before-SL, atomic-flip semantics,
  warmup, funding, equity downsample, batch insert, TimescaleDB ownership, symbol lock, no Redux** — all
  governed by the unchanged runner/live-manager and runner-owned fill loop. ✅
- **Rule #6 risk sizing** `qty=(equity·risk_pct)/|entry−stop|` — preserved exactly (now invoked by
  `RiskBudgetPortfolio` instead of `go_long`). ✅

---

## Appendix A — File-by-File Change Map

**Create:**
- `engine/core/models/risk.py` → add `AtrBracketRiskModel`, `ChandelierRiskModel`, `SignalExitRiskModel`
  (alongside `DefaultRiskModel`).
- `engine/core/models/portfolio.py` → add `RiskBudgetPortfolio`, `NotionalPortfolio` (rename current
  `DefaultPortfolioModel.size` logic into `RiskBudgetPortfolio`).
- `engine/tests/test_boundaries.py` → Alpha-boundary regression guard.
- `.claude/commands/golden-check.md`, `.claude/commands/check-boundaries.md` (on approval).

**Edit:**
- `engine/core/models/base.py` — rename/extend value objects + ABC method names (+ aliases).
- `engine/core/models/cost.py` — drop `is_worth_it`; rename class; `estimate(s, sig, constraints)`.
- `engine/core/models/execution.py` — `route()` replaces `plan()`; sole order-state writer.
- `engine/core/models/__init__.py` — export new names + aliases.
- `engine/core/pipeline.py` — every-candle `evaluate(s, current_holding)`.
- `engine/core/strategy.py` — `alpha_model=self`; demote `go_long/go_short` from abstract to shim; move
  `trail_stop`/`move_to_breakeven`/`flip_position` helpers toward the Risk/Execution models (keep shims one phase).
- `engine/services/backtest_runner.py` — Step C `current_holding` wiring (A0/A1/A2/B unchanged).
- `engine/core/live_bot_manager.py` — `_run_symbol_loop` `current_holding` wiring + live `_close_at_open`.
- `engine/strategies/*/__init__.py` (×5) — `forecast()` in, `go_long/go_short/update_position` out, bind models.

**Untouched (verified):** `position.py`, `margin.py`, `candle_manager.py`, `candle_importer.py`,
`binance_testnet.py`, `indicators/*`, all of `server/`, all of `client/`, all DB schemas.

---

## Appendix C — `drift-reviewer` Audit Confirmation

A read-only `drift-reviewer` subagent audited the current code against `newGuide.md`. It **confirms** this
plan's diagnosis (60+ concrete violations across all 5 boundaries + pervasive type drift) and the same fix
priority: (1) sizing out of Alpha/Risk → PCM; (2) cost veto out of TCM → PCM; (3) `current_holding` +
target-diff so flips/closes/trailing are Risk-emitted and Execution-routed (delete `_pending_flip`/
`_close_at_open`/`flip_position`/`update_position` from strategies); (4) rename/extend value objects.

**One refinement folded in (D6):** the audit flags that **sizing math itself** (`RiskModel.risk_budget_qty`,
`base.py:172-185`) physically lives in the **Risk** model, whereas `newGuide.md` (lines 36-42) makes sizing a
**PCM** responsibility — Risk should emit only the `max_position_size`/`budget` *constraint*.
- **Decision (D6):** In §5.3, `RiskBudgetPortfolio.size` performs the division itself —
  `qty = constraints.budget / constraints.risk_per_unit`, capped by `constraints.max_notional/price` — reading
  the *constraints* Risk emits rather than calling back into `risk_model.risk_budget_qty`. `risk_budget_qty`
  is kept one phase as a deprecated shim (`BaseStrategy.size_by_risk` still delegates to it for the
  legacy-shim window), then removed in Phase 6. This puts the division on the correct side of the boundary
  while staying golden-master-identical (same formula, same inputs).

## Appendix B — Resolved Decisions (user-approved 2026-06-21)

1. **D2 scope:** ✅ **Keep stop/TP params on the Alpha class** — Risk/Portfolio models read them off `s`. No
   client/server/schema change.
2. **D4 conviction:** ✅ **Defer — pin conviction = 1.0** for the refactor (golden-master-identical).
   Continuous conviction is a later, separately-validated behavior change.
3. **R3 drawdown breaker:** ✅ **Halt new entries only** (current semantics, golden-master-identical).
   Force-flat-on-breaker ships behind an opt-in flag, not on by default.
4. **Skills:** ✅ **Approved** — `/golden-check` and `/check-boundaries` created in `.claude/commands/`
   (validation tooling, created ahead of the refactor; the engine source refactor still awaits go-ahead).

These four answers lock the plan to the **golden-master-identical** path: every phase must
`compare → exit 0`. No metric-changing behavior (continuous conviction, cost veto, force-exit) is enabled by
default in this effort.
