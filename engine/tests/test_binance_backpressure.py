"""Plan 21 Step 21.5 (A-9) regression: weight tracking + 429/418 backpressure
in `engine/services/binance_testnet.py`.

Binance shares a 2400-weight/min budget across ALL of this server's outbound
requests (single egress IP, all users). Before this fix, `send_signed_request`
had no awareness of `X-MBX-USED-WEIGHT-1M`, no `Retry-After` handling on
429/418, and no way to defer non-critical polling — a busy multi-symbol Chaos
run's per-candle reconcile calls (positionRisk + openOrders + openAlgoOrders,
per symbol) could burn a large fraction of the shared budget with zero
backpressure, and an actual 429/418 would surface as a generic per-symbol
exception with no coordinated pause.

Drives the real module-level functions directly (`_check_backpressure`,
`_record_used_weight`, `_handle_rate_limit_response`,
`_is_order_critical_path`) plus `send_signed_request` end-to-end against a
fake httpx client, per this repo's convention of testing extracted/standalone
units.

Run inside the container::

    docker exec enma_trading_platform-engine-1 pytest /app/tests/test_binance_backpressure.py
"""
import asyncio
import time

import httpx
import pytest

import services.binance_testnet as bt


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture(autouse=True)
def _reset_module_state():
    """Each test gets a clean slate — these dicts are module-level global
    state shared across all calls, exactly like production."""
    bt._used_weight_1m.clear()
    bt._backpressure_until.clear()
    yield
    bt._used_weight_1m.clear()
    bt._backpressure_until.clear()


BASE = "https://demo-fapi.binance.com"


# ── _is_order_critical_path ─────────────────────────────────────────────────

def test_order_and_algo_order_paths_are_critical():
    assert bt._is_order_critical_path("/fapi/v1/order") is True
    assert bt._is_order_critical_path("/fapi/v1/algoOrder") is True


def test_position_and_orders_queries_are_not_critical():
    assert bt._is_order_critical_path("/fapi/v2/positionRisk") is False
    assert bt._is_order_critical_path("/fapi/v1/openOrders") is False
    assert bt._is_order_critical_path("/fapi/v1/openAlgoOrders") is False
    assert bt._is_order_critical_path("/fapi/v1/userTrades") is False


# ── _record_used_weight ─────────────────────────────────────────────────────

def test_record_used_weight_parses_header():
    bt._record_used_weight(BASE, {"X-MBX-USED-WEIGHT-1M": "1234"})
    weight, observed_at = bt._used_weight_1m[BASE]
    assert weight == 1234
    assert observed_at == pytest.approx(time.time(), abs=2)


def test_record_used_weight_missing_header_is_a_noop():
    bt._record_used_weight(BASE, {})
    assert BASE not in bt._used_weight_1m


def test_record_used_weight_malformed_header_is_a_noop():
    bt._record_used_weight(BASE, {"X-MBX-USED-WEIGHT-1M": "not-a-number"})
    assert BASE not in bt._used_weight_1m


# ── _check_backpressure (weight-threshold defer) ────────────────────────────

def test_defers_non_critical_call_when_weight_at_soft_limit():
    bt._used_weight_1m[BASE] = (bt._WEIGHT_SOFT_LIMIT, time.time())
    with pytest.raises(bt.BinanceBackpressureError):
        bt._check_backpressure(BASE, "/fapi/v2/positionRisk")


def test_allows_non_critical_call_when_weight_below_soft_limit():
    bt._used_weight_1m[BASE] = (bt._WEIGHT_SOFT_LIMIT - 1, time.time())
    bt._check_backpressure(BASE, "/fapi/v2/positionRisk")  # must not raise


def test_stale_weight_reading_does_not_gate():
    """A weight reading older than Binance's own 1-minute window can't be
    trusted to reflect the current minute's usage — must not gate."""
    bt._used_weight_1m[BASE] = (
        bt._WEIGHT_SOFT_LIMIT + 500,
        time.time() - bt._WEIGHT_READING_TTL_SECONDS - 1,
    )
    bt._check_backpressure(BASE, "/fapi/v2/positionRisk")  # must not raise


def test_order_critical_paths_are_never_deferred_by_weight():
    bt._used_weight_1m[BASE] = (bt._WEIGHT_SOFT_LIMIT + 999, time.time())
    bt._check_backpressure(BASE, "/fapi/v1/order")  # must not raise
    bt._check_backpressure(BASE, "/fapi/v1/algoOrder")  # must not raise


# ── _handle_rate_limit_response / pause ─────────────────────────────────────

def _fake_429(retry_after: str | None):
    request = httpx.Request("GET", f"{BASE}/fapi/v2/positionRisk")
    headers = {"Retry-After": retry_after} if retry_after else {}
    response = httpx.Response(429, request=request, headers=headers)
    return httpx.HTTPStatusError("429", request=request, response=response)


def test_429_sets_pause_honoring_retry_after():
    exc = _fake_429("30")
    bt._handle_rate_limit_response(BASE, exc)
    assert bt._backpressure_until[BASE] == pytest.approx(time.time() + 30, abs=2)


def test_429_missing_retry_after_uses_default():
    exc = _fake_429(None)
    bt._handle_rate_limit_response(BASE, exc)
    assert bt._backpressure_until[BASE] == pytest.approx(
        time.time() + bt._DEFAULT_RETRY_AFTER_SECONDS, abs=2
    )


def test_non_rate_limit_status_does_not_set_pause():
    request = httpx.Request("GET", f"{BASE}/fapi/v2/positionRisk")
    response = httpx.Response(500, request=request)
    exc = httpx.HTTPStatusError("500", request=request, response=response)
    bt._handle_rate_limit_response(BASE, exc)
    assert BASE not in bt._backpressure_until


def test_pause_defers_non_critical_but_not_order_critical():
    bt._backpressure_until[BASE] = time.time() + 60
    with pytest.raises(bt.BinanceBackpressureError):
        bt._check_backpressure(BASE, "/fapi/v1/openOrders")
    bt._check_backpressure(BASE, "/fapi/v1/order")  # must not raise


def test_expired_pause_no_longer_defers():
    bt._backpressure_until[BASE] = time.time() - 1  # already expired
    bt._check_backpressure(BASE, "/fapi/v1/openOrders")  # must not raise


# ── send_signed_request end-to-end (fake httpx client) ──────────────────────

class _FakeResponse:
    def __init__(self, status_code=200, json_body=None, headers=None):
        self.status_code = status_code
        self._json_body = json_body if json_body is not None else {}
        self.headers = headers or {}
        self.request = httpx.Request("GET", BASE)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                str(self.status_code), request=self.request,
                response=httpx.Response(self.status_code, request=self.request, headers=self.headers),
            )

    def json(self):
        return self._json_body


class _FakeClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    async def get(self, url, headers=None):
        self.calls.append(("GET", url))
        return self._responses.pop(0)

    async def post(self, url, headers=None):
        self.calls.append(("POST", url))
        return self._responses.pop(0)

    async def delete(self, url, headers=None):
        self.calls.append(("DELETE", url))
        return self._responses.pop(0)

    async def put(self, url, headers=None):
        self.calls.append(("PUT", url))
        return self._responses.pop(0)


@pytest.fixture(autouse=True)
def _stub_time_offset(monkeypatch):
    async def _fake_offset(base_url, force=False):
        return 0
    monkeypatch.setattr(bt, "_get_time_offset", _fake_offset)


def test_send_signed_request_records_weight_on_success(monkeypatch):
    fake = _FakeClient([
        _FakeResponse(200, {"ok": True}, headers={"X-MBX-USED-WEIGHT-1M": "42"}),
    ])
    monkeypatch.setattr(bt, "get_client", lambda: fake)

    result = _run(bt.send_signed_request(
        "GET", "/fapi/v2/positionRisk", "key", "secret", params={"symbol": "BTCUSDT"}, mode="testnet",
    ))

    assert result == {"ok": True}
    assert bt._used_weight_1m[BASE][0] == 42


def test_send_signed_request_429_sets_pause_and_raises(monkeypatch):
    fake = _FakeClient([
        _FakeResponse(429, {}, headers={"Retry-After": "5"}),
    ])
    monkeypatch.setattr(bt, "get_client", lambda: fake)

    with pytest.raises(httpx.HTTPStatusError):
        _run(bt.send_signed_request(
            "GET", "/fapi/v2/positionRisk", "key", "secret", params={"symbol": "BTCUSDT"}, mode="testnet",
        ))

    assert bt._backpressure_until[BASE] == pytest.approx(time.time() + 5, abs=2)


def test_send_signed_request_defers_non_critical_call_while_paused(monkeypatch):
    bt._backpressure_until[BASE] = time.time() + 60
    fake = _FakeClient([])  # must never be called
    monkeypatch.setattr(bt, "get_client", lambda: fake)

    with pytest.raises(bt.BinanceBackpressureError):
        _run(bt.send_signed_request(
            "GET", "/fapi/v1/openOrders", "key", "secret", params={"symbol": "BTCUSDT"}, mode="testnet",
        ))

    assert fake.calls == []  # never dispatched — deferred before the HTTP call


def test_send_signed_request_order_call_bypasses_pause(monkeypatch):
    bt._backpressure_until[BASE] = time.time() + 60
    fake = _FakeClient([
        _FakeResponse(200, {"orderId": 1}, headers={}),
    ])
    monkeypatch.setattr(bt, "get_client", lambda: fake)

    result = _run(bt.send_signed_request(
        "POST", "/fapi/v1/order", "key", "secret", params={"symbol": "BTCUSDT"}, mode="testnet",
    ))

    assert result == {"orderId": 1}
    assert len(fake.calls) == 1


def test_send_signed_request_supports_put_for_listen_key_keepalive(monkeypatch):
    """Regression: `_dispatch` previously had no PUT branch — every real
    listen-key keepalive (`user_data_stream.py`'s `_keepalive_listen_key`,
    which calls this with method="PUT" every 30 min) silently raised
    ValueError, was swallowed by that method's own try/except, and the
    listen key expired every ~60 min instead of being renewed — the system
    self-healed via the LISTEN_KEY_EXPIRED full-reconnect path (A-3, Plan
    21.1) but never actually renewed anything. Fixed by adding a PUT branch
    to `_dispatch`, mirroring GET/POST/DELETE exactly."""
    fake = _FakeClient([
        _FakeResponse(200, {}, headers={}),
    ])
    monkeypatch.setattr(bt, "get_client", lambda: fake)

    result = _run(bt.send_signed_request(
        "PUT", "/fapi/v1/listenKey", "key", "secret", mode="testnet",
    ))

    assert result == {}
    assert fake.calls == [("PUT", fake.calls[0][1])]


def test_send_signed_request_still_rejects_unsupported_methods(monkeypatch):
    fake = _FakeClient([])
    monkeypatch.setattr(bt, "get_client", lambda: fake)

    with pytest.raises(ValueError, match="Unsupported HTTP method"):
        _run(bt.send_signed_request(
            "PATCH", "/fapi/v1/order", "key", "secret", mode="testnet",
        ))
