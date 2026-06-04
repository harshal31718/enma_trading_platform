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


def annual_factor(timeframe: str) -> int:
    """Calculate annual factor representing the number of candles per year."""
    try:
        val = int(timeframe[:-1])
        unit = timeframe[-1]
        minutes_per_year = 525_600
        return minutes_per_year // (val * _UNIT_MINS[unit])
    except Exception:
        return 8760  # Default 1h factor
