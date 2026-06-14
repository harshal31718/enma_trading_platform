import numpy as np

from engine.core.strategy import BaseStrategy
import engine.indicators as ta

# Shared, library-agnostic swing-pivot detector (TradingView ta.pivothigh/low).
# Price pivots go through the public ta.pivot_high / ta.pivot_low convenience
# functions; oscillator/volume series reuse the same primitive directly so the
# pivot geometry is identical everywhere. Dual-root import mirrors strategy.py.
try:
    from engine.indicators.base import _compute_pivots
except ImportError:  # pragma: no cover - top-level module root
    from indicators.base import _compute_pivots


def _last2(series) -> tuple | None:
    """Return ``(newest, previous)`` confirmed pivot values from a NaN-padded
    pivot series, or ``None`` when fewer than two pivots exist yet."""
    arr = np.asarray(series, dtype=float)
    valid = arr[~np.isnan(arr)]
    if valid.size < 2:
        return None
    return float(valid[-1]), float(valid[-2])


def _div(pr_hi, pr_lo, osc_hi, osc_lo) -> int:
    """Classic regular divergence between price and an oscillator.

    Bearish (-1): price prints a higher high while the oscillator prints a
    lower high. Bullish (+1): price prints a lower low while the oscillator
    prints a higher low. Bullish is evaluated last so it wins a rare tie,
    mirroring the source Pine ``f_scr_div``.
    """
    result = 0
    if pr_hi is not None and osc_hi is not None:
        if pr_hi[0] > pr_hi[1] and osc_hi[0] < osc_hi[1]:
            result = -1
    if pr_lo is not None and osc_lo is not None:
        if pr_lo[0] < pr_lo[1] and osc_lo[0] > osc_lo[1]:
            result = 1
    return result


class MultiDivergence(BaseStrategy):
    """
    Multi-oscillator divergence confluence strategy.

    PORTED FROM
    -----------
    "Multi-Divergence Strategy | GainzAlgo" (TradingView Pine v6). The original
    is a screener that scores nine divergence sources *independently*. Here those
    nine signals are collapsed into a single tradeable decision via a confluence
    threshold: a trade fires only when at least ``min_confluence`` sources agree
    on the same direction at the moment a new price pivot confirms.

    DIVERGENCE SOURCES (toggle each on/off)
    ---------------------------------------
      0 RSI      — momentum
      1 MFI      — volume-weighted momentum
      2 STOCH    — stochastic %K
      3 Z-SCORE  — (close - SMA) / STDEV, statistical stretch
      4 ADX      — trend strength
      5 MACD     — MACD line
      6 OBV      — on-balance volume
      7 PRICE    — price-action swing-contraction (structural)
      8 SWING    — raw-volume swing divergence

    For each source the last two confirmed swing pivots of price are compared
    against the last two confirmed swing pivots of that source. Bullish
    divergence (lower price low + higher oscillator low) votes long; bearish
    divergence (higher price high + lower oscillator high) votes short.

    ENTRY
    -----
    Evaluated only on bars where a *new* price pivot confirms (non-repainting:
    a pivot needs ``piv_len`` bars on each side, so it is only ever read
    ``piv_len`` bars after it formed). Long when bullish votes >= threshold and
    strictly outnumber bearish votes; short for the mirror (if shorts allowed).

    RISK
    ----
    Stop is ATR-based (``sl_atr_mult`` * ATR) or a fixed ``custom_sl_pct`` of
    price. Take-profit is ``tp_atr_mult`` * ATR — preserving the source's
    independent ATR-multiple targets. Quantity is sized by true risk-per-trade
    (rule #6) via ``size_by_risk`` so each trade risks ``risk_pct`` of equity.
    Exits resolve on the static SL/TP the engine checks every candle.

    Recommended:
        Symbol   : BTCUSDT, ETHUSDT and other liquid pairs
        Timeframe: 15m – 4h
        Leverage : 1–5x
    """

    # MACD slow(26)+signal(9) warmup plus a full pivot window with margin.
    MIN_WARMUP_CANDLES: int = 60

    PARAMS = {
        "piv_len": {
            "type": "int", "default": 5, "min": 2, "max": 15,
            "label": "Divergence Pivot Length",
            "description": (
                "Bars required on each side of a swing to confirm a pivot. "
                "Increasing: only major structural pivots, fewer/slower signals. "
                "Decreasing: detects micro-divergences, more/earlier signals."
            ),
        },
        "min_confluence": {
            "type": "int", "default": 2, "min": 1, "max": 9,
            "label": "Min Divergence Confluence",
            "description": (
                "How many enabled sources must agree on a direction to trade. "
                "Increasing: stricter, far fewer but higher-conviction entries. "
                "Decreasing: looser, more trades; 1 = any single divergence."
            ),
        },
        "sl_atr_mult": {
            "type": "float", "default": 1.5, "min": 0.1, "max": 10.0,
            "label": "SL ATR Multiplier",
            "description": (
                "Stop distance as a multiple of 14-period ATR (ignored if custom "
                "SL is on). Increasing: wider stop, fewer stop-outs, larger risk. "
                "Decreasing: tighter stop, more stop-outs, smaller risk."
            ),
        },
        "tp_atr_mult": {
            "type": "float", "default": 2.5, "min": 0.1, "max": 20.0,
            "label": "TP ATR Multiplier",
            "description": (
                "Take-profit distance as a multiple of 14-period ATR. "
                "Increasing: targets bigger moves, lower hit rate, higher reward. "
                "Decreasing: closer target, higher hit rate, smaller reward."
            ),
        },
        "use_custom_sl": {
            "type": "int", "default": 0, "min": 0, "max": 1,
            "label": "Use Custom SL % (1 = yes)",
            "description": (
                "1: stop is a fixed percentage of price instead of ATR-based. "
                "0: ATR-based stop via SL ATR Multiplier."
            ),
        },
        "custom_sl_pct": {
            "type": "float", "default": 1.0, "min": 0.1, "max": 20.0,
            "label": "Custom SL %",
            "description": (
                "Fixed stop distance as a percent of entry price (only used when "
                "custom SL is enabled). Increasing: wider stop. Decreasing: tighter."
            ),
        },
        "allow_shorts": {
            "type": "int", "default": 1, "min": 0, "max": 1,
            "label": "Allow Short Trades (1 = yes)",
            "description": (
                "1: take both bullish-divergence longs and bearish-divergence "
                "shorts. 0: long-only, ignore bearish confluence."
            ),
        },
        "atr_period": {
            "type": "int", "default": 14, "min": 5, "max": 50,
            "label": "ATR Period (stops/targets)",
            "description": (
                "Lookback for the ATR used in sizing, stop and target. "
                "Increasing: smoother, slower volatility estimate. "
                "Decreasing: more reactive to recent volatility."
            ),
        },
        "rsi_period": {
            "type": "int", "default": 14, "min": 2, "max": 50,
            "label": "RSI Period",
            "description": (
                "Lookback for the RSI divergence source. "
                "Increasing: smoother RSI, fewer pivots. Decreasing: noisier, more pivots."
            ),
        },
        "mfi_period": {
            "type": "int", "default": 14, "min": 2, "max": 50,
            "label": "MFI Period",
            "description": (
                "Lookback for the Money Flow Index source. "
                "Increasing: smoother MFI. Decreasing: more reactive to volume bursts."
            ),
        },
        "stoch_period": {
            "type": "int", "default": 14, "min": 2, "max": 50,
            "label": "Stochastic Period",
            "description": (
                "Lookback for the Stochastic %K source. "
                "Increasing: smoother stochastic. Decreasing: faster, noisier."
            ),
        },
        "adx_period": {
            "type": "int", "default": 14, "min": 5, "max": 50,
            "label": "ADX Period",
            "description": (
                "Lookback for the ADX trend-strength source. "
                "Increasing: smoother trend reading. Decreasing: more reactive."
            ),
        },
        "macd_fast": {
            "type": "int", "default": 12, "min": 2, "max": 50,
            "label": "MACD Fast Length",
            "description": (
                "Fast EMA of the MACD source. Increasing: slower MACD line. "
                "Decreasing: faster, more sensitive MACD line."
            ),
        },
        "macd_slow": {
            "type": "int", "default": 26, "min": 5, "max": 100,
            "label": "MACD Slow Length",
            "description": (
                "Slow EMA of the MACD source. Increasing: more lag, smoother. "
                "Decreasing: faster, noisier MACD line."
            ),
        },
        "macd_signal": {
            "type": "int", "default": 9, "min": 2, "max": 50,
            "label": "MACD Signal Length",
            "description": (
                "Signal EMA of the MACD source (unused for divergence pivots, kept "
                "for a faithful MACD computation). Increasing/decreasing smooths/sharpens it."
            ),
        },
        "z_period": {
            "type": "int", "default": 20, "min": 5, "max": 100,
            "label": "Z-Score Period",
            "description": (
                "Lookback for the rolling mean/stdev of the Z-Score source. "
                "Increasing: longer-term statistical stretch. Decreasing: shorter-term."
            ),
        },
        "use_rsi": {
            "type": "int", "default": 1, "min": 0, "max": 1,
            "label": "Enable RSI Divergence",
            "description": "1: include RSI in the confluence vote. 0: exclude it.",
        },
        "use_mfi": {
            "type": "int", "default": 1, "min": 0, "max": 1,
            "label": "Enable MFI Divergence",
            "description": "1: include MFI in the confluence vote. 0: exclude it.",
        },
        "use_stoch": {
            "type": "int", "default": 1, "min": 0, "max": 1,
            "label": "Enable Stochastic Divergence",
            "description": "1: include Stochastic in the confluence vote. 0: exclude it.",
        },
        "use_zscore": {
            "type": "int", "default": 1, "min": 0, "max": 1,
            "label": "Enable Z-Score Divergence",
            "description": "1: include Z-Score in the confluence vote. 0: exclude it.",
        },
        "use_adx": {
            "type": "int", "default": 1, "min": 0, "max": 1,
            "label": "Enable ADX Divergence",
            "description": "1: include ADX in the confluence vote. 0: exclude it.",
        },
        "use_macd": {
            "type": "int", "default": 1, "min": 0, "max": 1,
            "label": "Enable MACD Divergence",
            "description": "1: include MACD in the confluence vote. 0: exclude it.",
        },
        "use_obv": {
            "type": "int", "default": 1, "min": 0, "max": 1,
            "label": "Enable OBV Divergence",
            "description": "1: include OBV in the confluence vote. 0: exclude it.",
        },
        "use_price": {
            "type": "int", "default": 1, "min": 0, "max": 1,
            "label": "Enable Price-Action Divergence",
            "description": "1: include price-swing-contraction in the vote. 0: exclude it.",
        },
        "use_swing": {
            "type": "int", "default": 1, "min": 0, "max": 1,
            "label": "Enable Swing-Volume Divergence",
            "description": "1: include raw-volume swing divergence in the vote. 0: exclude it.",
        },
    }

    def __init__(self):
        super().__init__()
        for key, spec in self.PARAMS.items():
            setattr(self, key, spec["default"])

    def validate_params(self) -> None:
        enabled = sum(
            getattr(self, f"use_{s}")
            for s in ("rsi", "mfi", "stoch", "zscore", "adx", "macd", "obv", "price", "swing")
        )
        if enabled == 0:
            raise ValueError("At least one divergence source must be enabled")
        if self.min_confluence > enabled:
            raise ValueError(
                f"min_confluence ({self.min_confluence}) exceeds the number of "
                f"enabled sources ({enabled})"
            )
        if self.macd_fast >= self.macd_slow:
            raise ValueError(
                f"macd_fast ({self.macd_fast}) must be less than macd_slow ({self.macd_slow})"
            )

    # ── Z-Score source (computed inline; no library equivalent) ─────────────

    def _zscore_series(self, close: np.ndarray) -> np.ndarray:
        """Vectorized rolling z-score: ``(close - SMA) / STDEV`` over ``z_period``."""
        w = int(self.z_period)
        n = close.size
        out = np.full(n, np.nan)
        if n < w:
            return out
        csum = np.cumsum(np.insert(close, 0, 0.0))
        csq = np.cumsum(np.insert(close * close, 0, 0.0))
        s = csum[w:] - csum[:-w]
        s2 = csq[w:] - csq[:-w]
        mean = s / w
        var = np.clip(s2 / w - mean * mean, 0.0, None)
        std = np.sqrt(var)
        with np.errstate(invalid="ignore", divide="ignore"):
            z = np.where(std > 0, (close[w - 1:] - mean) / std, 0.0)
        out[w - 1:] = z
        return out

    def _price_div(self, pr_hi, pr_lo) -> int:
        """Structural price-action divergence: a fresh high/low whose swing
        amplitude has contracted to < 70% of the prior swing (source f_price_div)."""
        if pr_hi is None or pr_lo is None:
            return 0
        pr_hi0, pr_hi1 = pr_hi
        pr_lo0, pr_lo1 = pr_lo
        swing_up_1 = pr_hi1 - pr_lo1
        swing_up_0 = pr_hi0 - pr_lo0
        swing_down_1 = pr_hi1 - pr_lo0
        swing_down_0 = pr_hi0 - pr_lo1
        result = 0
        if pr_hi0 > pr_hi1 and swing_up_0 < swing_up_1 * 0.7:
            result = -1
        if pr_lo0 < pr_lo1 and swing_down_0 < swing_down_1 * 0.7:
            result = 1
        return result

    # ── Per-candle signal computation ───────────────────────────────────────

    def before(self) -> None:
        self.vars["signal"] = 0
        n = len(self.candles)
        if n < self.MIN_WARMUP_CANDLES:
            return

        L = int(self.piv_len)
        c = n - 1 - L
        if c < 0:
            return

        atr = ta.atr(self.candles, period=self.atr_period)
        self.vars["atr"] = float(atr) if atr == atr else 0.0  # NaN guard

        # Price swing pivots (high column for highs, low column for lows).
        ph = ta.pivot_high(self.candles, L, L, "high", sequential=True)
        pl = ta.pivot_low(self.candles, L, L, "low", sequential=True)

        # Only act when a brand-new price pivot just confirmed at centre bar c.
        new_pivot = not np.isnan(ph[c]) or not np.isnan(pl[c])
        if not new_pivot:
            return

        pr_hi = _last2(ph)
        pr_lo = _last2(pl)
        if pr_hi is None and pr_lo is None:
            return

        votes = {"bull": 0, "bear": 0}

        def tally(d: int) -> None:
            if d == 1:
                votes["bull"] += 1
            elif d == -1:
                votes["bear"] += 1

        def osc_div(series) -> int:
            osc_hi = _last2(_compute_pivots(series, L, L, True))
            osc_lo = _last2(_compute_pivots(series, L, L, False))
            return _div(pr_hi, pr_lo, osc_hi, osc_lo)

        if self.use_rsi:
            tally(osc_div(ta.rsi(self.candles, period=self.rsi_period, sequential=True)))
        if self.use_mfi:
            tally(osc_div(ta.mfi(self.candles, period=self.mfi_period, sequential=True)))
        if self.use_stoch:
            k, _ = ta.stochastic(self.candles, period=self.stoch_period, sequential=True)
            tally(osc_div(k))
        if self.use_zscore:
            tally(osc_div(self._zscore_series(self.candles[:, 2].astype(float))))
        if self.use_adx:
            tally(osc_div(ta.adx(self.candles, period=self.adx_period, sequential=True)))
        if self.use_macd:
            line, _, _ = ta.macd(
                self.candles, fast=self.macd_fast, slow=self.macd_slow,
                signal=self.macd_signal, sequential=True,
            )
            tally(osc_div(line))
        if self.use_obv:
            tally(osc_div(ta.obv(self.candles, sequential=True)))
        if self.use_price:
            tally(self._price_div(pr_hi, pr_lo))
        if self.use_swing:
            tally(osc_div(self.candles[:, 5].astype(float)))

        bull, bear = votes["bull"], votes["bear"]
        thr = int(self.min_confluence)
        signal = 0
        if bull >= thr and bull > bear:
            signal = 1
        elif bear >= thr and bear > bull and self.allow_shorts:
            signal = -1

        self.vars["signal"] = signal
        self.vars["bull_votes"] = bull
        self.vars["bear_votes"] = bear

    # ── Entry decisions ─────────────────────────────────────────────────────

    def should_long(self) -> bool:
        return self.vars.get("signal", 0) == 1

    def should_short(self) -> bool:
        return bool(self.allow_shorts) and self.vars.get("signal", 0) == -1

    # ── Order placement ─────────────────────────────────────────────────────

    def _stop_distance(self, entry: float, atr: float) -> float:
        if self.use_custom_sl:
            return entry * (self.custom_sl_pct / 100.0)
        return atr * self.sl_atr_mult

    def go_long(self) -> None:
        entry = self.price
        atr = self.vars.get("atr", 0.0)
        if atr <= 0 or entry <= 0:
            return
        sl_dist = self._stop_distance(entry, atr)
        if sl_dist <= 0:
            return
        stop = entry - sl_dist
        target = entry + atr * self.tp_atr_mult
        qty = self.size_by_risk(stop, entry_price=entry)
        if qty <= 0:
            return
        self.buy = qty, entry
        self.stop_loss = qty, stop
        self.take_profit = qty, target

    def go_short(self) -> None:
        entry = self.price
        atr = self.vars.get("atr", 0.0)
        if atr <= 0 or entry <= 0:
            return
        sl_dist = self._stop_distance(entry, atr)
        if sl_dist <= 0:
            return
        stop = entry + sl_dist
        target = entry - atr * self.tp_atr_mult
        qty = self.size_by_risk(stop, entry_price=entry)
        if qty <= 0:
            return
        self.sell = qty, entry
        self.stop_loss = qty, stop
        self.take_profit = qty, target
