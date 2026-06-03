from engine.core.strategy import BaseStrategy
import engine.indicators as ta


class DonchianBreakout(BaseStrategy):
    """
    Donchian Channel Breakout Strategy.
    Goes long when price breaks above the upper Donchian channel.
    Goes short when price breaks below the lower Donchian channel.
    Stop-loss at the opposite channel band.
    """

    @property
    def upper(self):
        return ta.donchian(self.candles, period=20)[0]

    @property
    def lower(self):
        return ta.donchian(self.candles, period=20)[2]

    @property
    def mid(self):
        return ta.donchian(self.candles, period=20)[1]

    def should_long(self) -> bool:
        return self.close > self.upper

    def should_short(self) -> bool:
        return self.close < self.lower

    def should_cancel_entry(self) -> bool:
        return False

    def go_long(self) -> None:
        qty = self.balance * 0.1 / self.price
        self.buy = qty, self.price
        self.stop_loss = qty, self.lower
        self.take_profit = qty, self.price + (self.price - self.lower)

    def go_short(self) -> None:
        qty = self.balance * 0.1 / self.price
        self.sell = qty, self.price
        self.stop_loss = qty, self.upper
        self.take_profit = qty, self.price - (self.upper - self.price)

    def update_position(self) -> None:
        if self.is_long and self.close < self.mid:
            self.liquidate()
        elif self.is_short and self.close > self.mid:
            self.liquidate()
