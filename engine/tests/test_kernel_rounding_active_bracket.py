"""F10 residual (0_fixes-queue.md): kernel.py's post-route rounding block was
re-keyed off `strategy.active_bracket` instead of the mutable
`strategy.stop_loss`/`strategy.take_profit` tuple (2026-07-24).

Every route()/exec_algo write path sets active_bracket and the mutable tuple
together from the same source value, so this is behavior-preserving for every
real code path — these tests lock in that claim, including the one genuine
divergence case (an exec_algo slice with no SL on this particular slice,
leaving a stale non-None `strategy.stop_loss` while `active_bracket.stop_loss`
is None) which must be skipped, not crash or incorrectly re-round.

Run inside the container::

    docker exec enma_trading_platform-engine-1 pytest /app/tests/test_kernel_rounding_active_bracket.py
"""
import asyncio
from decimal import ROUND_DOWN, ROUND_UP

import numpy as np
import pytest

import core.kernel as kernel_mod
from core.kernel import ExecutionKernel, ExecutionAdapter
from core.models import OrderPlan
from utils.symbols import _rules_cache, Decimal


@pytest.fixture(autouse=True)
def _seed_rules():
    _rules_cache[("Binance Futures", "BTCUSDT")] = {
        "tickSize": Decimal("0.01"),
        "stepSize": Decimal("0.1"),
        "minQty": Decimal("0.1"),
        "minNotional": Decimal("5.0"),
    }
    yield
    _rules_cache.pop(("Binance Futures", "BTCUSDT"), None)


class _FakePosition:
    def __init__(self, direction, qty, entry):
        self.type = direction
        self.qty = qty
        self.entry_price = entry
        self.is_open = True

    def update_pnl(self, price):
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
        self.active_bracket = None
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


class _NoopAdapter(ExecutionAdapter):
    @property
    def is_live(self) -> bool:
        return False

    async def execute_entry(self, strategy, symbol, direction, qty, ref_price,
                            time_t, index_t, intent="enter", adjust_tag=""):
        strategy.position = _FakePosition(direction, qty, ref_price)
        return True

    async def execute_exit(self, strategy, symbol, qty, exit_price, reason,
                           time_t, index_t, high_t, low_t):
        strategy.position = None

    async def execute_flip(self, strategy, symbol, new_direction, new_qty, ref_price,
                           time_t, index_t, high_t, low_t, stop_loss=None, take_profit=None):
        return False

    async def execute_reduce(self, strategy, symbol, qty, exit_price, time_t, index_t, adjust_tag=""):
        pass

    async def verify_position(self, strategy, symbol):
        pass


def _candle():
    return np.array([1_700_000_000_000.0, 100.0, 100.0, 101.0, 99.0, 5000.0])


def test_long_entry_rounds_both_active_bracket_and_tuple():
    strat = _FakeStrategy()
    strat.position = _FakePosition("long", 2.0, 100.0)

    def fake_evaluate(strategy, current_holding=0.0):
        strategy.stop_loss = (2.0, 90.001)
        strategy.take_profit = (2.0, 110.009)
        strategy.active_bracket = OrderPlan(
            direction=1, qty=2.0, entry_price=100.0,
            stop_loss=90.001, take_profit=110.009, order_type="market", intent="maintain",
        )
        return strategy.active_bracket

    orig = kernel_mod.evaluate
    kernel_mod.evaluate = fake_evaluate
    try:
        kernel = ExecutionKernel(_NoopAdapter(), None)
        asyncio.get_event_loop().run_until_complete(
            kernel.evaluate_and_route(strat, "BTCUSDT", _candle(), 0, None))
    finally:
        kernel_mod.evaluate = orig

    # Long SL rounds DOWN (away from entry), long TP rounds UP (away from entry).
    assert strat.active_bracket.stop_loss == 90.00
    assert strat.active_bracket.take_profit == 110.01
    assert strat.stop_loss == (2.0, 90.00)
    assert strat.take_profit == (2.0, 110.01)


def test_short_entry_rounds_the_opposite_direction():
    strat = _FakeStrategy()
    strat.position = _FakePosition("short", 2.0, 100.0)

    def fake_evaluate(strategy, current_holding=0.0):
        strategy.stop_loss = (2.0, 110.001)
        strategy.take_profit = (2.0, 90.009)
        strategy.active_bracket = OrderPlan(
            direction=-1, qty=2.0, entry_price=100.0,
            stop_loss=110.001, take_profit=90.009, order_type="market", intent="maintain",
        )
        return strategy.active_bracket

    orig = kernel_mod.evaluate
    kernel_mod.evaluate = fake_evaluate
    try:
        kernel = ExecutionKernel(_NoopAdapter(), None)
        asyncio.get_event_loop().run_until_complete(
            kernel.evaluate_and_route(strat, "BTCUSDT", _candle(), 0, None))
    finally:
        kernel_mod.evaluate = orig

    # Short SL rounds UP (away from entry), short TP rounds DOWN (away from entry).
    assert strat.active_bracket.stop_loss == 110.01
    assert strat.active_bracket.take_profit == 90.00
    assert strat.stop_loss == (2.0, 110.01)
    assert strat.take_profit == (2.0, 90.00)


def test_active_bracket_none_skips_rounding_without_crashing_on_a_stale_tuple():
    # The one real divergence case: an exec_algo slice can leave
    # active_bracket.stop_loss as None (this slice carried no SL) while the
    # mutable tuple still holds a stale, already-rounded value from an
    # earlier slice/candle. The rounding block must not touch it (it's
    # already exchange-valid) and must not crash reading a None.
    strat = _FakeStrategy()
    strat.position = _FakePosition("long", 2.0, 100.0)
    strat.stop_loss = (2.0, 90.00)  # stale, already rounded
    strat.take_profit = (2.0, 110.01)

    def fake_evaluate(strategy, current_holding=0.0):
        strategy.active_bracket = OrderPlan(
            direction=1, qty=2.0, entry_price=100.0,
            stop_loss=None, take_profit=None, order_type="market", intent="maintain",
        )
        return strategy.active_bracket

    orig = kernel_mod.evaluate
    kernel_mod.evaluate = fake_evaluate
    try:
        kernel = ExecutionKernel(_NoopAdapter(), None)
        asyncio.get_event_loop().run_until_complete(
            kernel.evaluate_and_route(strat, "BTCUSDT", _candle(), 0, None))
    finally:
        kernel_mod.evaluate = orig

    assert strat.active_bracket.stop_loss is None
    assert strat.active_bracket.take_profit is None
    # Untouched — the stale tuple value survives exactly as it was.
    assert strat.stop_loss == (2.0, 90.00)
    assert strat.take_profit == (2.0, 110.01)


def test_flat_flat_active_bracket_none_and_no_position_skips_entirely():
    strat = _FakeStrategy()  # flat, no position, no buy/sell

    def fake_evaluate(strategy, current_holding=0.0):
        strategy.active_bracket = None
        return None

    orig = kernel_mod.evaluate
    kernel_mod.evaluate = fake_evaluate
    try:
        kernel = ExecutionKernel(_NoopAdapter(), None)
        asyncio.get_event_loop().run_until_complete(
            kernel.evaluate_and_route(strat, "BTCUSDT", _candle(), 0, None))
    finally:
        kernel_mod.evaluate = orig

    assert strat.active_bracket is None
    assert strat.stop_loss is None
    assert strat.take_profit is None
