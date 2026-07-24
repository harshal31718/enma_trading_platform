"""Plan 21 Step 21.4 (M-4) regression: `LiveBotManager._maybe_amend_exchange_sl()`
— cancel+replace the resting exchange SL algo order when
`DefaultExecution.route()`'s Path 5 tightens `strategy.stop_loss`
(trailing/breakeven/Chandelier stops).

Before this fix, a tightened stop was written to `strategy.stop_loss`
LOCALLY ONLY — the exchange-side `closePosition:"true"` STOP_MARKET order
stayed at its original, widest trigger for the position's entire life.
Between candles, only the stale wide stop protected the position on
Binance; real enforcement was the engine's own candle-close wick check, up
to one candle late.

Drives the real method directly (a proper `LiveBotManager` method, not an
embedded closure) against a stubbed Binance signed-request layer.

Run inside the container::

    docker exec enma_trading_platform-engine-1 pytest /app/tests/test_maybe_amend_exchange_sl.py
"""
import asyncio

import pytest

import services.binance_testnet as binance_mod
from core.live_bot_manager import LiveBotManager
from core.models.base import OrderPlan
from core.position import Position

SYM = "FAKEUSDT"
SID = "sess1"


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class _FakeStrategy:
    def __init__(self, position, stop_loss):
        self.position = position
        self.stop_loss = stop_loss
        # Plan 6 Step 6.3 phase (d3): maybe_amend_exchange_sl() reads
        # active_bracket now, not stop_loss directly — keep this fixture
        # consistent with the fixture's own stop_loss param.
        self.active_bracket = (
            OrderPlan(direction=1, qty=stop_loss[0], entry_price=100.0, stop_loss=stop_loss[1])
            if stop_loss is not None else None
        )
        # 2026-07-24: maybe_amend_exchange_sl() now reads strategy.price to
        # apply enforce_min_trigger_distance — every existing test here uses
        # a stop comfortably outside the 0.15% floor (>=2% from entry), so
        # this default is a no-op for all of them.
        self.price = position.entry_price if position is not None else 100.0


def _session(pos_info):
    return {
        "api_key": "k", "api_secret": "s",
        "open_positions": {SYM: pos_info},
    }


def _long_position(entry=100.0):
    return Position("long", 1.0, entry, leverage=1.0, isolated_wallet=entry)


def test_first_pass_records_baseline_without_amending(monkeypatch):
    """No armed_sl_price recorded yet -> record the current stop as the
    baseline (it's already the entry-time or restored order), don't call
    Binance at all."""
    async def fake_signed(*args, **kwargs):
        raise AssertionError("should not call Binance on the first baseline pass")

    monkeypatch.setattr(binance_mod, "send_signed_request", fake_signed)

    mgr = LiveBotManager()
    pos_info = {"algo_ids": {"sl": "111", "tp": None}}
    session = _session(pos_info)
    strat = _FakeStrategy(_long_position(), stop_loss=(1.0, 95.0))

    _run(mgr._maybe_amend_exchange_sl(session, SID, strat, SYM))

    assert session["open_positions"][SYM]["armed_sl_price"] == "95.0"


def test_long_tighten_cancels_old_and_places_new(monkeypatch):
    """SL moved UP for a long (tighten) -> cancel old algoId, place new,
    update tracked algo_ids + armed_sl_price."""
    calls = {"deleted": [], "posted": []}

    async def fake_signed(method, path, api_key, api_secret, params=None, mode="testnet"):
        if method == "DELETE" and path == "/fapi/v1/algoOrder":
            calls["deleted"].append(params["algoId"])
            return {}
        if method == "POST" and path == "/fapi/v1/algoOrder":
            calls["posted"].append(params["triggerPrice"])
            return {"algoId": "999"}
        raise AssertionError(f"unexpected call {method} {path} {params}")

    monkeypatch.setattr(binance_mod, "send_signed_request", fake_signed)

    mgr = LiveBotManager()
    pos_info = {"algo_ids": {"sl": "111", "tp": "222"}, "armed_sl_price": "95.0"}
    session = _session(pos_info)
    # Tightened from 95.0 -> 98.0 (moved closer to entry=100, still a valid stop for a long)
    strat = _FakeStrategy(_long_position(), stop_loss=(1.0, 98.0))

    _run(mgr._maybe_amend_exchange_sl(session, SID, strat, SYM))

    assert calls["deleted"] == ["111"]
    assert len(calls["posted"]) == 1
    updated = session["open_positions"][SYM]
    assert updated["algo_ids"]["sl"] == "999"
    assert updated["algo_ids"]["tp"] == "222"  # TP leg untouched
    assert float(updated["armed_sl_price"]) == pytest.approx(98.0)


def test_short_tighten_direction_is_downward(monkeypatch):
    """For a short, tightening means the SL moves DOWN (closer to price),
    not up — confirms the comparison is direction-aware, not a blind >."""
    calls = {"posted": []}

    async def fake_signed(method, path, api_key, api_secret, params=None, mode="testnet"):
        if method == "DELETE":
            return {}
        if method == "POST":
            calls["posted"].append(params["triggerPrice"])
            return {"algoId": "999"}
        raise AssertionError

    monkeypatch.setattr(binance_mod, "send_signed_request", fake_signed)

    mgr = LiveBotManager()
    pos_info = {"algo_ids": {"sl": "111"}, "armed_sl_price": "105.0"}
    session = _session(pos_info)
    short_pos = Position("short", 1.0, 100.0, leverage=1.0, isolated_wallet=100.0)
    strat = _FakeStrategy(short_pos, stop_loss=(1.0, 102.0))  # 105 -> 102 is a tighten for a short

    _run(mgr._maybe_amend_exchange_sl(session, SID, strat, SYM))

    assert len(calls["posted"]) == 1


def test_widening_is_never_amended(monkeypatch):
    """A stop that moved AWAY from price (looser, not tighter) must never
    be amended — the risk model's own tightening logic is documented to only
    ever tighten; if something upstream violates that, this method still must
    not push a wider stop to the exchange."""
    async def fake_signed(*args, **kwargs):
        raise AssertionError("should not call Binance for a widening stop")

    monkeypatch.setattr(binance_mod, "send_signed_request", fake_signed)

    mgr = LiveBotManager()
    pos_info = {"algo_ids": {"sl": "111"}, "armed_sl_price": "98.0"}
    session = _session(pos_info)
    strat = _FakeStrategy(_long_position(), stop_loss=(1.0, 95.0))  # 98 -> 95 is WIDER for a long

    _run(mgr._maybe_amend_exchange_sl(session, SID, strat, SYM))

    assert session["open_positions"][SYM]["armed_sl_price"] == "98.0"  # unchanged


def test_unchanged_stop_is_a_noop(monkeypatch):
    async def fake_signed(*args, **kwargs):
        raise AssertionError("should not call Binance when nothing changed")

    monkeypatch.setattr(binance_mod, "send_signed_request", fake_signed)

    mgr = LiveBotManager()
    pos_info = {"algo_ids": {"sl": "111"}, "armed_sl_price": "95.0"}
    session = _session(pos_info)
    strat = _FakeStrategy(_long_position(), stop_loss=(1.0, 95.0))

    _run(mgr._maybe_amend_exchange_sl(session, SID, strat, SYM))
    # No exception, no call — pass.


def test_no_open_position_is_a_noop(monkeypatch):
    async def fake_signed(*args, **kwargs):
        raise AssertionError("should not call Binance with no open position")

    monkeypatch.setattr(binance_mod, "send_signed_request", fake_signed)

    mgr = LiveBotManager()
    session = _session({"algo_ids": {"sl": "111"}, "armed_sl_price": "95.0"})
    strat = _FakeStrategy(position=None, stop_loss=(1.0, 98.0))

    _run(mgr._maybe_amend_exchange_sl(session, SID, strat, SYM))


def test_no_stop_loss_is_a_noop(monkeypatch):
    async def fake_signed(*args, **kwargs):
        raise AssertionError("should not call Binance with no stop_loss set")

    monkeypatch.setattr(binance_mod, "send_signed_request", fake_signed)

    mgr = LiveBotManager()
    session = _session({"algo_ids": {"sl": "111"}, "armed_sl_price": "95.0"})
    strat = _FakeStrategy(_long_position(), stop_loss=None)

    _run(mgr._maybe_amend_exchange_sl(session, SID, strat, SYM))


def test_amend_failure_is_caught_and_leaves_old_tracking_intact(monkeypatch):
    """If the cancel+replace itself fails, the method must not raise (the
    engine-side wick-check remains the fallback), and must not corrupt the
    tracked algo_ids/armed_sl_price with a half-applied change."""
    async def fake_signed(method, path, api_key, api_secret, params=None, mode="testnet"):
        if method == "DELETE":
            return {}
        if method == "POST":
            raise RuntimeError("simulated Binance 500 on SL replace")
        raise AssertionError

    monkeypatch.setattr(binance_mod, "send_signed_request", fake_signed)

    mgr = LiveBotManager()
    pos_info = {"algo_ids": {"sl": "111"}, "armed_sl_price": "95.0"}
    session = _session(pos_info)
    strat = _FakeStrategy(_long_position(), stop_loss=(1.0, 98.0))

    _run(mgr._maybe_amend_exchange_sl(session, SID, strat, SYM))  # must not raise

    # Old tracking stays as-is — no phantom algoId, no wrong armed price.
    assert session["open_positions"][SYM]["algo_ids"]["sl"] == "111"
    assert session["open_positions"][SYM]["armed_sl_price"] == "95.0"
