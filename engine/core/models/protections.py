"""Protections stack (A-001): post-trade, time-based lockouts.

Inspired by freqtrade's protections system. Each protection independently
evaluates whether trading should be halted (globally or per-pair).

Implemented:
  CooldownPeriod     — block re-entry into a pair for stop_duration after exit.
  StoplossGuard      — halt (global or per-pair) when stoploss count > trade_limit
                       within lookback_period, with optional required_profit filter.
  MaxDrawdown        — global halt when the realized-PnL equity curve's max
                       drawdown over lookback_period exceeds max_allowed_drawdown
                       (Plan 22 Step 22.3).
  LowProfitPairs     — per-pair halt when a pair's summed realized profit over
                       lookback_period falls below required_profit (Plan 22 Step
                       22.3). Note: operates on the same realized-dollar `profit`
                       value StoplossGuard already uses (this codebase's existing
                       convention, set by `record_trade_close`'s callers) — not
                       freqtrade's true profit-*ratio* semantics, since no call
                       site currently computes a ratio. Document this if wiring
                       a percentage-based `required_profit` from Zone 2 later.
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


class MaxDrawdownProtection(IProtection):
    """Plan 22 Step 22.3: global halt when the realized-PnL equity curve's
    max drawdown over `lookback_period` exceeds `max_allowed_drawdown`.

    Distinct from the Session Risk Governor's aggregate-drawdown check
    (`engine/core/models/governor.py`, Plan 22 Step 22.1): the governor
    watches *live equity* (realized + unrealized, every stats tick) and
    auto-transitions `trading_state`; this protection watches the
    *realized-only* trade-close history over a rolling window and issues a
    time-boxed lock (freqtrade's own MaxDrawdown semantics), same
    lock/unlock vocabulary as `StoplossGuard`. Both can be configured
    together — they answer different questions ("is unrealized risk too
    high right now" vs "has the recent realized track record been too bad").

    Config keys: `lookback_period` (min, base default 60), `trade_limit`
    (min closed trades in the window before evaluating — avoids reacting to
    too little data, default 2), `stop_duration` (min, base default 60),
    `max_allowed_drawdown` (float, default 0.20).
    """
    has_global_stop: bool = True
    has_local_stop: bool = False

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self._trade_limit: int = int(self.config.get("trade_limit", 2))
        self._max_allowed_drawdown: float = float(self.config.get("max_allowed_drawdown", 0.20))
        self._trade_events: list[dict] = []

    def record_trade(self, pair: str, profit: float, timestamp: float) -> None:
        """Every real close, not just stoplosses — the drawdown curve needs
        the full realized-PnL picture."""
        self._trade_events.append({"pair": pair, "profit": profit, "timestamp": timestamp})

    def _recent_trades(self, now: float) -> list[dict]:
        cutoff = now - self._lookback_period * 60
        return [ev for ev in self._trade_events if ev["timestamp"] >= cutoff]

    def _max_drawdown_fraction(self, trades: list[dict], starting_balance: float) -> float:
        """Walks the closed trades in chronological order, building a
        cumulative equity curve from `starting_balance`, and returns the
        largest peak-to-trough fractional drawdown observed. Returns 0.0 if
        the curve never has a positive peak to measure against (degenerate
        starting_balance)."""
        ordered = sorted(trades, key=lambda ev: ev["timestamp"])
        equity = starting_balance
        peak = starting_balance
        max_dd = 0.0
        for ev in ordered:
            equity += ev["profit"]
            if equity > peak:
                peak = equity
            if peak > 0:
                dd = (peak - equity) / peak
                if dd > max_dd:
                    max_dd = dd
        return max_dd

    def global_stop(
        self, date_now: datetime, side: str, starting_balance: float
    ) -> ProtectionReturn | None:
        now = date_now.timestamp()
        recent = self._recent_trades(now)
        if len(recent) < self._trade_limit:
            return None
        max_dd = self._max_drawdown_fraction(recent, starting_balance)
        if max_dd > self._max_allowed_drawdown:
            until = now + self._stop_duration * 60
            return ProtectionReturn(
                lock=True,
                until=until,
                reason=(
                    f"Max drawdown {max_dd:.1%} over {len(recent)} trades in "
                    f"{self._lookback_period} min exceeds {self._max_allowed_drawdown:.1%}, "
                    f"locking {self._stop_duration} min"
                ),
            )
        return None

    def stop_per_pair(
        self, pair: str, date_now: datetime, side: str, starting_balance: float
    ) -> ProtectionReturn | None:
        return None  # global-only, per freqtrade's own MaxDrawdownProtection


class LowProfitPairsProtection(IProtection):
    """Plan 22 Step 22.3: per-pair halt when a pair's summed realized profit
    over `lookback_period` falls below `required_profit`.

    See this module's docstring for the realized-dollar-vs-ratio caveat —
    operates on the same `profit` unit `StoplossGuard`/`record_trade_close`
    already use throughout this codebase.

    Config keys: `lookback_period` (min, base default 60), `trade_limit`
    (min closed trades on that pair before evaluating, default 2),
    `stop_duration` (min, base default 60), `required_profit` (float,
    default 0.0 — a pair whose summed profit over the window is negative
    gets locked).
    """
    has_global_stop: bool = False
    has_local_stop: bool = True

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self._trade_limit: int = int(self.config.get("trade_limit", 2))
        self._required_profit: float = float(self.config.get("required_profit", 0.0))
        self._trade_events: list[dict] = []

    def record_trade(self, pair: str, profit: float, timestamp: float) -> None:
        self._trade_events.append({"pair": pair, "profit": profit, "timestamp": timestamp})

    def _recent_pair_trades(self, pair: str, now: float) -> list[dict]:
        cutoff = now - self._lookback_period * 60
        return [ev for ev in self._trade_events if ev["pair"] == pair and ev["timestamp"] >= cutoff]

    def global_stop(
        self, date_now: datetime, side: str, starting_balance: float
    ) -> ProtectionReturn | None:
        return None  # per-pair-only, per freqtrade's own LowProfitPairsProtection

    def stop_per_pair(
        self, pair: str, date_now: datetime, side: str, starting_balance: float
    ) -> ProtectionReturn | None:
        now = date_now.timestamp()
        recent = self._recent_pair_trades(pair, now)
        if len(recent) < self._trade_limit:
            return None
        total_profit = sum(ev["profit"] for ev in recent)
        if total_profit < self._required_profit:
            until = now + self._stop_duration * 60
            return ProtectionReturn(
                lock=True,
                until=until,
                reason=(
                    f"{pair}: summed profit ${total_profit:.2f} over {len(recent)} trades in "
                    f"{self._lookback_period} min is below required ${self._required_profit:.2f}, "
                    f"locking {self._stop_duration} min"
                ),
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
            # Plan 22 Step 22.3: MaxDrawdown/LowProfitPairs need EVERY close
            # (not just stoplosses) — the equity curve / summed-profit signal
            # is diluted, not just missing a category, if wins are excluded.
            if isinstance(p, (MaxDrawdownProtection, LowProfitPairsProtection)):
                p.record_trade(pair, profit, close_timestamp)
