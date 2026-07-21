"""Transaction Cost Model — single owner of the platform's cost math.

estimate(s, sig, constraints) replaces the old estimate(s, target) signature.
Notional is estimated from the risk constraints (budget / risk_per_unit) rather
than from a sized target, so cost can be evaluated before PCM runs.

DefaultCostModel alias kept for one refactor phase.
"""
from __future__ import annotations

import math
import numpy as np

from .base import TransactionCostModel, CostEstimate, Cost, Signal, RiskConstraints
from core.candle_columns import CLOSE, VOLUME


class DefaultTransactionCostModel(TransactionCostModel):

    # Opt-in edge-vs-cost gate strength moved to PortfolioModel._edge_beats_cost().
    min_edge_mult: float = 0.0

    # ── Realized fill mechanics (single owner of fill cost math) ─────────────

    def adverse_fill(self, s, ref_price: float, side: str, qty: float | None = None) -> float:
        """Adverse slippage on a market fill of ref_price.

        buy (long entry / short cover): fills higher — ref*(1+slip).
        sell (short entry / long exit): fills lower — ref*(1-slip).
        Byte-identical to the runner's former inline arithmetic.

        ``qty`` (Plan 9 Step 9.10, QNT-11): accepted but unused here — added
        so `LadderedTransactionCostModel` (below) can compute a market-impact
        term without widening the call sites twice. Both `execution.py` call
        sites (`entry_fill`/`exit_fill`) already have `qty` in scope and pass
        it through; this base implementation's constant-slippage behavior is
        unaffected either way.
        """
        slip = float(getattr(s, "slippage_pct", 0.0))
        if side == "buy":
            return ref_price * (1.0 + slip)
        return ref_price * (1.0 - slip)

    def fee(self, s, notional: float) -> float:
        """Taker fee on a notional: notional * fee_rate.

        Byte-identical to the runner's former inline notional * taker_fee.
        """
        return notional * float(getattr(s, "fee_rate", 0.0))

    # ── Predictive cost estimate ──────────────────────────────────────────────

    def impact_cost(self, s, notional: float) -> float:
        """Market-impact term. Default 0.0 (opt-in; requires ADV data)."""
        return 0.0

    def estimate(self, s, sig: Signal, constraints: RiskConstraints) -> CostEstimate:
        """Expected cost of a candidate trade in quote currency.

        Notional is estimated from risk constraints rather than a sized target so
        cost can be computed before PCM runs. With min_edge_mult=0 (default) the
        returned value only matters for strategies that override min_edge_mult > 0.
        """
        if sig.direction == 0 or constraints.risk_per_unit <= 0 or s.price <= 0:
            return CostEstimate()
        qty_est = min(
            constraints.budget / constraints.risk_per_unit,
            constraints.max_notional / s.price,
        )
        notional = abs(qty_est) * s.price
        slip = float(getattr(s, "slippage_pct", 0.0))
        return CostEstimate(
            fee=self.fee(s, notional),
            slippage=notional * slip,
            impact=self.impact_cost(s, notional),
        )

    # ── Deprecated gate (moved to PortfolioModel._edge_beats_cost) ───────────

    def is_worth_it(self, s, sig: Signal, rf: RiskConstraints, cost: CostEstimate) -> bool:
        """Deprecated. Gate logic now lives in DefaultPortfolioModel._edge_beats_cost().

        Kept only for any call sites in legacy runners that have not been updated
        to the new pipeline. Always returns True (permissive) unless min_edge_mult
        is set — matching the former default behavior.
        """
        if self.min_edge_mult <= 0.0:
            return s.alpha_beats_cost(float(sig.direction))
        rrr = float(getattr(s, "rrr", 1.0))
        edge = abs(sig.conviction) * rf.risk_per_unit * rrr
        return edge >= self.min_edge_mult * cost.total and s.alpha_beats_cost(float(sig.direction))


# Backward-compat alias — remove in Phase 6 cleanup
DefaultCostModel = DefaultTransactionCostModel


class LadderedTransactionCostModel(DefaultTransactionCostModel):
    """Plan 9 Step 9.10 (QNT-11): fill-model ladder — a strategy's constant
    ``slippage_pct`` alone prices every fill like BTC regardless of size,
    symbol depth, or current volatility. This layers two more realistic
    rungs on top of it:

      1. Volatility-scaled slippage: ``vol_slip_mult * ATR%`` — a wider
         current ATR (relative to price) means a worse expected fill.
      2. Square-root market impact: ``impact_mult * sqrt(notional / ADV)``
         — larger orders against thinner recent volume move price more
         than proportionally (the standard square-root impact law).

    ADV (average daily volume, in quote currency) is approximated from the
    strategy's own candle history: ``sum(volume * close)`` over a trailing
    ~24h window sized from ``s.timeframe`` — the numpy candles array only
    carries base-asset ``volume``, not the DB's separate ``quote_volume``
    column, so this is a close approximation, not the exchange's own figure.

    **Spread half-cost (the ladder's first rung) is deliberately NOT
    modeled** — backtesting has no historical bid/ask spread data at all
    (TimescaleDB's `candles` table is OHLCV-only, unlike live's ticker
    cache). A live-only cost model could add it later; this class stays
    correct for backtest, where "no data" beats "invented data".

    Opt-in only: assign ``self.cost_model = LadderedTransactionCostModel()``
    in a strategy's ``__init__``. None of the 5 seeded strategies do —
    default behavior (``DefaultTransactionCostModel``, constant slippage) is
    completely untouched, so this is golden-master-safe by construction.
    """

    vol_slip_mult: float = 0.5   # extra slippage fraction = vol_slip_mult * ATR%
    impact_mult: float = 0.1     # impact fraction = impact_mult * sqrt(notional / ADV)
    atr_period: int = 14
    adv_lookback_candles: int | None = None  # None = derive ~24h of candles from s.timeframe

    def _atr_pct(self, s) -> float:
        """|ATR| / price, or 0.0 if unavailable (matches size_by_notional's
        own defensive style — never raises, never poisons the fill price)."""
        try:
            atr = float(s._atr(self.atr_period))
        except Exception:
            return 0.0
        price = float(getattr(s, "price", 0.0) or 0.0)
        if price <= 0 or np.isnan(atr):
            return 0.0
        return abs(atr) / price

    def _adv_quote(self, s) -> float:
        """Trailing ~24h volume in quote currency, approximated from the
        strategy's own candle window (see class docstring)."""
        candles = getattr(s, "candles", None)
        if candles is None or len(candles) == 0:
            return 0.0

        n = self.adv_lookback_candles
        if n is None:
            from utils.timeframes import to_ms
            tf_ms = to_ms(getattr(s, "timeframe", "1h") or "1h")
            n = max(1, int(86_400_000 / tf_ms)) if tf_ms > 0 else 24

        window = candles[-n:]
        if len(window) == 0:
            return 0.0
        volumes = window[:, VOLUME]
        closes = window[:, CLOSE]
        return float(np.sum(volumes * closes))

    def adverse_fill(self, s, ref_price: float, side: str, qty: float | None = None) -> float:
        base_slip = float(getattr(s, "slippage_pct", 0.0))
        vol_component = self.vol_slip_mult * self._atr_pct(s)

        impact_component = 0.0
        if qty is not None and qty > 0 and ref_price > 0:
            adv = self._adv_quote(s)
            if adv > 0:
                notional = qty * ref_price
                impact_component = self.impact_mult * math.sqrt(notional / adv)

        effective_slip = base_slip + vol_component + impact_component
        if side == "buy":
            return ref_price * (1.0 + effective_slip)
        return ref_price * (1.0 - effective_slip)
