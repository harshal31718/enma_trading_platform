"""QNT-1 regression: multi-symbol portfolio backtests must fire SL/TP.

Before the fix, ``_run_shared_portfolio`` never called ``record_equity()``
(only the single-symbol loop did), so ``strategy._entered_this_candle`` was
never cleared after a symbol's first entry. ``kernel.check_exits`` early-
returns while that flag is set, so stop-loss/take-profit/liquidation checks
were silently skipped for the rest of every multi-symbol position's life.

This test drives ``_run_shared_portfolio`` directly (the real portfolio
function, real ``Position``/``BacktestAdapter``/``ExecutionKernel``) against
two synthetic symbols with a stubbed five-model pipeline (``core.kernel.
evaluate`` monkeypatched, same technique as ``test_exec_algo_slicing.py``)
and asserts:

1. Both symbols' positions actually exit via ``stop_loss`` (not just via
   strategy-driven close/flip/force-close).
2. Cash conservation: with fees/slippage/funding all zeroed out, the final
   shared-wallet balance equals ``capital + sum(trade pnl)`` exactly — the
   property test called for in Plan 9 (audit_2_quant-core.md QNT-1).

Run inside the container::

    docker exec enma_trading_platform-engine-1 pytest /app/tests/test_multi_symbol_portfolio_exits.py
"""
import asyncio
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

import core.kernel as kernel_mod
from core.kernel import ExecutionKernel
from core.models.cost import DefaultTransactionCostModel
from services.backtest_runner import BacktestAdapter, _run_shared_portfolio


class _FakeRisk:
    def update_session_risk(self, strategy):
        pass


class _FakeStrategy:
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.exchange = "Binance Futures"
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
        self.candles = None
        self.leverage = 1
        self.fee_rate = 0.0
        self.slippage_pct = 0.0
        self.entry_tag = ""
        self.exit_tag = ""
        self.cost_model = DefaultTransactionCostModel()
        self.risk_model = _FakeRisk()
        self.balance = 0.0
        self.available_margin = 0.0
        self.available_capital = 0.0

    @property
    def is_long(self):
        return self.position is not None and self.position.type == "long"

    @property
    def is_short(self):
        return self.position is not None and self.position.type == "short"

    @property
    def has_pending_flip(self):
        return self._pending_flip is not None

    @property
    def price(self):
        return float(self.candles[-1, 2])

    @property
    def close(self):
        return float(self.candles[-1, 2])

    @property
    def high(self):
        return float(self.candles[-1, 3])

    @property
    def low(self):
        return float(self.candles[-1, 4])

    def before(self):
        pass

    def after(self):
        pass

    def before_terminate(self):
        pass

    def terminate(self):
        pass

    def adjust_trade_position(self):
        return None

    def should_cancel_entry(self):
        return False

    def on_open_position(self, order):
        pass

    def on_close_position(self, order):
        pass

    def on_increased_position(self, order):
        pass

    def on_reduced_position(self, order):
        pass


def _make_candles(base_price: float, stop_trigger_low: float, n: int = 8):
    """8 hourly candles: flat warmup, then a deep-wick candle at index 4
    that breaches a stop-loss placed 5% below ``base_price``."""
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    rows = []
    data = []
    for i in range(n):
        ts = start + timedelta(hours=i)
        low = stop_trigger_low if i == 4 else base_price - 1.0
        high = base_price + 1.0
        data.append([ts.timestamp() * 1000.0, base_price, base_price, high, low, 1000.0])
        rows.append({"time": ts})
    return rows, np.array(data, dtype=np.float64)


def test_multi_symbol_portfolio_fires_stop_loss_and_conserves_cash():
    capital = 10_000.0
    symbols = ["AAAUSDT", "BBBUSDT"]

    rows_a, candles_a = _make_candles(base_price=100.0, stop_trigger_low=50.0)
    rows_b, candles_b = _make_candles(base_price=200.0, stop_trigger_low=100.0)
    rows_by_sym = {"AAAUSDT": rows_a, "BBBUSDT": rows_b}
    candles_np_by_sym = {"AAAUSDT": candles_a, "BBBUSDT": candles_b}
    warmup_periods = {"AAAUSDT": 2, "BBBUSDT": 2}

    strategies = {sym: _FakeStrategy(sym) for sym in symbols}
    adapters = {
        sym: BacktestAdapter(
            execution_model=None, fee_rate=0.0, slippage_pct=0.0,
            funding_enabled=False, funding_rate=0.0, symbol=sym,
        )
        for sym in symbols
    }
    # BacktestAdapter.execute_entry/exit call self.execution.entry_fill/exit_fill,
    # which delegate cost math to s.cost_model — bind a real DefaultExecution.
    from core.models.execution import BacktestExecution
    for sym in symbols:
        adapters[sym].execution = BacktestExecution()
    kernels = {sym: ExecutionKernel(adapters[sym], exec_algo=None) for sym in symbols}

    entered = {"AAAUSDT": False, "BBBUSDT": False}
    stop_prices = {"AAAUSDT": 95.0, "BBBUSDT": 190.0}

    def fake_evaluate(strategy, current_holding=0.0):
        sym = strategy.symbol
        if strategy.position is None and not entered[sym]:
            entered[sym] = True
            strategy.buy = (1.0, strategy.price)
            strategy.stop_loss = (1.0, stop_prices[sym])
        return None

    orig = kernel_mod.evaluate
    kernel_mod.evaluate = fake_evaluate
    try:
        portfolio_ts, portfolio_bal = asyncio.get_event_loop().run_until_complete(
            _run_shared_portfolio(
                job_id="test_qnt1",
                symbols=symbols,
                strategies=strategies,
                adapters=adapters,
                kernels=kernels,
                rows_by_sym=rows_by_sym,
                candles_np_by_sym=candles_np_by_sym,
                warmup_periods=warmup_periods,
                capital=capital,
                timeframe="1h",
                r_client=_NoopRedis(),
                is_cancelled_fn=lambda: False,
            )
        )
    finally:
        kernel_mod.evaluate = orig

    all_trades = adapters["AAAUSDT"].trades + adapters["BBBUSDT"].trades
    assert len(all_trades) == 2, f"expected one closed trade per symbol, got {all_trades}"

    exit_reasons = {t["exitReason"] for t in all_trades}
    assert exit_reasons == {"stop_loss"}, (
        f"QNT-1 regression: expected both positions to exit via stop_loss, got {exit_reasons}"
    )

    total_trade_pnl = sum(float(t["pnl"]) for t in all_trades)
    finishing_balance = portfolio_bal[-1]
    expected_balance = capital + total_trade_pnl
    assert abs(finishing_balance - expected_balance) < 1e-6, (
        f"cash-conservation violated: final={finishing_balance} "
        f"expected={expected_balance} (capital + sum(trade pnl), fees/slippage/funding=0)"
    )


class _NoopRedis:
    async def publish(self, *args, **kwargs):
        pass
