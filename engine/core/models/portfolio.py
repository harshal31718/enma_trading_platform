"""Portfolio Construction Models — size the target position.

DefaultPortfolioModel — default risk-budget sizing (legacy-equivalent).
RiskBudgetPortfolio   — min(budget/risk_per_unit, max_notional/price) × conviction.
NotionalPortfolio     — equity × position_size_pct / price (BestSupertrend).

construct() is the primary contract. _size() is the internal sizing hook
that subclasses override; PortfolioModel.size() (deprecated shim on the ABC)
is not overridden and continues to call construct() via the ABC.
"""
from __future__ import annotations

from .base import (
    PortfolioModel, TargetPortfolio, Target, Signal, RiskConstraints, CostEstimate,
)


class DefaultPortfolioModel(PortfolioModel):
    """Combines veto checks, maintain logic, edge gate and sizing into one call.

    construct() implements the full five-path decision tree:
      flat+no-signal  → qty=0
      holding+same    → maintain current holding (no re-size)
      vetoed          → qty=0 (flat) or current_holding (holding, don't force close)
      edge-veto       → same as vetoed
      new/flip        → _size() → signed target
    """

    # Edge gate strength. Subclasses may override. 0.0 = always trade (default).
    min_edge_mult: float = 0.0

    def construct(
        self, s, sig: Signal, constraints: RiskConstraints,
        cost: CostEstimate, current_holding: float = 0.0,
    ) -> TargetPortfolio:
        is_holding = current_holding != 0.0
        same_dir = (
            (sig.direction > 0 and current_holding > 0) or
            (sig.direction < 0 and current_holding < 0)
        )

        # Flat/close signal
        if sig.direction == 0:
            return TargetPortfolio(qty=0.0)

        # Maintain: don't re-size an existing position in the same direction
        if is_holding and same_dir:
            return TargetPortfolio(qty=current_holding)

        # Risk veto — halts new entries and flips, but never force-closes
        if constraints.vetoed:
            return TargetPortfolio(qty=current_holding) if is_holding else TargetPortfolio(qty=0.0)

        # Edge-vs-cost gate (only blocks new entries/flips)
        if not self._edge_beats_cost(s, sig, constraints, cost):
            return TargetPortfolio(qty=current_holding) if is_holding else TargetPortfolio(qty=0.0)

        # Size the position (new entry or flip)
        raw_qty = self._size(s, sig, constraints)
        if raw_qty <= 0:
            return TargetPortfolio(qty=current_holding) if is_holding else TargetPortfolio(qty=0.0)

        # Portfolio exposure cap: veto if this position's risk exceeds max_portfolio_risk × equity.
        # Default 0.06 (6%). With risk_pct=0.01, new_risk_pct≈0.01 << 0.06 → never triggered
        # at default settings → golden-master safe. Only bites when risk_pct > max_portfolio_risk.
        max_port_risk = float(getattr(s, "max_portfolio_risk", 0.06))
        if max_port_risk > 0 and s.equity > 0 and constraints.risk_per_unit > 0:
            new_risk_pct = (constraints.risk_per_unit * raw_qty) / s.equity
            if new_risk_pct > max_port_risk:
                return TargetPortfolio(qty=current_holding) if is_holding else TargetPortfolio(qty=0.0)

        signed_qty = raw_qty * sig.direction
        weight = abs(signed_qty * s.price) / s.equity if s.equity > 0 else 0.0
        return TargetPortfolio(qty=signed_qty, weight=weight)

    def _size(self, s, sig: Signal, constraints: RiskConstraints) -> float:
        """Default risk-budget sizing. Byte-identical to the old size() behavior:
        (equity * risk_pct) / risk_per_unit, capped by max_qty() / leverage."""
        if constraints.stop_price is None:
            return 0.0
        conviction = max(0.0, min(float(sig.conviction), 1.0))
        return s.size_by_risk(constraints.stop_price) * conviction

    def _edge_beats_cost(
        self, s, sig: Signal, constraints: RiskConstraints, cost: CostEstimate,
    ) -> bool:
        """Returns False when estimated cost exceeds min_edge_mult × expected edge.

        Default min_edge_mult=0.0 → always True (never veto). Override in a
        subclass or set on an instance to opt in to the cost gate.

        Both sides are quote currency (Plan 9.11 M-2 fix): edge is scaled by the
        same qty_est the Cost Model used to estimate `cost.total`
        (min(budget/risk_per_unit, max_notional/price) — recomputed here rather
        than threaded through CostEstimate, since both call sites already have
        the constraints that produced it). Previously edge was a bare per-unit
        price distance compared against a whole-position quote cost, making the
        gate a function of the symbol's absolute price level.

        Edge strength (Plan 9.11 M-3 fix): uses `sig.magnitude` when the alpha
        model provides one (predicted move as a fraction of price), falling
        back to `abs(sig.conviction)` otherwise — previously `magnitude` was
        documented as feeding this gate but was read by nothing.
        """
        # Always honor strategy cost vetoes
        if not s.alpha_beats_cost(float(sig.direction)):
            return False

        mult = float(getattr(self, "min_edge_mult", 0.0))
        if mult <= 0.0:
            return True
        if constraints.risk_per_unit <= 0 or s.price <= 0:
            return True
        rrr = float(getattr(s, "rrr", 2.0))
        edge_frac = abs(sig.magnitude) if sig.magnitude else abs(sig.conviction)
        qty_est = min(
            constraints.budget / constraints.risk_per_unit if constraints.risk_per_unit > 0 else 0.0,
            constraints.max_notional / s.price,
        )
        edge_total = edge_frac * constraints.risk_per_unit * qty_est * rrr
        return edge_total >= mult * cost.total


class RiskBudgetPortfolio(DefaultPortfolioModel):
    """Risk-budget sizing: size = min(budget/risk_per_unit, max_notional/price) × conviction.

    Used by MicroScalper, MicroMacroRSIDivergence, MultiDivergence (via AtrBracketRiskModel)
    and AdaptiveTrend (via ChandelierRiskModel with max_notional = equity * min(max_leverage, lev)).

    Golden-master equivalent to the old _position_qty() and size_by_risk() calls
    in each strategy's go_long/go_short, because:
      budget      = equity * risk_pct
      risk_per_unit = |price - stop|
      max_notional = equity * leverage  (or equity * min(max_leverage, lev) for Chandelier)
      → min(budget/rpu, max_notional/price) × 1.0 = old min(qty, lev_cap, max_qty)
    """

    def _size(self, s, sig: Signal, constraints: RiskConstraints) -> float:
        if constraints.risk_per_unit <= 0 or constraints.budget <= 0 or s.price <= 0:
            return 0.0
        conviction = max(0.0, min(float(sig.conviction), 1.0))
        qty_by_risk     = constraints.budget / constraints.risk_per_unit
        qty_by_notional = constraints.max_notional / s.price
        return min(qty_by_risk, qty_by_notional) * conviction


class NotionalPortfolio(DefaultPortfolioModel):
    """Notional sizing: equity × position_size_pct / price. Used by BestSupertrend.

    Golden-master equivalent to BestSupertrend's go_long/go_short calling
    self.size_by_notional(self.position_size_pct) directly.
    """

    def _size(self, s, sig: Signal, constraints: RiskConstraints) -> float:
        conviction = max(0.0, min(float(sig.conviction), 1.0))
        pct = float(getattr(s, "position_size_pct", 0.1))
        return s.size_by_notional(pct) * conviction


def compute_realized_volatility(close_prices: "dict[str, list[float] | object]") -> dict[str, float]:
    """Plan 22 Step 22.6: per-symbol realized volatility (stdev of log
    returns) over whatever warmup window the caller hands in — pure
    rule-based (fork #2: no fitted/GARCH models), used only to weight
    `InverseVolatilityPortfolio.allocate()`.

    `close_prices` maps symbol -> a sequence of closing prices (already
    sliced to the desired lookback by the caller — this function has no
    opinion on lookback length, backtest and live each own that decision
    separately since backtest has upfront warmup candles and live has to
    fetch history). A symbol with fewer than 2 usable prices (after
    dropping NaN) is simply omitted from the result — the caller's
    allocate() degrades a missing symbol to equal-weight among the rest.
    """
    import numpy as np

    vols: dict[str, float] = {}
    for sym, prices in close_prices.items():
        arr = np.asarray(prices, dtype=float)
        arr = arr[~np.isnan(arr)]
        if len(arr) < 2 or np.any(arr <= 0):
            continue
        returns = np.diff(np.log(arr))
        if len(returns) < 1:
            continue
        vol = float(np.std(returns))
        if vol > 0:
            vols[sym] = vol
    return vols


class InverseVolatilityPortfolio(DefaultPortfolioModel):
    """Plan 22 Step 22.6 (fork #3): weights symbols ∝ 1/realized-volatility
    instead of the base class's equal split. `construct()` is inherited
    unchanged from `DefaultPortfolioModel` — only cross-symbol capital
    ALLOCATION differs, not per-candle position sizing.

    Config-gated at the call site (`backtest_runner.py`/`live_bot_manager.py`)
    via `risk_params["allocation"] == "inverse_vol"`; default `"equal"` keeps
    using the plain `DefaultPortfolioModel`/base `allocate()`, byte-identical
    to pre-22.6 behavior (golden-master requirement).
    """

    def allocate(
        self,
        total_capital: float,
        symbols: list[str],
        volatilities: dict[str, float] | None = None,
        floor_pct: float = 0.05,
        cap_pct: float = 0.5,
    ) -> dict[str, float]:
        """Weight ∝ 1/vol, then clamp each symbol's weight to [floor_pct,
        cap_pct] and renormalize so weights still sum to 1 (a clamp alone can
        leave the sum off — freqtrade/risk-parity implementations
        renormalize post-clamp, so do the same here). Symbols missing from
        `volatilities` (no usable price history — e.g. a newly-listed
        symbol) fall back to the mean of the KNOWN weights, not zero — a
        symbol we simply have no vol estimate for shouldn't be starved of
        capital outright.

        Degrades to the equal-weight base-class behavior when `volatilities`
        is empty/None or fewer than 2 symbols have a usable estimate (no
        meaningful "inverse" weighting possible with 0-1 data points).
        """
        n = len(symbols)
        if n == 0:
            return {}
        vols = volatilities or {}
        known = {sym: vols[sym] for sym in symbols if sym in vols and vols[sym] > 0}
        if len(known) < 2:
            return super().allocate(total_capital, symbols)

        inv = {sym: 1.0 / v for sym, v in known.items()}
        inv_sum = sum(inv.values())
        raw_weights = {sym: w / inv_sum for sym, w in inv.items()}
        mean_known_weight = sum(raw_weights.values()) / len(raw_weights)
        weights = {sym: raw_weights.get(sym, mean_known_weight) for sym in symbols}

        # Iterative clamp-and-renormalize (alternating projection onto the
        # simplex ∩ box[floor_pct, cap_pct]): a single clamp-then-renormalize
        # pass can push a previously-capped weight back OVER the cap once
        # the freed-up mass is redistributed (e.g. two symbols simultaneously
        # hit the floor while a third hits the cap — fixing all three in one
        # shot leaves 1-Σfixed unaccounted for). Repeatedly clamp then
        # renormalize the WHOLE set until stable; converges whenever
        # `floor_pct * n <= 1 <= cap_pct * n` (always true for this method's
        # own defaults with n>=2, since `known` requires >=2 entries).
        final_weights = dict(weights)
        for _ in range(200):
            total = sum(final_weights.values())
            if total <= 0:
                return super().allocate(total_capital, symbols)
            normalized = {sym: w / total for sym, w in final_weights.items()}
            clamped = {sym: min(max(w, floor_pct), cap_pct) for sym, w in normalized.items()}
            if max(abs(clamped[sym] - normalized[sym]) for sym in clamped) < 1e-12:
                final_weights = normalized
                break
            final_weights = clamped
        else:
            total = sum(final_weights.values())
            final_weights = {sym: w / total for sym, w in final_weights.items()} if total > 0 else weights

        return {sym: total_capital * w for sym, w in final_weights.items()}
