import numpy as np

from engine.core.strategy import BaseStrategy
import engine.indicators as ta


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

    MIN_WARMUP_CANDLES: int = 28   # slow_period (9) + atr_period (14) + 5 buffer

    PARAMS = {
        "fast_period": {
            "type": "int", "default": 3, "min": 2, "max": 20,
            "label": "Fast EMA Period",
            "description": (
                "Increasing: fewer, more delayed crossover signals. "
                "Decreasing: more frequent crossovers, maximum churn."
            ),
        },
        "slow_period": {
            "type": "int", "default": 9, "min": 3, "max": 50,
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
            "type": "float", "default": 0.5, "min": 0.0, "max": 3.0,
            "label": "ATR Volatility Threshold Multiplier (0 = filter off)",
            "description": (
                "Increasing: stricter volatility requirement, fewer trades. "
                "Decreasing: trades in quieter markets; 0 disables the filter."
            ),
        },
        "sl_atr_mult": {
            "type": "float", "default": 1.0, "min": 0.1, "max": 5.0,
            "label": "Stop-Loss ATR Multiplier",
            "description": (
                "Increasing: wider stop, fewer premature stop-outs but larger losses. "
                "Decreasing: tighter stop, stops out more often, smaller max loss."
            ),
        },
        "tp_atr_mult": {
            "type": "float", "default": 1.5, "min": 0.1, "max": 10.0,
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

    # ── Strategy interface ──────────────────────────────────────────────────

    def should_long(self) -> bool:
        if len(self.candles) < self.MIN_WARMUP_CANDLES:
            return False
        return self._crossed_above() and self._is_volatile()

    def should_short(self) -> bool:
        if len(self.candles) < self.MIN_WARMUP_CANDLES:
            return False
        return self._crossed_below() and self._is_volatile()

    def should_cancel_entry(self) -> bool:
        return False

    def go_long(self) -> None:
        stop = self.vars.get("atr_stop_long", self.price * 0.99)
        self.vars["str_sl"] = stop
        qty = self.size_by_risk(stop)
        self.buy         = qty, self.price
        self.stop_loss   = qty, stop
        self.take_profit = qty, self.vars.get("atr_tp_long", self.price * 1.01)

    def go_short(self) -> None:
        stop = self.vars.get("atr_stop_short", self.price * 1.01)
        self.vars["str_sl"] = stop
        qty = self.size_by_risk(stop)
        self.sell        = qty, self.price
        self.stop_loss   = qty, stop
        self.take_profit = qty, self.vars.get("atr_tp_short", self.price * 0.99)

    def update_position(self) -> None:
        """
        Stop-and-reverse: if we are long and a short signal fires (or vice
        versa), flip atomically. The engine closes the open leg and opens the
        opposite one as a single unit, with the new SL/TP armed immediately.
        """
        if not self._is_volatile():
            return

        if self.is_long and self._crossed_below():
            stop = self.vars.get("atr_stop_short", self.price * 1.01)
            qty  = self.size_by_risk(stop)
            self.flip_position(
                qty,
                stop_loss=stop,
                take_profit=self.vars.get("atr_tp_short", self.price * 0.99),
            )

        elif self.is_short and self._crossed_above():
            stop = self.vars.get("atr_stop_long", self.price * 0.99)
            qty  = self.size_by_risk(stop)
            self.flip_position(
                qty,
                stop_loss=stop,
                take_profit=self.vars.get("atr_tp_long", self.price * 1.01),
            )
