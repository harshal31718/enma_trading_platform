"""Plan 5 Step 5.5 (ENG-11) — live-engine money accumulation.

Drives the real `LiveAdapter.execute_exit` (same hermetic pattern as
test_live_fill_booking.py) across several closes on ONE strategy/session —
matching how the live candle loop actually reuses a single strategy instance
across many trades — and checks `strategy.balance` / `session["pnl"]`
accumulate exactly via `add_money()` rather than drifting.

Run inside the container::

    docker exec enma_trading_platform-engine-1 pytest /app/tests/test_live_money_accumulation.py
"""
import asyncio
from datetime import datetime, timezone

import pytest

import services.binance_testnet as binance_mod
import core.live_bot_manager as lbm_module
from core.live_bot_manager import LiveBotManager, LiveAdapter
from core.position import Position

SYM = "FAKEUSDT"


class _FakeExecutionModel:
    def exit_fee(self, strategy, qty, price):
        return abs(qty) * price * 0.0005


class _FakeStrategy:
    def __init__(self):
        self.position = None
        self.stop_loss = None
        self.take_profit = None
        self._pending_flip = None
        self.entry_tag = ""
        self.exit_tag = ""
        self.execution_model = _FakeExecutionModel()
        self.balance = 1000.0

    @property
    def is_long(self):
        return self.position is not None and self.position.type == "long"

    @property
    def is_short(self):
        return self.position is not None and self.position.type == "short"


def _make_session():
    return {
        "open_positions": {SYM: {"timestamp": datetime.now(timezone.utc).isoformat()}},
        "pnl": 0.0, "strategy_name": "X", "api_key": "k", "api_secret": "s", "user_id": "",
    }


@pytest.fixture(autouse=True)
def _stub_side_effects(monkeypatch):
    async def _noop(*args, **kwargs):
        return None
    monkeypatch.setattr(lbm_module, "record_trade", _noop)

    async def _noop_seq(*args, **kwargs):
        return 1
    monkeypatch.setattr(lbm_module, "append_event", _noop_seq)


def _run_close(mgr, sid, strat, exit_price):
    async def _fake_signed(method, path, api_key, api_secret, params=None, mode="testnet"):
        return {"orderId": 1, "avgPrice": str(exit_price), "status": "FILLED"}

    import unittest.mock as mock
    with mock.patch.object(binance_mod, "send_signed_request", _fake_signed):
        adapter = LiveAdapter(mgr, sid)
        asyncio.get_event_loop().run_until_complete(
            adapter.execute_exit(strat, SYM, strat.position.qty, exit_price=exit_price,
                                  reason="take_profit", time_t=datetime.now(timezone.utc),
                                  index_t=0, high_t=exit_price + 1, low_t=exit_price - 1))


def test_many_fractional_closes_accumulate_exactly_via_add_money():
    mgr = LiveBotManager()
    sid = "sess_accum"
    mgr.sessions[sid] = _make_session()
    monkeypatch_notify_calls = []

    async def _notify(session_id, payload):
        monkeypatch_notify_calls.append(payload)
    mgr._notifier.notify = _notify

    strat = _FakeStrategy()
    starting_balance = strat.balance

    # 20 small round-trips, each entry->exit at a fractional price delta
    # (0.01) chosen to exercise the classic float-drift shape.
    n_trades = 20
    for i in range(n_trades):
        strat.position = Position("long", qty=1.0, entry_price=100.0, leverage=1.0, isolated_wallet=100.0)
        _run_close(mgr, sid, strat, exit_price=100.01)

    # Sanity: every trade closed (position flat, no crashes above).
    assert strat.position is None

    # The exact expected pnl: n_trades * (0.01 * qty - fee), computed once in
    # real (non-repeated) arithmetic — not the thing under test.
    fee_per_trade = 1.0 * 100.01 * 0.0005
    expected_per_trade = 0.01 - fee_per_trade
    expected_total = round(n_trades * expected_per_trade, 8)

    assert strat.balance == pytest.approx(starting_balance + expected_total, abs=1e-8)
    assert mgr.sessions[sid]["pnl"] == pytest.approx(expected_total, abs=1e-8)
    # strategy.balance and session["pnl"] must never desync from each other —
    # both are updated from the same add_money() call site.
    assert (strat.balance - starting_balance) == pytest.approx(mgr.sessions[sid]["pnl"], abs=1e-9)
