"""Regression tests for live reconcile fixes (I-05 price_missing, I-07 restore fidelity).

Drives the real ``LiveBotManager._reconcile_exchange_state`` with a stubbed
Binance signed-request layer (no network), asserting:
  * I-07 — a position present on the exchange but not locally is restored with
    exchange-truth leverage / liquidation price AND its SL/TP brackets + algo_ids.
  * I-05 — when no usable mark price exists, ``price_missing`` is True and a
    legitimate 0.0 unrealized PnL is preserved (not dropped to None).

Run inside the container::

    docker exec enma_trading_platform-engine-1 pytest /app/tests/test_reconcile_fixes.py
"""
import asyncio
import os

import pytest

import services.binance_testnet as binance_mod
from core.live_bot_manager import LiveBotManager

SYM = "FAKEUSDT"


class _FakeStrategy:
    def __init__(self, price=100.0, leverage=5):
        self.position = None
        self.price = price
        self.leverage = leverage
        self.stop_loss = None
        self.take_profit = None
        self._pending_flip = None


def _make_session():
    return {"open_positions": {}, "pnl": 0.0, "strategy_name": "X",
            "api_key": "k", "api_secret": "s", "user_id": ""}


def _install_stub(monkeypatch, pos, algo_orders, open_orders=None):
    open_orders = open_orders or []

    async def fake_signed(method, path, api_key, api_secret, params=None, mode="testnet"):
        if path == "/fapi/v2/positionRisk":
            return [pos]
        if path == "/fapi/v1/openOrders":
            return open_orders
        if path == "/fapi/v1/openAlgoOrders":
            return algo_orders
        return []

    monkeypatch.setattr(binance_mod, "send_signed_request", fake_signed)


def _run(mgr, sid, strat):
    return asyncio.get_event_loop().run_until_complete(
        mgr._reconcile_exchange_state(sid, strat, SYM))


def test_restore_uses_exchange_leverage_and_rebuilds_brackets(monkeypatch):
    pos = {
        "symbol": SYM, "positionAmt": "1", "entryPrice": "100",
        "markPrice": "105", "unRealizedProfit": "5",
        "leverage": "10", "isolatedWallet": "10", "liquidationPrice": "90",
    }
    algo_orders = [
        {"algoId": 111, "clientAlgoId": "tpsl_abc_sl", "orderType": "STOP_MARKET",
         "orderStatus": "NEW", "triggerPrice": "95.0", "quantity": "1",
         "side": "SELL", "symbol": SYM, "createTime": 1},
        {"algoId": 222, "clientAlgoId": "tpsl_abc_tp", "orderType": "TAKE_PROFIT_MARKET",
         "orderStatus": "NEW", "triggerPrice": "110.0", "quantity": "1",
         "side": "SELL", "symbol": SYM, "createTime": 1},
    ]
    _install_stub(monkeypatch, pos, algo_orders)

    mgr = LiveBotManager()
    sid = "sess1"
    mgr.sessions[sid] = _make_session()
    monkeypatch.setattr(mgr._notifier, "notify", lambda *a, **k: asyncio.sleep(0))
    strat = _FakeStrategy(leverage=5)

    _run(mgr, sid, strat)

    # I-07: exchange-truth leverage + liq price, not leverage=1 / recomputed
    assert strat.position is not None
    assert strat.position.leverage == 10.0
    assert strat.position.liquidation_price == 90.0
    # brackets restored
    assert strat.stop_loss == (1.0, 95.0)
    assert strat.take_profit == (1.0, 110.0)
    # algo_ids restored for OUO peer-cancel
    info = mgr.sessions[sid]["open_positions"][SYM]
    assert info["algo_ids"] == {"sl": 111, "tp": 222}
    assert info["leverage"] == 10.0
    assert info["price_missing"] is False


def test_price_missing_true_when_no_usable_price(monkeypatch):
    pos = {
        "symbol": SYM, "positionAmt": "2", "entryPrice": "100",
        "markPrice": "0", "unRealizedProfit": "0",
        "leverage": "10", "isolatedWallet": "20", "liquidationPrice": "0",
    }
    _install_stub(monkeypatch, pos, algo_orders=[])

    mgr = LiveBotManager()
    sid = "sess2"
    mgr.sessions[sid] = _make_session()
    monkeypatch.setattr(mgr._notifier, "notify", lambda *a, **k: asyncio.sleep(0))
    strat = _FakeStrategy(price=None)  # no engine last-price fallback

    _run(mgr, sid, strat)

    info = mgr.sessions[sid]["open_positions"][SYM]
    # I-05: flag actually fires now (was permanently False before)
    assert info["price_missing"] is True
    assert info["mark_price"] is None
    # a legitimate 0.0 unrealized PnL is preserved, not dropped to None
    assert info["unrealized_pnl"] == "0.0"
