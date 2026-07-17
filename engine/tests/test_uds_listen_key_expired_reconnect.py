"""Plan 21 Step 21.1 (A-3) regression: `UserDataStreamManager._run_ws` must
reconnect (not die) when Binance sends a `listenKeyExpired` event.

Before the fix, the `LISTEN_KEY_EXPIRED` handler did `return` after
refreshing the listen key — that `return` exits the `_run_ws` **coroutine**
itself (there is no caller that re-invokes it), not just the inner
`async for` message loop. The comment claiming "reconnect loop picks it up"
was wrong: the task ends silently, and the whole user-data stream (hence the
event-driven fill path, F-020) is dead for the rest of the session the
moment a listen key expires (at most 24h after creation).

This test drives the real `_run_ws` against a fake `websockets.connect` that
simulates exactly that: the first "connection" delivers a `listenKeyExpired`
frame, and we assert `_run_ws` reconnects — i.e. `websockets.connect` is
called a second time, with the refreshed listen key in the URL — and keeps
processing frames afterward, rather than returning after the first frame.

Run inside the container::

    docker exec enma_trading_platform-engine-1 pytest /app/tests/test_uds_listen_key_expired_reconnect.py
"""
import asyncio
import json

import pytest

import services.user_data_stream as uds_mod
from services.user_data_stream import UserDataStreamManager, _BINANCE_FUTURES_WS


class _FakeWSConnection:
    """Minimal stand-in for the object `websockets.connect(...)` yields via
    `async with` — an async context manager that is also an async iterator
    over raw text frames."""

    def __init__(self, messages):
        self._messages = list(messages)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._messages:
            raise StopAsyncIteration
        return self._messages.pop(0)


def test_listen_key_expired_triggers_reconnect_not_death(monkeypatch):
    mgr = UserDataStreamManager(api_key="k", api_secret="s")
    mgr._running = True

    connect_calls = []

    async def fake_create_listen_key():
        return "REFRESHED_KEY"

    monkeypatch.setattr(mgr, "_create_listen_key", fake_create_listen_key)

    def fake_connect(url, **kwargs):
        connect_calls.append(url)
        if len(connect_calls) == 1:
            # First connection: Binance tells us the listen key expired.
            return _FakeWSConnection([json.dumps({"e": "listenKeyExpired"})])
        else:
            # Second connection (post-reconnect): a real event arrives,
            # proving the loop is alive and processing again. Stop the
            # manager afterward so the test terminates.
            return _FakeWSConnection([json.dumps({
                "e": "ORDER_TRADE_UPDATE",
                "o": {"s": "BTCUSDT", "X": "NEW", "c": "test_1"},
            })])

    monkeypatch.setattr(uds_mod.websockets, "connect", fake_connect)

    processed_second_frame = {"flag": False}

    async def _stop_after_second_frame(event_type, payload):
        processed_second_frame["flag"] = True
        mgr._running = False  # end the outer while loop cleanly

    mgr.register_stream_callback(_stop_after_second_frame)

    asyncio.get_event_loop().run_until_complete(
        asyncio.wait_for(mgr._run_ws(f"{_BINANCE_FUTURES_WS}/OLD_KEY"), timeout=5)
    )

    # The exact regression: a second connection attempt happened at all
    # (pre-fix, `return` killed the coroutine after the first frame — no
    # second connect call would ever be made).
    assert len(connect_calls) == 2
    # And it used the refreshed listen key, not the stale one.
    assert "REFRESHED_KEY" in connect_calls[1]
    assert "OLD_KEY" not in connect_calls[1]
    # The stream kept processing events after reconnecting.
    assert processed_second_frame["flag"] is True


def test_listen_key_expired_refreshes_key_before_reconnecting(monkeypatch):
    """The refreshed key must actually be requested from Binance (not just
    the URL string mutated) — confirms `_create_listen_key` is awaited."""
    mgr = UserDataStreamManager(api_key="k", api_secret="s")
    mgr._running = True

    create_key_calls = {"n": 0}

    async def fake_create_listen_key():
        create_key_calls["n"] += 1
        return f"KEY_{create_key_calls['n']}"

    monkeypatch.setattr(mgr, "_create_listen_key", fake_create_listen_key)

    connect_calls = []

    def fake_connect(url, **kwargs):
        connect_calls.append(url)
        if len(connect_calls) == 1:
            return _FakeWSConnection([json.dumps({"e": "listenKeyExpired"})])
        # Second connection: nothing more to deliver, stop the manager.
        mgr._running = False
        return _FakeWSConnection([])

    monkeypatch.setattr(uds_mod.websockets, "connect", fake_connect)

    asyncio.get_event_loop().run_until_complete(
        asyncio.wait_for(mgr._run_ws(f"{_BINANCE_FUTURES_WS}/INITIAL"), timeout=5)
    )

    assert create_key_calls["n"] == 1
    assert connect_calls[1].endswith("KEY_1")
