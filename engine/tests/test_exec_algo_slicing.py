"""I-01 regression: execution algorithms must fill the FULL parent quantity.

Before the fix, TWAP/VWAP/Iceberg only ever filled their first slice: the
kernel routed every slice to ``strategy.buy``/``strategy.sell``, which only
fill while flat. Once slice 1 opened the position, slices 2..N were dropped.

This test drives the kernel exactly like the backtest loop (execute_pending →
check_exits → evaluate_and_route per candle) with a stubbed five-model
pipeline and a fake adapter that records every fill, and asserts that the sum
of filled quantities equals the parent order quantity.

Run inside the container::

    docker exec enma_trading_platform-engine-1 pytest /app/tests/test_exec_algo_slicing.py
"""
import asyncio

import numpy as np
import pytest

import core.kernel as kernel_mod
from core.kernel import ExecutionKernel, ExecutionAdapter
from core.models import OrderPlan
from core.models.exec_algo import TWAPAlgorithm, IcebergAlgorithm


class _FakePosition:
    def __init__(self, direction: str, qty: float, entry: float):
        self.type = direction
        self.qty = qty
        self.entry_price = entry
        self.is_open = True

    def update_pnl(self, price):  # noqa: D401 - stub
        pass

    def is_liquidated(self, high, low):
        return False


class _FakeRisk:
    def update_session_risk(self, strategy):
        pass


class _FakeStrategy:
    def __init__(self):
        self.position = None
        self.buy = None
        self.sell = None
        self.stop_loss = None
        self.take_profit = None
        self._pending_flip = None
        self._close_at_open = False
        self.qty_to_adjust = 0.0
        self.adjust_tag = ""
        self.index = 0
        self.price = 100.0
        self.exchange = "Binance Futures"
        self.risk_model = _FakeRisk()

    @property
    def is_long(self):
        return self.position is not None and self.position.type == "long"

    @property
    def is_short(self):
        return self.position is not None and self.position.type == "short"

    @property
    def has_pending_flip(self):
        return self._pending_flip is not None

    def before(self):
        pass

    def after(self):
        pass

    def adjust_trade_position(self):
        return None

    def should_cancel_entry(self):
        return False


class _RecordingAdapter(ExecutionAdapter):
    def __init__(self):
        self.fills = []  # list of (intent, qty)

    async def execute_entry(self, strategy, symbol, direction, qty, ref_price,
                            time_t, index_t, intent="enter", adjust_tag=""):
        self.fills.append((intent, qty))
        if intent == "add" and strategy.position is not None:
            strategy.position.qty += qty
        else:
            strategy.position = _FakePosition(direction, qty, ref_price)
        return True

    async def execute_exit(self, strategy, symbol, qty, exit_price, reason,
                           time_t, index_t, high_t, low_t):
        pass

    async def execute_flip(self, strategy, symbol, new_direction, new_qty, ref_price,
                           time_t, index_t, high_t, low_t, stop_loss=None, take_profit=None):
        return False

    async def execute_reduce(self, strategy, symbol, qty, exit_price, time_t, index_t, adjust_tag=""):
        pass

    async def verify_position(self, strategy, symbol):
        pass


def _run_backtest(algo_factory, parent_qty, n_candles=8):
    strat = _FakeStrategy()
    adapter = _RecordingAdapter()
    algo = algo_factory(strat)
    kernel = ExecutionKernel(adapter, algo)

    # evaluate() returns the parent plan on the first candle, then None
    # (strategy holds — no new order) for the rest, which is exactly what the
    # real pipeline does once a position is open.
    calls = {"n": 0}

    def fake_evaluate(strategy, current_holding=0.0):
        calls["n"] += 1
        if calls["n"] == 1:
            return OrderPlan(direction=1, qty=parent_qty, entry_price=100.0,
                             stop_loss=None, take_profit=None, order_type="market")
        return None

    orig = kernel_mod.evaluate
    kernel_mod.evaluate = fake_evaluate
    try:
        candle = np.array([1_700_000_000_000.0, 100.0, 100.0, 101.0, 99.0, 5000.0])
        for t in range(n_candles):
            asyncio.get_event_loop().run_until_complete(
                kernel.execute_pending(strat, "BTCUSDT", candle, t, None))
            asyncio.get_event_loop().run_until_complete(
                kernel.check_exits(strat, "BTCUSDT", candle, False, t, None))
            asyncio.get_event_loop().run_until_complete(
                kernel.evaluate_and_route(strat, "BTCUSDT", candle, False, t, None))
    finally:
        kernel_mod.evaluate = orig
    return adapter, strat


def test_twap_fills_full_parent_quantity():
    adapter, strat = _run_backtest(
        lambda s: TWAPAlgorithm(s, "BTCUSDT", {"slices": 3}), parent_qty=9.0)
    total = sum(q for _, q in adapter.fills)
    assert abs(total - 9.0) < 1e-9, f"parent under-filled: {adapter.fills}"
    assert len(adapter.fills) == 3, f"expected 3 slices, got {adapter.fills}"
    assert adapter.fills[0][0] == "enter"
    assert all(intent == "add" for intent, _ in adapter.fills[1:])
    assert abs(strat.position.qty - 9.0) < 1e-9


def test_iceberg_fills_full_parent_quantity():
    adapter, strat = _run_backtest(
        lambda s: IcebergAlgorithm(s, "BTCUSDT", {"visible_qty": 2.0}),
        parent_qty=6.0, n_candles=10)
    total = sum(q for _, q in adapter.fills)
    assert abs(total - 6.0) < 1e-9, f"parent under-filled: {adapter.fills}"
    assert adapter.fills[0][0] == "enter"
    assert all(intent == "add" for intent, _ in adapter.fills[1:])


# ── QNT-2 regression: exec-algo mode must not erase close/flip intents ────────
#
# Before the fix, the kernel's exec-algo branch unconditionally cleared
# strategy._close_at_open / strategy._pending_flip before re-routing. Since
# DefaultExecution.route() encodes a close/flip via those two attributes and
# returns plan=None, nothing re-created the intent — it was silently erased
# every time an exec-algo (TWAP/VWAP/Iceberg) was configured.

class _ExitRecordingAdapter(ExecutionAdapter):
    def __init__(self):
        self.exits = []
        self.flips = []

    async def execute_entry(self, strategy, symbol, direction, qty, ref_price,
                            time_t, index_t, intent="enter", adjust_tag=""):
        return True

    async def execute_exit(self, strategy, symbol, qty, exit_price, reason,
                           time_t, index_t, high_t, low_t):
        self.exits.append((reason, qty))
        strategy.position = None
        strategy._pending_flip = None

    async def execute_flip(self, strategy, symbol, new_direction, new_qty, ref_price,
                           time_t, index_t, high_t, low_t, stop_loss=None, take_profit=None):
        self.flips.append((new_direction, new_qty))
        strategy.position = _FakePosition(new_direction, new_qty, ref_price)
        return True

    async def execute_reduce(self, strategy, symbol, qty, exit_price, time_t, index_t, adjust_tag=""):
        pass

    async def verify_position(self, strategy, symbol):
        pass


def test_twap_close_at_open_survives_exec_algo_clear():
    strat = _FakeStrategy()
    strat.position = _FakePosition("long", 5.0, 100.0)
    adapter = _ExitRecordingAdapter()
    algo = TWAPAlgorithm(strat, "BTCUSDT", {"slices": 3})
    kernel = ExecutionKernel(adapter, algo)

    def fake_evaluate(strategy, current_holding=0.0):
        strategy._close_at_open = True
        return None

    orig = kernel_mod.evaluate
    kernel_mod.evaluate = fake_evaluate
    try:
        candle = np.array([1_700_000_000_000.0, 100.0, 100.0, 101.0, 99.0, 5000.0])
        # Candle t: route() (faked) sets _close_at_open — the exec-algo clear
        # must not erase it.
        asyncio.get_event_loop().run_until_complete(
            kernel.evaluate_and_route(strat, "BTCUSDT", candle, False, 0, None))
        assert strat._close_at_open is True, (
            "QNT-2 regression: exec-algo clear erased _close_at_open")

        # Candle t+1: execute_pending must see the surviving intent and close.
        asyncio.get_event_loop().run_until_complete(
            kernel.execute_pending(strat, "BTCUSDT", candle, 1, None))
    finally:
        kernel_mod.evaluate = orig

    assert adapter.exits == [("strategy_exit", 5.0)], f"close never executed: {adapter.exits}"
    assert strat.position is None


def test_twap_pending_flip_survives_exec_algo_clear():
    strat = _FakeStrategy()
    strat.position = _FakePosition("long", 5.0, 100.0)
    adapter = _ExitRecordingAdapter()
    algo = TWAPAlgorithm(strat, "BTCUSDT", {"slices": 3})
    kernel = ExecutionKernel(adapter, algo)

    def fake_evaluate(strategy, current_holding=0.0):
        strategy._pending_flip = {"direction": "short", "qty": 5.0,
                                   "stop_loss": None, "take_profit": None}
        return None

    orig = kernel_mod.evaluate
    kernel_mod.evaluate = fake_evaluate
    try:
        candle = np.array([1_700_000_000_000.0, 100.0, 100.0, 101.0, 99.0, 5000.0])
        asyncio.get_event_loop().run_until_complete(
            kernel.evaluate_and_route(strat, "BTCUSDT", candle, False, 0, None))
        assert strat._pending_flip is not None, (
            "QNT-2 regression: exec-algo clear erased _pending_flip")

        asyncio.get_event_loop().run_until_complete(
            kernel.execute_pending(strat, "BTCUSDT", candle, 1, None))
    finally:
        kernel_mod.evaluate = orig

    assert adapter.flips == [("short", 5.0)], f"flip never executed: {adapter.flips}"
    assert strat.position is not None and strat.position.type == "short"
