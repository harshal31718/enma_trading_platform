"""Plan 21 Step 21.7 (A-14) regression: `LiveAdapter.execute_entry()` now
measures and logs slippage between the closed-candle `ref_price` used to
size/route the entry and the real Binance fill — previously never measured
at all (audit: "no max-deviation check between ref_price and fill... log
slippage per fill"). Below `_SLIPPAGE_ALERT_THRESHOLD_PCT` (1%) it's a
routine `info` log; at/above it, a `warning` log plus a session `log`
notification fires so an abnormal fill is visible instead of silent.

This is observability-only — it never rejects or alters the entry, matching
the audit's own "low urgency on testnet; required before mainnet" framing.
No golden-master re-baseline needed (logging-only, no output change).

Drives the real `LiveAdapter.execute_entry` directly against a stubbed
Binance signed-request layer, same harness as
`test_execute_entry_bracket_safety.py`.

Run inside the container::

    docker exec enma_trading_platform-engine-1 pytest /app/tests/test_execute_entry_slippage_log.py
"""
import asyncio
import logging
from datetime import datetime, timezone

import pytest

import services.binance_testnet as binance_mod
import core.live_bot_manager as lbm_module
from core.live_bot_manager import LiveBotManager, LiveAdapter

SYM = "FAKEUSDT"


class _FakeExecutionModel:
    def exit_fee(self, strategy, qty, price):
        return abs(qty) * price * 0.0005


class _FakeStrategy:
    def __init__(self):
        self.position = None
        self.stop_loss = None
        self.take_profit = None
        self.buy = 1.0
        self.sell = None
        self.entry_tag = ""
        self.exit_tag = ""
        self.execution_model = _FakeExecutionModel()
        self.balance = 1000.0
        self.leverage = 1


def _make_session():
    return {
        "open_positions": {},
        "pnl": 0.0, "strategy_name": "X", "api_key": "k", "api_secret": "s", "user_id": "",
        "trading_state": "active",
    }


class _Notified:
    def __init__(self):
        self.calls = []

    async def __call__(self, session_id, payload):
        self.calls.append(payload)


@pytest.fixture(autouse=True)
def _stub_side_effects(monkeypatch):
    async def _noop_record_trade(*args, **kwargs):
        return None
    monkeypatch.setattr(lbm_module, "record_trade", _noop_record_trade)

    async def _noop_append_event(*args, **kwargs):
        return 1
    monkeypatch.setattr(lbm_module, "append_event", _noop_append_event)


def _run_entry(adapter, strat, ref_price, fill_avg_price, monkeypatch):
    async def fake_signed(method, path, api_key, api_secret, params=None, mode="testnet"):
        if method == "POST" and path == "/fapi/v1/order":
            return {"orderId": 1, "avgPrice": str(fill_avg_price), "status": "FILLED"}
        raise AssertionError(f"unexpected call {method} {path} {params}")
    monkeypatch.setattr(binance_mod, "send_signed_request", fake_signed)

    return asyncio.get_event_loop().run_until_complete(adapter.execute_entry(
        strategy=strat, symbol=SYM, direction="long", qty=1.0, ref_price=ref_price,
        time_t=datetime.now(timezone.utc), index_t=0,
    ))


def _make_mgr_adapter(monkeypatch, notified=None):
    mgr = LiveBotManager()
    sid = "sess_entry_slippage"
    mgr.sessions[sid] = _make_session()
    monkeypatch.setattr(mgr._notifier, "notify", notified or _Notified())
    return mgr, LiveAdapter(mgr, sid)


def test_small_slippage_logs_info_only_no_alert(monkeypatch, caplog):
    notified = _Notified()
    mgr, adapter = _make_mgr_adapter(monkeypatch, notified)
    strat = _FakeStrategy()

    with caplog.at_level(logging.INFO, logger="core.live_bot_manager"):
        ok = _run_entry(adapter, strat, ref_price=100.0, fill_avg_price=100.2, monkeypatch=monkeypatch)  # 0.2%

    assert ok is True
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING and "slippage" in r.message]
    assert len(warnings) == 0
    info_lines = [r for r in caplog.records if r.levelno == logging.INFO and "slippage" in r.message]
    assert len(info_lines) == 1
    # No session-log alert notification for routine slippage.
    slippage_alerts = [c for c in notified.calls if c.get("event") == "log" and "slippage" in c.get("eventData", {}).get("message", "")]
    assert len(slippage_alerts) == 0


def test_large_slippage_logs_warning_and_alerts(monkeypatch, caplog):
    notified = _Notified()
    mgr, adapter = _make_mgr_adapter(monkeypatch, notified)
    strat = _FakeStrategy()

    with caplog.at_level(logging.INFO, logger="core.live_bot_manager"):
        ok = _run_entry(adapter, strat, ref_price=100.0, fill_avg_price=102.0, monkeypatch=monkeypatch)  # 2%

    assert ok is True
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING and "slippage" in r.message]
    assert len(warnings) == 1
    assert "2.00%" in warnings[0].message
    slippage_alerts = [
        c for c in notified.calls
        if c.get("event") == "log" and "slippage" in c.get("eventData", {}).get("message", "")
    ]
    assert len(slippage_alerts) == 1
    assert slippage_alerts[0]["eventData"]["type"] == "warning"


def test_negative_slippage_direction_also_measured(monkeypatch, caplog):
    """A fill BETTER than ref (fills below ref on a long) is still slippage
    in magnitude terms — the guard measures |fill-ref|/ref, not a one-sided
    adverse-only check, so a large favorable gap is flagged too (it's just as
    informative — the fill is not tracking ref for some reason)."""
    notified = _Notified()
    mgr, adapter = _make_mgr_adapter(monkeypatch, notified)
    strat = _FakeStrategy()

    ok = _run_entry(adapter, strat, ref_price=100.0, fill_avg_price=97.0, monkeypatch=monkeypatch)  # -3%

    assert ok is True
    slippage_alerts = [
        c for c in notified.calls
        if c.get("event") == "log" and "slippage" in c.get("eventData", {}).get("message", "")
    ]
    assert len(slippage_alerts) == 1
    assert "3.00%" in slippage_alerts[0]["eventData"]["message"]
