from engine.core.strategy import BaseStrategy
import engine.indicators as ta


class SimpleEMACross(BaseStrategy):
    """
    Simple EMA Crossover Strategy.
    Goes long when fast EMA crosses above slow EMA.
    Goes short when fast EMA crosses below slow EMA.
    Uses ATR for dynamic stop-loss sizing.
    """

    @property
    def fast_ema(self):
        return ta.ema(self.candles, period=9)

    @property
    def slow_ema(self):
        return ta.ema(self.candles, period=21)

    @property
    def fast_ema_prev(self):
        return ta.ema(self.candles[:-1], period=9)

    @property
    def slow_ema_prev(self):
        return ta.ema(self.candles[:-1], period=21)

    def should_long(self) -> bool:
        return (self.fast_ema > self.slow_ema and
                self.fast_ema_prev <= self.slow_ema_prev)

    def should_short(self) -> bool:
        return (self.fast_ema < self.slow_ema and
                self.fast_ema_prev >= self.slow_ema_prev)

    def should_cancel_entry(self) -> bool:
        return False

    def go_long(self) -> None:
        qty = self.balance * 0.1 / self.price
        atr = ta.atr(self.candles, period=14)
        self.buy = qty, self.price
        self.stop_loss = qty, self.price - (2 * atr)
        self.take_profit = qty, self.price + (3 * atr)

    def go_short(self) -> None:
        qty = self.balance * 0.1 / self.price
        atr = ta.atr(self.candles, period=14)
        self.sell = qty, self.price
        self.stop_loss = qty, self.price + (2 * atr)
        self.take_profit = qty, self.price - (3 * atr)
