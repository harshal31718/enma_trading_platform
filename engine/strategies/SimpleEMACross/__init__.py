from engine.core.strategy import BaseStrategy
import engine.indicators as ta


class SimpleEMACross(BaseStrategy):
    """
    Simple EMA Crossover Strategy.
    Goes long when fast EMA crosses above slow EMA.
    Goes short when fast EMA crosses below slow EMA.
    Uses ATR for dynamic stop-loss sizing.
    """

    PARAMS = {
        "fast_period": {"type": "int", "default": 9, "min": 2, "max": 50, "label": "Fast EMA Period"},
        "slow_period": {"type": "int", "default": 21, "min": 5, "max": 200, "label": "Slow EMA Period"},
        "risk_pct": {"type": "float", "default": 0.01, "min": 0.001, "max": 0.1, "label": "Risk % of Equity per Trade"},
    }

    def __init__(self):
        super().__init__()
        self.fast_period = 9
        self.slow_period = 21
        self.risk_pct = 0.01

    @property
    def fast_ema(self):
        return ta.ema(self.candles, period=self.fast_period)

    @property
    def slow_ema(self):
        return ta.ema(self.candles, period=self.slow_period)

    @property
    def fast_ema_prev(self):
        return ta.ema(self.candles[:-1], period=self.fast_period)

    @property
    def slow_ema_prev(self):
        return ta.ema(self.candles[:-1], period=self.slow_period)

    def should_long(self) -> bool:
        return (self.fast_ema > self.slow_ema and
                self.fast_ema_prev <= self.slow_ema_prev)

    def should_short(self) -> bool:
        return (self.fast_ema < self.slow_ema and
                self.fast_ema_prev >= self.slow_ema_prev)

    def should_cancel_entry(self) -> bool:
        return False

    def go_long(self) -> None:
        # Risk-based sizing: a 2-ATR stop loses exactly risk_pct of equity.
        stop = self.atr_stop("long", mult=2.0, period=14)
        qty = self.size_by_risk(stop)
        self.buy = qty, self.price
        self.stop_loss = qty, stop
        self.take_profit = qty, self.rr_target("long", stop, rr=1.5)  # 3-ATR target

    def go_short(self) -> None:
        stop = self.atr_stop("short", mult=2.0, period=14)
        qty = self.size_by_risk(stop)
        self.sell = qty, self.price
        self.stop_loss = qty, stop
        self.take_profit = qty, self.rr_target("short", stop, rr=1.5)
