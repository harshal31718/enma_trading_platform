from engine.core.strategy import BaseStrategy
import engine.indicators as ta


class MicroScalper(BaseStrategy):
    """
    High-frequency stop-and-reverse scalper built for pipeline stress testing.

    Goal: maximum trade volume, not profit.
    Logic: 3/9 EMA crossover on 1m candles with an optional ATR volatility
    filter. Always in a position — every crossover flips the bias immediately.

    Recommended backtest / live settings:
        Symbol   : BTCUSDT or any high-liquidity futures pair
        Timeframe: 1m
        Capital  : any
        Leverage : 1–5x
    """

    PARAMS = {
        "fast_period": {
            "type": "int",
            "default": 3,
            "min": 2,
            "max": 20,
            "label": "Fast EMA Period"
        },
        "slow_period": {
            "type": "int",
            "default": 9,
            "min": 3,
            "max": 50,
            "label": "Slow EMA Period"
        },
        "atr_period": {
            "type": "int",
            "default": 14,
            "min": 5,
            "max": 50,
            "label": "ATR Period"
        },
        "atr_multiplier": {
            "type": "float",
            "default": 0.5,
            "min": 0.0,
            "max": 3.0,
            "label": "ATR Volatility Threshold Multiplier (0 = filter off)"
        },
        "risk_pct": {
            "type": "float",
            "default": 0.05,
            "min": 0.01,
            "max": 1.0,
            "label": "Risk % of Balance per Trade"
        },
        "sl_atr_mult": {
            "type": "float",
            "default": 1.0,
            "min": 0.1,
            "max": 5.0,
            "label": "Stop-Loss ATR Multiplier"
        },
        "tp_atr_mult": {
            "type": "float",
            "default": 1.5,
            "min": 0.1,
            "max": 10.0,
            "label": "Take-Profit ATR Multiplier"
        },
    }

    def __init__(self):
        super().__init__()
        # Param defaults — overwritten by engine before first candle
        self.fast_period: int = self.PARAMS["fast_period"]["default"]
        self.slow_period: int = self.PARAMS["slow_period"]["default"]
        self.atr_period: int = self.PARAMS["atr_period"]["default"]
        self.atr_multiplier: float = self.PARAMS["atr_multiplier"]["default"]
        self.risk_pct: float = self.PARAMS["risk_pct"]["default"]
        self.sl_atr_mult: float = self.PARAMS["sl_atr_mult"]["default"]
        self.tp_atr_mult: float = self.PARAMS["tp_atr_mult"]["default"]

    # ------------------------------------------------------------------
    # Indicators
    # ------------------------------------------------------------------

    @property
    def fast_ema(self) -> float:
        return ta.ema(self.candles, period=self.fast_period)

    @property
    def slow_ema(self) -> float:
        return ta.ema(self.candles, period=self.slow_period)

    @property
    def fast_ema_prev(self) -> float:
        return ta.ema(self.candles[:-1], period=self.fast_period)

    @property
    def slow_ema_prev(self) -> float:
        return ta.ema(self.candles[:-1], period=self.slow_period)

    @property
    def atr(self) -> float:
        return ta.atr(self.candles, period=self.atr_period)

    @property
    def atr_sma(self) -> float:
        """Rolling SMA of ATR values — used as the volatility baseline."""
        atr_values = ta.atr(self.candles, period=self.atr_period, sequential=True)
        import talib
        result = talib.SMA(atr_values, timeperiod=self.atr_period * 2)
        return float(result[-1])

    # ------------------------------------------------------------------
    # Volatility gate
    # ------------------------------------------------------------------

    def _is_volatile(self) -> bool:
        """
        Returns True if the market is volatile enough to trade.
        If atr_multiplier is 0.0 the filter is completely disabled —
        the strategy will trade in all market conditions (maximum churn).
        """
        if self.atr_multiplier == 0.0:
            return True
        return self.atr > (self.atr_sma * self.atr_multiplier)

    # ------------------------------------------------------------------
    # Crossover detection
    # ------------------------------------------------------------------

    def _crossed_above(self) -> bool:
        return (
            self.fast_ema > self.slow_ema
            and self.fast_ema_prev <= self.slow_ema_prev
        )

    def _crossed_below(self) -> bool:
        return (
            self.fast_ema < self.slow_ema
            and self.fast_ema_prev >= self.slow_ema_prev
        )

    # ------------------------------------------------------------------
    # Strategy interface
    # ------------------------------------------------------------------

    def should_long(self) -> bool:
        return self._crossed_above() and self._is_volatile()

    def should_short(self) -> bool:
        return self._crossed_below() and self._is_volatile()

    def should_cancel_entry(self) -> bool:
        # Never cancel — we want every entry to fire
        return False

    def go_long(self) -> None:
        qty = (self.balance * self.risk_pct) / self.price
        atr = self.atr

        self.buy = qty, self.price
        self.stop_loss = qty, self.price - (self.sl_atr_mult * atr)
        self.take_profit = qty, self.price + (self.tp_atr_mult * atr)

    def go_short(self) -> None:
        qty = (self.balance * self.risk_pct) / self.price
        atr = self.atr

        self.sell = qty, self.price
        self.stop_loss = qty, self.price + (self.sl_atr_mult * atr)
        self.take_profit = qty, self.price - (self.tp_atr_mult * atr)

    def update_position(self) -> None:
        """
        Stop-and-reverse: if we are long and a short signal fires (or vice
        versa), close the current position immediately by setting the
        opposing order. The engine will close the open leg and open the new
        one on the same candle.
        """
        if self.is_long and self._crossed_below() and self._is_volatile():
            # Close long, flip to short
            qty = (self.balance * self.risk_pct) / self.price
            atr = self.atr
            self.sell = qty, self.price
            self.stop_loss = qty, self.price + (self.sl_atr_mult * atr)
            self.take_profit = qty, self.price - (self.tp_atr_mult * atr)

        elif self.is_short and self._crossed_above() and self._is_volatile():
            # Close short, flip to long
            qty = (self.balance * self.risk_pct) / self.price
            atr = self.atr
            self.buy = qty, self.price
            self.stop_loss = qty, self.price - (self.sl_atr_mult * atr)
            self.take_profit = qty, self.price + (self.tp_atr_mult * atr)
