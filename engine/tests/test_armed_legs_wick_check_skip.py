"""Plan 21 A-13: engine-side wick-check exits duplicate the exchange
conditionals. Decided (`DECISIONS.md` #25): skip `check_exits`'s own SL/TP
wick-check for a leg the caller confirms has a live, resting exchange
bracket order (`open_positions[symbol]["algo_ids"]`) — the exchange's own
MARK_PRICE-triggered conditional fires it instead, and the existing
reconcile loop picks up the resulting close within one candle, same as
always. A leg with no confirmed bracket (naked — A-7's fallback case) keeps
using this method's own wick-check exactly as before.

Drives the real `ExecutionKernel.check_exits` directly (`core/kernel.py`),
using the same fake strategy/adapter shapes as `test_entry_candle_exits.py`
(this repo's existing pattern for this exact test target).

Run inside the container::

    docker exec enma_trading_platform-engine-1 pytest /app/tests/test_armed_legs_wick_check_skip.py
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
    def __init__(self, is_long=True):
        self.position = _FakePosition()
        self.position.type = "long" if is_long else "short"
        self._entered_this_candle = False  # not the entry-candle guard's concern here
        # SL breached by the candle's low (long) / high (short); TP breached
        # by the candle's high (long) / low (short) — both legs are "in the
        # money to trigger" on the same CANDLE fixture below, so a test can
        # isolate exactly which leg fired (or didn't) via armed_legs.
        self.stop_loss = (1.0, 95.0) if is_long else (1.0, 105.0)
        self.take_profit = (1.0, 110.0) if is_long else (1.0, 90.0)
        self.candles = None
        self._is_long = is_long

    @property
    def is_long(self):
        return self._is_long

    @property
    def is_short(self):
        return not self._is_long


class _RecordingAdapter(ExecutionAdapter):
    def __init__(self, is_live: bool = True):
        self.exits = []
        self._is_live = is_live

    @property
    def is_live(self) -> bool:
        return self._is_live

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


# candle: [ts, open, close, high, low, volume]
# low=90 breaches long SL(95) and short TP(90); high=115 breaches long TP(110) and short SL(105).
CANDLE = np.array([1_700_000_000_000.0, 100.0, 100.0, 115.0, 90.0, 5000.0])


def _run(kernel, strat, armed_legs=None):
    return asyncio.get_event_loop().run_until_complete(
        kernel.check_exits(strat, "BTCUSDT", CANDLE, index_t=0, time_t=None, armed_legs=armed_legs)
    )


def test_default_none_preserves_prior_behavior_both_legs_checked():
    """armed_legs=None (the default, and what every backtest call site
    passes implicitly by never specifying it) must behave exactly like
    before this change — SL wins (checked first) since both are in range."""
    strat = _FakeStrategy(is_long=True)
    adapter = _RecordingAdapter()
    kernel = ExecutionKernel(adapter, exec_algo=None)

    _run(kernel, strat)

    assert adapter.exits == ["stop_loss"]


def test_sl_armed_skips_engine_sl_check_long():
    """SL confirmed resting on the exchange -> engine's own SL wick-check is
    skipped; since it's the only leg in range other than TP, TP is what
    should now fire (still not armed)."""
    strat = _FakeStrategy(is_long=True)
    adapter = _RecordingAdapter()
    kernel = ExecutionKernel(adapter, exec_algo=None)

    _run(kernel, strat, armed_legs={"sl": True, "tp": False})

    assert adapter.exits == ["take_profit"]


def test_both_legs_armed_skips_the_whole_wick_check_long():
    """Both legs confirmed resting on the exchange -> no local exit fires at
    all this candle, regardless of how far the wicks moved."""
    strat = _FakeStrategy(is_long=True)
    adapter = _RecordingAdapter()
    kernel = ExecutionKernel(adapter, exec_algo=None)

    _run(kernel, strat, armed_legs={"sl": True, "tp": True})

    assert adapter.exits == []


def test_sl_missing_falls_back_to_engine_wick_check_long():
    """SL leg NOT armed (A-7's naked-position case — brackets missing) ->
    the engine's own wick-check is the fallback and must still catch it."""
    strat = _FakeStrategy(is_long=True)
    adapter = _RecordingAdapter()
    kernel = ExecutionKernel(adapter, exec_algo=None)

    _run(kernel, strat, armed_legs={"sl": False, "tp": True})

    assert adapter.exits == ["stop_loss"]


def test_armed_legs_short_side_symmetric():
    strat = _FakeStrategy(is_long=False)
    adapter = _RecordingAdapter()
    kernel = ExecutionKernel(adapter, exec_algo=None)

    # short SL=105 (breached by high=115), short TP=90 (breached by low=90).
    # Both armed -> nothing fires.
    _run(kernel, strat, armed_legs={"sl": True, "tp": True})
    assert adapter.exits == []

    strat2 = _FakeStrategy(is_long=False)
    adapter2 = _RecordingAdapter()
    kernel2 = ExecutionKernel(adapter2, exec_algo=None)
    _run(kernel2, strat2, armed_legs={"sl": False, "tp": True})
    assert adapter2.exits == ["stop_loss"]


def test_armed_legs_never_applies_to_backtest_even_if_somehow_passed():
    """Defensive: even if a caller mistakenly passed armed_legs on a
    backtest call (is_live=False), the gap_through_stop_price/backtest-only
    exit-price math for the still-unarmed leg must be unaffected — this just
    confirms the armed check composes with is_live rather than replacing it."""
    strat = _FakeStrategy(is_long=True)
    adapter = _RecordingAdapter(is_live=False)
    kernel = ExecutionKernel(adapter, exec_algo=None)

    _run(kernel, strat, armed_legs={"sl": False, "tp": False})

    assert adapter.exits == ["stop_loss"]


def test_missing_key_in_armed_legs_dict_defaults_to_not_armed():
    """A dict missing a key entirely (e.g. algo_ids had no "tp" key at all)
    must behave as not-armed for that leg, not raise a KeyError."""
    strat = _FakeStrategy(is_long=True)
    adapter = _RecordingAdapter()
    kernel = ExecutionKernel(adapter, exec_algo=None)

    _run(kernel, strat, armed_legs={"sl": True})  # no "tp" key at all

    assert adapter.exits == ["take_profit"]
