import numpy as np

from engine.core.strategy import BaseStrategy
import engine.indicators as ta


class AdaptiveTrend(BaseStrategy):
    """
    Multi-factor, regime-aware trend-following strategy for BTC/ETH.

    DESIGN
    ------
    Four independent layers must agree before any trade is taken:

      1. REGIME FILTER — long trend EMA (default 200) defines direction.
         Longs only when price > trend EMA AND trend EMA is rising.
         Shorts only when price < trend EMA AND trend EMA is falling.

      2. MOMENTUM TRIGGER — fast/slow EMA crossover (default 21/55) fires
         the entry, but only in the regime-allowed direction.

      3. VOLATILITY GATE — ATR must be above a floor relative to its own
         rolling average (set atr_floor_mult = 0 to disable).

      4. ADAPTIVE RISK — volatility-targeted sizing and chandelier trailing
         stop (trail_atr_mult * ATR off the highest price since entry).

    D-01/D-03 FIX: All indicators computed once in before(), stored in
    self.vars. Zero TA-Lib calls in any other hook.

    Recommended:
        Symbol   : BTCUSDT, ETHUSDT
        Timeframe: 4h (primary) or 1h
        Leverage : 1–3x
    """

    # trend_period (200) + slope_lookback (5) + 10 buffer
    MIN_WARMUP_CANDLES: int = 215

    PARAMS = {
        "trend_period": {
            "type": "int", "default": 200, "min": 50, "max": 400,
            "label": "Trend Regime EMA Period",
            "description": (
                "Increasing: longer-term trend filter, ignores shorter swings, fewer trades. "
                "Decreasing: shorter trend view, more sensitive to medium-term moves, more trades."
            ),
        },
        "slope_lookback": {
            "type": "int", "default": 5, "min": 1, "max": 50,
            "label": "Trend Slope Lookback (bars)",
            "description": (
                "Increasing: requires a stronger, longer slope to confirm trend direction. "
                "Decreasing: more sensitive to short-term slope changes."
            ),
        },
        "fast_period": {
            "type": "int", "default": 21, "min": 3, "max": 100,
            "label": "Fast EMA Period (entry trigger)",
            "description": (
                "Increasing: slower fast EMA, fewer crossovers, less responsive to price. "
                "Decreasing: faster crossovers, more signals, more whipsaws."
            ),
        },
        "slow_period": {
            "type": "int", "default": 55, "min": 10, "max": 200,
            "label": "Slow EMA Period (entry trigger)",
            "description": (
                "Increasing: more lag before crossover, stronger confirmation. "
                "Decreasing: crossovers fire faster, noisier signals."
            ),
        },
        "atr_period": {
            "type": "int", "default": 14, "min": 5, "max": 50,
            "label": "ATR Period",
            "description": (
                "Increasing: smoother, slower ATR estimate, less responsive to volatility spikes. "
                "Decreasing: more reactive ATR, stop and sizing update faster."
            ),
        },
        "atr_floor_mult": {
            "type": "float", "default": 0.8, "min": 0.0, "max": 3.0,
            "label": "Volatility Floor (ATR vs its avg; 0 = off)",
            "description": (
                "Increasing: stricter volatility gate, sits out more low-volatility periods. "
                "Decreasing: trades in quieter markets; 0 disables the gate entirely."
            ),
        },
        "sl_atr_mult": {
            "type": "float", "default": 2.0, "min": 0.5, "max": 6.0,
            "label": "Initial Stop Distance (ATR multiple)",
            "description": (
                "Increasing: wider initial stop, survives more noise, larger potential loss per trade. "
                "Decreasing: tighter stop, stops out more easily, smaller max loss."
            ),
        },
        "trail_atr_mult": {
            "type": "float", "default": 3.0, "min": 0.5, "max": 10.0,
            "label": "Chandelier Trailing Distance (ATR multiple)",
            "description": (
                "Increasing: stop trails further from peak, lets winners run longer but gives back more profit. "
                "Decreasing: tighter trailing stop, locks in profit sooner but cuts winners short."
            ),
        },
        "breakeven_r": {
            "type": "float", "default": 1.0, "min": 0.0, "max": 5.0,
            "label": "Move Stop to Breakeven After (R multiple; 0 = off)",
            "description": (
                "Increasing: waits for more profit before moving stop to entry. "
                "Decreasing: moves stop to breakeven sooner; 0 disables the feature."
            ),
        },
        "tp_r_mult": {
            "type": "float", "default": 0.0, "min": 0.0, "max": 20.0,
            "label": "Fixed Take-Profit (R multiple; 0 = pure trailing)",
            "description": (
                "Increasing: sets a higher fixed TP target, combines with trailing. "
                "Decreasing: TP fires sooner; 0 = pure trailing stop exit only."
            ),
        },
        "max_leverage": {
            "type": "float", "default": 3.0, "min": 1.0, "max": 20.0,
            "label": "Max Notional Leverage Cap",
            "description": (
                "Increasing: allows larger positions as a multiple of equity. "
                "Decreasing: caps position size more conservatively."
            ),
        },
        "allow_shorts": {
            "type": "int", "default": 1, "min": 0, "max": 1,
            "label": "Allow Short Trades (1 = yes, 0 = long-only)",
            "description": (
                "Increasing to 1: strategy trades both directions. "
                "Decreasing to 0: long-only mode, ignores all short signals."
            ),
        },
    }

    def __init__(self):
        super().__init__()
        self.trend_period:   int   = self.PARAMS["trend_period"]["default"]
        self.slope_lookback: int   = self.PARAMS["slope_lookback"]["default"]
        self.fast_period:    int   = self.PARAMS["fast_period"]["default"]
        self.slow_period:    int   = self.PARAMS["slow_period"]["default"]
        self.atr_period:     int   = self.PARAMS["atr_period"]["default"]
        self.atr_floor_mult: float = self.PARAMS["atr_floor_mult"]["default"]
        self.sl_atr_mult:    float = self.PARAMS["sl_atr_mult"]["default"]
        self.trail_atr_mult: float = self.PARAMS["trail_atr_mult"]["default"]
        self.breakeven_r:    float = self.PARAMS["breakeven_r"]["default"]
        self.tp_r_mult:      float = self.PARAMS["tp_r_mult"]["default"]
        self.max_leverage:   float = self.PARAMS["max_leverage"]["default"]
        self.allow_shorts:   int   = self.PARAMS["allow_shorts"]["default"]

        # Per-trade state — reset on every entry
        self._entry_qty:     float = 0.0
        self._entry_price:   float = 0.0
        self._initial_risk:  float = 0.0
        self._current_stop:  float = 0.0
        self._extreme:       float = 0.0

    def validate_params(self) -> None:
        if self.fast_period >= self.slow_period:
            raise ValueError(
                f"fast_period ({self.fast_period}) must be less than slow_period ({self.slow_period})"
            )
        if self.trail_atr_mult < self.sl_atr_mult:
            raise ValueError(
                f"trail_atr_mult ({self.trail_atr_mult}) should be >= sl_atr_mult ({self.sl_atr_mult})"
            )

    # ── Indicators — computed once per candle in before() ──────────────────
    # D-01 fix: Previously 9+ TA-Lib calls per candle via @property accessors.
    # Now computed exactly once and stored in self.vars.

    def before(self) -> None:
        n = len(self.candles)
        if n < self.MIN_WARMUP_CANDLES:
            return

        # Trend regime (long EMA + slope)
        trend_ema      = ta.ema(self.candles, period=self.trend_period)
        trend_ema_prev = ta.ema(self.candles[:-self.slope_lookback], period=self.trend_period)
        self.vars["trend_ema"]      = trend_ema
        self.vars["trend_ema_prev"] = trend_ema_prev

        # Entry trigger (fast/slow EMA crossover)
        self.vars["fast_ema"]      = ta.ema(self.candles,      period=self.fast_period)
        self.vars["slow_ema"]      = ta.ema(self.candles,      period=self.slow_period)
        self.vars["fast_ema_prev"] = ta.ema(self.candles[:-1], period=self.fast_period)
        self.vars["slow_ema_prev"] = ta.ema(self.candles[:-1], period=self.slow_period)

        # Volatility
        atr = ta.atr(self.candles, period=self.atr_period)
        self.vars["atr"] = atr

        # ATR baseline for volatility gate (rolling mean of ATR series)
        if self.atr_floor_mult > 0.0:
            series = ta.atr(self.candles, period=self.atr_period, sequential=True)
            window = series[-(self.atr_period * 2):]
            window = window[~np.isnan(window)]
            self.vars["atr_baseline"] = float(np.mean(window)) if window.size > 0 else 0.0
        else:
            self.vars["atr_baseline"] = 0.0

        risk_per_unit = self.sl_atr_mult * atr
        self.vars["atr_stop_long"]  = self.price - risk_per_unit
        self.vars["atr_stop_short"] = self.price + risk_per_unit
        self.vars["risk_per_unit"]  = risk_per_unit

    # ── Regime and entry filter helpers ────────────────────────────────────

    def _is_alive(self) -> bool:
        """Volatility gate — sits out dead, range-bound markets."""
        if self.atr_floor_mult <= 0.0:
            return True
        baseline = self.vars.get("atr_baseline", 0.0)
        atr      = self.vars.get("atr", 0.0)
        if baseline <= 0:
            return True
        return atr > (baseline * self.atr_floor_mult)

    def _uptrend(self) -> bool:
        return (
            self.price > self.vars.get("trend_ema", self.price) and
            self.vars.get("trend_ema", 0) > self.vars.get("trend_ema_prev", 0)
        )

    def _downtrend(self) -> bool:
        return (
            self.price < self.vars.get("trend_ema", self.price) and
            self.vars.get("trend_ema", 0) < self.vars.get("trend_ema_prev", 0)
        )

    def _cross_up(self) -> bool:
        return (
            self.vars.get("fast_ema", 0) > self.vars.get("slow_ema", 0) and
            self.vars.get("fast_ema_prev", 0) <= self.vars.get("slow_ema_prev", 0)
        )

    def _cross_down(self) -> bool:
        return (
            self.vars.get("fast_ema", 0) < self.vars.get("slow_ema", 0) and
            self.vars.get("fast_ema_prev", 0) >= self.vars.get("slow_ema_prev", 0)
        )

    # ── Entry decisions ─────────────────────────────────────────────────────

    def should_long(self) -> bool:
        if len(self.candles) < self.MIN_WARMUP_CANDLES:
            return False
        atr = self.vars.get("atr", 0.0)
        if not atr or atr <= 0:
            return False
        if not self._is_alive():
            return False
        return self._uptrend() and self._cross_up()

    def should_short(self) -> bool:
        if not self.allow_shorts:
            return False
        if len(self.candles) < self.MIN_WARMUP_CANDLES:
            return False
        atr = self.vars.get("atr", 0.0)
        if not atr or atr <= 0:
            return False
        if not self._is_alive():
            return False
        return self._downtrend() and self._cross_down()

    def should_cancel_entry(self) -> bool:
        return False

    # ── Order placement ─────────────────────────────────────────────────────

    def _position_qty(self, entry: float, risk_per_unit: float) -> float:
        if risk_per_unit <= 0 or entry <= 0:
            return 0.0
        risk_capital = self.equity * self.risk_pct
        qty = risk_capital / risk_per_unit
        lev_cap = (self.equity * self.max_leverage) / entry
        return min(qty, lev_cap, self.max_qty(entry))

    def _reset_trade_state(self, entry: float, risk_per_unit: float,
                           qty: float, stop: float) -> None:
        self._entry_price  = entry
        self._initial_risk = risk_per_unit
        self._entry_qty    = qty
        self._current_stop = stop
        self._extreme      = entry

    def go_long(self) -> None:
        entry        = self.price
        risk_per_unit = self.vars.get("risk_per_unit", self.sl_atr_mult * self.vars.get("atr", 0))
        qty          = self._position_qty(entry, risk_per_unit)
        if qty <= 0:
            return
        stop = self.vars.get("atr_stop_long", entry - risk_per_unit)
        self.vars["str_sl"] = stop
        self.buy       = qty, entry
        self.stop_loss = qty, stop
        if self.tp_r_mult > 0:
            self.take_profit = qty, entry + (self.tp_r_mult * risk_per_unit)
        self._reset_trade_state(entry, risk_per_unit, qty, stop)

    def go_short(self) -> None:
        entry        = self.price
        risk_per_unit = self.vars.get("risk_per_unit", self.sl_atr_mult * self.vars.get("atr", 0))
        qty          = self._position_qty(entry, risk_per_unit)
        if qty <= 0:
            return
        stop = self.vars.get("atr_stop_short", entry + risk_per_unit)
        self.vars["str_sl"] = stop
        self.sell      = qty, entry
        self.stop_loss = qty, stop
        if self.tp_r_mult > 0:
            self.take_profit = qty, entry - (self.tp_r_mult * risk_per_unit)
        self._reset_trade_state(entry, risk_per_unit, qty, stop)

    # ── Open-position management: chandelier trailing + breakeven ───────────
    # SL moves in update_position() only tighten, never loosen.

    def update_position(self) -> None:
        atr = self.vars.get("atr", 0.0)
        if not atr or atr <= 0 or self._entry_qty <= 0:
            return

        if self.is_long:
            if self.price > self._extreme:
                self._extreme = self.price

            candidate = self._extreme - (self.trail_atr_mult * atr)

            if self.breakeven_r > 0 and \
                    self.price >= self._entry_price + (self.breakeven_r * self._initial_risk):
                candidate = max(candidate, self._entry_price)

            # Only tighten
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

            # Only tighten
            new_stop = min(self._current_stop, candidate)
            if new_stop < self._current_stop:
                self._current_stop = new_stop
                self.stop_loss = self._entry_qty, new_stop
