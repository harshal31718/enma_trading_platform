"""Plan 22 Step 22.3 regression: `MaxDrawdownProtection` and
`LowProfitPairsProtection` (`engine/core/models/protections.py`) — the two
new protections added for freqtrade parity, plus `ProtectionManager.
record_trade_close`'s dispatch to them (every close, not just stoplosses).

`core/models/protections.py` has zero external dependencies (no numpy/
TA-Lib/motor chain), so this drives the real classes directly with real
pytest — no stubbing needed, unlike the live_bot_manager.py-touching test
files elsewhere in this suite.

Run inside the container::

    docker exec enma_trading_platform-engine-1 pytest /app/tests/test_protections_max_drawdown_low_profit.py
"""
from datetime import datetime, timezone

from core.models.protections import (
    MaxDrawdownProtection,
    LowProfitPairsProtection,
    ProtectionManager,
    CooldownPeriod,
    StoplossGuard,
)


def _dt(offset_seconds=0):
    return datetime.now(timezone.utc)


def _ts(offset_seconds=0.0):
    return datetime.now(timezone.utc).timestamp() + offset_seconds


# ── MaxDrawdownProtection ────────────────────────────────────────────────────

def test_max_drawdown_no_trades_never_locks():
    prot = MaxDrawdownProtection({"max_allowed_drawdown": 0.2, "trade_limit": 2})
    assert prot.global_stop(_dt(), "*", 1000.0) is None


def test_max_drawdown_below_trade_limit_does_not_evaluate():
    prot = MaxDrawdownProtection({"max_allowed_drawdown": 0.2, "trade_limit": 3})
    now = _ts()
    prot.record_trade("BTCUSDT", -500.0, now)  # a single huge loss
    assert prot.global_stop(_dt(), "*", 1000.0) is None


def test_max_drawdown_within_limit_does_not_lock():
    prot = MaxDrawdownProtection({"max_allowed_drawdown": 0.2, "trade_limit": 2})
    now = _ts()
    prot.record_trade("BTCUSDT", -50.0, now)
    prot.record_trade("ETHUSDT", 20.0, now + 1)
    # Equity: 1000 -> 950 (5% dd from peak 1000) -> 970. Never > 20%.
    result = prot.global_stop(_dt(), "*", 1000.0)
    assert result is None


def test_max_drawdown_past_limit_locks_globally():
    prot = MaxDrawdownProtection({"max_allowed_drawdown": 0.2, "trade_limit": 2, "stop_duration": 30})
    now = _ts()
    prot.record_trade("BTCUSDT", -300.0, now)
    prot.record_trade("ETHUSDT", -100.0, now + 1)
    # 1000 -> 700 -> 600 = 40% dd from peak 1000, past 20%.
    result = prot.global_stop(_dt(), "*", 1000.0)
    assert result is not None
    assert result.lock is True
    assert result.is_active is True
    assert "40.0%" in result.reason


def test_max_drawdown_ignores_trades_outside_lookback():
    prot = MaxDrawdownProtection({"max_allowed_drawdown": 0.2, "trade_limit": 2, "lookback_period": 5})
    now = _ts()
    stale = now - (10 * 60)  # 10 min ago, outside a 5-min lookback
    prot.record_trade("BTCUSDT", -900.0, stale)
    prot.record_trade("ETHUSDT", -10.0, now)
    # Only one trade is inside the window -> below trade_limit=2 -> no evaluation.
    assert prot.global_stop(_dt(), "*", 1000.0) is None


def test_max_drawdown_never_has_a_local_stop():
    """Global-only, matching freqtrade's own MaxDrawdownProtection."""
    prot = MaxDrawdownProtection()
    assert prot.has_local_stop is False
    assert prot.stop_per_pair("BTCUSDT", _dt(), "*", 1000.0) is None


def test_max_drawdown_new_equity_high_resets_the_effective_peak():
    prot = MaxDrawdownProtection({"max_allowed_drawdown": 0.2, "trade_limit": 2})
    now = _ts()
    prot.record_trade("BTCUSDT", 500.0, now)       # 1000 -> 1500, new peak
    prot.record_trade("ETHUSDT", -200.0, now + 1)  # 1500 -> 1300 = 13.3% dd from 1500
    result = prot.global_stop(_dt(), "*", 1000.0)
    assert result is None


# ── LowProfitPairsProtection ─────────────────────────────────────────────────

def test_low_profit_pairs_no_trades_never_locks():
    prot = LowProfitPairsProtection({"required_profit": 0.0, "trade_limit": 2})
    assert prot.stop_per_pair("BTCUSDT", _dt(), "*", 1000.0) is None


def test_low_profit_pairs_below_trade_limit_does_not_evaluate():
    prot = LowProfitPairsProtection({"required_profit": 0.0, "trade_limit": 3})
    prot.record_trade("BTCUSDT", -100.0, _ts())
    assert prot.stop_per_pair("BTCUSDT", _dt(), "*", 1000.0) is None


def test_low_profit_pairs_summed_profit_below_threshold_locks():
    prot = LowProfitPairsProtection({"required_profit": 0.0, "trade_limit": 2, "stop_duration": 45})
    now = _ts()
    prot.record_trade("BTCUSDT", -30.0, now)
    prot.record_trade("BTCUSDT", -10.0, now + 1)  # summed -40 < 0
    result = prot.stop_per_pair("BTCUSDT", _dt(), "*", 1000.0)
    assert result is not None
    assert result.lock is True
    assert "BTCUSDT" in result.reason
    assert "-40.00" in result.reason


def test_low_profit_pairs_summed_profit_meets_threshold_does_not_lock():
    prot = LowProfitPairsProtection({"required_profit": 0.0, "trade_limit": 2})
    now = _ts()
    prot.record_trade("BTCUSDT", -10.0, now)
    prot.record_trade("BTCUSDT", 20.0, now + 1)  # summed +10 >= 0
    assert prot.stop_per_pair("BTCUSDT", _dt(), "*", 1000.0) is None


def test_low_profit_pairs_is_scoped_per_pair_not_session_wide():
    prot = LowProfitPairsProtection({"required_profit": 0.0, "trade_limit": 2})
    now = _ts()
    prot.record_trade("BTCUSDT", -50.0, now)
    prot.record_trade("BTCUSDT", -50.0, now + 1)  # BTCUSDT summed -100
    prot.record_trade("ETHUSDT", 30.0, now + 2)
    prot.record_trade("ETHUSDT", 30.0, now + 3)   # ETHUSDT summed +60

    btc_result = prot.stop_per_pair("BTCUSDT", _dt(), "*", 1000.0)
    eth_result = prot.stop_per_pair("ETHUSDT", _dt(), "*", 1000.0)

    assert btc_result is not None
    assert eth_result is None


def test_low_profit_pairs_never_has_a_global_stop():
    """Per-pair-only, matching freqtrade's own LowProfitPairsProtection."""
    prot = LowProfitPairsProtection()
    assert prot.has_global_stop is False
    assert prot.global_stop(_dt(), "*", 1000.0) is None


def test_low_profit_pairs_ignores_trades_outside_lookback():
    prot = LowProfitPairsProtection({"required_profit": 0.0, "trade_limit": 1, "lookback_period": 5})
    stale = _ts(-10 * 60)
    prot.record_trade("BTCUSDT", -500.0, stale)
    assert prot.stop_per_pair("BTCUSDT", _dt(), "*", 1000.0) is None


# ── ProtectionManager dispatch (record_trade_close feeds every protection) ──

def test_record_trade_close_feeds_max_drawdown_and_low_profit_on_every_close():
    """Even a WINNING close (not a stoploss) must reach both new protections
    — they need the full realized-PnL picture, not just losses."""
    mgr = ProtectionManager()
    max_dd = MaxDrawdownProtection({"max_allowed_drawdown": 0.01, "trade_limit": 1})
    low_profit = LowProfitPairsProtection({"required_profit": 100.0, "trade_limit": 1})
    mgr.add(max_dd)
    mgr.add(low_profit)

    # A "take_profit" close — NOT in StoplossGuard's tracked exit_reason set,
    # but must still reach both new protections since record_trade_close
    # dispatches to them unconditionally.
    mgr.record_trade_close(
        pair="BTCUSDT", side="long", exit_reason="take_profit",
        profit=5.0, close_timestamp=_ts(),
    )

    assert len(max_dd._trade_events) == 1
    assert len(low_profit._trade_events) == 1
    # required_profit=100 > the single +5 trade -> low_profit protection fires.
    assert low_profit.stop_per_pair("BTCUSDT", _dt(), "*", 1000.0) is not None


def test_record_trade_close_still_feeds_stoploss_guard_and_cooldown_as_before():
    """Regression: adding the two new dispatch branches must not disturb the
    existing CooldownPeriod/StoplossGuard wiring."""
    mgr = ProtectionManager()
    cooldown = CooldownPeriod({"stop_duration": 30})
    guard = StoplossGuard({"trade_limit": 1})
    mgr.add(cooldown)
    mgr.add(guard)

    mgr.record_trade_close(
        pair="BTCUSDT", side="long", exit_reason="stop_loss",
        profit=-20.0, close_timestamp=_ts(),
    )

    assert cooldown._pair_last_close.get("BTCUSDT") is not None
    assert len(guard._stoploss_events) == 1
    result = guard.stop_per_pair("BTCUSDT", _dt(), "long", 1000.0)
    assert result is not None
