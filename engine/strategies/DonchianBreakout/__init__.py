from engine.core.strategy import BaseStrategy
import engine.indicators as ta


class DonchianBreakout(BaseStrategy):
    """
    Donchian Channel Breakout Strategy.
    Goes long when price breaks above the upper Donchian channel.
    Goes short when price breaks below the lower Donchian channel.
    Stop-loss at the opposite channel band.
    """

    PARAMS = {
        "period": {"type": "int", "default": 20, "min": 5, "max": 100, "label": "Donchian Period"},
        "risk_pct": {"type": "float", "default": 0.1, "min": 0.01, "max": 1.0, "label": "Risk % of Balance"},
    }

    def __init__(self):
        super().__init__()
        self.period = 20
        self.risk_pct = 0.1

    @property
    def upper(self):
        return ta.donchian(self.candles, period=self.period)[0]

    @property
    def lower(self):
        return ta.donchian(self.candles, period=self.period)[2]

    @property
    def mid(self):
        return ta.donchian(self.candles, period=self.period)[1]

    def should_long(self) -> bool:
        return self.close > self.upper

    def should_short(self) -> bool:
        return self.close < self.lower

    def should_cancel_entry(self) -> bool:
        return False

    def go_long(self) -> None:
        qty = self.balance * self.risk_pct / self.price
        self.buy = qty, self.price
        self.stop_loss = qty, self.lower
        self.take_profit = qty, self.price + (self.price - self.lower)

    def go_short(self) -> None:
        qty = self.balance * self.risk_pct / self.price
        self.sell = qty, self.price
        self.stop_loss = qty, self.upper
        self.take_profit = qty, self.price - (self.upper - self.price)

    def update_position(self) -> None:
        if self.is_long and self.close < self.mid:
            self.liquidate()
        elif self.is_short and self.close > self.mid:
            self.liquidate()
