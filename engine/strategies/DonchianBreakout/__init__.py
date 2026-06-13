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
        "risk_pct": {"type": "float", "default": 0.01, "min": 0.001, "max": 0.1, "label": "Risk % of Equity per Trade"},
    }

    def __init__(self):
        super().__init__()
        self.period = 20
        self.risk_pct = 0.01

    @property
    def upper(self):
        return ta.donchian(self.candles[:-1], period=self.period)[0]

    @property
    def lower(self):
        return ta.donchian(self.candles[:-1], period=self.period)[2]

    @property
    def mid(self):
        return ta.donchian(self.candles[:-1], period=self.period)[1]

    def should_long(self) -> bool:
        return self.close > self.upper

    def should_short(self) -> bool:
        return self.close < self.lower

    def should_cancel_entry(self) -> bool:
        return False

    def go_long(self) -> None:
        # Stop at the lower channel band; target a 1:1 reward on that distance.
        stop = self.lower
        qty = self.size_by_risk(stop)
        self.buy = qty, self.price
        self.stop_loss = qty, stop
        self.take_profit = qty, self.rr_target("long", stop, rr=1.0)

    def go_short(self) -> None:
        stop = self.upper
        qty = self.size_by_risk(stop)
        self.sell = qty, self.price
        self.stop_loss = qty, stop
        self.take_profit = qty, self.rr_target("short", stop, rr=1.0)

    def update_position(self) -> None:
        if self.is_long and self.close < self.mid:
            self.liquidate()
        elif self.is_short and self.close > self.mid:
            self.liquidate()
