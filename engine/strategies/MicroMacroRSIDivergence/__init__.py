import numpy as np

from engine.core.strategy import BaseStrategy
import engine.indicators as ta


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
      • FILTERS  — all four Pine quality filters are ported and on by default:
                   RSI 50-level alignment, RSI momentum direction, smoothed-RSI
                   confirmation, and the min-RSI-difference / pivot-distance
                   noise gates. The 50-level and smoothed filters are applied in
                   the reversal-correct sense (bullish divergences in the lower
                   half / smoothed RSI sloping up; bearish in the upper half /
                   smoothed RSI sloping down) — the inverse of the literal Pine,
                   whose >50/<50 test would make reversal entries impossible at
                   genuine price extremes. Each filter is individually toggleable.

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

    # rsi_period(14) + smooth_length(60) + max_pivot_bars(100) + 2*macro(10) + buffer
    MIN_WARMUP_CANDLES: int = 210

    # Smoothing-type codes (Pine offers SMA/EMA/RMA/WMA/HMA; the engine ships
    # SMA and EMA, so only those are exposed. EMA is the Pine default.)
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
            "type": "int", "default": 2, "min": 1, "max": 20,
            "label": "Micro Pivot Length (left/right bars)",
            "description": (
                "Increasing: micro swings need more confirmation, fewer micro signals. "
                "Decreasing: very local swings, more reactive micro signals and noise."
            ),
        },
        "macro_pivot": {
            "type": "int", "default": 10, "min": 2, "max": 60,
            "label": "Macro Pivot Length (left/right bars)",
            "description": (
                "Increasing: larger structural swings, stronger but later/rarer signals "
                "(detection lags by this many bars). Decreasing: smaller macro structure, "
                "earlier but weaker macro signals."
            ),
        },
        "confluence_window": {
            "type": "int", "default": 30, "min": 1, "max": 200,
            "label": "Micro/Macro Confluence Window (bars)",
            "description": (
                "Max distance between the macro pivot and the corroborating micro pivot. "
                "Increasing: looser confluence, more trades. Decreasing: tighter alignment, "
                "fewer but higher-quality trades."
            ),
        },
        "min_pivot_bars": {
            "type": "int", "default": 5, "min": 1, "max": 100,
            "label": "Min Bars Between Pivots",
            "description": (
                "Rejects divergences whose two pivots are too close together. "
                "Increasing: ignores rapid back-to-back swings. Decreasing: allows them."
            ),
        },
        "max_pivot_bars": {
            "type": "int", "default": 100, "min": 5, "max": 500,
            "label": "Max Bars Between Pivots",
            "description": (
                "Rejects divergences spanning too many bars (stale structure). "
                "Increasing: allows wider divergences. Decreasing: only recent structure."
            ),
        },
        "min_div_diff": {
            "type": "float", "default": 4.0, "min": 0.0, "max": 50.0,
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
            "type": "int", "default": 60, "min": 2, "max": 200,
            "label": "Smoothed-RSI Length",
            "description": (
                "Lookback for the smoothed-RSI confirmation layer. "
                "Increasing: slower, broader-trend confirmation. Decreasing: more reactive."
            ),
        },
        "enable_rsi_level_filter": {
            "type": "int", "default": 1, "min": 0, "max": 1,
            "label": "RSI 50-Level Filter (1 = on)",
            "description": (
                "Require RSI on the momentum-aligned side of 50 at the pivot "
                "(>50 for bullish, <50 for bearish), per the Pine filter. 0 disables."
            ),
        },
        "enable_rsi_direction_filter": {
            "type": "int", "default": 1, "min": 0, "max": 1,
            "label": "RSI Direction Filter (1 = on)",
            "description": (
                "Require RSI momentum to be turning in the trade direction between pivots. "
                "0 disables."
            ),
        },
        "enable_smoothed_filter": {
            "type": "int", "default": 1, "min": 0, "max": 1,
            "label": "Smoothed-RSI Confirmation (1 = on)",
            "description": (
                "Require the smoothed RSI on the momentum-aligned side of 50 at the pivot. "
                "0 disables (also skips its computation)."
            ),
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
            "type": "float", "default": 2.0, "min": 0.5, "max": 6.0,
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
        """EMA/SMA of the RSI series, NaN-aligned to candle indices.

        The smoothing is computed on the warmup-trimmed RSI values via a
        synthetic candle array (RSI placed in the CLOSE column) so it goes
        through the pluggable indicator backend rather than being reimplemented.
        """
        valid = ~np.isnan(rsi_seq)
        out = np.full(rsi_seq.shape, np.nan)
        if int(valid.sum()) <= self.smooth_length:
            return out
        vals = rsi_seq[valid]
        synth = np.zeros((vals.size, 6), dtype=float)
        synth[:, 2] = vals  # CLOSE column
        if self.smooth_type == self.SMOOTH_SMA:
            sm = ta.sma(synth, period=self.smooth_length, sequential=True)
        else:
            sm = ta.ema(synth, period=self.smooth_length, sequential=True)
        out[valid] = np.asarray(sm, dtype=float)
        return out

    # ── Indicators — computed once per candle in before() ──────────────────
    def before(self) -> None:
        n = len(self.candles)
        if n < self.MIN_WARMUP_CANDLES:
            self.vars["ready"] = False
            return

        rsi_seq = np.asarray(
            ta.rsi(self.candles, period=self.rsi_period, sequential=True), dtype=float
        )
        smoothed_seq = self._smoothed_rsi(rsi_seq) if self.enable_smoothed_filter else None

        # Bound the pivot scan to a recent window for performance. RSI/smoothed
        # are full-history (cheap C calls); only the pivot geometry is windowed.
        span = self.max_pivot_bars + 4 * self.macro_pivot + 10
        off = max(0, n - span)
        win = self.candles[off:]

        self.vars.update(
            ready=True,
            n=n,
            off=off,
            rsi=rsi_seq,
            sm=smoothed_seq,
            atr=float(ta.atr(self.candles, period=self.atr_period)),
            micro_low=ta.pivot_low(win, self.micro_pivot, self.micro_pivot,
                                   source="low", sequential=True),
            micro_high=ta.pivot_high(win, self.micro_pivot, self.micro_pivot,
                                     source="high", sequential=True),
            macro_low=ta.pivot_low(win, self.macro_pivot, self.macro_pivot,
                                   source="low", sequential=True),
            macro_high=ta.pivot_high(win, self.macro_pivot, self.macro_pivot,
                                     source="high", sequential=True),
        )

    # ── Divergence evaluation on the last two pivots of a scale ─────────────
    def _last_two(self, piv_rel: np.ndarray):
        idxs = np.where(~np.isnan(piv_rel))[0]
        if idxs.size < 2:
            return None
        return int(idxs[-2]), int(idxs[-1])

    def _eval_bull(self, piv_rel: np.ndarray, right: int):
        """Regular BULLISH divergence on swing lows. Returns (valid, abs_centre, fired_now)."""
        pair = self._last_two(piv_rel)
        if pair is None:
            return False, -1, False
        off, n, rsi, sm = self.vars["off"], self.vars["n"], self.vars["rsi"], self.vars["sm"]
        p_rel, c_rel = pair
        p_abs, c_abs = off + p_rel, off + c_rel
        price_prev, price_cur = piv_rel[p_rel], piv_rel[c_rel]
        rsi_prev, rsi_cur = rsi[p_abs], rsi[c_abs]
        if np.isnan(rsi_prev) or np.isnan(rsi_cur):
            return False, c_abs, False

        dist = c_abs - p_abs
        cond = (price_cur < price_prev) and (rsi_cur > rsi_prev)
        if self.min_div_diff > 0:
            cond = cond and (rsi_cur - rsi_prev >= self.min_div_diff)
        cond = cond and (self.min_pivot_bars <= dist <= self.max_pivot_bars)
        # 50-level: a bullish reversal divergence must form in the lower half
        # (RSI < 50 at the low). NOTE: this is the reversal-correct inverse of
        # the source Pine filter (which required RSI > 50 and would make longs
        # essentially impossible at genuine price lows).
        if self.enable_rsi_level_filter:
            cond = cond and (rsi_cur < 50.0)
        # Direction: RSI momentum turning up between the two lows.
        if self.enable_rsi_direction_filter:
            cond = cond and (rsi_cur > rsi_prev)
        # Smoothed-RSI confirmation: the smoothed oscillator slopes up too.
        if self.enable_smoothed_filter and sm is not None:
            cond = cond and (not np.isnan(sm[c_abs])) and (not np.isnan(sm[p_abs])) \
                and (sm[c_abs] > sm[p_abs])

        fired_now = bool(cond) and (c_abs == n - 1 - right)
        return bool(cond), c_abs, fired_now

    def _eval_bear(self, piv_rel: np.ndarray, right: int):
        """Regular BEARISH divergence on swing highs. Returns (valid, abs_centre, fired_now)."""
        pair = self._last_two(piv_rel)
        if pair is None:
            return False, -1, False
        off, n, rsi, sm = self.vars["off"], self.vars["n"], self.vars["rsi"], self.vars["sm"]
        p_rel, c_rel = pair
        p_abs, c_abs = off + p_rel, off + c_rel
        price_prev, price_cur = piv_rel[p_rel], piv_rel[c_rel]
        rsi_prev, rsi_cur = rsi[p_abs], rsi[c_abs]
        if np.isnan(rsi_prev) or np.isnan(rsi_cur):
            return False, c_abs, False

        dist = c_abs - p_abs
        cond = (price_cur > price_prev) and (rsi_cur < rsi_prev)
        if self.min_div_diff > 0:
            cond = cond and (rsi_prev - rsi_cur >= self.min_div_diff)
        cond = cond and (self.min_pivot_bars <= dist <= self.max_pivot_bars)
        # 50-level: a bearish reversal divergence must form in the upper half
        # (RSI > 50 at the high) — reversal-correct inverse of the source Pine.
        if self.enable_rsi_level_filter:
            cond = cond and (rsi_cur > 50.0)
        # Direction: RSI momentum turning down between the two highs.
        if self.enable_rsi_direction_filter:
            cond = cond and (rsi_cur < rsi_prev)
        # Smoothed-RSI confirmation: the smoothed oscillator slopes down too.
        if self.enable_smoothed_filter and sm is not None:
            cond = cond and (not np.isnan(sm[c_abs])) and (not np.isnan(sm[p_abs])) \
                and (sm[c_abs] < sm[p_abs])

        fired_now = bool(cond) and (c_abs == n - 1 - right)
        return bool(cond), c_abs, fired_now

    # ── Confluence: macro fires the trigger, micro corroborates ─────────────
    def _confluent_long(self) -> bool:
        macro_valid, macro_c, macro_fired = self._eval_bull(self.vars["macro_low"], self.macro_pivot)
        if not macro_fired:
            return False
        micro_valid, micro_c, _ = self._eval_bull(self.vars["micro_low"], self.micro_pivot)
        return micro_valid and abs(macro_c - micro_c) <= self.confluence_window

    def _confluent_short(self) -> bool:
        macro_valid, macro_c, macro_fired = self._eval_bear(self.vars["macro_high"], self.macro_pivot)
        if not macro_fired:
            return False
        micro_valid, micro_c, _ = self._eval_bear(self.vars["micro_high"], self.micro_pivot)
        return micro_valid and abs(macro_c - micro_c) <= self.confluence_window

    # ── Entry decisions ─────────────────────────────────────────────────────
    def should_long(self) -> bool:
        if not self.vars.get("ready"):
            return False
        return self._confluent_long()

    def should_short(self) -> bool:
        if not self.vars.get("ready"):
            return False
        return self._confluent_short()

    def should_cancel_entry(self) -> bool:
        return False

    # ── Order placement: ATR stop + R:R target via the risk model ───────────
    def go_long(self) -> None:
        atr = self.vars.get("atr", 0.0)
        if not atr or atr <= 0:
            return
        stop = self.price - self.sl_atr_mult * atr
        qty = self.size_by_risk(stop)
        if qty <= 0:
            return
        self.buy = qty, self.price
        self.stop_loss = qty, stop
        self.take_profit = qty, self.rr_target("long", stop, rr=self.rrr)

    def go_short(self) -> None:
        atr = self.vars.get("atr", 0.0)
        if not atr or atr <= 0:
            return
        stop = self.price + self.sl_atr_mult * atr
        qty = self.size_by_risk(stop)
        if qty <= 0:
            return
        self.sell = qty, self.price
        self.stop_loss = qty, stop
        self.take_profit = qty, self.rr_target("short", stop, rr=self.rrr)

    # ── Open-position management: optional opposite-divergence exit ─────────
    # The ATR stop and R:R take-profit set at entry stay armed; this only adds
    # an early discretionary exit when the thesis flips.
    def update_position(self) -> None:
        if not self.exit_on_opposite or not self.vars.get("ready"):
            return
        if self.is_long and self._confluent_short():
            self.close_position()
        elif self.is_short and self._confluent_long():
            self.close_position()
