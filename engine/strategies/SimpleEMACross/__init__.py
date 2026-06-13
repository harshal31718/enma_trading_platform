from engine.core.strategy import BaseStrategy
import engine.indicators as ta


class SimpleEMACross(BaseStrategy):
    """
    Simple EMA Crossover Strategy.

    Goes long when fast EMA crosses above slow EMA, short when it crosses below.
    Uses an ATR-based structural SL; final sizing and TP are computed by the
    risk model from self.vars['str_sl'] and the injected risk_pct / rrr.

    Recommended: 1h–4h timeframe on BTC/ETH. Low-frequency, trend-following.
    """

    MIN_WARMUP_CANDLES: int = 35   # slow_period default (21) + 14 ATR + buffer

    PARAMS = {
        "fast_period": {
            "type": "int", "default": 9, "min": 2, "max": 50,
            "label": "Fast EMA Period",
            "description": (
                "Increasing: fewer, more delayed crossover signals. "
                "Decreasing: more frequent, noisier signals."
            ),
        },
        "slow_period": {
            "type": "int", "default": 21, "min": 5, "max": 200,
            "label": "Slow EMA Period",
            "description": (
                "Increasing: longer trend confirmation, fewer trades. "
                "Decreasing: shorter confirmation, more trades with more whipsaws."
            ),
        },
    }

    def __init__(self):
        super().__init__()
        self.fast_period: int = self.PARAMS["fast_period"]["default"]
        self.slow_period: int = self.PARAMS["slow_period"]["default"]

    def validate_params(self) -> None:
        if self.fast_period >= self.slow_period:
            raise ValueError(
                f"fast_period ({self.fast_period}) must be less than "
                f"slow_period ({self.slow_period})"
            )

    # ── Indicators — computed once per candle in before() ──────────────────

    def before(self) -> None:
        if len(self.candles) < self.MIN_WARMUP_CANDLES:
            return
        self.vars["fast_ema"]      = ta.ema(self.candles,       period=self.fast_period)
        self.vars["slow_ema"]      = ta.ema(self.candles,       period=self.slow_period)
        self.vars["fast_ema_prev"] = ta.ema(self.candles[:-1],  period=self.fast_period)
        self.vars["slow_ema_prev"] = ta.ema(self.candles[:-1],  period=self.slow_period)
        atr = ta.atr(self.candles, period=14)
        self.vars["atr"] = atr
        self.vars["atr_stop_long"]  = self.price - 2.0 * atr
        self.vars["atr_stop_short"] = self.price + 2.0 * atr

    def should_long(self) -> bool:
        if len(self.candles) < self.MIN_WARMUP_CANDLES:
            return False
        return (
            self.vars.get("fast_ema", 0) > self.vars.get("slow_ema", 0) and
            self.vars.get("fast_ema_prev", 0) <= self.vars.get("slow_ema_prev", 0)
        )

    def should_short(self) -> bool:
        if len(self.candles) < self.MIN_WARMUP_CANDLES:
            return False
        return (
            self.vars.get("fast_ema", 0) < self.vars.get("slow_ema", 0) and
            self.vars.get("fast_ema_prev", 0) >= self.vars.get("slow_ema_prev", 0)
        )

    def go_long(self) -> None:
        stop = self.vars.get("atr_stop_long", self.price * 0.98)
        # Signal ATR-based SL to risk model; final SL/TP/qty are computed by runner
        self.vars["str_sl"] = stop
        qty = self.size_by_risk(stop)
        self.buy = qty, self.price
        self.stop_loss   = qty, stop
        self.take_profit = qty, self.rr_target("long", stop, rr=1.5)

    def go_short(self) -> None:
        stop = self.vars.get("atr_stop_short", self.price * 1.02)
        self.vars["str_sl"] = stop
        qty = self.size_by_risk(stop)
        self.sell = qty, self.price
        self.stop_loss   = qty, stop
        self.take_profit = qty, self.rr_target("short", stop, rr=1.5)

    def should_cancel_entry(self) -> bool:
        return False
