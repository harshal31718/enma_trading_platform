import numpy as np

from engine.core.strategy import BaseStrategy
import engine.indicators as ta

try:
    from engine.core.models import AtrBracketRiskModel, RiskBudgetPortfolio, Signal
except ImportError:
    from core.models import AtrBracketRiskModel, RiskBudgetPortfolio, Signal


class MicroScalper(BaseStrategy):
    """
    High-frequency stop-and-reverse scalper built for pipeline stress testing.

    Goal: maximum trade volume for engine testing, not profit.
    Logic: fast/slow EMA crossover with an optional ATR volatility filter.
    Always in a position — every crossover flips the bias via flip_position().

    BUG-05 fix: `import talib` removed from atr_sma; now uses numpy rolling
    mean on the sequential ATR series, compatible with both talib and pandas_ta
    indicator backends.

    Recommended:
        Symbol   : BTCUSDT or any high-liquidity futures pair
        Timeframe: 1m
        Capital  : any
        Leverage : 1–5x
    """

    MIN_WARMUP_CANDLES: int = 25   # slow=21 + atr=14 + 2 buffer (rounded up)

    PARAMS = {
        "fast_period": {
            "type": "int", "default": 9, "min": 2, "max": 20,
            "label": "Fast EMA Period",
            "description": (
                "Increasing: fewer, more delayed crossover signals. "
                "Decreasing: more frequent crossovers, maximum churn."
            ),
        },
        "slow_period": {
            "type": "int", "default": 21, "min": 3, "max": 50,
            "label": "Slow EMA Period",
            "description": (
                "Increasing: longer trend confirmation, fewer flips. "
                "Decreasing: crossovers fire faster, more trades per hour."
            ),
        },
        "atr_period": {
            "type": "int", "default": 14, "min": 5, "max": 50,
            "label": "ATR Period",
            "description": (
                "Increasing: smoother ATR baseline, more stable volatility gate. "
                "Decreasing: more reactive ATR, gate changes frequently."
            ),
        },
        "atr_multiplier": {
            "type": "float", "default": 1.2, "min": 0.0, "max": 3.0,
            "label": "ATR Volatility Threshold Multiplier (0 = filter off)",
            "description": (
                "Increasing: stricter volatility requirement, fewer trades. "
                "Decreasing: trades in quieter markets; 0 disables the filter."
            ),
        },
        "sl_atr_mult": {
            "type": "float", "default": 1.5, "min": 0.1, "max": 5.0,
            "label": "Stop-Loss ATR Multiplier",
            "description": (
                "Increasing: wider stop, fewer premature stop-outs but larger losses. "
                "Decreasing: tighter stop, stops out more often, smaller max loss."
            ),
        },
        "tp_atr_mult": {
            "type": "float", "default": 2.0, "min": 0.1, "max": 10.0,
            "label": "Take-Profit ATR Multiplier",
            "description": (
                "Increasing: TP target further from entry, bigger wins but fewer. "
                "Decreasing: TP fires sooner, more small wins."
            ),
        },
    }

    def __init__(self):
        super().__init__()
        self.fast_period:    int   = self.PARAMS["fast_period"]["default"]
        self.slow_period:    int   = self.PARAMS["slow_period"]["default"]
        self.atr_period:     int   = self.PARAMS["atr_period"]["default"]
        self.atr_multiplier: float = self.PARAMS["atr_multiplier"]["default"]
        self.sl_atr_mult:    float = self.PARAMS["sl_atr_mult"]["default"]
        self.tp_atr_mult:    float = self.PARAMS["tp_atr_mult"]["default"]

        # Narang Black-Box: bind risk and portfolio models
        self.risk_model      = AtrBracketRiskModel()
        self.portfolio_model = RiskBudgetPortfolio()

    def validate_params(self) -> None:
        if self.fast_period >= self.slow_period:
            raise ValueError(
                f"fast_period ({self.fast_period}) must be less than slow_period ({self.slow_period})"
            )
        if self.tp_atr_mult <= self.sl_atr_mult:
            raise ValueError(
                f"tp_atr_mult ({self.tp_atr_mult}) must be greater than sl_atr_mult ({self.sl_atr_mult})"
            )

    # ── Indicators — computed once per candle in before() ──────────────────
    # BUG-05 fix: atr_sma previously used `import talib` directly, crashing
    # on the pandas_ta backend. Now uses numpy rolling mean on the sequential
    # ATR series, backend-agnostic.

    def before(self) -> None:
        if len(self.candles) < self.MIN_WARMUP_CANDLES:
            return

        self.vars["fast_ema"]      = ta.ema(self.candles,      period=self.fast_period)
        self.vars["slow_ema"]      = ta.ema(self.candles,      period=self.slow_period)
        self.vars["fast_ema_prev"] = ta.ema(self.candles[:-1], period=self.fast_period)
        self.vars["slow_ema_prev"] = ta.ema(self.candles[:-1], period=self.slow_period)

        atr = ta.atr(self.candles, period=self.atr_period)
        self.vars["atr"] = atr

        # ATR baseline for volatility filter — numpy rolling mean (BUG-05 fix)
        if self.atr_multiplier > 0.0:
            series = ta.atr(self.candles, period=self.atr_period, sequential=True)
            window = series[-(self.atr_period * 2):]
            window = window[~np.isnan(window)]
            self.vars["atr_baseline"] = float(np.mean(window)) if window.size > 0 else 0.0
        else:
            self.vars["atr_baseline"] = 0.0

        self.vars["atr_stop_long"]  = self.price - (self.sl_atr_mult * atr)
        self.vars["atr_stop_short"] = self.price + (self.sl_atr_mult * atr)
        self.vars["atr_tp_long"]    = self.price + (self.tp_atr_mult * atr)
        self.vars["atr_tp_short"]   = self.price - (self.tp_atr_mult * atr)

    # ── Volatility gate ─────────────────────────────────────────────────────

    def _is_volatile(self) -> bool:
        if self.atr_multiplier == 0.0:
            return True
        atr      = self.vars.get("atr", 0.0)
        baseline = self.vars.get("atr_baseline", 0.0)
        if baseline <= 0:
            return True
        return atr > (baseline * self.atr_multiplier)

    # ── Crossover detection ─────────────────────────────────────────────────

    def _crossed_above(self) -> bool:
        return (
            self.vars.get("fast_ema", 0) > self.vars.get("slow_ema", 0) and
            self.vars.get("fast_ema_prev", 0) <= self.vars.get("slow_ema_prev", 0)
        )

    def _crossed_below(self) -> bool:
        return (
            self.vars.get("fast_ema", 0) < self.vars.get("slow_ema", 0) and
            self.vars.get("fast_ema_prev", 0) >= self.vars.get("slow_ema_prev", 0)
        )

    # ── Alpha Model: forecast() handles both open and flat cases ────────────

    def forecast(self) -> Signal:
        """Stop-and-reverse scalper logic.

        While holding: flip direction on crossover (if volatile); maintain otherwise.
        While flat: enter on crossover (if volatile); stay flat otherwise.
        """
        if len(self.candles) < self.MIN_WARMUP_CANDLES:
            return Signal(direction=0)

        volatile = self._is_volatile()

        if self.is_open:
            # Holding — check for stop-and-reverse
            if volatile and self.is_long and self._crossed_below():
                return Signal(direction=-1, conviction=1.0, ref_price=self.price)
            if volatile and self.is_short and self._crossed_above():
                return Signal(direction=1, conviction=1.0, ref_price=self.price)
            # Maintain current direction
            return Signal(direction=1 if self.is_long else -1, conviction=1.0, ref_price=self.price)

        # Flat — look for entry
        if volatile and self._crossed_above():
            return Signal(direction=1, conviction=1.0, ref_price=self.price)
        if volatile and self._crossed_below():
            return Signal(direction=-1, conviction=1.0, ref_price=self.price)
        return Signal(direction=0, ref_price=self.price)
