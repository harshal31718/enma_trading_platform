import numpy as np

from engine.core.strategy import BaseStrategy
import engine.indicators as ta

try:
    from engine.core.models import AtrBracketRiskModel, RiskBudgetPortfolio, Signal
except ImportError:
    from core.models import AtrBracketRiskModel, RiskBudgetPortfolio, Signal


class MicroMacroRSIDivergence(BaseStrategy):
    """
    Micro + Macro RSI Divergence — confluence reversal strategy.

    Ported from the TradingView indicator "Micro and Macro RSI Divergence"
    (© Uncle_the_shooter). The Pine script is a *context* indicator, not a
    signal generator; this strategy adds the trading rules it deliberately
    omits, per the design decisions recorded with this port:

      • SIGNAL   — REGULAR divergences only (reversal trading). Hidden
                   divergences are intentionally not traded here.
      • SCALE    — micro + macro CONFLUENCE. A trade fires only when the slow
                   MACRO pivot confirms a regular divergence AND a same-side
                   MICRO regular divergence sits within ``confluence_window``
                   bars of it. Macro is the trigger (it confirms later, so the
                   micro signal has already formed); micro is corroboration.
      • EXIT     — ATR protective stop + reward:risk take-profit (sized through
                   the platform risk model), plus an optional early exit when an
                   opposite-side confluence divergence appears.
      • FILTERS  — the Pine quality filters are ported but, matching the Pine
                   source, default OFF (RSI 50-level alignment, RSI momentum
                   direction, smoothed-RSI confirmation). Only the always-on
                   noise gates remain by default: min-RSI-difference and
                   pivot-distance (min/max). With all the optional filters and a
                   strict confluence window stacked on, the strategy fired no
                   trades over a year of 1h candles — so the defaults were
                   relaxed toward the Pine source (filters off, min_div_diff 4→2,
                   confluence_window 30→80, min_pivot_bars 5→3). When enabled,
                   the 50-level and smoothed filters apply in the reversal-correct
                   sense (bullish divergences in the lower half / smoothed RSI
                   sloping up; bearish in the upper half / smoothed RSI sloping
                   down) — the inverse of the literal Pine, whose >50/<50 test
                   would make reversal entries impossible at genuine price
                   extremes. Each filter is individually toggleable.

    DIVERGENCE DEFINITIONS (regular)
    --------------------------------
      Bullish (→ long)  : price makes a LOWER low,  RSI makes a HIGHER low.
      Bearish (→ short) : price makes a HIGHER high, RSI makes a LOWER high.

    NO-LOOKAHEAD
    ------------
    Pivots are confirmed only ``right`` bars after they form (see
    ``ta.pivot_high``/``ta.pivot_low``). A signal "fires" on the exact candle a
    pivot becomes confirmed; the entry then fills at the next candle's open, so
    no future information is ever used.

    Recommended:
        Symbol   : BTCUSDT, ETHUSDT
        Timeframe: 1h / 4h (divergence is a swing concept — avoid sub-15m)
        Leverage : 1–3x
    """

    # rsi_period(14) + macro_pivot(5)*2 + buffer
    MIN_WARMUP_CANDLES: int = 30

    SMOOTH_SMA = 0
    SMOOTH_EMA = 1

    PARAMS = {
        "rsi_period": {
            "type": "int", "default": 14, "min": 2, "max": 50,
            "label": "RSI Period",
            "description": (
                "Increasing: slower RSI, smoother swings, fewer divergences. "
                "Decreasing: faster RSI, more reactive, more (noisier) divergences."
            ),
        },
        "micro_pivot": {
            "type": "int", "default": 3, "min": 1, "max": 20,
            "label": "Micro Pivot Length (left/right bars)",
            "description": (
                "Increasing: micro swings need more confirmation, fewer micro signals. "
                "Decreasing: very local swings, more reactive micro signals and noise."
            ),
        },
        "macro_pivot": {
            "type": "int", "default": 5, "min": 2, "max": 60,
            "label": "Macro Pivot Length (left/right bars)",
            "description": (
                "Increasing: larger structural swings, stronger but later/rarer signals. "
                "Decreasing: smaller macro structure, earlier but weaker macro signals."
            ),
        },
        "confluence_window": {
            "type": "int", "default": 20, "min": 1, "max": 200,
            "label": "Micro/Macro Confluence Window (bars)",
            "description": (
                "Max distance between the macro pivot and the corroborating micro pivot. "
                "Increasing: looser confluence, more trades. Decreasing: tighter alignment."
            ),
        },
        "min_pivot_bars": {
            "type": "int", "default": 1, "min": 1, "max": 100,
            "label": "Min Bars Between Pivots",
            "description": (
                "Rejects divergences whose two pivots are too close together. "
                "Increasing: ignores rapid back-to-back swings. Decreasing: allows them."
            ),
        },
        "max_pivot_bars": {
            "type": "int", "default": 500, "min": 5, "max": 500,
            "label": "Max Bars Between Pivots",
            "description": (
                "Rejects divergences spanning too many bars (stale structure). "
                "Increasing: allows wider divergences. Decreasing: only recent structure."
            ),
        },
        "min_div_diff": {
            "type": "float", "default": 0.0, "min": 0.0, "max": 50.0,
            "label": "Min RSI Difference Between Pivots",
            "description": (
                "Minimum RSI gap between the two pivots for a valid divergence (0 = off). "
                "Increasing: only pronounced divergences. Decreasing: accepts marginal ones."
            ),
        },
        "smooth_type": {
            "type": "int", "default": 1, "min": 0, "max": 1,
            "label": "Smoothed-RSI Type (0 = SMA, 1 = EMA)",
            "description": (
                "Moving-average type for the smoothed-RSI confirmation layer. "
                "0 = SMA (steadier), 1 = EMA (more responsive, Pine default)."
            ),
        },
        "smooth_length": {
            "type": "int", "default": 2, "min": 2, "max": 200,
            "label": "Smoothed-RSI Length",
            "description": (
                "Lookback for the smoothed-RSI confirmation layer. "
                "Increasing: slower, broader-trend confirmation. Decreasing: more reactive."
            ),
        },
        "enable_rsi_level_filter": {
            "type": "int", "default": 1, "min": 0, "max": 1,
            "label": "RSI 50-Level Filter (1 = on)",
            "description": "On by default; requires RSI < 50 for longs, RSI > 50 for shorts.",
        },
        "enable_rsi_direction_filter": {
            "type": "int", "default": 0, "min": 0, "max": 1,
            "label": "RSI Direction Filter (1 = on)",
            "description": "Off by default for maximum trades.",
        },
        "enable_smoothed_filter": {
            "type": "int", "default": 0, "min": 0, "max": 1,
            "label": "Smoothed-RSI Confirmation (1 = on)",
            "description": "Off by default for maximum trades.",
        },
        "exit_on_opposite": {
            "type": "int", "default": 1, "min": 0, "max": 1,
            "label": "Exit on Opposite Divergence (1 = on)",
            "description": (
                "Close early when an opposite-side confluence divergence fires. "
                "0 = rely solely on the ATR stop / take-profit."
            ),
        },
        "atr_period": {
            "type": "int", "default": 14, "min": 5, "max": 50,
            "label": "ATR Period (stop sizing)",
            "description": (
                "Increasing: smoother ATR, wider/steadier stops. "
                "Decreasing: more reactive ATR, tighter stops."
            ),
        },
        "sl_atr_mult": {
            "type": "float", "default": 1.5, "min": 0.5, "max": 6.0,
            "label": "Stop Distance (ATR multiple)",
            "description": (
                "Increasing: wider stop, survives more noise, larger risk per trade. "
                "Decreasing: tighter stop, stops out sooner, smaller max loss."
            ),
        },
    }

    def __init__(self):
        super().__init__()
        self.rsi_period:                  int   = self.PARAMS["rsi_period"]["default"]
        self.micro_pivot:                 int   = self.PARAMS["micro_pivot"]["default"]
        self.macro_pivot:                 int   = self.PARAMS["macro_pivot"]["default"]
        self.confluence_window:           int   = self.PARAMS["confluence_window"]["default"]
        self.min_pivot_bars:              int   = self.PARAMS["min_pivot_bars"]["default"]
        self.max_pivot_bars:              int   = self.PARAMS["max_pivot_bars"]["default"]
        self.min_div_diff:                float = self.PARAMS["min_div_diff"]["default"]
        self.smooth_type:                 int   = self.PARAMS["smooth_type"]["default"]
        self.smooth_length:               int   = self.PARAMS["smooth_length"]["default"]
        self.enable_rsi_level_filter:     int   = self.PARAMS["enable_rsi_level_filter"]["default"]
        self.enable_rsi_direction_filter: int   = self.PARAMS["enable_rsi_direction_filter"]["default"]
        self.enable_smoothed_filter:      int   = self.PARAMS["enable_smoothed_filter"]["default"]
        self.exit_on_opposite:            int   = self.PARAMS["exit_on_opposite"]["default"]
        self.atr_period:                  int   = self.PARAMS["atr_period"]["default"]
        self.sl_atr_mult:                 float = self.PARAMS["sl_atr_mult"]["default"]

        # Narang Black-Box: static ATR bracket, risk-budget sizing
        self.risk_model      = AtrBracketRiskModel()
        self.portfolio_model = RiskBudgetPortfolio()

    def validate_params(self) -> None:
        if self.min_pivot_bars >= self.max_pivot_bars:
            raise ValueError(
                f"min_pivot_bars ({self.min_pivot_bars}) must be less than "
                f"max_pivot_bars ({self.max_pivot_bars})"
            )
        if self.micro_pivot >= self.macro_pivot:
            raise ValueError(
                f"micro_pivot ({self.micro_pivot}) must be less than "
                f"macro_pivot ({self.macro_pivot})"
            )

    # ── Smoothed RSI (routed through ta.sma / ta.ema, never inline) ─────────
    def _smoothed_rsi(self, rsi_seq: np.ndarray) -> np.ndarray | None:
        valid = ~np.isnan(rsi_seq)
        out = np.full(rsi_seq.shape, np.nan)
        if int(valid.sum()) <= self.smooth_length:
            return out
        vals = rsi_seq[valid]
        synth = np.zeros((vals.size, 6), dtype=float)
        synth[:, 2] = vals
        if self.smooth_type == self.SMOOTH_SMA:
            sm = ta.sma(synth, period=self.smooth_length, sequential=True)
        else:
            sm = ta.ema(synth, period=self.smooth_length, sequential=True)
        out[valid] = np.asarray(sm, dtype=float)
        return out

    # ── Phase A: one-time vectorized pre-computation (full candle array) ─────
    def prepare(self, candles: np.ndarray) -> None:
        """Compute every indicator once over the full candle array.

        ``before()`` then only indexes into these ``self._*`` arrays at
        ``self.index`` — no TA-Lib calls in the hot loop. Replaces the former
        per-candle recompute (and the ``win = candles[off:]`` windowing): pivot
        arrays are now absolute-indexed over the whole array, and no-lookahead is
        enforced at read time by the ``i - right`` visibility horizon in
        ``_last_two_visible`` (a pivot at absolute index ``p`` is only confirmed
        once candle ``p + right`` has closed).
        """
        if len(candles) == 0:
            empty = np.array([])
            self._rsi = empty
            self._sm = None
            self._atr_seq = empty
            self._micro_low = self._micro_high = empty
            self._macro_low = self._macro_high = empty
            return

        self._rsi = np.asarray(
            ta.rsi(candles, period=self.rsi_period, sequential=True), dtype=float
        )
        self._sm = self._smoothed_rsi(self._rsi) if self.enable_smoothed_filter else None
        self._atr_seq = np.asarray(
            ta.atr(candles, period=self.atr_period, sequential=True), dtype=float
        )
        self._micro_low = ta.pivot_low(candles, self.micro_pivot, self.micro_pivot,
                                       source="low", sequential=True)
        self._micro_high = ta.pivot_high(candles, self.micro_pivot, self.micro_pivot,
                                         source="high", sequential=True)
        self._macro_low = ta.pivot_low(candles, self.macro_pivot, self.macro_pivot,
                                       source="low", sequential=True)
        self._macro_high = ta.pivot_high(candles, self.macro_pivot, self.macro_pivot,
                                         source="high", sequential=True)

    # ── Phase B: per-candle index lookup only (no TA-Lib) ───────────────────
    def before(self) -> None:
        i = self.index
        if (i + 1) < self.MIN_WARMUP_CANDLES:
            self.vars["ready"] = False
            return
        self.vars.update(
            ready=True,
            atr=float(self._atr_seq[i]),
        )

    # ── Divergence evaluation on the last two pivots of a scale ─────────────
    def _last_two_visible(self, piv_abs: np.ndarray, right: int):
        """Last two pivots confirmed by the current candle (no lookahead).

        A pivot at absolute index ``p`` needs ``right`` bars to its right to
        confirm, so it is only visible once ``self.index >= p + right`` — i.e.
        searching ``piv_abs[: i - right + 1]``. This reproduces the old
        windowed-sequential pivot visibility exactly.
        """
        i = self.index
        horizon = i - right
        if horizon < 0:
            return None
        idxs = np.where(~np.isnan(piv_abs[:horizon + 1]))[0]
        if idxs.size < 2:
            return None
        return int(idxs[-2]), int(idxs[-1])

    def _eval_bull(self, piv_abs: np.ndarray, right: int):
        pair = self._last_two_visible(piv_abs, right)
        if pair is None:
            return False, -1, False
        i, rsi, sm = self.index, self._rsi, self._sm
        p_abs, c_abs = pair
        price_prev, price_cur = piv_abs[p_abs], piv_abs[c_abs]
        rsi_prev, rsi_cur = rsi[p_abs], rsi[c_abs]
        if np.isnan(rsi_prev) or np.isnan(rsi_cur):
            return False, c_abs, False

        dist = c_abs - p_abs
        cond = (price_cur < price_prev) and (rsi_cur > rsi_prev)
        if self.min_div_diff > 0:
            cond = cond and (rsi_cur - rsi_prev >= self.min_div_diff)
        cond = cond and (self.min_pivot_bars <= dist <= self.max_pivot_bars)
        if self.enable_rsi_level_filter:
            cond = cond and (rsi_cur < 50.0)
        if self.enable_rsi_direction_filter:
            cond = cond and (rsi_cur > rsi_prev)
        if self.enable_smoothed_filter and sm is not None:
            cond = cond and (not np.isnan(sm[c_abs])) and (not np.isnan(sm[p_abs])) \
                and (sm[c_abs] > sm[p_abs])

        fired_now = bool(cond) and (c_abs == i - right)
        return bool(cond), c_abs, fired_now

    def _eval_bear(self, piv_abs: np.ndarray, right: int):
        pair = self._last_two_visible(piv_abs, right)
        if pair is None:
            return False, -1, False
        i, rsi, sm = self.index, self._rsi, self._sm
        p_abs, c_abs = pair
        price_prev, price_cur = piv_abs[p_abs], piv_abs[c_abs]
        rsi_prev, rsi_cur = rsi[p_abs], rsi[c_abs]
        if np.isnan(rsi_prev) or np.isnan(rsi_cur):
            return False, c_abs, False

        dist = c_abs - p_abs
        cond = (price_cur > price_prev) and (rsi_cur < rsi_prev)
        if self.min_div_diff > 0:
            cond = cond and (rsi_prev - rsi_cur >= self.min_div_diff)
        cond = cond and (self.min_pivot_bars <= dist <= self.max_pivot_bars)
        if self.enable_rsi_level_filter:
            cond = cond and (rsi_cur > 50.0)
        if self.enable_rsi_direction_filter:
            cond = cond and (rsi_cur < rsi_prev)
        if self.enable_smoothed_filter and sm is not None:
            cond = cond and (not np.isnan(sm[c_abs])) and (not np.isnan(sm[p_abs])) \
                and (sm[c_abs] < sm[p_abs])

        fired_now = bool(cond) and (c_abs == i - right)
        return bool(cond), c_abs, fired_now

    # ── Confluence: macro fires the trigger, micro corroborates ─────────────
    def _confluent_long(self) -> bool:
        macro_valid, macro_c, macro_fired = self._eval_bull(self._macro_low, self.macro_pivot)
        if not macro_fired:
            return False
        micro_valid, micro_c, _ = self._eval_bull(self._micro_low, self.micro_pivot)
        return micro_valid and abs(macro_c - micro_c) <= self.confluence_window

    def _confluent_short(self) -> bool:
        macro_valid, macro_c, macro_fired = self._eval_bear(self._macro_high, self.macro_pivot)
        if not macro_fired:
            return False
        micro_valid, micro_c, _ = self._eval_bear(self._micro_high, self.micro_pivot)
        return micro_valid and abs(macro_c - micro_c) <= self.confluence_window

    # ── Alpha Model: forecast() handles both open and flat cases ────────────

    def forecast(self) -> Signal:
        """ATR-stop divergence reversal logic.

        While holding: optional early exit on opposite confluence divergence;
        maintain otherwise (ATR bracket held by AtrBracketRiskModel).
        While flat: enter on confluence divergence signal.
        """
        if not self.vars.get("ready"):
            return Signal(direction=0)

        if self.is_open:
            # Optional early exit on opposite divergence
            if self.exit_on_opposite:
                if self.is_long and self._confluent_short():
                    return Signal(direction=0, ref_price=self.price)  # close
                if self.is_short and self._confluent_long():
                    return Signal(direction=0, ref_price=self.price)  # close
            # Maintain — bracket unchanged (AtrBracketRiskModel returns stored SL/TP)
            return Signal(
                direction=1 if self.is_long else -1,
                conviction=1.0,
                ref_price=self.price,
            )

        # Flat — look for confluence divergence entry
        if self._confluent_long():
            return Signal(direction=1, conviction=1.0, ref_price=self.price)
        if self._confluent_short():
            return Signal(direction=-1, conviction=1.0, ref_price=self.price)
        return Signal(direction=0, ref_price=self.price)
