"""Plan 9 Step 9.8 (QNT-3 residual / ENG-18): opt-in intrabar SL/TP-ordering
resolution via 1m detail candles.

When BOTH SL and TP wicks are hit within one base candle, the default
(`intrabar_detail=False`) keeps the existing conservative bias — SL assumed
first (`engine/CLAUDE.md`'s documented contract). `ExecutionKernel(...,
intrabar_detail=True, detail_candles_by_symbol=..., base_timeframe_ms=...)`
opts into resolving the ambiguity via 1m sub-candles, in chronological
order — whichever level's wick genuinely triggers first wins.

Run inside the container::

    docker exec enma_trading_platform-engine-1 pytest /app/tests/test_intrabar_detail_resolution.py
"""
import asyncio

import numpy as np
import pytest

from core.kernel import ExecutionKernel, ExecutionAdapter

HOUR_MS = 3_600_000.0


class _FakePosition:
    def __init__(self, is_long=True):
        self.type = "long" if is_long else "short"
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
    def __init__(self, is_long=True, sl=95.0, tp=110.0):
        self.position = _FakePosition(is_long)
        self._entered_this_candle = False
        self.stop_loss = (1.0, sl) if sl is not None else None
        self.take_profit = (1.0, tp) if tp is not None else None
        self.candles = None

    @property
    def is_long(self):
        return self.position.type == "long"

    @property
    def is_short(self):
        return self.position.type == "short"


class _RecordingAdapter(ExecutionAdapter):
    def __init__(self):
        self.exits = []

    @property
    def is_live(self) -> bool:
        return False

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


# One base (1h) candle at t=0 whose wick range hits BOTH sl=95 (long) and
# tp=110 (long) — ambiguous ordering.
AMBIGUOUS_CANDLE_LONG = np.array([0.0, 100.0, 100.0, 112.0, 90.0, 5000.0])
AMBIGUOUS_CANDLE_SHORT = np.array([0.0, 100.0, 100.0, 112.0, 90.0, 5000.0])


def _run(kernel, strat, candle, symbol="BTCUSDT"):
    asyncio.get_event_loop().run_until_complete(
        kernel.check_exits(strat, symbol, candle, index_t=0, time_t=None))


def _minute_candle(t_ms, o, c, h, l, v=10.0):
    return [t_ms, o, c, h, l, v]


def test_default_off_keeps_sl_first_conservative_bias():
    strat = _FakeStrategy(is_long=True, sl=95.0, tp=110.0)
    adapter = _RecordingAdapter()
    kernel = ExecutionKernel(adapter, exec_algo=None)  # intrabar_detail defaults False
    assert kernel.intrabar_detail is False

    _run(kernel, strat, AMBIGUOUS_CANDLE_LONG)
    assert adapter.exits == ["stop_loss"]


def test_opt_in_resolves_take_profit_actually_hit_first():
    # 1m candles: minute 0 touches TP (110) first, minute 5 touches SL (95).
    detail = np.array([
        _minute_candle(0.0,     100.0, 105.0, 111.0, 100.0),  # TP triggers here (high>=110)
        _minute_candle(60_000., 105.0, 90.0,  106.0,  90.0),  # SL would trigger here
    ])
    strat = _FakeStrategy(is_long=True, sl=95.0, tp=110.0)
    adapter = _RecordingAdapter()
    kernel = ExecutionKernel(
        adapter, exec_algo=None, intrabar_detail=True,
        detail_candles_by_symbol={"BTCUSDT": detail}, base_timeframe_ms=HOUR_MS,
    )

    _run(kernel, strat, AMBIGUOUS_CANDLE_LONG)
    assert adapter.exits == ["take_profit"]


def test_opt_in_resolves_stop_loss_actually_hit_first():
    detail = np.array([
        _minute_candle(0.0,     100.0, 90.0,  101.0,  90.0),  # SL triggers here (low<=95)
        _minute_candle(60_000., 90.0,  112.0, 112.0,  90.0),  # TP would trigger here
    ])
    strat = _FakeStrategy(is_long=True, sl=95.0, tp=110.0)
    adapter = _RecordingAdapter()
    kernel = ExecutionKernel(
        adapter, exec_algo=None, intrabar_detail=True,
        detail_candles_by_symbol={"BTCUSDT": detail}, base_timeframe_ms=HOUR_MS,
    )

    _run(kernel, strat, AMBIGUOUS_CANDLE_LONG)
    assert adapter.exits == ["stop_loss"]


def test_opt_in_falls_back_to_sl_first_when_detail_missing_for_symbol():
    strat = _FakeStrategy(is_long=True, sl=95.0, tp=110.0)
    adapter = _RecordingAdapter()
    kernel = ExecutionKernel(
        adapter, exec_algo=None, intrabar_detail=True,
        detail_candles_by_symbol={},  # no entry for BTCUSDT at all
        base_timeframe_ms=HOUR_MS,
    )
    _run(kernel, strat, AMBIGUOUS_CANDLE_LONG)
    assert adapter.exits == ["stop_loss"]


def test_opt_in_falls_back_to_sl_first_when_detail_window_empty():
    # Detail candles exist for the symbol but none fall inside this base
    # candle's [0, 3_600_000) window (all from a much later bucket).
    detail = np.array([_minute_candle(10_000_000.0, 100.0, 100.0, 101.0, 99.0)])
    strat = _FakeStrategy(is_long=True, sl=95.0, tp=110.0)
    adapter = _RecordingAdapter()
    kernel = ExecutionKernel(
        adapter, exec_algo=None, intrabar_detail=True,
        detail_candles_by_symbol={"BTCUSDT": detail}, base_timeframe_ms=HOUR_MS,
    )
    _run(kernel, strat, AMBIGUOUS_CANDLE_LONG)
    assert adapter.exits == ["stop_loss"]


def test_opt_in_falls_back_when_neither_level_actually_hit_within_detail_window():
    # Detail candles exist in-window but never actually touch either level —
    # e.g. the outer candle's wick data disagreed with 1m reality (shouldn't
    # normally happen, but must degrade safely, not silently drop the exit).
    detail = np.array([_minute_candle(0.0, 100.0, 100.0, 101.0, 99.0)])
    strat = _FakeStrategy(is_long=True, sl=95.0, tp=110.0)
    adapter = _RecordingAdapter()
    kernel = ExecutionKernel(
        adapter, exec_algo=None, intrabar_detail=True,
        detail_candles_by_symbol={"BTCUSDT": detail}, base_timeframe_ms=HOUR_MS,
    )
    _run(kernel, strat, AMBIGUOUS_CANDLE_LONG)
    assert adapter.exits == ["stop_loss"]


def test_only_sl_hit_unaffected_by_intrabar_flag():
    # Not ambiguous (only SL's wick is hit) — intrabar resolution must never
    # even be consulted, same result on or off.
    strat_off = _FakeStrategy(is_long=True, sl=95.0, tp=None)
    strat_on = _FakeStrategy(is_long=True, sl=95.0, tp=None)
    candle = np.array([0.0, 100.0, 100.0, 101.0, 90.0, 5000.0])  # low=90 <= sl=95, no tp

    adapter_off = _RecordingAdapter()
    _run(ExecutionKernel(adapter_off, exec_algo=None), strat_off, candle)

    adapter_on = _RecordingAdapter()
    _run(
        ExecutionKernel(adapter_on, exec_algo=None, intrabar_detail=True,
                         detail_candles_by_symbol={}, base_timeframe_ms=HOUR_MS),
        strat_on, candle,
    )
    assert adapter_off.exits == adapter_on.exits == ["stop_loss"]


def test_short_side_opt_in_resolves_correctly():
    # Short: SL triggers on high>=sl, TP triggers on low<=tp.
    detail = np.array([
        _minute_candle(0.0,     100.0, 111.0, 111.0, 99.0),   # SL (105) triggers here
        _minute_candle(60_000., 111.0, 90.0,  111.0, 90.0),   # TP (95) would trigger here
    ])
    strat = _FakeStrategy(is_long=False, sl=105.0, tp=95.0)
    adapter = _RecordingAdapter()
    kernel = ExecutionKernel(
        adapter, exec_algo=None, intrabar_detail=True,
        detail_candles_by_symbol={"BTCUSDT": detail}, base_timeframe_ms=HOUR_MS,
    )
    candle_short = np.array([0.0, 100.0, 100.0, 111.0, 90.0, 5000.0])
    _run(kernel, strat, candle_short)
    assert adapter.exits == ["stop_loss"]


def test_resolve_intrabar_winner_returns_none_when_flag_off():
    kernel = ExecutionKernel(_RecordingAdapter(), exec_algo=None, intrabar_detail=False)
    assert kernel._resolve_intrabar_winner("BTCUSDT", True, 95.0, 110.0, 0.0) is None


def test_resolve_intrabar_winner_returns_none_when_base_timeframe_ms_missing():
    kernel = ExecutionKernel(
        _RecordingAdapter(), exec_algo=None, intrabar_detail=True,
        detail_candles_by_symbol={"BTCUSDT": np.array([_minute_candle(0.0, 100, 100, 101, 99)])},
        base_timeframe_ms=None,
    )
    assert kernel._resolve_intrabar_winner("BTCUSDT", True, 95.0, 110.0, 0.0) is None
