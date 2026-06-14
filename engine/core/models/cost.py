"""Default Transaction Cost Model — single owner of the platform's cost math.

Phase 2 (see plan.md) makes this model the one place that knows what a market
fill costs. It owns three things, all reading the same parameters the engines
already inject (``slippage_pct``, ``fee_rate``):

* **Realized mechanics** — ``adverse_fill`` (adverse slippage on a market fill
  price) and ``fee`` (taker fee on a notional). The backtest runner routes every
  one of its fills through these instead of computing them inline, so backtest,
  the cost *estimate*, and (later) live all share one implementation. Defaults
  are byte-identical to the runner's former inline arithmetic.
* **Predictive estimate** — ``estimate`` returns the fee + slippage + market
  impact a candidate ``Target`` is expected to incur, built from the same
  ``fee``/slippage rates so the prediction can never drift from the realized
  fill. ``impact_cost`` is a default-zero hook (linear ADV impact lands once
  volume is plumbed through).
* **Edge-vs-cost gate** — ``is_worth_it`` compares the trade's expected edge
  against ``cost.total``. The default is **permissive** (returns True, matching
  the legacy ``alpha_beats_cost`` stub) unless an opt-in ``min_edge_mult`` is
  set, so the default Cost Model changes no numbers. The gate is wired into the
  shared decision pipeline in Phase 5 (``pipeline.evaluate``); the runner's
  Phase-2 decision path is unchanged.
"""
from __future__ import annotations

from .base import CostModel, Cost, Signal, RiskFrame, Target


class DefaultCostModel(CostModel):

    # Opt-in edge-vs-cost gate strength. 0.0 ⇒ permissive (legacy behavior):
    # never veto. >0 ⇒ require expected edge ≥ min_edge_mult · estimated cost.
    min_edge_mult: float = 0.0

    # ── Realized fill mechanics (owned by the Cost Model) ────────────────────

    def adverse_fill(self, s, ref_price: float, side: str) -> float:
        """Adverse slippage on a market fill of ``ref_price``.

        A ``"buy"`` (long entry / short cover) fills *higher* — ``ref·(1+slip)``;
        a ``"sell"`` (short entry / long exit) fills *lower* — ``ref·(1-slip)``.
        ``slip`` is the strategy's ``slippage_pct`` (the runner mirrors its
        per-run ``_slippage`` onto the strategy), so this is byte-identical to
        the runner's former inline ``open_t * (1.0 ± _slippage)``.
        """
        slip = float(getattr(s, "slippage_pct", 0.0))
        if side == "buy":
            return ref_price * (1.0 + slip)
        return ref_price * (1.0 - slip)

    def fee(self, s, notional: float) -> float:
        """Taker fee on a market fill of ``notional`` (``notional·fee_rate``).

        Byte-identical to the runner's former inline ``notional * taker_fee``
        (the runner mirrors its ``taker_fee`` onto ``s.fee_rate``).
        """
        return notional * float(getattr(s, "fee_rate", 0.0))

    # ── Predictive cost estimate (consumed by the pipeline, Phase 5) ─────────

    def impact_cost(self, s, target: Target) -> float:
        """Market-impact term. Default 0.0 (linear ADV impact is opt-in until
        average-daily-volume data is plumbed through to the model)."""
        return 0.0

    def estimate(self, s, target: Target) -> Cost:
        """Expected cost of trading ``target``: fee + adverse slippage + impact,
        all in quote currency. Built from the same rates as the realized fill so
        prediction and execution can never diverge."""
        notional = abs(target.qty) * s.price
        slip = float(getattr(s, "slippage_pct", 0.0))
        return Cost(
            fee=self.fee(s, notional),
            slippage=notional * slip,
            impact=self.impact_cost(s, target),
        )

    # ── Edge-vs-cost gate ────────────────────────────────────────────────────

    def is_worth_it(self, s, sig: Signal, rf: RiskFrame, cost: Cost) -> bool:
        """True if expected edge justifies the estimated cost.

        Default permissive (== legacy ``alpha_beats_cost``: always trade) unless
        ``min_edge_mult`` is set. When enabled, the expected edge is the reward
        leg of the trade — ``conviction · risk_per_unit · rrr`` — and the trade
        passes only if that edge clears ``min_edge_mult`` times the total cost.
        """
        if self.min_edge_mult <= 0.0:
            return s.alpha_beats_cost(float(sig.direction))
        rrr = float(getattr(s, "rrr", 1.0))
        edge = abs(sig.conviction) * rf.risk_per_unit * rrr
        return edge >= self.min_edge_mult * cost.total and s.alpha_beats_cost(float(sig.direction))
