"""Regression tests for metric-fidelity fixes (I-08 Calmar, I-09 Sortino, I-13 ProfitFactor/Payoff).

Run inside the container::

    docker exec enma_trading_platform-engine-1 pytest /app/tests/test_metrics_fixes.py
"""
import numpy as np

from services.metrics import (
    MetricContext,
    CalmarStat,
    CAGRStat,
    SortinoStat,
    ProfitFactorStat,
    PayoffRatioStat,
    Statistic,
    StatisticRegistry,
)

_YEAR_MS = 365.25 * 24 * 3600 * 1000.0


def _ctx(balances, trades=None, span_years=2.0, capital=1000.0, annual_factor=365.0):
    balances = np.asarray(balances, dtype=np.float64)
    n = balances.size
    # candles_np: [ts_ms, open, close, high, low, volume]; ts spans span_years.
    ts = np.linspace(0.0, span_years * _YEAR_MS, n)
    candles_np = np.column_stack([ts] + [np.full(n, 100.0)] * 5).astype(np.float64)
    return MetricContext(
        trades=trades or [],
        balances=balances,
        equity_timestamps=[""] * n,
        candles_np=candles_np,
        capital=capital,
        timeframe="1d",
        annual_factor=annual_factor,
        warmup_period=0,
        total_fees=0.0,
        total_funding=0.0,
        liquidations=0,
        leverage=1,
    )


# ── I-08: Calmar uses CAGR, not total return ─────────────────────────────────

def test_calmar_uses_cagr_not_total_return():
    # capital 1000 → 2000 over exactly 2 years; intermediate dip to 900 → maxDD -10%
    ctx = _ctx([1000.0, 900.0, 2000.0], span_years=2.0)
    # CAGR = (2 ** (1/2) - 1) * 100 = 41.42%
    assert CAGRStat().compute(ctx) == "41.42"
    # Calmar = CAGR / |maxDD| = 41.42 / 10 = 4.14  (old buggy value was 100/10 = 10.00)
    assert CalmarStat().compute(ctx) == "4.14"


def test_calmar_zero_drawdown_returns_zero():
    ctx = _ctx([1000.0, 1500.0, 2000.0], span_years=2.0)  # monotonic, no DD
    assert CalmarStat().compute(ctx) == "0.00"


# ── I-09: Sortino downside deviation against target 0 ────────────────────────

def test_sortino_zero_when_no_downside():
    ctx = _ctx([1000.0, 1100.0, 1200.0, 1300.0])  # all-positive returns
    assert SortinoStat().compute(ctx) == "0.00"


def test_sortino_finite_with_a_drawdown():
    ctx = _ctx([1000.0, 1100.0, 990.0, 1200.0])  # has a negative return
    out = SortinoStat().compute(ctx)
    assert out not in ("0.00",) and float(out) != 0.0


# ── I-13: ProfitFactor / PayoffRatio sentinel when no losses ─────────────────

def _trades(pnls):
    return [{"pnl": str(p), "exitReason": "take_profit"} for p in pnls]


def test_profit_factor_inf_when_all_wins():
    ctx = _ctx([1000.0, 1200.0], trades=_trades([100.0, 50.0]))
    assert ProfitFactorStat().compute(ctx) == "inf"
    assert PayoffRatioStat().compute(ctx) == "inf"


def test_profit_factor_finite_with_losses():
    ctx = _ctx([1000.0, 1050.0], trades=_trades([100.0, -50.0]))
    assert ProfitFactorStat().compute(ctx) == "2.00"  # 100 / 50


def test_profit_factor_zero_when_no_trades():
    ctx = _ctx([1000.0, 1000.0], trades=[])
    assert ProfitFactorStat().compute(ctx) == "0.00"


# ── QNT-13: StatisticRegistry.compute_all fails loud, not silent ─────────────

class _BrokenStat(Statistic):
    name = "brokenStat"
    def compute(self, ctx):
        raise ValueError("simulated stat bug")


class _IntNameBrokenStat(Statistic):
    name = "brokenIntStat"
    def compute(self, ctx):
        raise RuntimeError("simulated int-metric bug")


def test_compute_all_still_falls_back_to_zero_on_exception():
    """Fallback VALUE is unchanged — a broken stat must never poison the
    result doc or crash the whole backtest."""
    r = StatisticRegistry()
    r.register(_BrokenStat())
    r.register(ProfitFactorStat())
    ctx = _ctx([1000.0, 1050.0], trades=_trades([100.0, -50.0]))
    out = r.compute_all(ctx)
    assert out["brokenStat"] == "0.00"
    assert out["profitFactor"] == "2.00"  # the healthy stat is unaffected


def test_compute_all_logs_the_failure(caplog):
    """QNT-13: a broken metric must now be diagnosable via logs, not
    silently indistinguishable from a legitimately-zero one."""
    import logging
    r = StatisticRegistry()
    r.register(_BrokenStat())
    ctx = _ctx([1000.0, 1000.0], trades=[])
    with caplog.at_level(logging.ERROR, logger="services.metrics"):
        r.compute_all(ctx)
    assert any("brokenStat" in rec.message and "simulated stat bug" in rec.message for rec in caplog.records)


def test_compute_all_no_log_on_success(caplog):
    import logging
    r = StatisticRegistry()
    r.register(ProfitFactorStat())
    ctx = _ctx([1000.0, 1050.0], trades=_trades([100.0, -50.0]))
    with caplog.at_level(logging.ERROR, logger="services.metrics"):
        out = r.compute_all(ctx)
    assert out["profitFactor"] == "2.00"
    assert len(caplog.records) == 0
