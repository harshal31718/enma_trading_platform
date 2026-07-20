"""Pluggable execution algorithms (A-016).

Defines the base class ``ExecAlgorithm`` and concrete implementations:
* ``TWAPAlgorithm`` (Time-Weighted Average Price): slices order into N equal chunks.
* ``VWAPAlgorithm`` (Volume-Weighted Average Price): slices order based on volume participation.
* ``IcebergAlgorithm``: shows a fixed visible quantity per slice.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from core.models import OrderPlan


class ExecAlgorithm(ABC):
    """Abstract base class for execution algorithms."""

    def __init__(self, strategy, symbol: str, params: dict | None = None) -> None:
        self.strategy = strategy
        self.symbol = symbol
        self.params = params or {}
        self.active_plan: OrderPlan | None = None
        self.remaining_qty: float = 0.0
        self.direction: int = 0

    @abstractmethod
    def process_order_plan(self, plan: OrderPlan) -> OrderPlan | None:
        """Process a new OrderPlan. Returns the first slice or None."""

    @abstractmethod
    def step(self, current_price: float, candle_volume: float) -> OrderPlan | None:
        """Execute the next slice based on the current market state."""

    @property
    def is_active(self) -> bool:
        return self.active_plan is not None and self.remaining_qty > 0.0


class TWAPAlgorithm(ExecAlgorithm):
    """TWAP (Time-Weighted Average Price) slices entries into N equal chunks."""

    def __init__(self, strategy, symbol: str, params: dict | None = None) -> None:
        super().__init__(strategy, symbol, params)
        self.slices: int = int(self.params.get("slices", 5))
        self.slices_left: int = 0

    def process_order_plan(self, plan: OrderPlan) -> OrderPlan | None:
        # Exits should NOT be sliced to minimize market risk exposure
        if plan.direction == 0 or plan.qty <= 0:
            self.active_plan = None
            self.remaining_qty = 0.0
            return plan

        # If we have an active flip or exit, do not slice
        if getattr(self.strategy, "_close_at_open", False) or getattr(self.strategy, "_pending_flip", None) is not None:
            self.active_plan = None
            self.remaining_qty = 0.0
            return plan

        self.active_plan = plan
        self.remaining_qty = plan.qty
        self.direction = plan.direction
        self.slices_left = self.slices

        return self.step(plan.entry_price, 0.0)

    def step(self, current_price: float, candle_volume: float) -> OrderPlan | None:
        if self.slices_left <= 0 or self.remaining_qty <= 0:
            self.active_plan = None
            self.remaining_qty = 0.0
            return None

        slice_qty = self.remaining_qty / self.slices_left
        self.slices_left -= 1
        self.remaining_qty -= slice_qty

        # Build plan for this slice
        sl = self.active_plan.stop_loss if self.active_plan else None
        tp = self.active_plan.take_profit if self.active_plan else None

        return OrderPlan(
            direction=self.direction,
            qty=slice_qty,
            entry_price=current_price,
            stop_loss=sl,
            take_profit=tp,
            order_type=self.active_plan.order_type if self.active_plan else "market",
        )


class VWAPAlgorithm(ExecAlgorithm):
    """VWAP (Volume participation) slices orders based on a percentage of candle volume."""

    def __init__(self, strategy, symbol: str, params: dict | None = None) -> None:
        super().__init__(strategy, symbol, params)
        self.participation_rate: float = float(self.params.get("participation_rate", 0.05)) # default 5%
        self.min_slice_qty: float = float(self.params.get("min_slice_qty", 0.001))

    def process_order_plan(self, plan: OrderPlan) -> OrderPlan | None:
        if plan.direction == 0 or plan.qty <= 0:
            self.active_plan = None
            self.remaining_qty = 0.0
            return plan

        self.active_plan = plan
        self.remaining_qty = plan.qty
        self.direction = plan.direction

        # The initial order plan is processed without candle volume info,
        # so we assume a small participation or delegate to the first step.
        return self.step(plan.entry_price, 1000.0) # default fallback volume

    def step(self, current_price: float, candle_volume: float) -> OrderPlan | None:
        if self.remaining_qty <= 0:
            self.active_plan = None
            return None

        # Slice size is bounded by the participation rate of the candle's volume
        target_qty = candle_volume * self.participation_rate
        slice_qty = max(self.min_slice_qty, min(self.remaining_qty, target_qty))
        
        self.remaining_qty -= slice_qty

        sl = self.active_plan.stop_loss if self.active_plan else None
        tp = self.active_plan.take_profit if self.active_plan else None

        return OrderPlan(
            direction=self.direction,
            qty=slice_qty,
            entry_price=current_price,
            stop_loss=sl,
            take_profit=tp,
            order_type=self.active_plan.order_type if self.active_plan else "market",
        )


class IcebergAlgorithm(ExecAlgorithm):
    """Iceberg algorithm submits a constant visible qty per slice."""

    def __init__(self, strategy, symbol: str, params: dict | None = None) -> None:
        super().__init__(strategy, symbol, params)
        self.visible_qty: float = float(self.params.get("visible_qty", 0.1))

    def process_order_plan(self, plan: OrderPlan) -> OrderPlan | None:
        if plan.direction == 0 or plan.qty <= 0:
            self.active_plan = None
            self.remaining_qty = 0.0
            return plan

        self.active_plan = plan
        self.remaining_qty = plan.qty
        self.direction = plan.direction

        return self.step(plan.entry_price, 0.0)

    def step(self, current_price: float, candle_volume: float) -> OrderPlan | None:
        if self.remaining_qty <= 0:
            self.active_plan = None
            return None

        slice_qty = min(self.remaining_qty, self.visible_qty)
        self.remaining_qty -= slice_qty

        sl = self.active_plan.stop_loss if self.active_plan else None
        tp = self.active_plan.take_profit if self.active_plan else None

        return OrderPlan(
            direction=self.direction,
            qty=slice_qty,
            entry_price=current_price,
            stop_loss=sl,
            take_profit=tp,
            order_type=self.active_plan.order_type if self.active_plan else "market",
        )
