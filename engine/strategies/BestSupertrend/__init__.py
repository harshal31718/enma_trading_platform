import numpy as np
import pandas as pd
from engine.core.strategy import BaseStrategy
import engine.indicators as ta
from engine.indicators.base import HIGH, LOW, CLOSE


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
    """

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
            "default": 3,
            "min": 1,
            "max": 100,
            "label": "Supertrend ATR Period"
        },
        "tf": {
            "type": "str",
            "default": "daily",
            "options": ["daily", "weekly", "monthly", "quarterly", "yearly"],
            "label": "Supertrend Timeframe"
        },
        "position_size_pct": {
            "type": "float",
            "default": 0.1,
            "min": 0.01,
            "max": 1.0,
            "label": "Position Size (% of Equity)"
        }
    }

    def __init__(self):
        super().__init__()
        # Initialize default parameter values
        self.order_type: str = self.PARAMS["order_type"]["default"]
        self.fast_length: int = self.PARAMS["fast_length"]["default"]
        self.slow_length: int = self.PARAMS["slow_length"]["default"]
        self.factor: float = self.PARAMS["factor"]["default"]
        self.pd: int = self.PARAMS["pd"]["default"]
        self.tf: str = self.PARAMS["tf"]["default"]
        self.position_size_pct: float = self.PARAMS["position_size_pct"]["default"]

    def _is_same_timeframe(self) -> bool:
        """Helper to check if target Supertrend timeframe matches chart timeframe."""
        tf_map = {
            "daily": "1d",
            "weekly": "1w",
            "monthly": "1M",
            "quarterly": "3M",
            "yearly": "12M"
        }
        mapped = tf_map.get(self.tf.lower())
        if mapped is None:
            return False
        return self.timeframe.lower() == mapped.lower()

    def _get_resampled_candles(self) -> np.ndarray:
        """
        Resamples self.candles to the timeframe specified in self.tf.
        To avoid lookahead bias, we only include the data that has completed.
        """
        if self._is_same_timeframe():
            return self.candles

        tf_map = {
            "daily": "D",
            "weekly": "W-MON",
            "monthly": "MS",
            "quarterly": "3MS",
            "yearly": "YS"
        }
        rule = tf_map.get(self.tf.lower(), "D")

        # Convert self.candles (numpy array) to pandas DataFrame
        # Columns: [timestamp, open, close, high, low, volume]
        df = pd.DataFrame(self.candles, columns=['timestamp', 'open', 'close', 'high', 'low', 'volume'])
        df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
        df.set_index('datetime', inplace=True)

        # Resample OHLCV
        resampler = df.resample(rule)
        resampled_df = resampler.agg({
            'open': 'first',
            'close': 'last',
            'high': 'max',
            'low': 'min',
            'volume': 'sum'
        })
        resampled_df.dropna(subset=['open', 'close', 'high', 'low'], inplace=True)

        # Convert back to numpy array with timestamp
        resampled = np.column_stack([
            resampled_df.index.astype(np.int64) // 10**6, # timestamp in ms
            resampled_df['open'].values.astype(np.float64),
            resampled_df['close'].values.astype(np.float64),
            resampled_df['high'].values.astype(np.float64),
            resampled_df['low'].values.astype(np.float64),
            resampled_df['volume'].values.astype(np.float64)
        ])
        return resampled

    def _calculate_supertrend(self, candles: np.ndarray) -> np.ndarray:
        """
        Calculates the Supertrend indicator values on the given candles.
        Equivalent to Pinescript's f_supertrend(Factor, Pd).
        """
        # Calculate ATR series
        atr_series = ta.atr(candles, period=self.pd, sequential=True)

        # hl2 calculation
        highs = candles[:, HIGH].astype(float)
        lows = candles[:, LOW].astype(float)
        closes = candles[:, CLOSE].astype(float)
        hl2 = (highs + lows) / 2.0

        n = len(candles)
        up = hl2 - (self.factor * atr_series)
        dn = hl2 + (self.factor * atr_series)

        trend_up = np.zeros(n)
        trend_down = np.zeros(n)
        trend = np.zeros(n)
        tsl = np.zeros(n)

        # Initial values
        trend_up[0] = up[0]
        trend_down[0] = dn[0]
        trend[0] = 1
        tsl[0] = trend_up[0]

        for i in range(1, n):
            if np.isnan(atr_series[i]):
                trend_up[i] = up[i]
                trend_down[i] = dn[i]
                trend[i] = 1
                tsl[i] = up[i]
                continue

            # TrendUp logic
            if closes[i-1] > trend_up[i-1]:
                trend_up[i] = max(up[i], trend_up[i-1])
            else:
                trend_up[i] = up[i]

            # TrendDown logic
            if closes[i-1] < trend_down[i-1]:
                trend_down[i] = min(dn[i], trend_down[i-1])
            else:
                trend_down[i] = dn[i]

            # Trend logic
            if closes[i] > trend_down[i-1]:
                trend[i] = 1
            elif closes[i] < trend_up[i-1]:
                trend[i] = -1
            else:
                trend[i] = trend[i-1] if trend[i-1] != 0 else 1

            # Trailing Stop Line (Tsl)
            tsl[i] = trend_up[i] if trend[i] == 1 else trend_down[i]

        return tsl

    def _get_htf_supertrend(self) -> float | None:
        """Retrieves the Supertrend value of the previous completed higher-timeframe candle."""
        resampled = self._get_resampled_candles()
        
        # We need enough candles to calculate the ATR and have a completed candle
        if len(resampled) < self.pd + 2:
            return None

        tsl = self._calculate_supertrend(resampled)
        # Using tsl[-2] gives the Supertrend value of the previous completed candle,
        # preventing lookahead bias.
        return float(tsl[-2])

    def _evaluate_signals(self) -> tuple[bool, bool, bool, bool]:
        """
        Calculates and returns (bull, bear, long_exit, short_exit) signal booleans.
        Equivalent to:
          long_exit  = crossunder(sma_fast, sma_slow)
          short_exit = crossover(sma_fast, sma_slow)
          cross_buy  = (most recent cross is crossover)
          cross_sell = (most recent cross is crossunder)
          bull = close >= st_tsl_TF and cross_buy
          bear = close <= st_tsl_TF and cross_sell
        """
        if len(self.candles) < max(self.fast_length, self.slow_length) + 1:
            return False, False, False, False

        # Compute SMA series on the base timeframe
        sma_fast_series = ta.sma(self.candles, period=self.fast_length, sequential=True)
        sma_slow_series = ta.sma(self.candles, period=self.slow_length, sequential=True)

        if np.isnan(sma_fast_series[-1]) or np.isnan(sma_slow_series[-1]):
            return False, False, False, False

        # Current and previous SMA values
        fast_curr, slow_curr = float(sma_fast_series[-1]), float(sma_slow_series[-1])
        fast_prev, slow_prev = float(sma_fast_series[-2]), float(sma_slow_series[-2])

        # long_exit / short_exit crossovers on base timeframe
        long_exit = (fast_prev >= slow_prev) and (fast_curr < slow_curr)
        short_exit = (fast_prev <= slow_prev) and (fast_curr > slow_curr)

        # Scan backwards to find the most recent crossover event
        cross_buy = False
        cross_sell = False
        for idx in range(len(self.candles) - 1, 0, -1):
            f_curr, s_curr = sma_fast_series[idx], sma_slow_series[idx]
            f_prev, s_prev = sma_fast_series[idx-1], sma_slow_series[idx-1]

            if np.isnan(f_curr) or np.isnan(s_curr) or np.isnan(f_prev) or np.isnan(s_prev):
                break

            is_crossover = (f_prev <= s_prev) and (f_curr > s_curr)
            is_crossunder = (f_prev >= s_prev) and (f_curr < s_curr)

            if is_crossover:
                cross_buy = True
                break
            elif is_crossunder:
                cross_sell = True
                break

        # Get the lookahead-free Higher Timeframe Supertrend value
        st_tsl_tf = self._get_htf_supertrend()
        if st_tsl_tf is None:
            return False, False, False, False

        bull = (self.price >= st_tsl_tf) and cross_buy
        bear = (self.price <= st_tsl_tf) and cross_sell

        return bull, bear, long_exit, short_exit

    def should_long(self) -> bool:
        if self.order_type == "ShortsOnly":
            return False
        bull, _, _, _ = self._evaluate_signals()
        return bull

    def should_short(self) -> bool:
        if self.order_type == "LongsOnly":
            return False
        _, bear, _, _ = self._evaluate_signals()
        return bear

    def go_long(self) -> None:
        qty = self.size_by_notional(self.position_size_pct)
        if qty > 0:
            self.buy = qty, self.price

    def go_short(self) -> None:
        qty = self.size_by_notional(self.position_size_pct)
        if qty > 0:
            self.sell = qty, self.price

    def update_position(self) -> None:
        """Exits active position or flips atomically if reverse signals trigger."""
        bull, bear, long_exit, short_exit = self._evaluate_signals()

        if self.is_long:
            if long_exit:
                # If short exit crossover occurs and we have a bear entry signal, reverse position
                if self.order_type != "LongsOnly" and bear:
                    qty = self.size_by_notional(self.position_size_pct)
                    if qty > 0:
                        self.flip_position(qty)
                else:
                    self.liquidate()

        elif self.is_short:
            if short_exit:
                # If long exit crossover occurs and we have a bull entry signal, reverse position
                if self.order_type != "ShortsOnly" and bull:
                    qty = self.size_by_notional(self.position_size_pct)
                    if qty > 0:
                        self.flip_position(qty)
                else:
                    self.liquidate()
