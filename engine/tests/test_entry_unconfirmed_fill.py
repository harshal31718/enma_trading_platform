"""F7 hardening regression: `LiveAdapter.execute_entry()` no longer treats a
truthy-but-zero `avgPrice` string (Binance's `"0.00000000"`) as a real fill.

Root-cause context (workspace/plan/0_fixes-queue.md F7, CURRENT_STATE.md's
Known Technical Debt — FXSUSDT stuck-open-after-stop anomaly from the
2026-07-16 live Chaos run): the entry path was the one order-placement site
in `live_bot_manager.py` that did NOT follow the ENG-2 contract already
applied to every close path (`_extract_fill_price()` + `_query_real_fill_price()`
re-query, never a silent estimate fallback). `if entry_result.get("avgPrice"):`
is true for the *string* `"0.00000000"` even though the fill itself is zero,
so a market order whose RESULT response raced ahead of Binance settling
`avgPrice` (or one that genuinely filled for zero, e.g. EXPIRED on a
low-liquidity symbol) silently kept `fill_price == ref_price` (the pre-trade
candle-close estimate) and opened a local `Position` + `open_positions` entry
that was never confirmed against a real Binance fill — a plausible
"phantom local position" root cause for the FXSUSDT symptom (a position that
never behaved like a real one and stayed stuck through session stop).

This is observability/correctness-only for the unconfirmed-fill case — a
normal fill with a real `avgPrice` behaves identically to before. No
golden-master re-baseline needed (live-adapter-only, zero backtest overlap,
same precedent as `test_execute_entry_slippage_log.py`).

Run inside the container::

    docker exec enma_trading_platform-engine-1 pytest /app/tests/test_entry_unconfirmed_fill.py
"""
import asyncio
from datetime import datetime, timezone

import pytest

import services.binance_testnet as binance_mod
import core.live_bot_manager as lbm_module
from core.live_bot_manager import LiveBotManager, LiveAdapter

SYM = "FAKEUSDT"


class _FakeExecutionModel:
    def exit_fee(self, strategy, qty, price):
        return abs(qty) * price * 0.0005


class _FakeStrategy:
    def __init__(self):
        self.position = None
        self.stop_loss = None
        self.take_profit = None
        self.buy = 1.0
        self.sell = None
        self.entry_tag = ""
        self.exit_tag = ""
        self.execution_model = _FakeExecutionModel()
        self.balance = 1000.0
        self.leverage = 1


def _make_session():
    return {
        "open_positions": {},
        "pnl": 0.0, "strategy_name": "X", "api_key": "k", "api_secret": "s", "user_id": "",
        "trading_state": "active",
    }


class _Notified:
    def __init__(self):
        self.calls = []

    async def __call__(self, session_id, payload):
        self.calls.append(payload)


@pytest.fixture(autouse=True)
def _stub_side_effects(monkeypatch):
    async def _noop_record_trade(*args, **kwargs):
        return None
    monkeypatch.setattr(lbm_module, "record_trade", _noop_record_trade)

    async def _noop_append_event(*args, **kwargs):
        return 1
    monkeypatch.setattr(lbm_module, "append_event", _noop_append_event)


def _make_mgr_adapter(monkeypatch, notified=None):
    mgr = LiveBotManager()
    sid = "sess_entry_unconfirmed"
    mgr.sessions[sid] = _make_session()
    monkeypatch.setattr(mgr, "_notify_node", notified or _Notified())
    return mgr, LiveAdapter(mgr, sid)


def _run_entry(adapter, strat, ref_price, order_call, requery_call, monkeypatch):
    async def fake_signed(method, path, api_key, api_secret, params=None, mode="testnet"):
        if method == "POST" and path == "/fapi/v1/order":
            return order_call(params)
        if method == "GET" and path == "/fapi/v1/order":
            return requery_call(params)
        raise AssertionError(f"unexpected call {method} {path} {params}")
    monkeypatch.setattr(binance_mod, "send_signed_request", fake_signed)

    return asyncio.get_event_loop().run_until_complete(adapter.execute_entry(
        strategy=strat, symbol=SYM, direction="long", qty=1.0, ref_price=ref_price,
        time_t=datetime.now(timezone.utc), index_t=0,
    ))


def test_real_fill_still_opens_position_unchanged(monkeypatch):
    """Regression: a normal fill with a real avgPrice behaves exactly as
    before — no change to the happy path."""
    mgr, adapter = _make_mgr_adapter(monkeypatch)
    strat = _FakeStrategy()

    ok = _run_entry(
        adapter, strat, ref_price=100.0,
        order_call=lambda params: {"orderId": 1, "avgPrice": "100.50", "status": "FILLED"},
        requery_call=lambda params: pytest.fail("should not re-query when avgPrice is already real"),
        monkeypatch=monkeypatch,
    )

    assert ok is True
    assert strat.position is not None
    assert strat.position.entry_price == pytest.approx(100.50)
    assert SYM in mgr.sessions["sess_entry_unconfirmed"]["open_positions"]


def test_zero_avgprice_string_requeries_and_recovers_real_fill(monkeypatch):
    """`avgPrice: "0.00000000"` (truthy string, zero value) must NOT be
    trusted directly — re-query by clientOrderId recovers the real fill and
    the entry still succeeds with the correct price."""
    mgr, adapter = _make_mgr_adapter(monkeypatch)
    strat = _FakeStrategy()

    ok = _run_entry(
        adapter, strat, ref_price=100.0,
        order_call=lambda params: {"orderId": 1, "avgPrice": "0.00000000", "status": "NEW"},
        requery_call=lambda params: {"avgPrice": "100.75", "status": "FILLED"},
        monkeypatch=monkeypatch,
    )

    assert ok is True
    assert strat.position is not None
    assert strat.position.entry_price == pytest.approx(100.75)
    assert SYM in mgr.sessions["sess_entry_unconfirmed"]["open_positions"]


def test_zero_avgprice_and_failed_requery_does_not_open_phantom_position(monkeypatch):
    """The FXSUSDT regression case: neither the order response nor the
    re-query ever produce a real fill price. The entry must be treated as
    FAILED — no local Position, no open_positions entry, no phantom that
    could get stuck through a later session stop."""
    notified = _Notified()
    mgr, adapter = _make_mgr_adapter(monkeypatch, notified)
    strat = _FakeStrategy()

    ok = _run_entry(
        adapter, strat, ref_price=100.0,
        order_call=lambda params: {"orderId": 1, "avgPrice": "0.00000000", "status": "EXPIRED"},
        requery_call=lambda params: {"avgPrice": "0.00000000", "status": "EXPIRED"},
        monkeypatch=monkeypatch,
    )

    assert ok is False
    assert strat.position is None
    assert SYM not in mgr.sessions["sess_entry_unconfirmed"]["open_positions"]
    error_logs = [
        c for c in notified.calls
        if c.get("event") == "log" and c.get("eventData", {}).get("type") == "error"
        and "unconfirmed" in c.get("eventData", {}).get("message", "")
    ]
    assert len(error_logs) == 1
