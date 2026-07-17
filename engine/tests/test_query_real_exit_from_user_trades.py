"""Plan 21 Step 21.1 (A-1) regression: `_query_real_exit_from_user_trades()`
must actually call Binance's signed `/fapi/v1/userTrades` endpoint with
credentials, not silently no-op.

Before the fix, the call site omitted the required `api_key`/`api_secret`
positionals that `send_signed_request(method, path, api_key, api_secret, ...)`
has no defaults for. That raised a `TypeError` on every invocation, swallowed
by the surrounding `except Exception`, so the function always returned
`None` — the Plan 5.2 "reconstruct the real close from Binance's own trade
history" path had never executed; every `exchange_sync` close silently fell
back to the candle/SL-TP estimate instead of Binance's authoritative
`realizedPnl`.

Run inside the container::

    docker exec enma_trading_platform-engine-1 pytest /app/tests/test_query_real_exit_from_user_trades.py
"""
import asyncio
from datetime import datetime, timezone

import pytest

import services.binance_testnet as binance_mod
from core.live_bot_manager import _query_real_exit_from_user_trades

SYM = "FAKEUSDT"


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_userTrades_call_receives_credentials_and_endpoint(monkeypatch):
    """The exact regression: assert api_key/api_secret actually reach
    send_signed_request, and the call targets /fapi/v1/userTrades signed."""
    received = {}

    async def fake_signed(method, path, api_key, api_secret, params=None, mode="testnet"):
        received["method"] = method
        received["path"] = path
        received["api_key"] = api_key
        received["api_secret"] = api_secret
        received["params"] = params
        received["mode"] = mode
        return []  # no trades — exercises the "no relevant trades" branch too

    monkeypatch.setattr(binance_mod, "send_signed_request", fake_signed)

    result = _run(_query_real_exit_from_user_trades(
        "REAL_KEY", "REAL_SECRET", SYM, datetime.now(timezone.utc),
    ))

    assert received["method"] == "GET"
    assert received["path"] == "/fapi/v1/userTrades"
    assert received["api_key"] == "REAL_KEY"
    assert received["api_secret"] == "REAL_SECRET"
    assert received["params"]["symbol"] == SYM
    assert received["mode"] == "testnet"
    # Empty trades list -> no matching fills -> None, not a crash.
    assert result is None


def test_userTrades_result_is_actually_consumed(monkeypatch):
    """Drives a realistic multi-fill userTrades response and asserts the
    real exit price / net realized PnL are computed from it — i.e. the
    reconcile Case 2 path genuinely uses Binance's own data, not an
    estimate."""
    entry_time = datetime(2026, 7, 16, 12, 0, 0, tzinfo=timezone.utc)
    entry_ms = entry_time.timestamp() * 1000

    fake_trades = [
        # Before entry — must be excluded from the average.
        {"time": entry_ms - 60_000, "qty": "5.0", "price": "50.0", "realizedPnl": "0", "commission": "0.01"},
        # Two fills after entry that together closed the position.
        {"time": entry_ms + 1_000, "qty": "1.0", "price": "100.0", "realizedPnl": "2.0", "commission": "0.02"},
        {"time": entry_ms + 2_000, "qty": "1.0", "price": "102.0", "realizedPnl": "3.0", "commission": "0.02"},
    ]

    async def fake_signed(method, path, api_key, api_secret, params=None, mode="testnet"):
        assert api_key and api_secret  # A-1: must be non-empty, never omitted
        return fake_trades

    monkeypatch.setattr(binance_mod, "send_signed_request", fake_signed)

    result = _run(_query_real_exit_from_user_trades("k", "s", SYM, entry_time))

    assert result is not None
    avg_price, net_pnl = result
    # Weighted average of the two post-entry fills only (100*1 + 102*1) / 2
    assert avg_price == pytest.approx(101.0)
    # (2.0 + 3.0) realizedPnl - (0.02 + 0.02) commission, pre-entry fill excluded
    assert net_pnl == pytest.approx(4.96)


def test_userTrades_exception_is_caught_and_returns_none(monkeypatch):
    """A genuine Binance/network failure must still degrade to None (the
    reconcile caller's documented fallback-to-estimate contract), not
    propagate and crash the reconcile loop."""
    async def fake_signed(method, path, api_key, api_secret, params=None, mode="testnet"):
        raise RuntimeError("simulated Binance 500")

    monkeypatch.setattr(binance_mod, "send_signed_request", fake_signed)

    result = _run(_query_real_exit_from_user_trades("k", "s", SYM, datetime.now(timezone.utc)))
    assert result is None
