"""Plan 21 Step 21.5c (A-9c): batched positionRisk/openOrders/openAlgoOrders
snapshot shared across every symbol reconciling the same candle wave.

Drives ``LiveBotManager._reconcile_exchange_state`` (which now accepts
``wave_key``) with a stubbed Binance signed-request layer that records every
call's path + whether ``symbol`` was present in params, so these tests can
assert the actual call-count/shape claim this step makes: one un-parametered
call per session per wave, not one per symbol.

Run inside the container::

    docker exec enma_trading_platform-engine-1 pytest /app/tests/test_batched_reconcile_snapshot.py
"""
import asyncio

import services.binance_testnet as binance_mod
from core.live_bot_manager import LiveBotManager

SYM_A = "AAAUSDT"
SYM_B = "BBBUSDT"


class _FakeStrategy:
    def __init__(self, price=100.0, leverage=5):
        self.position = None
        self.price = price
        self.leverage = leverage
        self.stop_loss = None
        self.take_profit = None
        self.active_bracket = None
        self._pending_flip = None


def _make_session():
    return {"open_positions": {}, "pnl": 0.0, "strategy_name": "X",
            "api_key": "k", "api_secret": "s", "user_id": ""}


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _install_recording_stub(monkeypatch, positions_by_symbol=None, orders_by_symbol=None,
                             algo_orders_by_symbol=None, fail_batched_position=False, delay=0.0):
    """calls: list of (path, "batched" | "per-symbol:<sym>")."""
    positions_by_symbol = positions_by_symbol or {}
    orders_by_symbol = orders_by_symbol or {}
    algo_orders_by_symbol = algo_orders_by_symbol or {}
    calls = []

    async def fake_signed(method, path, api_key, api_secret, params=None, mode="testnet"):
        params = params or {}
        sym = params.get("symbol")
        if delay:
            await asyncio.sleep(delay)
        calls.append((path, sym))

        if path == "/fapi/v2/positionRisk":
            if sym is None and fail_batched_position:
                raise RuntimeError("simulated positionRisk failure")
            if sym is not None:
                p = positions_by_symbol.get(sym)
                return [p] if p else []
            return list(positions_by_symbol.values())

        if path == "/fapi/v1/openOrders":
            if sym is not None:
                return orders_by_symbol.get(sym, [])
            out = []
            for v in orders_by_symbol.values():
                out.extend(v)
            return out

        if path == "/fapi/v1/openAlgoOrders":
            if sym is not None:
                return algo_orders_by_symbol.get(sym, [])
            out = []
            for v in algo_orders_by_symbol.values():
                out.extend(v)
            return out

        return []

    monkeypatch.setattr(binance_mod, "send_signed_request", fake_signed)
    return calls


def _make_mgr(sid):
    mgr = LiveBotManager()
    mgr.sessions[sid] = _make_session()
    return mgr


def test_two_symbols_same_wave_share_one_batched_snapshot(monkeypatch):
    calls = _install_recording_stub(monkeypatch)
    mgr = _make_mgr("sess1")
    strat_a, strat_b = _FakeStrategy(), _FakeStrategy()

    _run(mgr._reconcile_exchange_state("sess1", strat_a, SYM_A, 101.0, 99.0, wave_key=1000))
    _run(mgr._reconcile_exchange_state("sess1", strat_b, SYM_B, 101.0, 99.0, wave_key=1000))

    position_calls = [c for c in calls if c[0] == "/fapi/v2/positionRisk"]
    order_calls = [c for c in calls if c[0] == "/fapi/v1/openOrders"]
    algo_calls = [c for c in calls if c[0] == "/fapi/v1/openAlgoOrders"]
    # Exactly one un-parametered (sym=None) call per endpoint total, not one per symbol.
    assert position_calls == [("/fapi/v2/positionRisk", None)]
    assert order_calls == [("/fapi/v1/openOrders", None)]
    assert algo_calls == [("/fapi/v1/openAlgoOrders", None)]


def test_different_wave_triggers_a_fresh_fetch(monkeypatch):
    calls = _install_recording_stub(monkeypatch)
    mgr = _make_mgr("sess1")
    strat = _FakeStrategy()

    _run(mgr._reconcile_exchange_state("sess1", strat, SYM_A, 101.0, 99.0, wave_key=1000))
    _run(mgr._reconcile_exchange_state("sess1", strat, SYM_A, 101.0, 99.0, wave_key=2000))

    position_calls = [c for c in calls if c[0] == "/fapi/v2/positionRisk"]
    assert len(position_calls) == 2


def test_batched_snapshot_slices_the_correct_symbol(monkeypatch):
    pos_a = {"symbol": SYM_A, "positionAmt": "1", "entryPrice": "100",
             "markPrice": "105", "unRealizedProfit": "5",
             "leverage": "10", "isolatedWallet": "10", "liquidationPrice": "90"}
    pos_b = {"symbol": SYM_B, "positionAmt": "0", "entryPrice": "0",
             "markPrice": "0", "unRealizedProfit": "0",
             "leverage": "10", "isolatedWallet": "0", "liquidationPrice": "0"}
    algo_a = [{"algoId": 111, "clientAlgoId": "tpsl_abc_sl", "orderType": "STOP_MARKET",
               "orderStatus": "NEW", "triggerPrice": "95.0", "quantity": "1",
               "side": "SELL", "symbol": SYM_A, "createTime": 1}]
    _install_recording_stub(
        monkeypatch,
        positions_by_symbol={SYM_A: pos_a, SYM_B: pos_b},
        algo_orders_by_symbol={SYM_A: algo_a},
    )
    mgr = _make_mgr("sess1")
    monkeypatch.setattr(mgr._notifier, "notify", lambda *a, **k: asyncio.sleep(0))
    strat_a, strat_b = _FakeStrategy(), _FakeStrategy()

    _run(mgr._reconcile_exchange_state("sess1", strat_a, SYM_A, 101.0, 99.0, wave_key=1000))
    _run(mgr._reconcile_exchange_state("sess1", strat_b, SYM_B, 101.0, 99.0, wave_key=1000))

    # SYM_A restored from its own slice of the batch, with its own bracket —
    # not SYM_B's (flat) data.
    assert strat_a.position is not None
    assert strat_a.position.leverage == 10.0
    assert strat_a.stop_loss == (1.0, 95.0)
    # SYM_B genuinely flat in the batch — no position restored, no bracket.
    assert strat_b.position is None
    assert strat_b.stop_loss is None


def test_batched_positionrisk_failure_blocks_case2_fabricated_close(monkeypatch):
    """A-15's invariant must hold in the batched path too: if the shared
    positionRisk call itself fails, no symbol's Case 2 (fabricate a close)
    may fire off that wave's snapshot — position_query_ok must propagate
    False to every symbol sharing it, not just the one that triggered the
    fetch."""
    from core.position import Position

    _install_recording_stub(monkeypatch, fail_batched_position=True)
    mgr = _make_mgr("sess1")
    monkeypatch.setattr(mgr._notifier, "notify", lambda *a, **k: asyncio.sleep(0))
    strat = _FakeStrategy()
    strat.position = Position("long", qty=1.0, entry_price=100.0, leverage=5.0, isolated_wallet=20.0)
    mgr.sessions["sess1"]["open_positions"][SYM_A] = {
        "symbol": SYM_A, "side": "long", "qty": "1.0", "price": "100.0",
        "timestamp": "2026-01-01T00:00:00+00:00",
    }

    _run(mgr._reconcile_exchange_state("sess1", strat, SYM_A, 101.0, 99.0, wave_key=1000))

    # Local position must survive — never fabricated closed on an unconfirmed query.
    assert strat.position is not None


def test_concurrent_symbols_same_wave_issue_exactly_one_fetch(monkeypatch):
    """The real point of this step: many symbol tasks reconciling the same
    candle wave concurrently must not each trigger their own batch fetch —
    only the first arrival fetches, the rest await and reuse it."""
    calls = _install_recording_stub(monkeypatch, delay=0.02)
    mgr = _make_mgr("sess1")
    strategies = [_FakeStrategy() for _ in range(5)]
    symbols = [f"SYM{i}USDT" for i in range(5)]

    async def _go():
        await asyncio.gather(*[
            mgr._reconcile_exchange_state("sess1", s, sym, 101.0, 99.0, wave_key=5000)
            for s, sym in zip(strategies, symbols)
        ])

    _run(_go())

    position_calls = [c for c in calls if c[0] == "/fapi/v2/positionRisk"]
    assert len(position_calls) == 1


def test_event_driven_call_without_wave_key_is_unbatched_per_symbol(monkeypatch):
    """No wave_key (the `_on_fill`/`_on_account_update` call shape) must keep
    querying per-symbol, fresh, every time — zero change from pre-21.5c
    behavior for the event-driven path."""
    calls = _install_recording_stub(monkeypatch)
    mgr = _make_mgr("sess1")
    strat = _FakeStrategy()

    _run(mgr._reconcile_exchange_state("sess1", strat, SYM_A))
    _run(mgr._reconcile_exchange_state("sess1", strat, SYM_A))

    position_calls = [c for c in calls if c[0] == "/fapi/v2/positionRisk"]
    assert position_calls == [
        ("/fapi/v2/positionRisk", SYM_A),
        ("/fapi/v2/positionRisk", SYM_A),
    ]
