from engine.core.strategy import BaseStrategy
import engine.indicators as ta


class DonchianBreakout(BaseStrategy):
    """
    Donchian Channel Breakout Strategy.

    Goes long when price breaks above the previous-bar upper channel.
    Goes short when price breaks below the previous-bar lower channel.
    Exits to the midline using close_position() — guaranteed next-open fill.

    ta.donchian() is called exactly once per candle inside before(), fixing
    the D-03 design issue where it was called 3× per candle via properties.
    """

    MIN_WARMUP_CANDLES: int = 30   # default period (20) + buffer

    PARAMS = {
        "period": {
            "type": "int", "default": 20, "min": 5, "max": 100,
            "label": "Donchian Period",
            "description": (
                "Increasing: wider channel, fewer breakouts, larger SL distance. "
                "Decreasing: narrower channel, more frequent breakouts, tighter SL."
            ),
        },
    }

    def __init__(self):
        super().__init__()
        self.period: int = self.PARAMS["period"]["default"]

    # ── Indicators — computed once per candle in before() ──────────────────

    def before(self) -> None:
        if len(self.candles) < self.MIN_WARMUP_CANDLES:
            return
        # Use candles[:-1] so we break on confirmed previous-bar channel,
        # avoiding lookahead into the current bar's range.
        upper, mid, lower = ta.donchian(self.candles[:-1], period=self.period)
        self.vars["upper"] = upper
        self.vars["mid"]   = mid
        self.vars["lower"] = lower

    def should_long(self) -> bool:
        if len(self.candles) < self.MIN_WARMUP_CANDLES:
            return False
        return self.close > self.vars.get("upper", float("inf"))

    def should_short(self) -> bool:
        if len(self.candles) < self.MIN_WARMUP_CANDLES:
            return False
        return self.close < self.vars.get("lower", float("-inf"))

    def should_cancel_entry(self) -> bool:
        return False

    def go_long(self) -> None:
        stop = self.vars.get("lower", self.price * 0.97)
        self.vars["str_sl"] = stop          # hint ATR-based SL to risk model
        qty = self.size_by_risk(stop)
        self.buy = qty, self.price
        self.stop_loss   = qty, stop
        self.take_profit = qty, self.rr_target("long", stop, rr=1.0)

    def go_short(self) -> None:
        stop = self.vars.get("upper", self.price * 1.03)
        self.vars["str_sl"] = stop
        qty = self.size_by_risk(stop)
        self.sell = qty, self.price
        self.stop_loss   = qty, stop
        self.take_profit = qty, self.rr_target("short", stop, rr=1.0)

    def update_position(self) -> None:
        """Exit to midline using close_position() — guaranteed next-open fill."""
        mid = self.vars.get("mid")
        if mid is None:
            return
        if self.is_long and self.close < mid:
            self.close_position()
        elif self.is_short and self.close > mid:
            self.close_position()
