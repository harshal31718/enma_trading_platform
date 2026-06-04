from engine.core.strategy import BaseStrategy
import engine.indicators as ta


class RSIReversion(BaseStrategy):
    """
    RSI Mean Reversion Strategy.
    Goes long when RSI is oversold (below 30).
    Goes short when RSI is overbought (above 70).
    Exits when RSI reaches the opposite extreme or middle (50).
    """

    PARAMS = {
        "rsi_period": {"type": "int", "default": 14, "min": 2, "max": 50, "label": "RSI Period"},
        "oversold": {"type": "int", "default": 30, "min": 10, "max": 45, "label": "Oversold Level"},
        "overbought": {"type": "int", "default": 70, "min": 55, "max": 90, "label": "Overbought Level"},
        "risk_pct": {"type": "float", "default": 0.1, "min": 0.01, "max": 1.0, "label": "Risk % of Balance"},
    }

    def __init__(self):
        super().__init__()
        self.rsi_period = 14
        self.oversold = 30
        self.overbought = 70
        self.risk_pct = 0.1

    @property
    def rsi(self):
        return ta.rsi(self.candles, period=self.rsi_period)

    def should_long(self) -> bool:
        return self.rsi < self.oversold

    def should_short(self) -> bool:
        return self.rsi > self.overbought

    def should_cancel_entry(self) -> bool:
        return False

    def go_long(self) -> None:
        qty = self.balance * self.risk_pct / self.price
        atr = ta.atr(self.candles, period=14)
        self.buy = qty, self.price
        self.stop_loss = qty, self.price - (2 * atr)
        self.take_profit = qty, self.price + (4 * atr)

    def go_short(self) -> None:
        qty = self.balance * self.risk_pct / self.price
        atr = ta.atr(self.candles, period=14)
        self.sell = qty, self.price
        self.stop_loss = qty, self.price + (2 * atr)
        self.take_profit = qty, self.price - (4 * atr)

    def update_position(self) -> None:
        if self.is_long and self.rsi > 50:
            self.liquidate()
        elif self.is_short and self.rsi < 50:
            self.liquidate()
