"""QNT-3 (Plan 9 Step 9.4): opt-in entry-candle exit evaluation.

Backtest normally skips SL/TP/liquidation checks on the same candle a
position was entered (``strategy._entered_this_candle``), an optimistic bias
relative to live (exchange-side SL/TP orders are active immediately after
the entry fill there). ``ExecutionKernel(..., entry_candle_exits=True)``
opts into evaluating exits on the entry candle too; the default (False) must
stay byte-identical to the pre-9.4 behavior.

Run inside the container::

    docker exec enma_trading_platform-engine-1 pytest /app/tests/test_entry_candle_exits.py
"""
import asyncio

import numpy as np
import pytest

from core.kernel import ExecutionKernel, ExecutionAdapter


class _FakePosition:
    def __init__(self):
        self.type = "long"
        self.qty = 1.0
        self.entry_price = 100.0
        self.is_open = True
        self.margin = 33.0
        self.pnl = 0.0
        self.pnl_pct = 0.0

    def update_pnl(self, price):
        self.pnl = (price - self.entry_price) * self.qty

    def is_liquidated(self, high, low):
        return False


class _FakeStrategy:
    def __init__(self):
        self.position = _FakePosition()
        self._entered_this_candle = True  # just filled this candle
        self.stop_loss = (1.0, 95.0)      # breached by the candle's low below
        self.take_profit = None
        self.candles = None

    @property
    def is_long(self):
        return True

    @property
    def is_short(self):
        return False


class _RecordingAdapter(ExecutionAdapter):
    def __init__(self):
        self.exits = []

    async def execute_entry(self, *a, **kw):
        return True

    async def execute_exit(self, strategy, symbol, qty, exit_price, reason, time_t, index_t, high_t, low_t):
        self.exits.append(reason)

    async def execute_flip(self, *a, **kw):
        return False

    async def execute_reduce(self, *a, **kw):
        pass

    async def verify_position(self, *a, **kw):
        pass

    async def charge_funding(self, *a, **kw):
        pass


# candle: [ts, open, close, high, low, volume] — low=90 breaches stop_loss=95
CANDLE = np.array([1_700_000_000_000.0, 100.0, 100.0, 101.0, 90.0, 5000.0])


def test_entry_candle_exits_default_off_skips_the_entry_candle():
    strat = _FakeStrategy()
    adapter = _RecordingAdapter()
    kernel = ExecutionKernel(adapter, exec_algo=None)  # default entry_candle_exits=False
    assert kernel.entry_candle_exits is False

    asyncio.get_event_loop().run_until_complete(
        kernel.check_exits(strat, "BTCUSDT", CANDLE, is_live=False, index_t=0, time_t=None))

    assert adapter.exits == [], "default behavior must stay byte-identical: no exit on the entry candle"


def test_entry_candle_exits_opt_in_evaluates_the_entry_candle():
    strat = _FakeStrategy()
    adapter = _RecordingAdapter()
    kernel = ExecutionKernel(adapter, exec_algo=None, entry_candle_exits=True)

    asyncio.get_event_loop().run_until_complete(
        kernel.check_exits(strat, "BTCUSDT", CANDLE, is_live=False, index_t=0, time_t=None))

    assert adapter.exits == ["stop_loss"], "opt-in flag must evaluate SL/TP on the entry candle"


def test_entry_candle_exits_has_no_effect_when_not_freshly_entered():
    # Not the entry candle (_entered_this_candle already False) — both modes
    # must behave identically since the guard never applied in the first place.
    strat = _FakeStrategy()
    strat._entered_this_candle = False
    adapter_off = _RecordingAdapter()
    adapter_on = _RecordingAdapter()

    asyncio.get_event_loop().run_until_complete(
        ExecutionKernel(adapter_off, exec_algo=None, entry_candle_exits=False)
        .check_exits(strat, "BTCUSDT", CANDLE, is_live=False, index_t=0, time_t=None))
    asyncio.get_event_loop().run_until_complete(
        ExecutionKernel(adapter_on, exec_algo=None, entry_candle_exits=True)
        .check_exits(strat, "BTCUSDT", CANDLE, is_live=False, index_t=0, time_t=None))

    assert adapter_off.exits == adapter_on.exits == ["stop_loss"]


def test_entry_candle_exits_never_applies_live():
    # is_live=True bypasses the whole guard regardless of entry_candle_exits —
    # live SL/TP are exchange-side orders, not this kernel's concern.
    strat = _FakeStrategy()
    adapter = _RecordingAdapter()
    kernel = ExecutionKernel(adapter, exec_algo=None, entry_candle_exits=False)

    asyncio.get_event_loop().run_until_complete(
        kernel.check_exits(strat, "BTCUSDT", CANDLE, is_live=True, index_t=0, time_t=None))

    assert adapter.exits == ["stop_loss"]
