from abc import ABC, abstractmethod
import numpy as np


class BaseStrategy(ABC):
    """
    Base class for all Enma trading strategies.
    Mirrors Jesse's strategy API for portability.
    All strategies must extend this class.
    """

    def __init__(self):
        # Candle data — set by the backtest/live engine before each call
        self.candles: np.ndarray = np.array([])
        self.exchange: str = ""
        self.symbol: str = ""
        self.timeframe: str = ""

        # Position state — set by the engine
        self.position = None
        self.balance: float = 0.0
        self.available_margin: float = 0.0
        self.leverage: int = 1
        self.fee_rate: float = 0.001
        self.exchange_type: str = "futures"  # "spot" | "futures"

        # Order setters — strategy writes to these, engine reads them
        self.buy = None        # (qty, price) or [(qty, price), ...]
        self.sell = None       # (qty, price) or [(qty, price), ...]
        self.stop_loss = None  # (qty, price) or [(qty, price), ...]
        self.take_profit = None  # (qty, price) or [(qty, price), ...]

        # Candle index counter — incremented by engine on each candle
        self.index: int = 0

        # Custom variables — strategy can store anything here
        self.vars: dict = {}

        # Mode flags — set by engine
        self.is_backtesting: bool = False
        self.is_livetrading: bool = False
        self.is_papertrading: bool = False

    # ─────────────────────────────────────────
    # Candle property accessors
    # ─────────────────────────────────────────

    @property
    def current_candle(self) -> np.ndarray:
        """Returns the current candle as [timestamp, open, close, high, low, volume]"""
        return self.candles[-1] if len(self.candles) > 0 else np.array([])

    @property
    def close(self) -> float:
        return float(self.current_candle[2]) if len(self.current_candle) > 0 else 0.0

    @property
    def price(self) -> float:
        return self.close

    @property
    def open(self) -> float:
        return float(self.current_candle[1]) if len(self.current_candle) > 0 else 0.0

    @property
    def high(self) -> float:
        return float(self.current_candle[3]) if len(self.current_candle) > 0 else 0.0

    @property
    def low(self) -> float:
        return float(self.current_candle[4]) if len(self.current_candle) > 0 else 0.0

    @property
    def volume(self) -> float:
        return float(self.current_candle[5]) if len(self.current_candle) > 0 else 0.0

    # ─────────────────────────────────────────
    # Position property accessors
    # ─────────────────────────────────────────

    @property
    def is_open(self) -> bool:
        return self.position is not None and self.position.is_open

    @property
    def is_close(self) -> bool:
        return not self.is_open

    @property
    def is_long(self) -> bool:
        return self.is_open and self.position.type == "long"

    @property
    def is_short(self) -> bool:
        return self.is_open and self.position.type == "short"

    @property
    def is_live(self) -> bool:
        return self.is_livetrading or self.is_papertrading

    @property
    def is_spot_trading(self) -> bool:
        return self.exchange_type == "spot"

    @property
    def is_futures_trading(self) -> bool:
        return self.exchange_type == "futures"

    # ─────────────────────────────────────────
    # Required methods — must be overridden
    # ─────────────────────────────────────────

    @abstractmethod
    def should_long(self) -> bool:
        """Return True to open a long position. Called only when no position is open."""
        raise NotImplementedError

    @abstractmethod
    def should_short(self) -> bool:
        """Return True to open a short position. Called only when no position is open."""
        raise NotImplementedError

    @abstractmethod
    def should_cancel_entry(self) -> bool:
        """Return True to cancel a pending entry order."""
        raise NotImplementedError

    @abstractmethod
    def go_long(self) -> None:
        """Define entry, stop-loss, and take-profit for a long trade.
        Set self.buy, self.stop_loss, self.take_profit.
        """
        raise NotImplementedError

    @abstractmethod
    def go_short(self) -> None:
        """Define entry, stop-loss, and take-profit for a short trade.
        Set self.sell, self.stop_loss, self.take_profit.
        """
        raise NotImplementedError

    # ─────────────────────────────────────────
    # Optional lifecycle methods — override as needed
    # ─────────────────────────────────────────

    def before(self) -> None:
        """Called before each candle. Use for updating self.vars."""
        pass

    def after(self) -> None:
        """Called after each candle. Use for cleanup or logging."""
        pass

    def update_position(self) -> None:
        """Called every candle when a position is open.
        Use to update stop-loss, take-profit, or add to position.
        """
        pass

    def before_terminate(self) -> None:
        """Called right before termination. Can submit orders."""
        pass

    def terminate(self) -> None:
        """Called on termination. Cannot submit orders. Use for logging."""
        pass

    # ─────────────────────────────────────────
    # Optional event methods — override as needed
    # ─────────────────────────────────────────

    def on_open_position(self, order) -> None:
        """Called right after an open-position order is executed."""
        pass

    def on_close_position(self, order) -> None:
        """Called when position is closed by stop-loss or take-profit."""
        pass

    def on_increased_position(self, order) -> None:
        """Called when position size is increased."""
        pass

    def on_reduced_position(self, order) -> None:
        """Called when position size is reduced (but not closed)."""
        pass

    def on_cancel(self) -> None:
        """Called after all active orders are canceled."""
        pass

    # ─────────────────────────────────────────
    # Utility methods
    # ─────────────────────────────────────────

    def liquidate(self) -> None:
        """Close the open position immediately at market price."""
        if self.is_open:
            if self.is_long:
                self.take_profit = self.position.qty, self.price
            else:
                self.stop_loss = self.position.qty, self.price

    def log(self, msg: str) -> None:
        """Log a message during strategy execution."""
        print(f"[{self.symbol}] {msg}")
