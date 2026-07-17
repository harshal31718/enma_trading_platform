"""Plan 22 Step 22.1 (B-11 engine backstop) regression:
`_fetch_available_balance()` in `engine/core/live_bot_manager.py` — the
engine-side defensive clamp queries the real Binance Testnet available
balance once at `start_session` so a configured `capital` that exceeds the
actual wallet (previously an honor-system number never checked against
reality — B-11) gets clamped instead of silently sizing every order too
large and only discovering it via Binance's own margin-rejection errors.

Drives the real standalone async function directly (module-level, not an
embedded closure) against a stubbed Binance signed-request layer.

Run inside the container::

    docker exec enma_trading_platform-engine-1 pytest /app/tests/test_fetch_available_balance.py
"""
import asyncio

import pytest

import services.binance_testnet as binance_mod
from core.live_bot_manager import _fetch_available_balance


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_returns_parsed_available_balance(monkeypatch):
    async def fake_signed(method, path, api_key, api_secret, params=None, mode="testnet"):
        assert method == "GET"
        assert path == "/fapi/v2/account"
        assert api_key == "k"
        assert api_secret == "s"
        return {"availableBalance": "1234.56", "totalWalletBalance": "2000.0"}

    monkeypatch.setattr(binance_mod, "send_signed_request", fake_signed)

    result = _run(_fetch_available_balance("k", "s"))

    assert result == pytest.approx(1234.56)


def test_missing_credentials_returns_none_without_calling_binance(monkeypatch):
    async def fake_signed(*args, **kwargs):
        raise AssertionError("must not call Binance with no credentials")

    monkeypatch.setattr(binance_mod, "send_signed_request", fake_signed)

    assert _run(_fetch_available_balance("", "")) is None
    assert _run(_fetch_available_balance("k", "")) is None
    assert _run(_fetch_available_balance("", "s")) is None


def test_binance_failure_degrades_to_none_not_raise(monkeypatch):
    async def fake_signed(*args, **kwargs):
        raise RuntimeError("simulated Binance 500")

    monkeypatch.setattr(binance_mod, "send_signed_request", fake_signed)

    assert _run(_fetch_available_balance("k", "s")) is None  # must not raise


def test_malformed_balance_field_degrades_to_none(monkeypatch):
    async def fake_signed(*args, **kwargs):
        return {"availableBalance": "not-a-number"}

    monkeypatch.setattr(binance_mod, "send_signed_request", fake_signed)

    assert _run(_fetch_available_balance("k", "s")) is None


def test_missing_balance_field_degrades_to_none(monkeypatch):
    async def fake_signed(*args, **kwargs):
        return {}  # no availableBalance key at all

    monkeypatch.setattr(binance_mod, "send_signed_request", fake_signed)

    assert _run(_fetch_available_balance("k", "s")) is None
