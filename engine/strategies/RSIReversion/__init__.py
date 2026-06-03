from engine.core.strategy import BaseStrategy
import engine.indicators as ta


class RSIReversion(BaseStrategy):
    """
    RSI Mean Reversion Strategy.
    Goes long when RSI is oversold (below 30).
    Goes short when RSI is overbought (above 70).
    Exits when RSI reaches the opposite extreme or middle (50).
    """

    @property
    def rsi(self):
        return ta.rsi(self.candles, period=14)

    def should_long(self) -> bool:
        return self.rsi < 30

    def should_short(self) -> bool:
        return self.rsi > 70

    def should_cancel_entry(self) -> bool:
        return False

    def go_long(self) -> None:
        qty = self.balance * 0.1 / self.price
        atr = ta.atr(self.candles, period=14)
        self.buy = qty, self.price
        self.stop_loss = qty, self.price - (2 * atr)
        self.take_profit = qty, self.price + (4 * atr)

    def go_short(self) -> None:
        qty = self.balance * 0.1 / self.price
        atr = ta.atr(self.candles, period=14)
        self.sell = qty, self.price
        self.stop_loss = qty, self.price + (2 * atr)
        self.take_profit = qty, self.price - (4 * atr)

    def update_position(self) -> None:
        if self.is_long and self.rsi > 50:
            self.liquidate()
        elif self.is_short and self.rsi < 50:
            self.liquidate()
