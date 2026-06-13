import numpy as np

from engine.core.strategy import BaseStrategy
import engine.indicators as ta


class AdaptiveTrend(BaseStrategy):
    """
    Multi-factor, regime-aware trend-following strategy for BTC/ETH and other
    high-liquidity pairs.

    DESIGN
    ------
    The edge here is structural, not a magic indicator. Four independent layers
    must agree before any trade is taken, and risk is sized to volatility:

      1. REGIME FILTER (the "higher timeframe" proxy)
         A long trend EMA (default 200) defines the dominant direction.
         Longs only when price > trend EMA *and* the trend EMA is rising.
         Shorts only when price < trend EMA *and* the trend EMA is falling.
         This is the single-timeframe equivalent of Elder's Triple Screen /
         the classic "trade with the daily trend" rule.

      2. MOMENTUM TRIGGER
         A fast/slow EMA crossover (default 21/55) fires the entry, but only
         in the direction the regime filter already allows. Counter-trend
         crosses are ignored — this is what removes most of the noise that
         kills naive crossover systems.

      3. VOLATILITY GATE
         ATR must be above a floor relative to its own rolling average, so the
         bot sits out dead, range-bound chop. Set atr_floor_mult = 0 to disable.

      4. ADAPTIVE RISK (the part most retail strategies get wrong)
         - Position size is volatility-targeted: every trade risks a fixed %
           of equity. Size = (equity * risk_pct) / (sl_atr_mult * ATR), capped
           by max_leverage and by what the engine's configured leverage can
           actually afford, so it never exceeds available margin.
         - Initial stop is ATR-based (sl_atr_mult * ATR).
         - Exit is a CHANDELIER TRAILING STOP (trail_atr_mult * ATR off the
           highest price since entry), which lets winners run — the exit style
           that most improved risk-adjusted return in published BTC trend tests.
         - Stop ratchets to breakeven after breakeven_r of profit.
         - Optional fixed take-profit (tp_r_mult, in R); 0 = pure trailing.

    NOTE ON SHORTS
    --------------
    Crypto has a structural long bias, so shorting fights the tide. allow_shorts
    defaults to ON, but consider disabling it (set to 0) for spot-style behavior.

    RECOMMENDED CONFIG
    ------------------
        Symbol(s) : BTCUSDT, ETHUSDT (or other deep-liquidity pairs)
        Timeframe : 4h (primary) or 1h. Avoid sub-15m — trend logic needs room.
        Mode      : paper first, always.
        Leverage  : low (1-3x). The strategy sizes risk itself; leverage only
                    raises the notional cap.

    IMPORTANT
    ---------
    This is a starting framework, not a guaranteed money-maker. Before trusting
    it: backtest across BOTH trending and choppy periods, walk-forward validate
    (separate tune/test windows), and account for fees, slippage, and perp
    funding — any of which can erode a real edge. Treat backtest output as
    evidence, not proof.

    Built only on ta.ema / ta.atr for engine compatibility.
    """

    PARAMS = {
        "trend_period": {
            "type": "int", "default": 200, "min": 50, "max": 400,
            "label": "Trend Regime EMA Period",
        },
        "slope_lookback": {
            "type": "int", "default": 5, "min": 1, "max": 50,
            "label": "Trend Slope Lookback (bars)",
        },
        "fast_period": {
            "type": "int", "default": 21, "min": 3, "max": 100,
            "label": "Fast EMA Period (entry trigger)",
        },
        "slow_period": {
            "type": "int", "default": 55, "min": 10, "max": 200,
            "label": "Slow EMA Period (entry trigger)",
        },
        "atr_period": {
            "type": "int", "default": 14, "min": 5, "max": 50,
            "label": "ATR Period",
        },
        "atr_floor_mult": {
            "type": "float", "default": 0.8, "min": 0.0, "max": 3.0,
            "label": "Volatility Floor (ATR vs its avg; 0 = off)",
        },
        "risk_pct": {
            "type": "float", "default": 0.01, "min": 0.001, "max": 0.1,
            "label": "Risk % of Equity per Trade",
        },
        "sl_atr_mult": {
            "type": "float", "default": 2.0, "min": 0.5, "max": 6.0,
            "label": "Initial Stop Distance (ATR multiple)",
        },
        "trail_atr_mult": {
            "type": "float", "default": 3.0, "min": 0.5, "max": 10.0,
            "label": "Chandelier Trailing Distance (ATR multiple)",
        },
        "breakeven_r": {
            "type": "float", "default": 1.0, "min": 0.0, "max": 5.0,
            "label": "Move Stop to Breakeven After (R multiple; 0 = off)",
        },
        "tp_r_mult": {
            "type": "float", "default": 0.0, "min": 0.0, "max": 20.0,
            "label": "Fixed Take-Profit (R multiple; 0 = pure trailing)",
        },
        "max_leverage": {
            "type": "float", "default": 3.0, "min": 1.0, "max": 20.0,
            "label": "Max Notional Leverage Cap",
        },
        "allow_shorts": {
            "type": "int", "default": 1, "min": 0, "max": 1,
            "label": "Allow Short Trades (1 = yes, 0 = long-only)",
        },
    }

    def __init__(self):
        super().__init__()
        # Param defaults — overwritten by the engine before the first candle.
        self.trend_period: int = self.PARAMS["trend_period"]["default"]
        self.slope_lookback: int = self.PARAMS["slope_lookback"]["default"]
        self.fast_period: int = self.PARAMS["fast_period"]["default"]
        self.slow_period: int = self.PARAMS["slow_period"]["default"]
        self.atr_period: int = self.PARAMS["atr_period"]["default"]
        self.atr_floor_mult: float = self.PARAMS["atr_floor_mult"]["default"]
        self.risk_pct: float = self.PARAMS["risk_pct"]["default"]
        self.sl_atr_mult: float = self.PARAMS["sl_atr_mult"]["default"]
        self.trail_atr_mult: float = self.PARAMS["trail_atr_mult"]["default"]
        self.breakeven_r: float = self.PARAMS["breakeven_r"]["default"]
        self.tp_r_mult: float = self.PARAMS["tp_r_mult"]["default"]
        self.max_leverage: float = self.PARAMS["max_leverage"]["default"]
        self.allow_shorts: int = self.PARAMS["allow_shorts"]["default"]

        # Per-trade state — reset on every entry.
        self._entry_qty: float = 0.0
        self._entry_price: float = 0.0
        self._initial_risk: float = 0.0   # price distance of the initial stop
        self._current_stop: float = 0.0
        self._extreme: float = 0.0        # best price reached since entry

    # ------------------------------------------------------------------
    # Indicators (latest scalar values, computed off self.candles)
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
    def trend_ema(self) -> float:
        return ta.ema(self.candles, period=self.trend_period)

    @property
    def trend_ema_prev(self) -> float:
        # Trend EMA `slope_lookback` bars ago — used to measure trend slope.
        return ta.ema(self.candles[:-self.slope_lookback], period=self.trend_period)

    @property
    def atr(self) -> float:
        return ta.atr(self.candles, period=self.atr_period)

    @property
    def atr_baseline(self) -> float:
        """Rolling average of ATR — the volatility "normal" the live ATR is
        compared against in the volatility gate.

        NOTE: this must be the mean of the ATR *series*, not ``ta.sma`` (which
        averages closing price). Comparing ATR against a price SMA would make
        the volatility gate reject essentially every candle.
        """
        series = ta.atr(self.candles, period=self.atr_period, sequential=True)
        window = series[-(self.atr_period * 2):]
        window = window[~np.isnan(window)]
        if window.size == 0:
            return 0.0
        return float(np.mean(window))

    # ------------------------------------------------------------------
    # Filters & triggers
    # ------------------------------------------------------------------

    def _has_enough_candles(self) -> bool:
        return len(self.candles) > (self.trend_period + self.slope_lookback + 2)

    def _is_alive(self, atr: float) -> bool:
        """Volatility gate — keeps the bot out of dead, range-bound markets."""
        if self.atr_floor_mult <= 0.0:
            return True
        baseline = self.atr_baseline
        if baseline <= 0:
            return True
        return atr > (baseline * self.atr_floor_mult)

    def _uptrend(self) -> bool:
        return self.price > self.trend_ema and self.trend_ema > self.trend_ema_prev

    def _downtrend(self) -> bool:
        return self.price < self.trend_ema and self.trend_ema < self.trend_ema_prev

    def _cross_up(self) -> bool:
        return (
            self.fast_ema > self.slow_ema
            and self.fast_ema_prev <= self.slow_ema_prev
        )

    def _cross_down(self) -> bool:
        return (
            self.fast_ema < self.slow_ema
            and self.fast_ema_prev >= self.slow_ema_prev
        )

    # ------------------------------------------------------------------
    # Entry decisions
    # ------------------------------------------------------------------

    def should_long(self) -> bool:
        if not self._has_enough_candles():
            return False
        atr = self.atr
        if not atr or atr <= 0:
            return False
        if not self._is_alive(atr):
            return False
        # Layer 1 (regime up) + Layer 2 (fresh momentum cross up)
        return self._uptrend() and self._cross_up()

    def should_short(self) -> bool:
        if not self.allow_shorts:
            return False
        if not self._has_enough_candles():
            return False
        atr = self.atr
        if not atr or atr <= 0:
            return False
        if not self._is_alive(atr):
            return False
        return self._downtrend() and self._cross_down()

    def should_cancel_entry(self) -> bool:
        # Entries fire at market, so there is no resting order to cancel.
        return False

    # ------------------------------------------------------------------
    # Order placement (volatility-targeted sizing + ATR stop)
    # ------------------------------------------------------------------

    def _position_qty(self, entry: float, risk_per_unit: float) -> float:
        """Risk a fixed % of equity, capped by the leverage notional limit and
        by what the engine's configured leverage can actually afford."""
        if risk_per_unit <= 0 or entry <= 0:
            return 0.0
        risk_capital = self.equity * self.risk_pct
        qty = risk_capital / risk_per_unit
        lev_cap = (self.equity * self.max_leverage) / entry
        # max_qty() reflects the engine's configured leverage; staying under it
        # guarantees the order is affordable and won't be rejected on entry.
        return min(qty, lev_cap, self.max_qty(entry))

    def _reset_trade_state(self, entry: float, risk_per_unit: float,
                           qty: float, stop: float) -> None:
        self._entry_price = entry
        self._initial_risk = risk_per_unit
        self._entry_qty = qty
        self._current_stop = stop
        self._extreme = entry

    def go_long(self) -> None:
        entry = self.price
        atr = self.atr
        risk_per_unit = self.sl_atr_mult * atr
        qty = self._position_qty(entry, risk_per_unit)
        if qty <= 0:
            return

        stop = entry - risk_per_unit
        self.buy = qty, entry
        self.stop_loss = qty, stop
        if self.tp_r_mult > 0:
            self.take_profit = qty, entry + (self.tp_r_mult * risk_per_unit)

        self._reset_trade_state(entry, risk_per_unit, qty, stop)

    def go_short(self) -> None:
        entry = self.price
        atr = self.atr
        risk_per_unit = self.sl_atr_mult * atr
        qty = self._position_qty(entry, risk_per_unit)
        if qty <= 0:
            return

        stop = entry + risk_per_unit
        self.sell = qty, entry
        self.stop_loss = qty, stop
        if self.tp_r_mult > 0:
            self.take_profit = qty, entry - (self.tp_r_mult * risk_per_unit)

        self._reset_trade_state(entry, risk_per_unit, qty, stop)

    # ------------------------------------------------------------------
    # Open-position management: chandelier trailing stop + breakeven
    # ------------------------------------------------------------------

    def update_position(self) -> None:
        atr = self.atr
        if not atr or atr <= 0 or self._entry_qty <= 0:
            return

        if self.is_long:
            if self.price > self._extreme:
                self._extreme = self.price

            candidate = self._extreme - (self.trail_atr_mult * atr)

            # Ratchet to breakeven once we are far enough in profit.
            if self.breakeven_r > 0 and \
                    self.price >= self._entry_price + (self.breakeven_r * self._initial_risk):
                candidate = max(candidate, self._entry_price)

            # Stops only move up, never down.
            new_stop = max(self._current_stop, candidate)
            if new_stop > self._current_stop:
                self._current_stop = new_stop
                self.stop_loss = self._entry_qty, new_stop

        elif self.is_short:
            if self.price < self._extreme:
                self._extreme = self.price

            candidate = self._extreme + (self.trail_atr_mult * atr)

            if self.breakeven_r > 0 and \
                    self.price <= self._entry_price - (self.breakeven_r * self._initial_risk):
                candidate = min(candidate, self._entry_price)

            # Stops only move down, never up.
            new_stop = min(self._current_stop, candidate)
            if new_stop < self._current_stop:
                self._current_stop = new_stop
                self.stop_loss = self._entry_qty, new_stop
