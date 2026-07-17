"""Plan 9.11 Step A regression: `DefaultPortfolioModel._edge_beats_cost()`
(engine/core/models/portfolio.py), the PCM edge-vs-cost veto.

Covers the three `[Certain]` findings from Plan 21's five-model audit
(21_live-algo-industry-standard-audit.md Part A2):

  M-1 — the injected `min_edge_mult` value must land on the object the gate
        actually reads (`strategy.portfolio_model`, not `strategy.cost_model`).
        Covered by `test_start_session_risk_params_shape.py` /
        `backtest_runner.py` and `live_bot_manager.py` inspection — this file
        only exercises the gate function itself once given a `min_edge_mult`.
  M-2 — the formula must be quote-vs-quote (edge scaled by the same qty_est
        the Cost Model used), not a bare per-unit price distance vs a whole-
        position quote cost — i.e. the veto boundary must NOT be a function
        of the symbol's absolute price level.
  M-3 — `Signal.magnitude` must feed the gate when provided, falling back to
        `abs(conviction)` when it isn't.

Run inside the container::

    docker exec enma_trading_platform-engine-1 pytest /app/tests/test_edge_beats_cost_gate.py
"""
from core.models.portfolio import DefaultPortfolioModel
from core.models.base import Signal, RiskConstraints, CostEstimate


class _FakeStrategy:
    def __init__(self, price: float, rrr: float = 2.0):
        self.price = price
        self.rrr = rrr

    def alpha_beats_cost(self, direction: float) -> bool:
        return True


def _pcm(mult: float) -> DefaultPortfolioModel:
    pcm = DefaultPortfolioModel()
    pcm.min_edge_mult = mult
    return pcm


def test_gate_off_by_default_always_passes():
    pcm = _pcm(0.0)
    s = _FakeStrategy(price=100.0)
    sig = Signal(direction=1, conviction=1.0)
    constraints = RiskConstraints(risk_per_unit=10.0, budget=100.0, max_notional=10_000.0)
    cost = CostEstimate(fee=1e9)  # absurdly large — would veto if the gate were active
    assert pcm._edge_beats_cost(s, sig, constraints, cost) is True


def test_gate_vetoes_when_cost_exceeds_scaled_edge():
    pcm = _pcm(1.0)
    s = _FakeStrategy(price=100.0, rrr=2.0)
    sig = Signal(direction=1, conviction=1.0)
    # qty_est = min(100/10, 10_000/100) = 10 -> edge_total = 1*10*10*2 = 200
    constraints = RiskConstraints(risk_per_unit=10.0, budget=100.0, max_notional=10_000.0)
    assert pcm._edge_beats_cost(s, sig, constraints, CostEstimate(fee=150.0)) is True
    assert pcm._edge_beats_cost(s, sig, constraints, CostEstimate(fee=250.0)) is False


def test_veto_boundary_is_price_level_invariant():
    """M-2: the same *relative* risk/cost setup must produce the same veto
    decision whether the symbol is priced like BTC or a sub-cent altcoin —
    proving the gate compares quote-vs-quote, not a raw per-unit price
    distance vs a whole-position quote cost (the pre-fix bug: always-pass on
    BTC-priced symbols, always-veto on sub-cent ones)."""
    pcm = _pcm(1.0)
    sig = Signal(direction=1, conviction=1.0)

    high_priced = _FakeStrategy(price=60_000.0, rrr=2.0)
    high_priced_constraints = RiskConstraints(
        risk_per_unit=6_000.0, budget=100.0, max_notional=10_000.0,
    )

    sub_cent = _FakeStrategy(price=0.0006, rrr=2.0)
    sub_cent_constraints = RiskConstraints(
        risk_per_unit=0.00006, budget=100.0, max_notional=10_000.0,
    )

    # Same 10% stop-distance-to-price ratio on both symbols, same budget/cap ->
    # same qty_est and same edge_total on both, so the same cost must flip
    # both the same way.
    cost_that_passes = CostEstimate(fee=1.0)
    cost_that_vetoes = CostEstimate(fee=1e6)

    assert pcm._edge_beats_cost(high_priced, sig, high_priced_constraints, cost_that_passes) is True
    assert pcm._edge_beats_cost(sub_cent, sig, sub_cent_constraints, cost_that_passes) is True

    assert pcm._edge_beats_cost(high_priced, sig, high_priced_constraints, cost_that_vetoes) is False
    assert pcm._edge_beats_cost(sub_cent, sig, sub_cent_constraints, cost_that_vetoes) is False


def test_magnitude_overrides_conviction_when_provided():
    """M-3: a nonzero `sig.magnitude` supplies the edge-strength factor
    instead of `conviction`."""
    pcm = _pcm(1.0)
    s = _FakeStrategy(price=100.0, rrr=2.0)
    constraints = RiskConstraints(risk_per_unit=10.0, budget=100.0, max_notional=10_000.0)
    # qty_est = 10 -> edge_total = magnitude * 10 * 10 * 2
    cost = CostEstimate(fee=210.0)  # between the conviction=1.0 (200) and magnitude=1.5 (300) edges

    low_conviction_no_magnitude = Signal(direction=1, conviction=1.0, magnitude=0.0)
    assert pcm._edge_beats_cost(s, low_conviction_no_magnitude, constraints, cost) is False

    high_magnitude = Signal(direction=1, conviction=1.0, magnitude=1.5)
    assert pcm._edge_beats_cost(s, high_magnitude, constraints, cost) is True


def test_alpha_veto_short_circuits_regardless_of_mult():
    pcm = _pcm(1.0)
    s = _FakeStrategy(price=100.0)

    class _AlphaVetoStrategy(_FakeStrategy):
        def alpha_beats_cost(self, direction: float) -> bool:
            return False

    sig = Signal(direction=1, conviction=1.0)
    constraints = RiskConstraints(risk_per_unit=10.0, budget=100.0, max_notional=10_000.0)
    assert pcm._edge_beats_cost(_AlphaVetoStrategy(price=100.0), sig, constraints, CostEstimate()) is False
