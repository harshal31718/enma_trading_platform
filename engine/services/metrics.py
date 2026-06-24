"""Pluggable statistic registry for backtest metrics (A-012).

Each statistic is a small class with a ``name`` and a ``compute(context)``
method.  The backtest runner builds a ``MetricContext`` from the per-run
artefacts (trades, equity curve, candles, capital, timeframe, …) and asks the
registry to compute every registered statistic.  Adding a new metric = writing
one class and calling ``registry.register(MyMetric())``; no edits to the
runner hot path.

The original monolithic metrics dict is still produced by ``compute_metrics``
for backward compatibility (existing UI fields are unchanged).  New metrics
additive to that dict are returned alongside.

Design notes
------------
* Compute all metrics with NumPy where possible — the inner per-candle loop
  in ``backtest_runner`` is hot, but this module only runs once per backtest
  (post-loop) so complexity is fine.
* All metric values are formatted as ``str`` with two decimal places to match
  the rest of the metrics dict.
* Statistics never raise — they return ``"0.00"`` for undefined inputs so a
  broken calculator can't poison the result document.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Sequence
import math
import numpy as np


# ── Context object passed to every statistic ──────────────────────────────────

@dataclass
class MetricContext:
    """All per-run artefacts a statistic might need.

    Built once at the end of ``run_backtest_simulation`` from the local
    variables the runner already tracks.  Kept narrow on purpose: adding a
    new artefact is a deliberate edit, not an accident.
    """
    trades: list[dict]
    balances: np.ndarray              # equity curve (raw, no downsampling)
    equity_timestamps: list[str]      # ISO strings aligned with balances
    candles_np: np.ndarray            # [timestamp_ms, open, close, high, low, volume]
    capital: float
    timeframe: str
    annual_factor: float              # from utils.timeframes.annual_factor(timeframe)
    warmup_period: int                # index where simulation started
    total_fees: float
    total_funding: float
    liquidations: int
    leverage: int


# ── Base class ────────────────────────────────────────────────────────────────

class Statistic:
    """Subclass and set ``name`` + implement ``compute``.

    Subclasses are auto-discovered via subclass introspection — any
    ``Statistic`` subclass defined at import time that sets ``name`` is
    picked up by :func:`default_registry`.
    """
    name: str = ""

    def compute(self, ctx: MetricContext) -> Any:  # pragma: no cover - interface
        raise NotImplementedError


# ── Concrete statistics (each = one row in the tracker.md catalog) ────────────

class TotalTradesStat(Statistic):
    name = "totalTrades"
    def compute(self, ctx: MetricContext) -> int:
        return len(ctx.trades)


class WinningTradesStat(Statistic):
    name = "winningTrades"
    def compute(self, ctx: MetricContext) -> int:
        return sum(1 for tr in ctx.trades if float(tr["pnl"]) > 0)


class LosingTradesStat(Statistic):
    name = "losingTrades"
    def compute(self, ctx: MetricContext) -> int:
        return sum(1 for tr in ctx.trades if float(tr["pnl"]) <= 0)


class WinRateStat(Statistic):
    name = "winRate"
    def compute(self, ctx: MetricContext) -> str:
        n = len(ctx.trades)
        if n == 0:
            return "0.00"
        wins = sum(1 for tr in ctx.trades if float(tr["pnl"]) > 0)
        return f"{wins / n:.2f}"


class NetProfitStat(Statistic):
    name = "netProfit"
    def compute(self, ctx: MetricContext) -> str:
        return f"{ctx.balances[-1] - ctx.capital:.2f}"


class NetProfitPctStat(Statistic):
    name = "netProfitPct"
    def compute(self, ctx: MetricContext) -> str:
        return f"{((ctx.balances[-1] - ctx.capital) / ctx.capital) * 100:.2f}"


class StartingBalanceStat(Statistic):
    name = "startingBalance"
    def compute(self, ctx: MetricContext) -> str:
        return f"{ctx.capital:.2f}"


class FinishingBalanceStat(Statistic):
    name = "finishingBalance"
    def compute(self, ctx: MetricContext) -> str:
        return f"{ctx.balances[-1]:.2f}"


class TotalFeesStat(Statistic):
    name = "totalFees"
    def compute(self, ctx: MetricContext) -> str:
        return f"{ctx.total_fees:.2f}"


class TotalFundingStat(Statistic):
    name = "totalFunding"
    def compute(self, ctx: MetricContext) -> str:
        return f"{ctx.total_funding:.2f}"


class LiquidationsStat(Statistic):
    name = "liquidations"
    def compute(self, ctx: MetricContext) -> int:
        return ctx.liquidations


class LeverageStat(Statistic):
    name = "leverage"
    def compute(self, ctx: MetricContext) -> int:
        return ctx.leverage


class MaxDrawdownStat(Statistic):
    name = "maxDrawdown"
    def compute(self, ctx: MetricContext) -> str:
        if ctx.balances.size == 0:
            return "0.00"
        running_max = np.maximum.accumulate(ctx.balances)
        dd = np.where(running_max > 0, (ctx.balances - running_max) / running_max, 0.0)
        return f"{float(np.min(dd)) * 100:.2f}"


class MaxRunupStat(Statistic):
    name = "maxRunup"
    def compute(self, ctx: MetricContext) -> str:
        if ctx.balances.size == 0:
            return "0.00"
        running_min = np.minimum.accumulate(ctx.balances)
        ru = np.where(running_min > 0, (ctx.balances - running_min) / running_min, 0.0)
        return f"{float(np.max(ru)) * 100:.2f}"


class _ReturnsHelper:
    """Internal: vectorised per-candle returns from a balances array."""

    @staticmethod
    def per_candle_returns(balances: np.ndarray) -> np.ndarray:
        if balances.size <= 1:
            return np.array([])
        prev = balances[:-1]
        curr = balances[1:]
        mask = prev > 0
        return np.where(mask, (curr - prev) / prev, 0.0)


class SharpeStat(Statistic):
    name = "sharpeRatio"
    def compute(self, ctx: MetricContext) -> str:
        rets = _ReturnsHelper.per_candle_returns(ctx.balances)
        if rets.size == 0:
            return "0.00"
        std = float(np.std(rets))
        if std <= 0:
            return "0.00"
        return f"{(float(np.mean(rets)) / std) * math.sqrt(ctx.annual_factor):.2f}"


class SortinoStat(Statistic):
    name = "sortinoRatio"
    def compute(self, ctx: MetricContext) -> str:
        rets = _ReturnsHelper.per_candle_returns(ctx.balances)
        if rets.size == 0:
            return "0.00"
        mean = float(np.mean(rets))
        # I-09: downside deviation must be measured against the target (0) over
        # ALL periods, not the std of the negative subset about its own mean.
        # Mirror freqtrade: std of returns clipped at 0 (positives → 0).
        down_std = float(np.std(np.clip(rets, a_min=None, a_max=0.0)))
        if down_std <= 0:
            return "0.00"
        return f"{(mean / down_std) * math.sqrt(ctx.annual_factor):.2f}"


def _annualized_return_pct(ctx: MetricContext) -> float | None:
    """CAGR in percent, or None if the run is too short / inputs are invalid.

    Shared by ``CAGRStat`` and ``CalmarStat`` so the two can never drift —
    Calmar is annualized return over max drawdown, not total return.
    """
    if ctx.balances.size == 0 or ctx.capital <= 0:
        return None
    if ctx.candles_np.shape[0] <= ctx.warmup_period:
        return None
    start_ts = ctx.candles_np[ctx.warmup_period, 0]   # ms
    end_ts = ctx.candles_np[-1, 0]
    seconds = (end_ts - start_ts) / 1000.0
    years = seconds / (365.25 * 24 * 3600)
    if years <= 0:
        return None
    ratio = ctx.balances[-1] / ctx.capital
    if ratio <= 0:
        return -100.0
    return ((ratio ** (1.0 / years)) - 1.0) * 100.0


class CalmarStat(Statistic):
    name = "calmarRatio"
    def compute(self, ctx: MetricContext) -> str:
        if ctx.balances.size == 0:
            return "0.00"
        running_max = np.maximum.accumulate(ctx.balances)
        dd = np.where(running_max > 0, (ctx.balances - running_max) / running_max, 0.0)
        max_dd = float(np.min(dd)) * 100.0
        # I-08: Calmar = CAGR / |maxDD| (annualized return), not total return.
        cagr = _annualized_return_pct(ctx)
        if max_dd == 0 or cagr is None:
            return "0.00"
        return f"{cagr / abs(max_dd):.2f}"


class BuyHoldReturnStat(Statistic):
    name = "buyHoldReturnPct"
    def compute(self, ctx: MetricContext) -> str:
        if ctx.candles_np.shape[0] <= ctx.warmup_period:
            return "0.00"
        first = float(ctx.candles_np[ctx.warmup_period, 2])
        last = float(ctx.candles_np[-1, 2])
        if first <= 0:
            return "0.00"
        return f"{((last - first) / first) * 100:.2f}"


# ── A-007 ★★★ NEW METRICS ────────────────────────────────────────────────────

class CAGRStat(Statistic):
    """Compound Annual Growth Rate of starting → finishing equity."""
    name = "cagrPct"

    def compute(self, ctx: MetricContext) -> str:
        cagr = _annualized_return_pct(ctx)
        return "0.00" if cagr is None else f"{cagr:.2f}"


class SQNStat(Statistic):
    """Van Tharp System Quality Number: sqrt(N) * mean(pnl) / std(pnl)."""
    name = "sqn"

    def compute(self, ctx: MetricContext) -> str:
        if len(ctx.trades) < 2:
            return "0.00"
        pnls = np.array([float(t["pnl"]) for t in ctx.trades], dtype=np.float64)
        std = float(np.std(pnls))
        if std <= 0:
            return "0.00"
        return f"{math.sqrt(len(ctx.trades)) * float(np.mean(pnls)) / std:.2f}"


class ExpectancyStat(Statistic):
    """Average $ per trade (already in legacy metrics) — restated here for registry completeness."""
    name = "expectancy"
    def compute(self, ctx: MetricContext) -> str:
        if not ctx.trades:
            return "0.00"
        pnls = np.array([float(t["pnl"]) for t in ctx.trades], dtype=np.float64)
        return f"{float(np.mean(pnls)):.2f}"


class ExpectancyRatioStat(Statistic):
    """Expectancy ratio = (avg_win * win_rate - |avg_loss| * loss_rate) / |avg_loss|.

    Edge-per-trade normalised by average loss — answers "is this strategy's
    edge real per unit of risk?" (freqtrade reports this in strategy table).
    """
    name = "expectancyRatio"

    def compute(self, ctx: MetricContext) -> str:
        n = len(ctx.trades)
        if n == 0:
            return "0.00"
        pnls = np.array([float(t["pnl"]) for t in ctx.trades], dtype=np.float64)
        wins  = pnls[pnls > 0]
        losses = pnls[pnls <= 0]
        if losses.size == 0:
            return "inf" if wins.size > 0 else "0.00"
        win_rate = wins.size / n
        loss_rate = 1 - win_rate
        avg_win  = float(np.mean(wins))  if wins.size  else 0.0
        avg_loss = float(np.mean(losses))
        if avg_loss == 0:
            return "0.00"
        # Per-unit-of-loss expectancy: edge per loss-encounter
        return f"{((avg_win * win_rate) - (abs(avg_loss) * loss_rate)) / abs(avg_loss):.2f}"


class MaxConsecutiveWinsStat(Statistic):
    name = "maxConsecutiveWins"
    def compute(self, ctx: MetricContext) -> int:
        m = c = 0
        for tr in ctx.trades:
            if float(tr["pnl"]) > 0:
                c += 1
                m = max(m, c)
            else:
                c = 0
        return m


class MaxConsecutiveLossesStat(Statistic):
    name = "maxConsecutiveLosses"
    def compute(self, ctx: MetricContext) -> int:
        m = c = 0
        for tr in ctx.trades:
            if float(tr["pnl"]) <= 0:
                c += 1
                m = max(m, c)
            else:
                c = 0
        return m


class GrossProfitStat(Statistic):
    name = "grossProfit"
    def compute(self, ctx: MetricContext) -> str:
        if not ctx.trades:
            return "0.00"
        pnls = np.array([float(t["pnl"]) for t in ctx.trades], dtype=np.float64)
        return f"{float(np.sum(pnls[pnls > 0])):.2f}"


class GrossLossStat(Statistic):
    name = "grossLoss"
    def compute(self, ctx: MetricContext) -> str:
        if not ctx.trades:
            return "0.00"
        pnls = np.array([float(t["pnl"]) for t in ctx.trades], dtype=np.float64)
        return f"{float(np.sum(pnls[pnls <= 0])):.2f}"


class ProfitFactorStat(Statistic):
    name = "profitFactor"
    def compute(self, ctx: MetricContext) -> str:
        if not ctx.trades:
            return "0.00"
        pnls = np.array([float(t["pnl"]) for t in ctx.trades], dtype=np.float64)
        win  = float(np.sum(pnls[pnls > 0]))
        loss = float(np.sum(pnls[pnls <= 0]))
        # I-13: no losses + some wins → undefined/∞ profit factor, not 0.00
        # (which is indistinguishable from the worst case). Matches the "inf"
        # sentinel ExpectancyRatioStat already returns.
        if loss == 0:
            return "inf" if win > 0 else "0.00"
        return f"{win / abs(loss):.2f}"


class PayoffRatioStat(Statistic):
    name = "payoffRatio"
    def compute(self, ctx: MetricContext) -> str:
        if not ctx.trades:
            return "0.00"
        pnls = np.array([float(t["pnl"]) for t in ctx.trades], dtype=np.float64)
        wins   = pnls[pnls > 0]
        losses = pnls[pnls <= 0]
        # I-13: no losses + some wins → undefined/∞ payoff, not 0.00.
        if losses.size == 0:
            return "inf" if wins.size else "0.00"
        avg_l = float(np.mean(losses))
        if avg_l == 0:
            return "0.00"
        avg_w = float(np.mean(wins))   if wins.size   else 0.0
        return f"{avg_w / abs(avg_l):.2f}"


class AverageWinStat(Statistic):
    name = "averageWin"
    def compute(self, ctx: MetricContext) -> str:
        if not ctx.trades:
            return "0.00"
        pnls = np.array([float(t["pnl"]) for t in ctx.trades], dtype=np.float64)
        wins = pnls[pnls > 0]
        return f"{float(np.mean(wins)):.2f}" if wins.size else "0.00"


class AverageLossStat(Statistic):
    name = "averageLoss"
    def compute(self, ctx: MetricContext) -> str:
        if not ctx.trades:
            return "0.00"
        pnls = np.array([float(t["pnl"]) for t in ctx.trades], dtype=np.float64)
        losses = pnls[pnls <= 0]
        return f"{float(np.mean(losses)):.2f}" if losses.size else "0.00"


class LargestWinStat(Statistic):
    name = "largestWin"
    def compute(self, ctx: MetricContext) -> str:
        if not ctx.trades:
            return "0.00"
        pnls = np.array([float(t["pnl"]) for t in ctx.trades], dtype=np.float64)
        wins = pnls[pnls > 0]
        return f"{float(np.max(wins)):.2f}" if wins.size else "0.00"


class LargestLossStat(Statistic):
    name = "largestLoss"
    def compute(self, ctx: MetricContext) -> str:
        if not ctx.trades:
            return "0.00"
        pnls = np.array([float(t["pnl"]) for t in ctx.trades], dtype=np.float64)
        losses = pnls[pnls <= 0]
        return f"{float(np.min(losses)):.2f}" if losses.size else "0.00"


class AverageHoldingStat(Statistic):
    name = "averageHoldingPeriod"
    def compute(self, ctx: MetricContext) -> str:
        if not ctx.trades:
            return "0"
        durations = []
        for tr in ctx.trades:
            if "_exit_dt" in tr and "_entry_dt" in tr:
                durations.append((tr["_exit_dt"] - tr["_entry_dt"]).total_seconds())
        return f"{int(np.mean(durations))}" if durations else "0"


# ── Drawdown duration (A-007 — time underwater, not just depth) ──────────────

class MaxDrawdownDurationStat(Statistic):
    """Longest consecutive candles the equity curve sat below its running peak.

    Reported in candles (matches the timeframe's granularity).  freqtrade
    reports the same metric in minutes; candles is more directly comparable
    to the strategy horizon and avoids timezone-dependent conversions.
    """
    name = "maxDrawdownDurationCandles"

    def compute(self, ctx: MetricContext) -> int:
        if ctx.balances.size == 0:
            return 0
        running_max = np.maximum.accumulate(ctx.balances)
        # 1.0 when at or above peak, 0.0 when below
        above = (ctx.balances >= running_max).astype(np.int32)
        # Longest run of zeros
        longest = cur = 0
        for v in above:
            if v == 0:
                cur += 1
                longest = max(longest, cur)
            else:
                cur = 0
        return longest


# ── A-008 ★★ breakdown tables ────────────────────────────────────────────────

class ByExitReasonStat(Statistic):
    """Group closed trades by ``exitReason`` and compute per-group stats."""
    name = "byExitReason"

    def compute(self, ctx: MetricContext) -> dict:
        groups: dict[str, list[float]] = {}
        for tr in ctx.trades:
            groups.setdefault(tr.get("exitReason", "unknown"), []).append(float(tr["pnl"]))
        out: dict[str, dict] = {}
        for reason, pnls in groups.items():
            n = len(pnls)
            wins = [p for p in pnls if p > 0]
            losses = [p for p in pnls if p <= 0]
            out[reason] = {
                "totalTrades": n,
                "winningTrades": len(wins),
                "losingTrades": len(losses),
                "winRate": f"{(len(wins) / n):.2f}" if n else "0.00",
                "netProfit": f"{sum(pnls):.2f}",
                "averageWin":  f"{(sum(wins) / len(wins)):.2f}"  if wins   else "0.00",
                "averageLoss": f"{(sum(losses) / len(losses)):.2f}" if losses else "0.00",
            }
        return out


# ── Registry ──────────────────────────────────────────────────────────────────

class StatisticRegistry:
    """Holds an ordered list of :class:`Statistic` instances.

    Iteration order is insertion order; downstream code that depends on key
    ordering (JSON serialisation, golden-master diff) gets a stable result.
    """

    def __init__(self) -> None:
        self._stats: list[Statistic] = []

    def register(self, stat: Statistic) -> None:
        # Avoid duplicate-name registration — last one wins.
        self._stats = [s for s in self._stats if s.name != stat.name]
        self._stats.append(stat)

    def names(self) -> list[str]:
        return [s.name for s in self._stats]

    def compute_all(self, ctx: MetricContext) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for stat in self._stats:
            try:
                out[stat.name] = stat.compute(ctx)
            except Exception:  # never poison the result doc
                out[stat.name] = "0.00" if isinstance(stat.name, str) else 0
        return out


def default_registry() -> StatisticRegistry:
    """Build the default registry — every statistic shipped by Enma.

    Order = order the metrics appear in the result document.
    """
    r = StatisticRegistry()
    # ── A-007 / A-012 base block ───────────────────────────────────────────
    for s in (
        TotalTradesStat(),
        WinningTradesStat(),
        LosingTradesStat(),
        WinRateStat(),
        NetProfitStat(),
        NetProfitPctStat(),
        MaxDrawdownStat(),
        MaxRunupStat(),
        SharpeStat(),
        SortinoStat(),
        CalmarStat(),
        CAGRStat(),                       # NEW — A-007
        SQNStat(),                        # NEW — A-007
        ExpectancyStat(),
        ExpectancyRatioStat(),            # NEW — A-007
        StartingBalanceStat(),
        FinishingBalanceStat(),
        TotalFeesStat(),
        TotalFundingStat(),
        LiquidationsStat(),
        LeverageStat(),
        AverageWinStat(),
        AverageLossStat(),
        LargestWinStat(),
        LargestLossStat(),
        AverageHoldingStat(),
        GrossProfitStat(),
        GrossLossStat(),
        ProfitFactorStat(),
        PayoffRatioStat(),
        BuyHoldReturnStat(),
        MaxConsecutiveWinsStat(),
        MaxConsecutiveLossesStat(),
        MaxDrawdownDurationStat(),        # NEW — A-007
        ByExitReasonStat(),               # NEW — A-008
    ):
        r.register(s)
    return r