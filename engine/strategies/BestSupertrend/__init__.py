import numpy as np
import pandas as pd
from engine.core.strategy import BaseStrategy
import engine.indicators as ta
from engine.indicators.base import HIGH, LOW, CLOSE

try:
    from engine.core.models import AtrBracketRiskModel, NotionalPortfolio, Signal
except ImportError:
    from core.models import AtrBracketRiskModel, NotionalPortfolio, Signal


class BestSupertrend(BaseStrategy):
    """
    BEST Supertrend Strategy.

    Filters entries using a multi-timeframe Supertrend indicator and enters/exits
    based on fast/slow SMA crossovers.

    Pinescript source logic:
      - Supertrend calculated on a user-defined timeframe (default Daily).
      - Fast and Slow SMAs (default 7/20) calculated on the base timeframe.
      - Enters Long when: Close >= Supertrend and SMA Crossover has happened (cross_buy).
      - Enters Short when: Close <= Supertrend and SMA Crossunder has happened (cross_sell).
      - Exits Long when: Fast SMA crosses under Slow SMA.
      - Exits Short when: Fast SMA crosses over Slow SMA.

    Known deviation from prior implementation: exits now use _close_at_open
    (next-open fill) instead of liquidate() (same-candle close price). This is an
    intentional boundary-clean change; a new golden-master baseline is required.
    See workspace/docs/core/DECISIONS.md for rationale.
    """

    # Maps tf param values to Binance interval strings
    TF_MAP = {
        "1h": "1h",
        "4h": "4h",
        "daily": "1d",
        "weekly": "1w",
        "monthly": "1M",
    }

    # Maps tf param values to pandas resample rules (backtest path)
    _RESAMPLE_RULES = {
        "1h": "1h",
        "4h": "4h",
        "daily": "D",
        "weekly": "W-MON",
        "monthly": "MS",
    }

    PARAMS = {
        "order_type": {
            "type": "str",
            "default": "Longs+Shorts",
            "options": ["Longs+Shorts", "LongsOnly", "ShortsOnly"],
            "label": "Order Type Filter"
        },
        "fast_length": {
            "type": "int",
            "default": 7,
            "min": 1,
            "max": 100,
            "label": "Fast SMA Length"
        },
        "slow_length": {
            "type": "int",
            "default": 20,
            "min": 2,
            "max": 200,
            "label": "Slow SMA Length"
        },
        "factor": {
            "type": "float",
            "default": 3.0,
            "min": 1.0,
            "max": 100.0,
            "label": "Supertrend Factor"
        },
        "pd": {
            "type": "int",
            "default": 10,
            "min": 1,
            "max": 100,
            "label": "Supertrend ATR Period"
        },
        "sl_atr_mult": {
            "type": "float",
            "default": 2.0,
            "min": 0.5,
            "max": 10.0,
            "label": "Stop-Loss ATR Multiplier"
        },
        "atr_period": {
            "type": "int",
            "default": 14,
            "min": 5,
            "max": 50,
            "label": "ATR Period (stop sizing)"
        },
        "tf": {
            "type": "str",
            "default": "daily",
            "options": ["1h", "4h", "daily", "weekly", "monthly"],
            "label": "Supertrend Timeframe"
        },
        "position_size_pct": {
            "type": "float",
            "default": 0.9,
            "min": 0.01,
            "max": 1.0,
            "label": "Position Size (% of Equity)"
        }
    }

    def __init__(self):
        super().__init__()
        self.order_type: str       = self.PARAMS["order_type"]["default"]
        self.fast_length: int      = self.PARAMS["fast_length"]["default"]
        self.slow_length: int      = self.PARAMS["slow_length"]["default"]
        self.factor: float         = self.PARAMS["factor"]["default"]
        self.pd: int               = self.PARAMS["pd"]["default"]
        self.tf: str               = self.PARAMS["tf"]["default"]
        self.position_size_pct: float = self.PARAMS["position_size_pct"]["default"]
        self.sl_atr_mult: float    = self.PARAMS["sl_atr_mult"]["default"]
        self.atr_period: int       = self.PARAMS["atr_period"]["default"]

        # Pre-fetched HTF candles injected by live_bot_manager (None in backtest → resampling path)
        self._htf_candles = None

        # Narang Black-Box: ATR bracket for hard SL protection; signal-driven
        # exits still fire first via forecast() returning direction=0 on crossover.
        self.risk_model      = AtrBracketRiskModel()
        self.portfolio_model = NotionalPortfolio()

    def _safe_sma(self, candles: np.ndarray, period: int) -> np.ndarray:
        """Return SMA series or NaNs when not enough data to avoid TA errors.
        The underlying indicator may raise a Bad Parameter error if period > data length.
        This helper returns an array of NaNs matching the candle length in such cases.
        """
        if len(candles) < period:
            return np.full(len(candles), np.nan, dtype=float)
        return ta.sma(candles, period=period, sequential=True)


    def _is_same_timeframe(self) -> bool:
        mapped = self.TF_MAP.get(self.tf.lower())
        if mapped is None:
            return False
        # Case-sensitive: "1m" (1 min) must not match "1M" (monthly)
        return self.timeframe == mapped

    # ── Phase A: one-time vectorized pre-computation (full candle array) ─────
    def prepare(self, candles: np.ndarray) -> None:
        """Pre-compute SMA crossover arrays and the HTF supertrend once.

        Replaces the per-candle work in ``_evaluate_signals()`` (pandas resample +
        supertrend + backward SMA-crossover scan, all O(N) per candle):
          * SMA fast/slow sequences and per-index ``cross_up``/``cross_dn`` (which
            are exactly the short_exit/long_exit conditions) + a ``recent`` state
            machine giving the most-recent crossover at or before each candle
            (== the original backward "first crossover scanning down").
          * The HTF supertrend computed once over the full resample; the
            last-completed HTF bar value (the original ``tsl[-2]``) is looked up
            per base candle via its HTF bucket index ``k`` → ``htf_tsl[k-1]``.
            Causal supertrend ⇒ a prefix resample equals the full resample for
            every completed bucket, so this is identical to the per-candle form.
        """
        n = len(candles)
        if n == 0:
            e = np.array([])
            self._sma_fast = e
            self._sma_slow = e
            self._cross_up = np.zeros(0, dtype=bool)
            self._cross_dn = np.zeros(0, dtype=bool)
            self._recent = np.zeros(0, dtype=int)
            self._htf_tsl = e
            self._htf_k = None
            self._htf_is_constant = False
            self._htf_constant_val = None
            return

        self._sma_fast = self._safe_sma(candles, self.fast_length)
        self._sma_slow = self._safe_sma(candles, self.slow_length)
        self._cross_up, self._cross_dn, self._recent = self._build_cross_arrays(
            self._sma_fast, self._sma_slow
        )

        self._htf_is_constant = False
        self._htf_constant_val = None
        self._htf_k = None
        self._htf_tsl = np.array([])

        if self._is_same_timeframe():
            R = candles
            self._htf_k = np.arange(n)
        elif self._htf_candles is not None and len(self._htf_candles) > 0:
            # Live path: HTF series is fixed for the current candle → constant tsl[-2]
            R = self._htf_candles
            self._htf_is_constant = True
        else:
            R, self._htf_k = self._resample_with_map(candles)

        if len(R) > 0:
            self._htf_tsl = self._calculate_supertrend(R)
        if self._htf_is_constant:
            self._htf_constant_val = (
                float(self._htf_tsl[-2])
                if len(R) >= self.pd + 2 and len(self._htf_tsl) >= 2 else None
            )

    def _resample_with_map(self, candles: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Resample the base candles to the HTF (default pandas semantics, matching
        the prior implementation) and return ``(resampled, k_per_candle)`` where
        ``k_per_candle[i]`` is the HTF bucket-row index containing base candle ``i``.

        Bucket mapping uses ``searchsorted`` on bucket-start labels — exact for the
        left-labeled rules (1h/4h/daily/monthly). Weekly (W-MON, right-labeled) is
        a known off-by-one edge to revisit; it is not part of the golden config.
        """
        rule = self._RESAMPLE_RULES.get(self.tf.lower(), "D")

        df = pd.DataFrame(candles, columns=['timestamp', 'open', 'close', 'high', 'low', 'volume'])
        df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
        df.set_index('datetime', inplace=True)

        resampled_df = df.resample(rule).agg({
            'open': 'first',
            'close': 'last',
            'high': 'max',
            'low': 'min',
            'volume': 'sum'
        })
        resampled_df.dropna(subset=['open', 'close', 'high', 'low'], inplace=True)

        resampled = np.column_stack([
            resampled_df.index.astype(np.int64) // 10**6,
            resampled_df['open'].values.astype(np.float64),
            resampled_df['close'].values.astype(np.float64),
            resampled_df['high'].values.astype(np.float64),
            resampled_df['low'].values.astype(np.float64),
            resampled_df['volume'].values.astype(np.float64)
        ])
        if len(resampled) == 0:
            return resampled, np.zeros(len(candles), dtype=int)

        # Map each base candle to its HTF bucket row via the actual datetimes
        # (forward-fill the most recent bucket label ≤ candle time). This avoids
        # the column-0 unit pitfall: pandas 2.x to_datetime(unit='ms') yields a
        # datetime64[ms] index, so index.astype(int64)//1e6 corrupts the epoch.
        bucket_pos = pd.Series(np.arange(len(resampled_df)), index=resampled_df.index)
        k = bucket_pos.reindex(df.index, method='ffill').to_numpy()
        k = np.nan_to_num(k, nan=0.0).astype(int)
        k = np.clip(k, 0, len(resampled) - 1)
        return resampled, k

    @staticmethod
    def _build_cross_arrays(f: np.ndarray, s: np.ndarray):
        """Per-index SMA cross flags + most-recent-crossover state.

        ``cross_up[i]``  : fast crosses above slow at i  (== short_exit / cross_buy condition)
        ``cross_dn[i]``  : fast crosses below slow at i  (== long_exit / cross_sell condition)
        ``recent[i]``    : +1 if the most recent crossover at/before i was up, -1 if down, else 0
                           (reproduces the original backward "first crossover scanning down").
        """
        n = len(f)
        cross_up = np.zeros(n, dtype=bool)
        cross_dn = np.zeros(n, dtype=bool)
        recent = np.zeros(n, dtype=int)
        state = 0
        for i in range(1, n):
            fp, sp, fc, sc = f[i - 1], s[i - 1], f[i], s[i]
            if not (np.isnan(fp) or np.isnan(sp) or np.isnan(fc) or np.isnan(sc)):
                if fp <= sp and fc > sc:
                    cross_up[i] = True
                    state = 1
                elif fp >= sp and fc < sc:
                    cross_dn[i] = True
                    state = -1
            recent[i] = state
        return cross_up, cross_dn, recent

    def _calculate_supertrend(self, candles: np.ndarray) -> np.ndarray:
        atr_series = ta.atr(candles, period=self.pd, sequential=True)

        highs  = candles[:, HIGH].astype(float)
        lows   = candles[:, LOW].astype(float)
        closes = candles[:, CLOSE].astype(float)
        hl2    = (highs + lows) / 2.0

        n  = len(candles)
        up = hl2 - (self.factor * atr_series)
        dn = hl2 + (self.factor * atr_series)

        trend_up   = np.zeros(n)
        trend_down = np.zeros(n)
        trend      = np.zeros(n)
        tsl        = np.zeros(n)

        trend_up[0]   = up[0]
        trend_down[0] = dn[0]
        trend[0]      = 1
        tsl[0]        = trend_up[0]

        for i in range(1, n):
            if np.isnan(atr_series[i]):
                trend_up[i]   = up[i]
                trend_down[i] = dn[i]
                trend[i]      = 1
                tsl[i]        = up[i]
                continue

            trend_up[i]   = max(up[i], trend_up[i-1])   if closes[i-1] > trend_up[i-1]   else up[i]
            trend_down[i] = min(dn[i], trend_down[i-1]) if closes[i-1] < trend_down[i-1] else dn[i]

            if closes[i] > trend_down[i-1]:
                trend[i] = 1
            elif closes[i] < trend_up[i-1]:
                trend[i] = -1
            else:
                trend[i] = trend[i-1] if trend[i-1] != 0 else 1

            tsl[i] = trend_up[i] if trend[i] == 1 else trend_down[i]

        return tsl

    def _htf_st_at(self, i: int) -> float | None:
        """Last-completed HTF supertrend value as of base candle ``i`` — the
        precomputed equivalent of the original ``tsl[-2]``."""
        if self._htf_is_constant:
            return self._htf_constant_val
        if self._htf_k is None or len(self._htf_tsl) == 0:
            return None
        k = int(self._htf_k[i])
        # len(prefix resample) == k + 1; original returns None when < pd + 2
        if (k + 1) < self.pd + 2:
            return None
        if not (0 <= k - 1 < len(self._htf_tsl)):
            return None
        return float(self._htf_tsl[k - 1])

    # ── Phase B: per-candle index lookup only (no TA-Lib / pandas) ──────────
    def _evaluate_signals(self) -> tuple[bool, bool, bool, bool]:
        i = self.index
        if (i + 1) < max(self.fast_length, self.slow_length) + 1:
            return False, False, False, False

        if np.isnan(self._sma_fast[i]) or np.isnan(self._sma_slow[i]):
            return False, False, False, False

        long_exit  = bool(self._cross_dn[i])
        short_exit = bool(self._cross_up[i])
        cross_buy  = self._recent[i] == 1
        cross_sell = self._recent[i] == -1

        st_tsl_tf = self._htf_st_at(i)
        if st_tsl_tf is None:
            return False, False, False, False

        bull = (self.price >= st_tsl_tf) and cross_buy
        bear = (self.price <= st_tsl_tf) and cross_sell

        return bull, bear, long_exit, short_exit

    # ── Alpha Model: forecast() handles both open and flat cases ────────────

    def forecast(self) -> Signal:
        """Signal-exit supertrend logic.

        While holding long:
          - long_exit + bear + not LongsOnly → flip short
          - long_exit only → close (signal exit)
          - else → maintain
        While holding short:
          - short_exit + bull + not ShortsOnly → flip long
          - short_exit only → close
          - else → maintain
        While flat:
          - bull (and not ShortsOnly) → long
          - bear (and not LongsOnly) → short
          - else → flat
        """
        bull, bear, long_exit, short_exit = self._evaluate_signals()

        if self.is_long:
            if long_exit:
                if self.order_type != "LongsOnly" and bear:
                    return Signal(direction=-1, conviction=1.0, ref_price=self.price)
                return Signal(direction=0, ref_price=self.price)  # close
            return Signal(direction=1, conviction=1.0, ref_price=self.price)

        if self.is_short:
            if short_exit:
                if self.order_type != "ShortsOnly" and bull:
                    return Signal(direction=1, conviction=1.0, ref_price=self.price)
                return Signal(direction=0, ref_price=self.price)  # close
            return Signal(direction=-1, conviction=1.0, ref_price=self.price)

        # Flat
        if self.order_type != "ShortsOnly" and bull:
            return Signal(direction=1, conviction=1.0, ref_price=self.price)
        if self.order_type != "LongsOnly" and bear:
            return Signal(direction=-1, conviction=1.0, ref_price=self.price)
        return Signal(direction=0, ref_price=self.price)
