"""Plan 6 Step 6.1 (ENG-1): unit tests for `MarketDataFeed`, extracted from
`LiveBotManager` as a pure move (behavior-preserving — see golden-master
`before_plan6.json`/`after_plan6_1.json`, byte-identical).

Run inside the container::

    docker exec enma_trading_platform-engine-1 pytest /app/tests/test_market_data_feed.py
"""
import asyncio
from datetime import datetime, timezone

import numpy as np
import pytest

import core.market_data_feed as mdf_mod
from core.market_data_feed import MarketDataFeed


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _row(ts, o, h, l, c, v):
    return {
        "time": datetime.fromtimestamp(ts / 1000, tz=timezone.utc),
        "open": o, "high": h, "low": l, "close": c, "volume": v,
    }


class _FakeConn:
    def __init__(self, rows):
        self._rows = rows

    async def fetch(self, query, *params):
        return self._rows

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeAcquireCtx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc):
        return False


class _FakePool:
    def __init__(self, rows):
        self._rows = rows

    def acquire(self):
        return _FakeAcquireCtx(_FakeConn(self._rows))


def test_fetch_warmup_candles_orders_oldest_first(monkeypatch):
    # DB returns DESC (newest first) — the method must reverse to oldest-first.
    rows = [_row(3000, 3, 3, 3, 3, 30), _row(2000, 2, 2, 2, 2, 20), _row(1000, 1, 1, 1, 1, 10)]
    monkeypatch.setattr(mdf_mod, "get_pool", lambda: _FakePool(rows))

    feed = MarketDataFeed()
    candles = _run(feed.fetch_warmup_candles("BTCUSDT", "1h", 3))

    assert candles is not None
    assert candles.shape == (3, 6)
    assert list(candles[:, 0]) == [1000.0, 2000.0, 3000.0]


def test_fetch_warmup_candles_empty_returns_none(monkeypatch):
    monkeypatch.setattr(mdf_mod, "get_pool", lambda: _FakePool([]))
    feed = MarketDataFeed()
    assert _run(feed.fetch_warmup_candles("BTCUSDT", "1h", 3)) is None


def test_fetch_warmup_candles_db_error_returns_none(monkeypatch):
    class _BoomPool:
        def acquire(self):
            raise RuntimeError("db down")

    monkeypatch.setattr(mdf_mod, "get_pool", lambda: _BoomPool())
    feed = MarketDataFeed()
    assert _run(feed.fetch_warmup_candles("BTCUSDT", "1h", 3)) is None


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _FakeAsyncClient:
    def __init__(self, payload, capture=None):
        self._payload = payload
        self._capture = capture

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, params=None):
        if self._capture is not None:
            self._capture["url"] = url
            self._capture["params"] = params
        return _FakeResp(self._payload)


def test_fetch_candles_from_rest_excludes_open_candle(monkeypatch):
    # Binance kline: [openTime, open, high, low, close, volume, ...]
    payload = [
        [1000, "1", "1.5", "0.5", "1.2", "10"],
        [2000, "2", "2.5", "1.5", "2.2", "20"],  # currently-open candle, must be dropped
    ]
    capture = {}
    monkeypatch.setattr(mdf_mod.httpx, "AsyncClient", lambda timeout=15.0: _FakeAsyncClient(payload, capture))

    feed = MarketDataFeed()
    candles = _run(feed.fetch_candles_from_rest("BTCUSDT", "1h", 2))

    assert candles.shape == (1, 6)
    assert candles[0, 0] == 1000.0
    assert candles[0, 2] == 1.2  # close = kline index 4
    assert capture["params"]["symbol"] == "BTCUSDT"


def test_fetch_candles_from_rest_error_returns_empty(monkeypatch):
    class _BoomClient:
        async def __aenter__(self):
            raise RuntimeError("network down")

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(mdf_mod.httpx, "AsyncClient", lambda timeout=15.0: _BoomClient())
    feed = MarketDataFeed()
    candles = _run(feed.fetch_candles_from_rest("BTCUSDT", "1h", 2))
    assert candles.shape == (0, 6)


def test_fetch_htf_candles_same_shape_as_base(monkeypatch):
    payload = [
        [1000, "10", "11", "9", "10.5", "5"],
        [2000, "11", "12", "10", "11.5", "6"],
    ]
    monkeypatch.setattr(mdf_mod.httpx, "AsyncClient", lambda timeout=15.0: _FakeAsyncClient(payload))
    feed = MarketDataFeed()
    candles = _run(feed.fetch_htf_candles("BTCUSDT", "4h", limit=50))
    assert candles.shape == (1, 6)
    assert candles[0, 0] == 1000.0


def test_append_candle_new_timestamp_appends():
    feed = MarketDataFeed()
    candles = np.array([[1000, 1, 1, 1, 1, 1]], dtype=np.float64)
    new = np.array([2000, 2, 2, 2, 2, 2], dtype=np.float64)
    out = feed.append_candle(candles, new)
    assert out.shape == (2, 6)
    assert out[-1, 0] == 2000.0


def test_append_candle_same_timestamp_updates_last():
    feed = MarketDataFeed()
    candles = np.array([[1000, 1, 1, 1, 1, 1]], dtype=np.float64)
    new = np.array([1000, 9, 9, 9, 9, 9], dtype=np.float64)
    out = feed.append_candle(candles, new)
    assert out.shape == (1, 6)
    assert out[0, 1] == 9.0


def test_append_candle_older_timestamp_ignored():
    feed = MarketDataFeed()
    candles = np.array([[2000, 2, 2, 2, 2, 2]], dtype=np.float64)
    new = np.array([1000, 1, 1, 1, 1, 1], dtype=np.float64)
    out = feed.append_candle(candles, new)
    assert out.shape == (1, 6)
    assert out[0, 0] == 2000.0


def test_append_candle_empty_seeds_array():
    feed = MarketDataFeed()
    candles = np.empty((0, 6), dtype=np.float64)
    new = np.array([1000, 1, 1, 1, 1, 1], dtype=np.float64)
    out = feed.append_candle(candles, new)
    assert out.shape == (1, 6)


def test_append_candle_trims_to_last_500():
    feed = MarketDataFeed()
    candles = np.arange(501 * 6, dtype=np.float64).reshape(501, 6)
    candles[:, 0] = np.arange(501, dtype=np.float64)  # ascending timestamps
    new = np.array([501.0, 1, 1, 1, 1, 1], dtype=np.float64)
    out = feed.append_candle(candles, new)
    assert out.shape == (500, 6)
    assert out[0, 0] == 2.0  # oldest of the original 501 was dropped
    assert out[-1, 0] == 501.0
