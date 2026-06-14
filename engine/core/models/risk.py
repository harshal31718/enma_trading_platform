"""Default Risk Model — legacy-equivalent.

Owns the platform's risk math: the drawdown circuit breaker (``can_trade``),
session-equity tracking, ATR stop placement and risk-budget sizing (inherited
from the ``RiskModel`` base), plus the liquidation-buffer rule. ``frame`` builds
the authoritative risk envelope for the shared decision pipeline; today each
strategy still computes its own stop inside go_long()/go_short(), so the runner
path is unchanged — ``frame`` and ``respects_liq_buffer`` are the forward-looking
defaults the pipeline (Phase 5) and execution (Phase 4) consume.
"""
from __future__ import annotations

from .base import RiskModel, RiskFrame, Signal


class DefaultRiskModel(RiskModel):

    def can_trade(self, s) -> bool:
        # Identical to the original BaseStrategy.can_trade().
        return s.session_drawdown < s.max_session_dd

    def frame(self, s, sig: Signal) -> RiskFrame:
        direction = "long" if sig.direction > 0 else "short"
        # ATR stop + risk budget via this model's own helpers (one owner).
        stop = self.atr_stop(s, direction)
        risk_per_unit = abs(s.price - stop)
        budget = s.equity * float(getattr(s, "risk_pct", 0.01))
        max_notional = s.equity * max(int(getattr(s, "leverage", 1)), 1)
        vetoed = (not self.can_trade(s)) or risk_per_unit <= 0
        return RiskFrame(
            vetoed=vetoed,
            stop_price=stop,
            risk_per_unit=risk_per_unit,
            budget=budget,
            max_notional=max_notional,
        )

    def respects_liq_buffer(
        self, s, entry: float, stop: float, qty: float, leverage: float, direction: str
    ) -> bool:
        """True when ``stop`` triggers safely before liquidation.

        The protective stop must sit on the safe side of the isolated-margin
        liquidation price by at least ``s.liq_buffer_pct`` of price (long: stop
        above liq; short: stop below liq) so a stop can never be pre-empted by an
        exchange liquidation. The Risk Model is the single owner of the
        ``liq_buffer_pct`` rule; the Execution phase calls this once entry / qty /
        leverage are known. Uses the same isolated-margin math as the runner.
        """
        try:
            from engine.core.margin import liquidation_price, initial_margin
        except ImportError:  # pragma: no cover - top-level module root
            from core.margin import liquidation_price, initial_margin
        qty = abs(qty)
        if qty <= 0 or entry <= 0:
            return False
        margin = initial_margin(qty * entry, leverage)
        liq = liquidation_price(direction, qty, entry, margin)
        if liq <= 0:
            return True  # degenerate inputs / no liquidation modeled
        buf = float(getattr(s, "liq_buffer_pct", 0.0)) * entry
        if direction == "long":
            return stop >= liq + buf
        return stop <= liq - buf
