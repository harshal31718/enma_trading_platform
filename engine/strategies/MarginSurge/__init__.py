import numpy as np

from engine.core.strategy import BaseStrategy
import engine.indicators as ta

from engine.core.models import AtrBracketRiskModel, RiskBudgetPortfolio, Signal


def _rolling_percentile_rank(values: np.ndarray, window: int) -> np.ndarray:
    """For each i >= window-1, the fraction of the trailing `window` values
    (ending at i, inclusive) that are <= values[i]; NaN before enough history
    or if the window contains any NaN (matches a naive per-index loop exactly,
    just vectorized via sliding_window_view instead of a Python-level loop —
    needed once this strategy is run through grid search / Monte Carlo, which
    call `prepare()` far more times than a single backtest does).
    """
    from numpy.lib.stride_tricks import sliding_window_view

    n = len(values)
    out = np.full(n, np.nan)
    if n < window:
        return out
    windows = sliding_window_view(values, window)  # shape (n-window+1, window)
    current = windows[:, -1]
    has_nan = np.isnan(windows).any(axis=1)
    with np.errstate(invalid="ignore"):
        rank = np.mean(windows <= current[:, None], axis=1)
    rank[has_nan] = np.nan
    out[window - 1:] = rank
    return out


class MarginSurge(BaseStrategy):
    """
    Volatility-compression breakout scalper (Plan 23 — see
    workspace/plan/23_high-risk-leverage-strategy.md for the full design
    rationale, validation gates, and the leverage-selection process this
    strategy is meant to be run through before any live session).

    Long entry — all of: close breaks above the PRIOR candle's Donchian
    upper band (shifted by 1 — comparing against yesterday's already-formed
    channel, not one that includes today's own high) while that prior
    candle's Bollinger(20) bandwidth sits in the bottom `squeeze_pct` of its
    trailing 200-candle history (compression precondition — breakouts from a
    squeeze carry the edge; breakouts in already-expanded volatility are
    chase entries); ADX(14) >= adx_min and rising vs 3 candles ago (momentum
    confirmation); MFI(14) >= 55 (flow confirmation — volume behind the
    break, not a wick); close > EMA(200) (trend alignment). Short entry is
    the exact mirror.

    Stops/TP/trailing/breakeven and the ATR-percentile volatility floor all
    live in AtrBracketRiskModel (bound below) — this class is Alpha-only.
    The `max_hold_candles` time-stop is the one exception that needs
    strategy-side state (a risk model has no notion of "how long have we
    held"); tracked via self.vars using only self.is_open/self.index (never
    self.position directly) so it behaves identically in backtest and live
    — LiveAdapter does not call on_open_position/on_close_position the way
    BacktestAdapter does, so entry-index tracking cannot depend on those
    hooks without a backtest/live parity gap.

    Recommended:
        Symbol   : BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT (fixed majors — see
                   Plan 23 section 8's resolved open question: dynamic
                   pairlist is a later iteration, not this validation pass)
        Timeframe: 5m or 15m (validate both — see Plan 23 section 8)
        Leverage : selected via Plan 23 section 4's measured process
                   (10/20/35/50 backtested + Monte Carlo ruin/drawdown
                   curves), never a fixed default baked into this file
    """

    # EMA(200) is the longest lookback; the rolling-200 bandwidth-percentile
    # window needs a further ~20 (BB period) + 200 candles before it's valid.
    # 250 covers both with margin and stays well under the live retention
    # cap (MAX_CANDLES_RETAINED=500, Plan 8 Step 8.3/ENG-8) so this strategy
    # becomes ready deterministically live, not just in backtest.
    MIN_WARMUP_CANDLES: int = 250

    _BB_PERIOD = 20
    _BB_STD = 2.0
    _BW_HISTORY_WINDOW = 200
    _ADX_PERIOD = 14
    _MFI_PERIOD = 14
    _EMA_PERIOD = 200
    _ADX_RISING_LOOKBACK = 3
    _MFI_LONG_MIN = 55.0
    _MFI_SHORT_MAX = 45.0

    PARAMS = {
        "dc_period": {
            "type": "int", "default": 20, "min": 10, "max": 55,
            "label": "Donchian Breakout Period",
            "description": (
                "Increasing: breakout level further from price, fewer but more "
                "significant breaks. Decreasing: shorter channel, more frequent "
                "(noisier) breakout signals."
            ),
        },
        "squeeze_pct": {
            "type": "float", "default": 0.30, "min": 0.1, "max": 0.6,
            "label": "Compression Threshold (bottom % of 200-candle bandwidth history)",
            "description": (
                "Increasing: accepts less-compressed setups, more entries but weaker "
                "compression edge. Decreasing: only the tightest squeezes qualify, "
                "fewer but higher-conviction entries."
            ),
        },
        "adx_min": {
            "type": "int", "default": 25, "min": 15, "max": 40,
            "label": "Minimum ADX for Momentum Confirmation",
            "description": (
                "Increasing: requires a stronger trend to confirm the breakout, fewer "
                "false starts. Decreasing: confirms weaker trends too, more entries "
                "including more whipsaws."
            ),
        },
        "sl_atr_mult": {
            "type": "float", "default": 0.75, "min": 0.5, "max": 2.0,
            "label": "Stop-Loss ATR Multiplier",
            "description": (
                "Increasing: wider stop, fewer premature stop-outs but larger loss per "
                "trade and less liquidation clearance at high leverage. Decreasing: "
                "tighter stop (the design's risk unit), more stop-outs, smaller loss per trade."
            ),
        },
        "rrr": {
            "type": "float", "default": 2.0, "min": 1.0, "max": 4.0,
            "label": "Reward:Risk Ratio (take-profit target)",
            "description": (
                "Increasing: further TP target, higher payoff per win but lower win "
                "rate needed carefully against fee drag. Decreasing: closer TP, higher "
                "win rate but smaller payoff — see Plan 23 section 3's breakeven-WR note."
            ),
        },
        "breakeven_r": {
            "type": "float", "default": 1.0, "min": 0.0, "max": 2.0,
            "label": "Move Stop to Breakeven at (R multiple)",
            "description": (
                "Increasing: stop stays at risk longer before locking in breakeven, more "
                "room for the trade to work. Decreasing (incl. 0=off): locks in breakeven "
                "sooner (or never), protects capital earlier at the cost of getting stopped "
                "out of trades that would have run further."
            ),
        },
        "trail_atr_mult": {
            "type": "float", "default": 1.0, "min": 0.0, "max": 3.0,
            "label": "ATR Trailing-Stop Multiplier (after breakeven, 0 = off)",
            "description": (
                "Increasing: looser trail, rides bigger moves but gives back more open "
                "profit. Decreasing (incl. 0=off): tighter trail or none, locks in gains "
                "sooner but caps the runner."
            ),
        },
        "atr_percentile_min": {
            "type": "float", "default": 0.40, "min": 0.0, "max": 0.8,
            "label": "ATR Percentile Floor (0 = off)",
            "description": (
                "Increasing: vetoes entries in an even wider range of low-volatility "
                "conditions (dead-market filter), fewer but cleaner trades. Decreasing "
                "(incl. 0=off): trades in quieter markets too, more entries but more fee "
                "bleed on tight stops in dead markets."
            ),
        },
        "max_hold_candles": {
            "type": "int", "default": 24, "min": 6, "max": 96,
            "label": "Time-Stop (candles)",
            "description": (
                "Increasing: gives compression breakouts more time to develop before a "
                "forced exit, fewer time-stops but more capital tied up in dead trades. "
                "Decreasing: exits stalled trades sooner, frees capital faster but may "
                "cut off slow-developing winners."
            ),
        },
    }

    def __init__(self):
        super().__init__()
        self.dc_period:          int   = self.PARAMS["dc_period"]["default"]
        self.squeeze_pct:        float = self.PARAMS["squeeze_pct"]["default"]
        self.adx_min:            int   = self.PARAMS["adx_min"]["default"]
        self.sl_atr_mult:        float = self.PARAMS["sl_atr_mult"]["default"]
        self.rrr:                float = self.PARAMS["rrr"]["default"]
        self.breakeven_r:        float = self.PARAMS["breakeven_r"]["default"]
        self.trail_atr_mult:     float = self.PARAMS["trail_atr_mult"]["default"]
        self.atr_percentile_min: float = self.PARAMS["atr_percentile_min"]["default"]
        self.max_hold_candles:   int   = self.PARAMS["max_hold_candles"]["default"]

        # Narang Black-Box: bind risk and portfolio models. AtrBracketRiskModel
        # owns the SL/TP bracket, breakeven move, ATR trail, and the
        # atr_percentile_min veto (all read from strategy attrs set here, per
        # its own getattr(s, ...) contract) — none of that logic lives in
        # this class.
        self.risk_model      = AtrBracketRiskModel()
        self.portfolio_model = RiskBudgetPortfolio()

    def validate_params(self) -> None:
        if self.rrr <= 0:
            raise ValueError(f"rrr ({self.rrr}) must be positive")
        if self.sl_atr_mult <= 0:
            raise ValueError(f"sl_atr_mult ({self.sl_atr_mult}) must be positive")
        if self.squeeze_pct <= 0 or self.squeeze_pct > 1:
            raise ValueError(f"squeeze_pct ({self.squeeze_pct}) must be in (0, 1]")

    # ── Phase A: one-time vectorized pre-computation over the FULL array ────
    def prepare(self, candles: np.ndarray) -> None:
        if len(candles) == 0:
            empty = np.array([])
            self._dc_upper = self._dc_lower = empty
            self._bw = self._bw_pct_rank = empty
            self._adx_seq = self._mfi_seq = self._ema200_seq = self._atr_seq = empty
            return

        dc_upper, _dc_mid, dc_lower = ta.donchian(candles, period=self.dc_period, sequential=True)
        self._dc_upper = np.asarray(dc_upper, dtype=float)
        self._dc_lower = np.asarray(dc_lower, dtype=float)

        bb_upper, bb_mid, bb_lower = ta.bollinger_bands(
            candles, period=self._BB_PERIOD, std=self._BB_STD, sequential=True)
        bb_upper = np.asarray(bb_upper, dtype=float)
        bb_mid = np.asarray(bb_mid, dtype=float)
        bb_lower = np.asarray(bb_lower, dtype=float)
        with np.errstate(divide="ignore", invalid="ignore"):
            self._bw = np.where(bb_mid != 0, (bb_upper - bb_lower) / bb_mid, np.nan)
        self._bw_pct_rank = _rolling_percentile_rank(self._bw, self._BW_HISTORY_WINDOW)

        self._adx_seq = np.asarray(ta.adx(candles, period=self._ADX_PERIOD, sequential=True), dtype=float)
        self._mfi_seq = np.asarray(ta.mfi(candles, period=self._MFI_PERIOD, sequential=True), dtype=float)
        self._ema200_seq = np.asarray(ta.ema(candles, period=self._EMA_PERIOD, sequential=True), dtype=float)
        self._atr_seq = np.asarray(ta.atr(candles, period=14, sequential=True), dtype=float)

    # ── Phase B: pure index lookup per candle (no ta.* calls here) ───────────
    def before(self) -> None:
        i = self.index
        if (i + 1) < self.MIN_WARMUP_CANDLES:
            return

        atr = float(self._atr_seq[i])
        self.vars["atr"] = atr
        self.vars["atr_stop_long"]  = self.price - (self.sl_atr_mult * atr)
        self.vars["atr_stop_short"] = self.price + (self.sl_atr_mult * atr)
        # tp_atr_mult intentionally left unset (defaults to 0 inside
        # AtrBracketRiskModel) — the design's TP is `rrr`-based (2R), set
        # via self.rrr above, not a fixed ATR multiple.

        prior = i - 1
        self.vars["dc_upper_prior"] = float(self._dc_upper[prior]) if prior >= 0 else None
        self.vars["dc_lower_prior"] = float(self._dc_lower[prior]) if prior >= 0 else None
        self.vars["bw_pct_prior"]   = (
            float(self._bw_pct_rank[prior])
            if prior >= 0 and not np.isnan(self._bw_pct_rank[prior]) else None
        )

        self.vars["adx"]      = float(self._adx_seq[i]) if not np.isnan(self._adx_seq[i]) else None
        adx_lb = i - self._ADX_RISING_LOOKBACK
        self.vars["adx_rising"] = (
            adx_lb >= 0 and not np.isnan(self._adx_seq[adx_lb]) and self.vars["adx"] is not None
            and self.vars["adx"] > float(self._adx_seq[adx_lb])
        )
        self.vars["mfi"] = float(self._mfi_seq[i]) if not np.isnan(self._mfi_seq[i]) else None
        self.vars["ema200"] = float(self._ema200_seq[i]) if not np.isnan(self._ema200_seq[i]) else None

        # Time-stop bookkeeping — deliberately NOT using on_open_position()
        # (see class docstring): LiveAdapter never calls it, so relying on it
        # here would make max_hold_candles a backtest-only behavior.
        if self.is_open:
            if self.vars.get("_holding_since") is None:
                self.vars["_holding_since"] = i
        else:
            self.vars["_holding_since"] = None

    # ── Entry condition helpers ──────────────────────────────────────────────

    def _long_entry_ready(self) -> bool:
        dc_upper = self.vars.get("dc_upper_prior")
        bw_pct = self.vars.get("bw_pct_prior")
        adx = self.vars.get("adx")
        mfi = self.vars.get("mfi")
        ema200 = self.vars.get("ema200")
        if None in (dc_upper, bw_pct, adx, mfi, ema200):
            return False
        return (
            self.price > dc_upper
            and bw_pct < self.squeeze_pct
            and adx >= self.adx_min
            and self.vars.get("adx_rising", False)
            and mfi >= self._MFI_LONG_MIN
            and self.price > ema200
        )

    def _short_entry_ready(self) -> bool:
        dc_lower = self.vars.get("dc_lower_prior")
        bw_pct = self.vars.get("bw_pct_prior")
        adx = self.vars.get("adx")
        mfi = self.vars.get("mfi")
        ema200 = self.vars.get("ema200")
        if None in (dc_lower, bw_pct, adx, mfi, ema200):
            return False
        return (
            self.price < dc_lower
            and bw_pct < self.squeeze_pct
            and adx >= self.adx_min
            and self.vars.get("adx_rising", False)
            and mfi <= self._MFI_SHORT_MAX
            and self.price < ema200
        )

    # ── Alpha Model: predict only ─────────────────────────────────────────
    def forecast(self) -> Signal:
        if (self.index + 1) < self.MIN_WARMUP_CANDLES:
            return Signal(direction=0, ref_price=self.price)

        if self.is_open:
            direction = 1 if self.is_long else -1
            holding_since = self.vars.get("_holding_since")
            if holding_since is not None and (self.index - holding_since) >= self.max_hold_candles:
                return Signal(direction=0, ref_price=self.price)  # time-stop
            return Signal(direction=direction, conviction=1.0, ref_price=self.price)

        if self._long_entry_ready():
            return Signal(direction=1, conviction=1.0, ref_price=self.price)
        if self._short_entry_ready():
            return Signal(direction=-1, conviction=1.0, ref_price=self.price)
        return Signal(direction=0, ref_price=self.price)
