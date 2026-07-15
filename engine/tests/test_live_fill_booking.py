"""Plan 5 Step 5.2 (ENG-2) regression: live position closes must book the
REAL exchange fill, and must NEVER fabricate a close when the exchange
order itself failed.

Before this fix, `LiveAdapter.execute_exit` discarded the Binance close-order
response entirely, closed the local position at the caller-supplied
trigger-price estimate regardless of what actually happened on the
exchange, and did so even when placing the order raised an exception.

Drives the real `LiveAdapter.execute_exit` / `_extract_fill_price` /
`_query_real_exit_from_user_trades` with a stubbed Binance signed-request
layer (no network).

Run inside the container::

    docker exec enma_trading_platform-engine-1 pytest /app/tests/test_live_fill_booking.py
"""
import asyncio
from datetime import datetime, timezone

import pytest

import services.binance_testnet as binance_mod
import core.live_bot_manager as lbm_module
from core.live_bot_manager import LiveBotManager, LiveAdapter, _extract_fill_price, _query_real_exit_from_user_trades
from core.position import Position

SYM = "FAKEUSDT"


class _FakeExecutionModel:
    def exit_fee(self, strategy, qty, price):
        return abs(qty) * price * 0.0005  # flat 0.05% taker fee, matches the real model's shape


class _FakeStrategy:
    def __init__(self, position):
        self.position = position
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


def _make_position(entry=100.0, qty=1.0, direction="long", leverage=1.0):
    return Position(direction, qty, entry, leverage=leverage, isolated_wallet=entry * qty)


class _Notified:
    def __init__(self):
        self.calls = []

    async def __call__(self, session_id, payload):
        self.calls.append(payload)


@pytest.fixture(autouse=True)
def _stub_record_trade(monkeypatch):
    async def _noop(*args, **kwargs):
        return None
    monkeypatch.setattr(lbm_module, "record_trade", _noop)


# ── _extract_fill_price: pure function ──────────────────────────────────────

def test_extract_fill_price_reads_avg_price():
    assert _extract_fill_price({"avgPrice": "64801.20"}) == 64801.20


def test_extract_fill_price_none_when_missing():
    assert _extract_fill_price({}) is None


def test_extract_fill_price_none_when_zero():
    # Binance sometimes returns avgPrice "0" before the fill is fully
    # processed — must NOT be treated as a real (zero-dollar) fill.
    assert _extract_fill_price({"avgPrice": "0"}) is None


def test_extract_fill_price_none_when_malformed():
    assert _extract_fill_price({"avgPrice": "not-a-number"}) is None


# ── execute_exit: the core ENG-2 fix ─────────────────────────────────────────

def test_close_order_failure_does_not_fabricate_a_close(monkeypatch):
    """The exchange order raises — position must stay open, no PnL credited,
    no trade recorded, and Node is notified of the failure (not a fake close)."""
    async def failing_signed(method, path, api_key, api_secret, params=None, mode="testnet"):
        raise RuntimeError("simulated Binance 500")

    monkeypatch.setattr(binance_mod, "send_signed_request", failing_signed)

    mgr = LiveBotManager()
    sid = "sess_fail"
    mgr.sessions[sid] = _make_session()
    notified = _Notified()
    monkeypatch.setattr(mgr, "_notify_node", notified)

    pos = _make_position()
    strat = _FakeStrategy(pos)
    adapter = LiveAdapter(mgr, sid)

    asyncio.get_event_loop().run_until_complete(
        adapter.execute_exit(strat, SYM, pos.qty, exit_price=105.0, reason="stop_loss",
                              time_t=datetime.now(timezone.utc), index_t=0, high_t=106.0, low_t=99.0))

    # Position must still be open — nothing was fabricated.
    assert strat.position is not None
    assert strat.position.is_open
    assert mgr.sessions[sid]["pnl"] == 0.0
    # Node was told about the failure, not a fake position:close.
    assert len(notified.calls) == 1
    assert notified.calls[0]["event"] == "close_failed"
    assert notified.calls[0]["eventData"]["symbol"] == SYM


def test_close_order_success_books_the_real_fill_not_the_trigger_price(monkeypatch):
    """The exchange fills at a DIFFERENT price than the SL trigger that
    caused the close (realistic — slippage) — the booked exit must be the
    real fill, not the trigger estimate the caller passed in."""
    REAL_FILL_PRICE = 94.87  # SL trigger was 95.0 — a real, slightly worse fill

    async def fake_signed(method, path, api_key, api_secret, params=None, mode="testnet"):
        assert path == "/fapi/v1/order"
        assert params["reduceOnly"] == "true"
        assert params["newOrderRespType"] == "RESULT"
        return {"orderId": 555, "avgPrice": str(REAL_FILL_PRICE), "status": "FILLED"}

    monkeypatch.setattr(binance_mod, "send_signed_request", fake_signed)

    mgr = LiveBotManager()
    sid = "sess_ok"
    mgr.sessions[sid] = _make_session()
    notified = _Notified()
    monkeypatch.setattr(mgr, "_notify_node", notified)

    pos = _make_position(entry=100.0, qty=1.0, direction="long")
    strat = _FakeStrategy(pos)
    adapter = LiveAdapter(mgr, sid)

    asyncio.get_event_loop().run_until_complete(
        adapter.execute_exit(strat, SYM, pos.qty, exit_price=95.0, reason="stop_loss",
                              time_t=datetime.now(timezone.utc), index_t=0, high_t=101.0, low_t=94.0))

    # Position closed.
    assert strat.position is None
    # PnL booked against the REAL fill (94.87), not the trigger estimate (95.0).
    expected_gross = (REAL_FILL_PRICE - 100.0) * 1.0
    expected_fee = 1.0 * REAL_FILL_PRICE * 0.0005
    expected_pnl = expected_gross - expected_fee
    assert mgr.sessions[sid]["pnl"] == pytest.approx(expected_pnl, abs=0.01)
    # Node was told about a real close with the real fill price.
    close_events = [c for c in notified.calls if c.get("event") == "position:close"]
    assert len(close_events) == 1
    assert close_events[0]["eventData"]["exitPrice"] == str(REAL_FILL_PRICE)


def test_close_order_falls_back_to_order_query_when_avg_price_missing(monkeypatch):
    """Binance's immediate response omits avgPrice (a real, documented
    Binance quirk) — the adapter must re-query the order by client id
    instead of silently trusting the trigger-price estimate."""
    REAL_FILL_PRICE = 94.5
    calls = {"post": 0, "get": 0}

    async def fake_signed(method, path, api_key, api_secret, params=None, mode="testnet"):
        if method == "POST":
            calls["post"] += 1
            return {"orderId": 777, "status": "NEW"}  # no avgPrice yet
        if method == "GET" and path == "/fapi/v1/order":
            calls["get"] += 1
            assert params["origClientOrderId"]
            return {"orderId": 777, "avgPrice": str(REAL_FILL_PRICE), "status": "FILLED"}
        raise AssertionError(f"unexpected call: {method} {path}")

    monkeypatch.setattr(binance_mod, "send_signed_request", fake_signed)

    mgr = LiveBotManager()
    sid = "sess_requery"
    mgr.sessions[sid] = _make_session()
    monkeypatch.setattr(mgr, "_notify_node", _Notified())

    pos = _make_position(entry=100.0, qty=1.0, direction="long")
    strat = _FakeStrategy(pos)
    adapter = LiveAdapter(mgr, sid)

    asyncio.get_event_loop().run_until_complete(
        adapter.execute_exit(strat, SYM, pos.qty, exit_price=95.0, reason="stop_loss",
                              time_t=datetime.now(timezone.utc), index_t=0, high_t=101.0, low_t=94.0))

    assert calls["post"] == 1 and calls["get"] == 1
    expected_gross = (REAL_FILL_PRICE - 100.0) * 1.0
    expected_fee = 1.0 * REAL_FILL_PRICE * 0.0005
    assert mgr.sessions[sid]["pnl"] == pytest.approx(expected_gross - expected_fee, abs=0.01)


# ── _query_real_exit_from_user_trades: reconciliation's "closed on exchange" path ──

def test_user_trades_query_computes_weighted_avg_price_and_net_pnl(monkeypatch):
    entry_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
    trades = [
        {"time": (entry_time.timestamp() + 10) * 1000, "price": "100.0", "qty": "0.5",
         "realizedPnl": "5.0", "commission": "0.1"},
        {"time": (entry_time.timestamp() + 20) * 1000, "price": "102.0", "qty": "0.5",
         "realizedPnl": "6.0", "commission": "0.1"},
    ]

    async def fake_signed(method, path, api_key, api_secret, params=None, mode="testnet"):
        assert path == "/fapi/v1/userTrades"
        return trades

    monkeypatch.setattr(binance_mod, "send_signed_request", fake_signed)

    result = asyncio.get_event_loop().run_until_complete(
        _query_real_exit_from_user_trades("k", "s", SYM, entry_time))

    assert result is not None
    avg_price, net_pnl = result
    assert avg_price == pytest.approx(101.0, abs=0.001)  # equal-weighted 100/102
    assert net_pnl == pytest.approx(10.8, abs=0.001)  # (5+6) - (0.1+0.1)


def test_user_trades_query_returns_none_when_no_trades(monkeypatch):
    async def fake_signed(method, path, api_key, api_secret, params=None, mode="testnet"):
        return []

    monkeypatch.setattr(binance_mod, "send_signed_request", fake_signed)

    result = asyncio.get_event_loop().run_until_complete(
        _query_real_exit_from_user_trades("k", "s", SYM, datetime.now(timezone.utc)))
    assert result is None
