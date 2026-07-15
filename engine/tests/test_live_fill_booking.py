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


@pytest.fixture(autouse=True)
def _stub_append_event(monkeypatch):
    """Plan 5 Step 5.1: append_event is a live Mongo write — stub it out
    here so these unit tests stay hermetic (no DB dependency), matching
    _stub_record_trade above. event_log.py itself is covered by
    test_execution_event_log.py."""
    async def _noop(*args, **kwargs):
        return 1
    monkeypatch.setattr(lbm_module, "append_event", _noop)


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


# ── execute_entry: Plan 5 Step 5.3 (ENG-10) idempotency ─────────────────────

def _make_flat_strategy():
    strat = _FakeStrategy(position=None)
    strat.leverage = 10
    strat.buy = None
    strat.sell = None
    return strat


def test_entry_order_timeout_then_actually_filled_does_not_report_failure(monkeypatch):
    """The entry order call raises (simulated timeout) but the order actually
    reached Binance — the re-query by clientOrderId must find the real fill
    and the entry must be treated as successful, NOT retried (which would
    double-enter a real position, exactly the ENG-10 duplication risk)."""
    calls = {"n": 0}

    async def flaky_then_found(method, path, api_key, api_secret, params=None, mode="testnet"):
        if method == "POST" and path == "/fapi/v1/order" and params and params.get("reduceOnly") is None:
            calls["n"] += 1
            raise RuntimeError("simulated timeout")
        if method == "GET" and path == "/fapi/v1/order":
            return {"avgPrice": "101.5", "status": "FILLED"}
        raise AssertionError(f"unexpected call {method} {path} {params}")

    monkeypatch.setattr(binance_mod, "send_signed_request", flaky_then_found)

    mgr = LiveBotManager()
    sid = "sess_entry_timeout"
    mgr.sessions[sid] = _make_session()
    mgr.sessions[sid]["open_positions"] = {}
    notified = _Notified()
    monkeypatch.setattr(mgr, "_notify_node", notified)

    strat = _make_flat_strategy()
    adapter = LiveAdapter(mgr, sid)

    ok = asyncio.get_event_loop().run_until_complete(
        adapter.execute_entry(strat, SYM, "long", 1.0, ref_price=100.0,
                               time_t=datetime.now(timezone.utc), index_t=0))

    assert ok is True
    assert calls["n"] == 1  # the raising call happened exactly once, not retried in-process
    assert strat.position is not None
    open_events = [c for c in notified.calls if c.get("event") == "position:open"]
    assert len(open_events) == 1
    # Booked at the REAL fill price found via re-query, not the ref_price estimate.
    assert open_events[0]["eventData"]["price"] == "101.5"


def test_entry_order_genuine_failure_still_reports_failure(monkeypatch):
    """When the order truly never reached Binance (re-query finds nothing),
    execute_entry must still report failure — the idempotency re-query must
    not paper over a real failure."""
    async def always_fails(method, path, api_key, api_secret, params=None, mode="testnet"):
        if method == "POST" and path == "/fapi/v1/order":
            raise RuntimeError("simulated network error")
        if method == "GET" and path == "/fapi/v1/order":
            return {}  # no fill found
        raise AssertionError(f"unexpected call {method} {path}")

    monkeypatch.setattr(binance_mod, "send_signed_request", always_fails)

    mgr = LiveBotManager()
    sid = "sess_entry_fail"
    mgr.sessions[sid] = _make_session()
    mgr.sessions[sid]["open_positions"] = {}
    monkeypatch.setattr(mgr, "_notify_node", _Notified())

    strat = _make_flat_strategy()
    adapter = LiveAdapter(mgr, sid)

    ok = asyncio.get_event_loop().run_until_complete(
        adapter.execute_entry(strat, SYM, "long", 1.0, ref_price=100.0,
                               time_t=datetime.now(timezone.utc), index_t=0))

    assert ok is False
    assert strat.position is None


# ── execute_entry: Plan 12 Step 1b (max_open_positions) ─────────────────────

def test_entry_blocked_when_session_at_max_open_positions(monkeypatch):
    """A new symbol must NOT open when the session is already at its
    max_open_positions cap — no order call should even be attempted."""
    order_calls = {"n": 0}

    async def fail_if_called(method, path, api_key, api_secret, params=None, mode="testnet"):
        order_calls["n"] += 1
        raise AssertionError("should not place an order when at max_open_positions")

    monkeypatch.setattr(binance_mod, "send_signed_request", fail_if_called)

    mgr = LiveBotManager()
    sid = "sess_max_open"
    session = _make_session()
    session["max_open_positions"] = 2
    session["open_positions"] = {"BTCUSDT": {}, "ETHUSDT": {}}  # already at cap
    mgr.sessions[sid] = session
    monkeypatch.setattr(mgr, "_notify_node", _Notified())

    strat = _make_flat_strategy()
    adapter = LiveAdapter(mgr, sid)

    ok = asyncio.get_event_loop().run_until_complete(
        adapter.execute_entry(strat, "SOLUSDT", "long", 1.0, ref_price=100.0,
                               time_t=datetime.now(timezone.utc), index_t=0))

    assert ok is False
    assert order_calls["n"] == 0
    assert strat.position is None


def test_entry_allowed_for_already_open_symbol_even_at_cap(monkeypatch):
    """The cap only blocks NEW symbols — a symbol already counted among the
    open positions (e.g. a re-evaluation) must not be blocked by its own
    presence in the count."""
    async def fake_signed(method, path, api_key, api_secret, params=None, mode="testnet"):
        if method == "POST" and path == "/fapi/v1/order":
            return {"orderId": 1, "avgPrice": "100.0", "status": "FILLED"}
        raise AssertionError(f"unexpected call {method} {path}")

    monkeypatch.setattr(binance_mod, "send_signed_request", fake_signed)

    mgr = LiveBotManager()
    sid = "sess_max_open_existing"
    session = _make_session()
    session["max_open_positions"] = 1
    session["open_positions"] = {SYM: {}}  # SYM itself already counted
    mgr.sessions[sid] = session
    monkeypatch.setattr(mgr, "_notify_node", _Notified())

    strat = _make_flat_strategy()
    adapter = LiveAdapter(mgr, sid)

    ok = asyncio.get_event_loop().run_until_complete(
        adapter.execute_entry(strat, SYM, "long", 1.0, ref_price=100.0,
                               time_t=datetime.now(timezone.utc), index_t=0))

    assert ok is True


def test_entry_allowed_when_max_open_positions_unset(monkeypatch):
    """Default (unset) max_open_positions must behave exactly as before —
    no cap, no behavior change for any existing session."""
    async def fake_signed(method, path, api_key, api_secret, params=None, mode="testnet"):
        if method == "POST" and path == "/fapi/v1/order":
            return {"orderId": 1, "avgPrice": "100.0", "status": "FILLED"}
        raise AssertionError(f"unexpected call {method} {path}")

    monkeypatch.setattr(binance_mod, "send_signed_request", fake_signed)

    mgr = LiveBotManager()
    sid = "sess_no_cap"
    session = _make_session()
    session["open_positions"] = {"BTCUSDT": {}, "ETHUSDT": {}, "SOLUSDT": {}, "ADAUSDT": {}}
    mgr.sessions[sid] = session  # no max_open_positions key at all
    monkeypatch.setattr(mgr, "_notify_node", _Notified())

    strat = _make_flat_strategy()
    adapter = LiveAdapter(mgr, sid)

    ok = asyncio.get_event_loop().run_until_complete(
        adapter.execute_entry(strat, "DOTUSDT", "long", 1.0, ref_price=100.0,
                               time_t=datetime.now(timezone.utc), index_t=0))

    assert ok is True
