"""Plan 6 Step 6.2 (ENG-4) — call-site migration tests.

Deliberately NOT a re-test of reconcile/order-placement/user-data-stream
BEHAVIOR — that's covered end-to-end by the existing 20+ test files (they all
already pass unchanged after this migration, since every `Exchange` method
still routes through `send_signed_request` and every test monkeypatches
`services.binance_testnet.send_signed_request`, the same convention the whole
suite already used). This file's job is to verify the NEW wiring itself:
`Reconciler`/`OrderRouter`/`UserDataStreamManager` actually resolve and use a
session's own `Exchange` instance instead of a hardcoded `mode="testnet"`
literal, and `start_session` puts one on every session.

Run inside the container::

    docker exec enma_trading_platform-engine-1 pytest /app/tests/test_exchange_migration.py
"""
import asyncio

import pytest

import services.binance_testnet as binance_mod
from core.exchange import BinanceFuturesTestnet, BinanceFuturesMainnet
from core.reconciler import _resolve_exchange
from core.order_router import OrderRouter
from services.user_data_stream import UserDataStreamManager


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ── Reconciler._resolve_exchange ────────────────────────────────────────

def test_resolve_exchange_defaults_to_testnet_when_session_has_none():
    exchange = _resolve_exchange({})
    assert isinstance(exchange, BinanceFuturesTestnet)


def test_resolve_exchange_honors_session_provided_instance():
    mainnet = BinanceFuturesMainnet()
    exchange = _resolve_exchange({"exchange": mainnet})
    assert exchange is mainnet


# ── OrderRouter honors an injected Exchange (not just the default) ─────

def test_place_market_order_routes_through_injected_exchange_mode(monkeypatch):
    calls = []

    async def fake_signed(method, path, api_key, api_secret, params=None, mode="testnet"):
        calls.append(mode)
        return {"orderId": 1, "avgPrice": "1.0"}
    monkeypatch.setattr(binance_mod, "send_signed_request", fake_signed)

    _run(OrderRouter.place_market_order(
        "k", "s", "BTCUSDT", "BUY", 1.0, "cid", exchange=BinanceFuturesMainnet(),
    ))
    assert calls == ["mainnet"]


def test_place_market_order_defaults_to_testnet_mode_when_no_exchange_given(monkeypatch):
    calls = []

    async def fake_signed(method, path, api_key, api_secret, params=None, mode="testnet"):
        calls.append(mode)
        return {"orderId": 1, "avgPrice": "1.0"}
    monkeypatch.setattr(binance_mod, "send_signed_request", fake_signed)

    _run(OrderRouter.place_market_order("k", "s", "BTCUSDT", "BUY", 1.0, "cid"))
    assert calls == ["testnet"]


# ── UserDataStreamManager ────────────────────────────────────────────────

def test_uds_defaults_to_testnet_exchange():
    uds = UserDataStreamManager(api_key="k", api_secret="s")
    assert isinstance(uds._exchange, BinanceFuturesTestnet)


def test_uds_honors_injected_exchange_for_listen_key_and_ws_url(monkeypatch):
    calls = []

    async def fake_signed(method, path, api_key, api_secret, params=None, mode="testnet"):
        calls.append((method, path, mode))
        return {"listenKey": "abc123"}
    monkeypatch.setattr(binance_mod, "send_signed_request", fake_signed)

    mainnet = BinanceFuturesMainnet()
    uds = UserDataStreamManager(api_key="k", api_secret="s", exchange=mainnet)
    key = _run(uds._create_listen_key())

    assert key == "abc123"
    assert calls == [("POST", "/fapi/v1/listenKey", "mainnet")]
    assert uds._exchange.user_data_ws_url(key) == f"{mainnet.user_data_ws_base}/abc123"


# ── start_session wires a per-session Exchange ──────────────────────────
# Inlined rather than importing test_start_session_risk_params_shape.py's own
# `_run_start_session` helper — cross-test-file imports aren't reliably on
# sys.path when this file runs standalone (only as part of the full `pytest
# tests/` collection), so this stays self-contained.

class _FakeUDS:
    def __init__(self, *a, **kw):
        pass

    async def start(self):
        pass

    async def stop(self):
        pass


def test_start_session_puts_a_testnet_exchange_on_the_session(monkeypatch):
    # start_session dynamically imports the real MicroScalper strategy, which
    # imports `engine.core.strategy` — resolved via the engine_alias import
    # hook installed globally for the test process by tests/conftest.py.
    import core.live_bot_manager as lbm_module
    from core.live_bot_manager import LiveBotManager

    monkeypatch.setattr(lbm_module, "UserDataStreamManager", _FakeUDS)
    mgr = LiveBotManager()
    session_config = {
        "session_id": "sess_exchange_wiring_test",
        "strategy_name": "MicroScalper",
        "symbols": ["FAKEUSDT"],
        "timeframe": "1m",
        "params": {},
        "capital": "1000",
        "leverage": 1,
        "fee_rate": 0.0005,
        "risk_params": {"default": {}},
        "user_id": "u1",
        "api_key": "",
        "api_secret": "",
    }
    _run(mgr.start_session(session_config))
    session = mgr.sessions["sess_exchange_wiring_test"]
    # Cancel the background per-symbol loops start_session scheduled via
    # asyncio.create_task — they cannot have executed yet (no await between
    # task creation and here in the single-threaded event loop), so this
    # never touches real candle/exchange I/O (same pattern
    # test_start_session_risk_params_shape.py's own `_run_start_session` uses).
    for task in mgr._tasks.get("sess_exchange_wiring_test", []):
        task.cancel()
    assert isinstance(session["exchange"], BinanceFuturesTestnet)
