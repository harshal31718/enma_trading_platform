import numpy as np
import talib


def ema(candles: np.ndarray, period: int = 9, sequential: bool = False):
    """Exponential Moving Average"""
    close = candles[:, 2].astype(float)
    result = talib.EMA(close, timeperiod=period)
    return result if sequential else float(result[-1])


def sma(candles: np.ndarray, period: int = 20, sequential: bool = False):
    """Simple Moving Average"""
    close = candles[:, 2].astype(float)
    result = talib.SMA(close, timeperiod=period)
    return result if sequential else float(result[-1])


def rsi(candles: np.ndarray, period: int = 14, sequential: bool = False):
    """Relative Strength Index"""
    close = candles[:, 2].astype(float)
    result = talib.RSI(close, timeperiod=period)
    return result if sequential else float(result[-1])


def atr(candles: np.ndarray, period: int = 14, sequential: bool = False):
    """Average True Range"""
    high = candles[:, 3].astype(float)
    low = candles[:, 4].astype(float)
    close = candles[:, 2].astype(float)
    result = talib.ATR(high, low, close, timeperiod=period)
    return result if sequential else float(result[-1])


def donchian(candles: np.ndarray, period: int = 20, sequential: bool = False):
    """
    Donchian Channel.
    Returns: (upper, middle, lower)
    """
    high = candles[:, 3].astype(float)
    low = candles[:, 4].astype(float)
    upper = talib.MAX(high, timeperiod=period)
    lower = talib.MIN(low, timeperiod=period)
    middle = (upper + lower) / 2
    if sequential:
        return upper, middle, lower
    return float(upper[-1]), float(middle[-1]), float(lower[-1])


def macd(candles: np.ndarray, fast: int = 12, slow: int = 26, signal: int = 9, sequential: bool = False):
    """MACD — returns (macd_line, signal_line, histogram)"""
    close = candles[:, 2].astype(float)
    macd_line, signal_line, histogram = talib.MACD(close, fastperiod=fast, slowperiod=slow, signalperiod=signal)
    if sequential:
        return macd_line, signal_line, histogram
    return float(macd_line[-1]), float(signal_line[-1]), float(histogram[-1])


def bollinger_bands(candles: np.ndarray, period: int = 20, std: float = 2.0, sequential: bool = False):
    """Bollinger Bands — returns (upper, middle, lower)"""
    close = candles[:, 2].astype(float)
    upper, middle, lower = talib.BBANDS(close, timeperiod=period, nbdevup=std, nbdevdn=std)
    if sequential:
        return upper, middle, lower
    return float(upper[-1]), float(middle[-1]), float(lower[-1])
