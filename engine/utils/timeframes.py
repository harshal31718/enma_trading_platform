from datetime import timedelta

_UNIT_MS = {"m": 60_000, "h": 3_600_000, "d": 86_400_000, "w": 604_800_000}
_UNIT_MINS = {"m": 1, "h": 60, "d": 1_440, "w": 10_080}


def to_ms(timeframe: str) -> int:
    """Convert timeframe string to milliseconds (e.g., '1h' -> 3600000)."""
    try:
        val = int(timeframe[:-1])
        unit = timeframe[-1]
        return val * _UNIT_MS[unit]
    except Exception:
        return 3_600_000  # Default 1h in ms


def to_timedelta(timeframe: str) -> timedelta:
    """Convert timeframe string to timedelta (e.g., '1h' -> timedelta(hours=1))."""
    try:
        val = int(timeframe[:-1])
        unit = timeframe[-1]
        return timedelta(minutes=val * _UNIT_MINS[unit])
    except Exception:
        return timedelta(hours=1)  # Default 1h


# Plan 24 finding S-3: strategies with a higher-timeframe ("HTF") supertrend
# concept (e.g. BestSupertrend's `tf` param: "1h"/"4h"/"daily"/"weekly"/
# "monthly") can be structurally unable to ever form enough completed HTF
# buckets within a given base-timeframe candle window — most acutely
# tf="weekly"/"monthly" against a short base-candle window, where the
# strategy silently produces zero trades forever with no diagnostic. Day-
# length ratios (not `to_ms`/`to_timedelta` above, which don't parse the
# word-form HTF labels) let a caller estimate the required base-candle count
# and fail loud/log instead of guessing why a strategy never trades.
_HTF_TF_DAYS = {"1h": 1 / 24, "4h": 4 / 24, "daily": 1.0, "weekly": 7.0, "monthly": 30.0}
_BASE_TF_DAYS = {
    "1m": 1 / 1440, "3m": 3 / 1440, "5m": 5 / 1440, "15m": 15 / 1440, "30m": 30 / 1440,
    "1h": 1 / 24, "2h": 2 / 24, "4h": 4 / 24, "6h": 6 / 24, "8h": 8 / 24, "12h": 12 / 24,
    "1d": 1.0,
}


def required_base_candles_for_htf(htf_tf: str, htf_pd: int, base_timeframe: str) -> int | None:
    """Estimate how many base-timeframe candles are needed to form
    ``htf_pd + 2`` completed HTF buckets (the warmup floor used throughout
    BestSupertrend — see `_htf_st_at`'s own `pd + 2` gate). Returns ``None``
    when either timeframe string isn't recognized (caller should skip the
    check rather than guess) — never raises.
    """
    htf_days = _HTF_TF_DAYS.get((htf_tf or "").lower())
    base_days = _BASE_TF_DAYS.get((base_timeframe or "").lower())
    if htf_days is None or not base_days:
        return None
    return int((htf_pd + 2) * htf_days / base_days)


def annual_factor(timeframe: str) -> int:
    """Calculate annual factor representing the number of candles per year."""
    try:
        val = int(timeframe[:-1])
        unit = timeframe[-1]
        minutes_per_year = 525_600
        return minutes_per_year // (val * _UNIT_MINS[unit])
    except Exception:
        return 8760  # Default 1h factor
