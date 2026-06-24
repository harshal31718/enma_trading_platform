"""Protections stack (A-001): post-trade, time-based lockouts.

Inspired by freqtrade's protections system. Each protection independently
evaluates whether trading should be halted (globally or per-pair).

Implemented:
  CooldownPeriod  — block re-entry into a pair for stop_duration after exit.
  StoplossGuard   — halt (global or per-pair) when stoploss count > trade_limit
                    within lookback_period, with optional required_profit filter.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class ProtectionReturn:
    lock: bool = False
    until: float = 0.0
    reason: str = ""
    lock_side: str = "*"

    @property
    def is_active(self) -> bool:
        return self.lock and time.time() < self.until


class IProtection(ABC):
    name: str = ""
    has_global_stop: bool = False
    has_local_stop: bool = False

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self._stop_duration: int = int(self.config.get("stop_duration", 60))
        self._lookback_period: int = int(self.config.get("lookback_period", 60))

    @abstractmethod
    def global_stop(
        self, date_now: datetime, side: str, starting_balance: float
    ) -> ProtectionReturn | None:
        ...

    @abstractmethod
    def stop_per_pair(
        self, pair: str, date_now: datetime, side: str, starting_balance: float
    ) -> ProtectionReturn | None:
        ...

    def _calculate_lock_end(self, close_timestamps: list[float]) -> float:
        if not close_timestamps:
            return 0.0
        return max(close_timestamps) + self._stop_duration * 60


class CooldownPeriod(IProtection):
    has_global_stop: bool = False
    has_local_stop: bool = True

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self._pair_last_close: dict[str, float] = {}

    def record_trade(self, pair: str, close_timestamp: float) -> None:
        self._pair_last_close[pair] = close_timestamp

    def global_stop(
        self, date_now: datetime, side: str, starting_balance: float
    ) -> ProtectionReturn | None:
        return None

    def stop_per_pair(
        self, pair: str, date_now: datetime, side: str, starting_balance: float
    ) -> ProtectionReturn | None:
        last_close = self._pair_last_close.get(pair)
        if last_close is None:
            return None
        lock_until = last_close + self._stop_duration * 60
        if time.time() < lock_until:
            return ProtectionReturn(
                lock=True,
                until=lock_until,
                reason=f"Cooldown period for {self._stop_duration} min after exit on {pair}",
            )
        return None


class StoplossGuard(IProtection):
    has_global_stop: bool = True
    has_local_stop: bool = True

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self._trade_limit: int = int(self.config.get("trade_limit", 10))
        self._profit_limit: float = float(self.config.get("required_profit", 0.0))
        self._only_per_side: bool = bool(self.config.get("only_per_side", False))
        self._stoploss_events: list[dict] = []

    def record_stoploss(
        self, pair: str, side: str, profit: float, timestamp: float
    ) -> None:
        self._stoploss_events.append({
            "pair": pair,
            "side": side,
            "profit": profit,
            "timestamp": timestamp,
        })

    def _count_recent_stoplosses(self, pair: str | None, side: str, now: float) -> int:
        cutoff = now - self._lookback_period * 60
        count = 0
        for ev in self._stoploss_events:
            if ev["timestamp"] < cutoff:
                continue
            if pair is not None and ev["pair"] != pair:
                continue
            if self._only_per_side and ev["side"] != side:
                continue
            if ev["profit"] < self._profit_limit:
                count += 1
        return count

    def global_stop(
        self, date_now: datetime, side: str, starting_balance: float
    ) -> ProtectionReturn | None:
        count = self._count_recent_stoplosses(None, side, date_now.timestamp())
        if count >= self._trade_limit:
            until = date_now.timestamp() + self._stop_duration * 60
            return ProtectionReturn(
                lock=True,
                until=until,
                reason=f"{count} stoplosses in {self._lookback_period} min, locking {self._stop_duration} min",
            )
        return None

    def stop_per_pair(
        self, pair: str, date_now: datetime, side: str, starting_balance: float
    ) -> ProtectionReturn | None:
        count = self._count_recent_stoplosses(pair, side, date_now.timestamp())
        if count >= self._trade_limit:
            until = date_now.timestamp() + self._stop_duration * 60
            return ProtectionReturn(
                lock=True,
                until=until,
                reason=f"{count} stoplosses on {pair} in {self._lookback_period} min",
            )
        return None


class ProtectionManager:
    """Orchestrates a stack of protections for one session."""

    def __init__(self, protections: list[IProtection] | None = None) -> None:
        self.protections: list[IProtection] = protections or []

    def add(self, protection: IProtection) -> None:
        self.protections.append(protection)

    def check_entry(
        self, pair: str, side: str, starting_balance: float
    ) -> ProtectionReturn | None:
        now = datetime.now(timezone.utc)
        for p in self.protections:
            if p.has_global_stop:
                result = p.global_stop(now, side, starting_balance)
                if result and result.is_active:
                    return result
            if p.has_local_stop:
                result = p.stop_per_pair(pair, now, side, starting_balance)
                if result and result.is_active:
                    return result
        return None

    def record_trade_close(
        self, pair: str, side: str, exit_reason: str,
        profit: float, close_timestamp: float
    ) -> None:
        for p in self.protections:
            if isinstance(p, CooldownPeriod):
                p.record_trade(pair, close_timestamp)
            if isinstance(p, StoplossGuard) and exit_reason in (
                "stop_loss", "trailing_stop_loss", "stoploss_on_exchange", "liquidation"
            ):
                p.record_stoploss(pair, side, profit, close_timestamp)
