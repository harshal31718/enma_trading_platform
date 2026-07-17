"""Plan 21 A-12: live signal candles sourced from mainnet's public kline WS
instead of testnet's own feed (`DECISIONS.md` #24). Warmup candles
(TimescaleDB/REST) and HTF candles (`_fetch_htf_candles`) were already
mainnet-sourced; testnet's own live kline stream was the one remaining
splice point where the price series could step discontinuously on an
illiquid testnet symbol. Order EXECUTION is untouched — every signed
Binance call in `live_bot_manager.py` still passes mode="testnet"; only this
read-only stream URL moves.

`core/live_bot_manager.py` has a heavy TA-Lib/numpy/motor/asyncpg/websockets
dependency chain that doesn't fully install in this sandbox (`websockets`,
`motor`, `asyncpg` time out via pip). `_kline_ws_url`/`_MAINNET_WS_BASE`
themselves are pure, dependency-free string logic, so rather than falling
back to `ast.parse`-only (this repo's usual fallback for modules like this),
this file stubs the three missing third-party modules just enough to satisfy
`live_bot_manager.py`'s import-time requirements, then imports and calls the
REAL function — not a reimplementation of its logic. Inside the actual
container (where these packages are genuinely installed) this test runs
identically without the stubs ever engaging (they're only registered if the
real module isn't already importable — see the try/except below).

Run inside the container::

    docker exec enma_trading_platform-engine-1 pytest /app/tests/test_kline_ws_url.py
"""
import sys
import types

import pytest


def _import_live_bot_manager():
    """Import the real core.live_bot_manager, stubbing websockets/motor/
    asyncpg only if they're genuinely unavailable (sandbox) — inside the
    real container these are installed and the stubs never get used."""
    try:
        import core.live_bot_manager as m
        return m
    except ModuleNotFoundError:
        pass

    for modname in ("websockets", "motor", "motor.motor_asyncio", "asyncpg"):
        if modname not in sys.modules:
            sys.modules[modname] = types.ModuleType(modname)

    sys.modules["motor"].motor_asyncio = sys.modules["motor.motor_asyncio"]

    class _FakeAsyncIOMotorClient:
        def __init__(self, *a, **kw):
            pass

    if not hasattr(sys.modules["motor.motor_asyncio"], "AsyncIOMotorClient"):
        sys.modules["motor.motor_asyncio"].AsyncIOMotorClient = _FakeAsyncIOMotorClient

    async def _fake_connect(*a, **kw):
        raise RuntimeError("stubbed websockets.connect — not implemented, test doesn't call it")

    if not hasattr(sys.modules["websockets"], "connect"):
        sys.modules["websockets"].connect = _fake_connect

    class _FakePool:
        pass

    if not hasattr(sys.modules["asyncpg"], "Pool"):
        sys.modules["asyncpg"].Pool = _FakePool

    async def _fake_create_pool(*a, **kw):
        raise RuntimeError("stubbed asyncpg.create_pool — not implemented, test doesn't call it")

    if not hasattr(sys.modules["asyncpg"], "create_pool"):
        sys.modules["asyncpg"].create_pool = _fake_create_pool

    import core.live_bot_manager as m
    return m


@pytest.fixture(scope="module")
def lbm():
    return _import_live_bot_manager()


def test_mainnet_ws_base_is_the_public_market_stream_path(lbm):
    """Must be /market/ws/ (kline streams), not /public/ws/ (depth-only) —
    mirrors client/src/lib/binanceWS.js's own routing (A-12's cited
    reference implementation)."""
    assert lbm._MAINNET_WS_BASE == "wss://fstream.binance.com/market/ws"


def test_kline_ws_url_builds_the_expected_stream_name(lbm):
    assert lbm._kline_ws_url("BTCUSDT", "1h") == "wss://fstream.binance.com/market/ws/btcusdt@kline_1h"


def test_kline_ws_url_lowercases_symbol_regardless_of_input_case(lbm):
    assert lbm._kline_ws_url("ethusdt", "4h") == "wss://fstream.binance.com/market/ws/ethusdt@kline_4h"
    assert lbm._kline_ws_url("EthUsdt", "4h") == "wss://fstream.binance.com/market/ws/ethusdt@kline_4h"


def test_kline_ws_url_is_not_the_old_testnet_host(lbm):
    """Regression guard: the whole point of A-12 is that this no longer
    points at testnet's own feed."""
    url = lbm._kline_ws_url("BTCUSDT", "1h")
    assert "fstream.binancefuture.com" not in url
    assert "fstream.binance.com" in url


def test_kline_ws_url_passes_through_arbitrary_binance_intervals(lbm):
    for interval in ("1m", "5m", "15m", "1h", "4h", "1d", "1w", "1M"):
        assert lbm._kline_ws_url("BTCUSDT", interval) == f"wss://fstream.binance.com/market/ws/btcusdt@kline_{interval}"
