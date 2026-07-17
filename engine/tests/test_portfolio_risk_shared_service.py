"""Plan 22 Step 22.4 regression: `services/portfolio_risk.py` — the shared
VaR/CVaR computation both the Zone 1 dashboard (`routers/risk.py`) and the
live Session Risk Governor (`core/models/governor.py`'s `check_var`, wired
from `core/live_bot_manager.py`) go through.

Same stub-injection approach as `test_kline_ws_url.py` / `test_execute_
entry_portfolio_risk_and_liq_buffer.py` — `config.timescale` imports
`asyncpg` at module level, which isn't installed in this sandbox; register
a minimal fake before importing the real module. See those files'
docstrings for why this technique (not a reimplementation) is used.

Central acceptance criterion this file proves: "dashboard value and
governor value provably identical (same function, one test)" — see
`test_dashboard_and_governor_get_identical_values_from_one_call` and
`test_second_call_within_ttl_reuses_the_cached_fetch_not_a_fresh_one`
(the latter proves the two call sites are actually SHARING one cached
fetch, not just coincidentally computing the same thing from independent
stub calls that happen to return identical canned data).

Run inside the container::

    docker exec enma_trading_platform-engine-1 pytest /app/tests/test_portfolio_risk_shared_service.py
"""
import sys
import types
import asyncio

import numpy as np
import pytest


def _ensure_importable():
    try:
        import config.timescale  # noqa: F401
        return
    except ModuleNotFoundError:
        pass
    for modname in ("asyncpg",):
        if modname not in sys.modules:
            sys.modules[modname] = types.ModuleType(modname)

    class _FakePool:
        pass

    if not hasattr(sys.modules["asyncpg"], "Pool"):
        sys.modules["asyncpg"].Pool = _FakePool

    async def _fake_create_pool(*a, **kw):
        raise RuntimeError("stubbed asyncpg.create_pool — not implemented, test doesn't call it")

    if not hasattr(sys.modules["asyncpg"], "create_pool"):
        sys.modules["asyncpg"].create_pool = _fake_create_pool


_ensure_importable()

import services.portfolio_risk as pr


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture(autouse=True)
def _clear_caches():
    pr.clear_caches()
    yield
    pr.clear_caches()


# ── extract_position_notionals ──────────────────────────────────────────────

def test_extract_position_notionals_parses_open_positions_only():
    account_data = {
        "positions": [
            {"symbol": "BTCUSDT", "positionAmt": "0.5", "entryPrice": "50000", "notional": "25000", "leverage": "10"},
            {"symbol": "ETHUSDT", "positionAmt": "0", "entryPrice": "3000", "notional": "0", "leverage": "5"},
            {"symbol": "SOLUSDT", "positionAmt": "-10", "entryPrice": "100", "notional": "-1000", "leverage": "3"},
        ]
    }
    symbols, notionals, exposures = pr.extract_position_notionals(account_data)
    assert set(symbols) == {"BTCUSDT", "SOLUSDT"}  # ETHUSDT has amt=0, excluded
    assert notionals["BTCUSDT"] == pytest.approx(25000.0)
    assert notionals["SOLUSDT"] == pytest.approx(-1000.0)
    assert exposures["BTCUSDT"]["side"] == "long"
    assert exposures["SOLUSDT"]["side"] == "short"


# ── Caching ──────────────────────────────────────────────────────────────────

def test_fetch_account_positions_is_cached_within_ttl(monkeypatch):
    calls = {"n": 0}

    async def fake_signed(method, path, api_key, api_secret, params=None, mode="testnet"):
        calls["n"] += 1
        return {"positions": [], "call": calls["n"]}

    import services.binance_testnet as binance_mod
    monkeypatch.setattr(binance_mod, "send_signed_request", fake_signed)

    r1 = _run(pr.fetch_account_positions("k", "s", "testnet"))
    r2 = _run(pr.fetch_account_positions("k", "s", "testnet"))
    assert r1 == r2
    assert r1["call"] == 1  # second call served from cache, not a fresh fetch
    assert calls["n"] == 1


def test_fetch_account_positions_cache_is_keyed_by_api_key_and_mode(monkeypatch):
    calls = {"n": 0}

    async def fake_signed(method, path, api_key, api_secret, params=None, mode="testnet"):
        calls["n"] += 1
        return {"positions": [], "key": api_key, "mode": mode}

    import services.binance_testnet as binance_mod
    monkeypatch.setattr(binance_mod, "send_signed_request", fake_signed)

    _run(pr.fetch_account_positions("keyA", "s", "testnet"))
    _run(pr.fetch_account_positions("keyB", "s", "testnet"))  # different key -> fresh fetch
    assert calls["n"] == 2


def test_fetch_close_prices_is_cached_per_symbol_set(monkeypatch):
    calls = {"n": 0}

    class _FakeConn:
        async def fetch(self, query, symbols, cutoff):
            calls["n"] += 1
            return [{"symbol": s, "close": 100.0 + i} for i, s in enumerate(symbols)]

    class _FakeAcquire:
        async def __aenter__(self):
            return _FakeConn()

        async def __aexit__(self, *a):
            return False

    class _FakePool:
        def acquire(self):
            return _FakeAcquire()

    monkeypatch.setattr(pr, "get_pool", lambda: _FakePool())

    r1 = _run(pr.fetch_close_prices(["BTCUSDT", "ETHUSDT"]))
    r2 = _run(pr.fetch_close_prices(["ETHUSDT", "BTCUSDT"]))  # same set, different order
    assert calls["n"] == 1  # sorted cache key -> order-independent, second call cached
    assert set(r1.keys()) == {"BTCUSDT", "ETHUSDT"}
    assert list(r2["BTCUSDT"]) == list(r1["BTCUSDT"])


def test_fetch_close_prices_empty_symbols_short_circuits_without_db_call(monkeypatch):
    def _fail_get_pool():
        raise AssertionError("get_pool should never be called for an empty symbol list")
    monkeypatch.setattr(pr, "get_pool", _fail_get_pool)
    result = _run(pr.fetch_close_prices([]))
    assert result == {}


# ── The acceptance-critical identity test ───────────────────────────────────

def test_dashboard_and_governor_get_identical_values_from_one_call(monkeypatch):
    """Simulates both call sites: `routers/risk.py`'s dashboard route and
    `LiveAdapter.execute_entry`'s governor gate both ultimately call
    `compute_var_cvar` with the same (api_key, mode). Proves they receive
    byte-identical (var_amount, cvar_amount) tuples AND that the underlying
    account/price fetches only happened once each — i.e., they are
    genuinely sharing the cached computation, not just coincidentally
    landing on equal numbers from independently re-stubbed calls."""
    account_calls = {"n": 0}
    price_calls = {"n": 0}

    async def fake_signed(method, path, api_key, api_secret, params=None, mode="testnet"):
        account_calls["n"] += 1
        return {
            "positions": [
                {"symbol": "BTCUSDT", "positionAmt": "1.0", "entryPrice": "50000",
                 "notional": "50000", "leverage": "5"},
            ]
        }

    class _FakeConn:
        async def fetch(self, query, symbols, cutoff):
            price_calls["n"] += 1
            rng = np.linspace(49000, 51000, 40)
            rows = []
            for s in symbols:
                for v in rng:
                    rows.append({"symbol": s, "close": float(v)})
            return rows

    class _FakeAcquire:
        async def __aenter__(self):
            return _FakeConn()

        async def __aexit__(self, *a):
            return False

    class _FakePool:
        def acquire(self):
            return _FakeAcquire()

    import services.binance_testnet as binance_mod
    monkeypatch.setattr(binance_mod, "send_signed_request", fake_signed)
    monkeypatch.setattr(pr, "get_pool", lambda: _FakePool())

    # "Dashboard" call
    dashboard_var, dashboard_cvar = _run(pr.compute_var_cvar("k", "s", "testnet", confidence_level=0.95))
    # "Governor" call — same api_key/mode, well within both TTLs
    governor_var, governor_cvar = _run(pr.compute_var_cvar("k", "s", "testnet", confidence_level=0.95))

    assert dashboard_var == governor_var
    assert dashboard_cvar == governor_cvar
    assert account_calls["n"] == 1  # shared cache, not two independent fetches
    assert price_calls["n"] == 1


def test_compute_full_metrics_var95_matches_compute_var_cvar(monkeypatch):
    """The dashboard route's `compute_full_metrics` must derive its var95/
    cvar95 from the exact same underlying call `compute_var_cvar` makes —
    not a parallel reimplementation that could silently drift."""
    async def fake_signed(method, path, api_key, api_secret, params=None, mode="testnet"):
        return {
            "positions": [
                {"symbol": "BTCUSDT", "positionAmt": "1.0", "entryPrice": "50000",
                 "notional": "50000", "leverage": "5"},
            ],
            "totalWalletBalance": "10000", "totalMarginBalance": "10000", "totalInitialMargin": "500",
        }

    class _FakeConn:
        async def fetch(self, query, symbols, cutoff):
            rng = np.linspace(49000, 51000, 40)
            return [{"symbol": s, "close": float(v)} for s in symbols for v in rng]

    class _FakeAcquire:
        async def __aenter__(self):
            return _FakeConn()

        async def __aexit__(self, *a):
            return False

    class _FakePool:
        def acquire(self):
            return _FakeAcquire()

    import services.binance_testnet as binance_mod
    monkeypatch.setattr(binance_mod, "send_signed_request", fake_signed)
    monkeypatch.setattr(pr, "get_pool", lambda: _FakePool())

    full = _run(pr.compute_full_metrics("k", "s", "testnet"))
    var_direct, cvar_direct = _run(pr.compute_var_cvar("k", "s", "testnet", confidence_level=0.95))

    assert full["var95"] == var_direct
    assert full["cvar95"] == cvar_direct
