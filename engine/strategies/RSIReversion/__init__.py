from engine.core.strategy import BaseStrategy
import engine.indicators as ta


class RSIReversion(BaseStrategy):
    """
    RSI Mean Reversion Strategy.

    Long entry: RSI crosses BELOW the oversold threshold (fresh reversal signal).
    Short entry: RSI crosses ABOVE the overbought threshold (fresh reversal signal).

    D-09 fix: entry fires on RSI *crossover* (crossing the threshold), NOT on
    RSI simply being below/above the level. This prevents cascading re-entry on
    the same oversold/overbought condition and removes the entry cascade bug.

    Exit: RSI crosses back through the 50 midline using close_position()
    for a guaranteed next-open fill.
    """

    MIN_WARMUP_CANDLES: int = 24   # rsi_period default (14) + buffer

    PARAMS = {
        "rsi_period": {
            "type": "int", "default": 14, "min": 2, "max": 50,
            "label": "RSI Period",
            "description": (
                "Increasing: slower RSI, fewer extremes reached, fewer trades. "
                "Decreasing: faster RSI, more frequent extremes, more trades."
            ),
        },
        "oversold": {
            "type": "int", "default": 30, "min": 10, "max": 45,
            "label": "Oversold Level",
            "description": (
                "Increasing: easier to trigger a long (closer to 50), more trades. "
                "Decreasing: requires deeper oversold condition, fewer but stronger signals."
            ),
        },
        "overbought": {
            "type": "int", "default": 70, "min": 55, "max": 90,
            "label": "Overbought Level",
            "description": (
                "Increasing: requires deeper overbought condition, fewer short signals. "
                "Decreasing: easier to trigger a short (closer to 50), more trades."
            ),
        },
    }

    def __init__(self):
        super().__init__()
        self.rsi_period: int = self.PARAMS["rsi_period"]["default"]
        self.oversold:   int = self.PARAMS["oversold"]["default"]
        self.overbought: int = self.PARAMS["overbought"]["default"]

    def validate_params(self) -> None:
        if self.oversold >= self.overbought:
            raise ValueError(
                f"oversold ({self.oversold}) must be less than overbought ({self.overbought})"
            )

    # ── Indicators — computed once per candle in before() ──────────────────

    def before(self) -> None:
        if len(self.candles) < self.MIN_WARMUP_CANDLES:
            return
        self.vars["rsi"]      = ta.rsi(self.candles,      period=self.rsi_period)
        self.vars["rsi_prev"] = ta.rsi(self.candles[:-1], period=self.rsi_period)
        atr = ta.atr(self.candles, period=14)
        self.vars["atr"]             = atr
        self.vars["atr_stop_long"]   = self.price - 2.0 * atr
        self.vars["atr_stop_short"]  = self.price + 2.0 * atr

    def should_long(self) -> bool:
        """RSI crossover below oversold — D-09 fix: crossover not level."""
        if len(self.candles) < self.MIN_WARMUP_CANDLES:
            return False
        rsi      = self.vars.get("rsi", 50.0)
        rsi_prev = self.vars.get("rsi_prev", 50.0)
        # Cross: was above oversold, now below or equal
        return rsi_prev > self.oversold and rsi <= self.oversold

    def should_short(self) -> bool:
        """RSI crossover above overbought — D-09 fix: crossover not level."""
        if len(self.candles) < self.MIN_WARMUP_CANDLES:
            return False
        rsi      = self.vars.get("rsi", 50.0)
        rsi_prev = self.vars.get("rsi_prev", 50.0)
        # Cross: was below overbought, now above or equal
        return rsi_prev < self.overbought and rsi >= self.overbought

    def should_cancel_entry(self) -> bool:
        return False

    def go_long(self) -> None:
        stop = self.vars.get("atr_stop_long", self.price * 0.98)
        self.vars["str_sl"] = stop
        qty = self.size_by_risk(stop)
        self.buy = qty, self.price
        self.stop_loss   = qty, stop
        self.take_profit = qty, self.rr_target("long", stop, rr=2.0)

    def go_short(self) -> None:
        stop = self.vars.get("atr_stop_short", self.price * 1.02)
        self.vars["str_sl"] = stop
        qty = self.size_by_risk(stop)
        self.sell = qty, self.price
        self.stop_loss   = qty, stop
        self.take_profit = qty, self.rr_target("short", stop, rr=2.0)

    def update_position(self) -> None:
        """Exit when RSI crosses back through the 50 midline."""
        rsi      = self.vars.get("rsi", 50.0)
        rsi_prev = self.vars.get("rsi_prev", 50.0)
        if self.is_long and rsi_prev < 50 and rsi >= 50:
            self.close_position()
        elif self.is_short and rsi_prev > 50 and rsi <= 50:
            self.close_position()
