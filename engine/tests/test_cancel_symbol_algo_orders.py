"""Plan 21 Step 21.3 (A-4/A-5) regression: `LiveBotManager._cancel_symbol_algo_orders()`
— cancels resting SL/TP conditional (`/fapi/v1/algoOrder`) orders for a
symbol after any close, so a stale `closePosition:"true"` trigger can never
market-close a position that opens on that symbol later (a different
session, a later re-entry, or a user manually trading it).

Drives the real method (unlike `_on_fill`/`_on_account_update`, this is a
proper `LiveBotManager` method, not a closure embedded in a large method —
directly callable, no need for the "test the extracted unit" workaround
used elsewhere in this suite) against a stubbed Binance signed-request
layer, same harness shape as `test_execute_flip_idempotency.py`.

Run inside the container::

    docker exec enma_trading_platform-engine-1 pytest /app/tests/test_cancel_symbol_algo_orders.py
"""
import asyncio

import pytest

import services.binance_testnet as binance_mod
from core.live_bot_manager import LiveBotManager

SYM = "FAKEUSDT"


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _session():
    return {"api_key": "k", "api_secret": "s"}


def test_tracked_ids_cancelled_directly_no_get_call(monkeypatch):
    """Both ids known -> cancel each by id, no openAlgoOrders lookup needed."""
    calls = {"get": 0, "deleted": []}

    async def fake_signed(method, path, api_key, api_secret, params=None, mode="testnet"):
        if method == "GET" and path == "/fapi/v1/openAlgoOrders":
            calls["get"] += 1
            return []
        if method == "DELETE" and path == "/fapi/v1/algoOrder":
            calls["deleted"].append(params["algoId"])
            return {}
        raise AssertionError(f"unexpected call {method} {path} {params}")

    monkeypatch.setattr(binance_mod, "send_signed_request", fake_signed)

    mgr = LiveBotManager()
    _run(mgr._cancel_symbol_algo_orders(_session(), SYM, {"sl": "111", "tp": "222"}))

    assert calls["get"] == 0
    assert sorted(calls["deleted"]) == ["111", "222"]


def test_partial_tracked_ids_only_cancels_the_present_one(monkeypatch):
    """One leg already had no id tracked (e.g. TP was never placed) —
    cancel only the leg that exists, and still skip the GET fallback since
    at least one real id was available."""
    calls = {"get": 0, "deleted": []}

    async def fake_signed(method, path, api_key, api_secret, params=None, mode="testnet"):
        if method == "GET" and path == "/fapi/v1/openAlgoOrders":
            calls["get"] += 1
            return []
        if method == "DELETE" and path == "/fapi/v1/algoOrder":
            calls["deleted"].append(params["algoId"])
            return {}
        raise AssertionError(f"unexpected call {method} {path} {params}")

    monkeypatch.setattr(binance_mod, "send_signed_request", fake_signed)

    mgr = LiveBotManager()
    _run(mgr._cancel_symbol_algo_orders(_session(), SYM, {"sl": "111", "tp": None}))

    assert calls["get"] == 0
    assert calls["deleted"] == ["111"]


def test_no_tracked_ids_falls_back_to_discovery(monkeypatch):
    """algo_ids is None/empty (session-stop on a symbol the engine never
    fully tracked, or a restored/orphaned position) -> discover open algo
    orders via GET, then cancel every one found."""
    calls = {"get": 0, "deleted": []}

    async def fake_signed(method, path, api_key, api_secret, params=None, mode="testnet"):
        if method == "GET" and path == "/fapi/v1/openAlgoOrders":
            calls["get"] += 1
            return [{"algoId": "333"}, {"algoId": "444"}]
        if method == "DELETE" and path == "/fapi/v1/algoOrder":
            calls["deleted"].append(params["algoId"])
            return {}
        raise AssertionError(f"unexpected call {method} {path} {params}")

    monkeypatch.setattr(binance_mod, "send_signed_request", fake_signed)

    mgr = LiveBotManager()
    _run(mgr._cancel_symbol_algo_orders(_session(), SYM, None))

    assert calls["get"] == 1
    assert sorted(calls["deleted"]) == ["333", "444"]


def test_both_ids_none_falls_back_to_discovery(monkeypatch):
    """{"sl": None, "tp": None} (the default shape when nothing was ever
    placed) must trigger the same fallback as algo_ids=None, not silently
    no-op with zero ids and zero cancels attempted."""
    calls = {"get": 0}

    async def fake_signed(method, path, api_key, api_secret, params=None, mode="testnet"):
        if method == "GET" and path == "/fapi/v1/openAlgoOrders":
            calls["get"] += 1
            return []
        raise AssertionError(f"unexpected call {method} {path} {params}")

    monkeypatch.setattr(binance_mod, "send_signed_request", fake_signed)

    mgr = LiveBotManager()
    _run(mgr._cancel_symbol_algo_orders(_session(), SYM, {"sl": None, "tp": None}))

    assert calls["get"] == 1


def test_no_credentials_is_a_pure_noop(monkeypatch):
    """Missing api_key/api_secret must never crash and must never attempt a
    Binance call — matches every other Binance-call site's guard pattern."""
    async def fake_signed(*args, **kwargs):
        raise AssertionError("should never be called without credentials")

    monkeypatch.setattr(binance_mod, "send_signed_request", fake_signed)

    mgr = LiveBotManager()
    _run(mgr._cancel_symbol_algo_orders({"api_key": "", "api_secret": ""}, SYM, {"sl": "111"}))
    # No exception raised == pass.


def test_one_delete_failure_does_not_block_the_other(monkeypatch):
    """A already-triggered/expired id failing to cancel (expected — e.g.
    the peer leg already died via OUO peer-cancel) must not prevent the
    remaining id(s) from still being attempted."""
    calls = {"deleted": []}

    async def fake_signed(method, path, api_key, api_secret, params=None, mode="testnet"):
        if method == "DELETE" and path == "/fapi/v1/algoOrder":
            if params["algoId"] == "111":
                raise RuntimeError("simulated: algo order already triggered/expired")
            calls["deleted"].append(params["algoId"])
            return {}
        raise AssertionError(f"unexpected call {method} {path} {params}")

    monkeypatch.setattr(binance_mod, "send_signed_request", fake_signed)

    mgr = LiveBotManager()
    # Should not raise despite "111" failing.
    _run(mgr._cancel_symbol_algo_orders(_session(), SYM, {"sl": "111", "tp": "222"}))

    assert calls["deleted"] == ["222"]


def test_discovery_get_failure_is_caught_not_raised(monkeypatch):
    async def fake_signed(method, path, api_key, api_secret, params=None, mode="testnet"):
        if method == "GET" and path == "/fapi/v1/openAlgoOrders":
            raise RuntimeError("simulated Binance 500")
        raise AssertionError(f"unexpected call {method} {path} {params}")

    monkeypatch.setattr(binance_mod, "send_signed_request", fake_signed)

    mgr = LiveBotManager()
    # Should not raise.
    _run(mgr._cancel_symbol_algo_orders(_session(), SYM, None))
