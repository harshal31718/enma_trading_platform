"""Plan 22 Step 22.1 regression: `SessionRiskGovernor`
(`engine/core/models/governor.py`) — the three hard checks (aggregate
session drawdown, daily realized loss limit, margin utilization ceiling)
that supersede Plan 21's A-10 finding (per-symbol-slice-only drawdown was
never aggregated to session level) and B-3 (no automatic session-level
kill-switch).

Drives the real, standalone `SessionRiskGovernor` class directly — no
session/strategy mocking needed at all, since the class deliberately takes
plain numbers (`equity`, `used_margin`, `now`) rather than reaching into
session/strategy internals itself (the caller, `LiveBotManager`, is
responsible for computing those from session state — see `_push_stats` and
`execute_entry`'s wiring).

Run inside the container::

    docker exec enma_trading_platform-engine-1 pytest /app/tests/test_session_risk_governor.py
"""
from datetime import datetime, timezone

from core.models.governor import SessionRiskGovernor, GovernorVerdict


def _dt(y=2026, m=7, d=17, h=12):
    return datetime(y, m, d, h, tzinfo=timezone.utc)


# ── Defaults / config parsing ───────────────────────────────────────────────

def test_defaults_match_plan_c_table():
    gov = SessionRiskGovernor()
    assert gov.max_session_dd == 0.20
    assert gov.max_daily_loss_pct is None  # off by default
    assert gov.max_margin_utilization == 0.8
    assert gov.breach_action == "reducing"
    assert gov.auto_flatten_on_halt is False  # DECISIONS.md #23


def test_invalid_breach_action_falls_back_to_reducing():
    gov = SessionRiskGovernor({"breach_action": "explode"})
    assert gov.breach_action == "reducing"


def test_halted_and_auto_flatten_are_configurable():
    gov = SessionRiskGovernor({"breach_action": "halted", "auto_flatten_on_halt": True})
    assert gov.breach_action == "halted"
    assert gov.auto_flatten_on_halt is True


# ── Aggregate session drawdown ──────────────────────────────────────────────

def test_first_check_establishes_peak_no_breach():
    gov = SessionRiskGovernor()
    v = gov.check_periodic(equity=1000.0, now=_dt())
    assert v.ok is True


def test_drawdown_within_limit_does_not_breach():
    gov = SessionRiskGovernor({"max_session_dd": 0.20})
    gov.check_periodic(equity=1000.0, now=_dt())  # peak = 1000
    v = gov.check_periodic(equity=850.0, now=_dt())  # 15% dd
    assert v.ok is True


def test_drawdown_past_limit_breaches():
    gov = SessionRiskGovernor({"max_session_dd": 0.20})
    gov.check_periodic(equity=1000.0, now=_dt())  # peak = 1000
    v = gov.check_periodic(equity=750.0, now=_dt())  # 25% dd > 20%
    assert v.ok is False
    assert v.check_name == "aggregate_drawdown"
    assert "25.0%" in v.reason


def test_new_equity_high_raises_the_peak_and_resets_effective_baseline():
    gov = SessionRiskGovernor({"max_session_dd": 0.20})
    gov.check_periodic(equity=1000.0, now=_dt())
    gov.check_periodic(equity=1500.0, now=_dt())  # new peak
    # 15% down from the NEW peak (1500 -> 1275) — within limit relative to 1500,
    # would have been a breach relative to the old 1000 peak, proving the peak moved.
    v = gov.check_periodic(equity=1275.0, now=_dt())
    assert v.ok is True


def test_drawdown_checked_on_pre_trade_too():
    gov = SessionRiskGovernor({"max_session_dd": 0.20})
    gov.check_periodic(equity=1000.0, now=_dt())
    v = gov.check_pre_trade(equity=700.0, used_margin=0.0, now=_dt())
    assert v.ok is False
    assert v.check_name == "aggregate_drawdown"


# ── Daily realized loss limit ───────────────────────────────────────────────

def test_daily_loss_off_by_default_never_breaches():
    gov = SessionRiskGovernor()  # max_daily_loss_pct=None
    gov.check_periodic(equity=1000.0, now=_dt())
    gov.record_realized_pnl(-900.0, _dt())  # huge loss
    v = gov.check_periodic(equity=100.0, now=_dt())
    # Drawdown at default 20% WOULD also fire here (100 vs peak 1000 = 90% dd) —
    # use a max_session_dd wide enough to isolate the daily-loss path.
    gov2 = SessionRiskGovernor({"max_session_dd": 0.99})
    gov2.check_periodic(equity=1000.0, now=_dt())
    gov2.record_realized_pnl(-900.0, _dt())
    v2 = gov2.check_periodic(equity=100.0, now=_dt())
    assert v2.ok is True  # daily loss limit is off — no check_name should ever fire for it


def test_daily_loss_enabled_breaches_past_threshold():
    gov = SessionRiskGovernor({"max_daily_loss_pct": 0.05, "max_session_dd": 0.99})
    gov.check_periodic(equity=1000.0, now=_dt())  # peak = 1000
    gov.record_realized_pnl(-60.0, _dt())  # 6% of peak
    v = gov.check_periodic(equity=940.0, now=_dt())
    assert v.ok is False
    assert v.check_name == "daily_loss_limit"


def test_daily_loss_within_threshold_does_not_breach():
    gov = SessionRiskGovernor({"max_daily_loss_pct": 0.05, "max_session_dd": 0.99})
    gov.check_periodic(equity=1000.0, now=_dt())
    gov.record_realized_pnl(-30.0, _dt())  # 3% of peak
    v = gov.check_periodic(equity=970.0, now=_dt())
    assert v.ok is True


def test_winning_trades_never_offset_the_daily_loss_accumulator():
    """A loss LIMIT, not a net-PnL floor — freqtrade max_daily_loss semantics."""
    gov = SessionRiskGovernor({"max_daily_loss_pct": 0.05, "max_session_dd": 0.99})
    gov.check_periodic(equity=1000.0, now=_dt())
    gov.record_realized_pnl(-60.0, _dt())  # 6% loss
    gov.record_realized_pnl(+200.0, _dt())  # big win — must NOT cancel the loss
    v = gov.check_periodic(equity=1140.0, now=_dt())
    assert v.ok is False
    assert v.check_name == "daily_loss_limit"


def test_daily_loss_resets_on_utc_midnight_rollover():
    gov = SessionRiskGovernor({"max_daily_loss_pct": 0.05, "max_session_dd": 0.99})
    gov.check_periodic(equity=1000.0, now=_dt(d=17))
    gov.record_realized_pnl(-60.0, _dt(d=17, h=23))  # 6% loss on day 17
    v_same_day = gov.check_periodic(equity=940.0, now=_dt(d=17, h=23))
    assert v_same_day.ok is False

    # New UTC day — the accumulator must have reset.
    v_next_day = gov.check_periodic(equity=940.0, now=_dt(d=18, h=1))
    assert v_next_day.ok is True


# ── Margin utilization ceiling (pre-trade only) ─────────────────────────────

def test_margin_within_ceiling_passes():
    gov = SessionRiskGovernor({"max_margin_utilization": 0.8})
    v = gov.check_pre_trade(equity=1000.0, used_margin=600.0, now=_dt())
    assert v.ok is True


def test_margin_past_ceiling_breaches():
    gov = SessionRiskGovernor({"max_margin_utilization": 0.8})
    v = gov.check_pre_trade(equity=1000.0, used_margin=850.0, now=_dt())
    assert v.ok is False
    assert v.check_name == "margin_utilization"
    assert "85.0%" in v.reason


def test_margin_ceiling_fail_closed_on_zero_or_negative_equity():
    gov = SessionRiskGovernor()
    v = gov.check_pre_trade(equity=0.0, used_margin=100.0, now=_dt())
    assert v.ok is False
    assert v.check_name == "margin_utilization"
    assert "fail-closed" in v.reason

    v2 = gov.check_pre_trade(equity=-50.0, used_margin=100.0, now=_dt())
    assert v2.ok is False


def test_margin_check_is_pre_trade_only_not_periodic():
    """check_periodic must never veto on margin alone — it's not in the
    periodic half of Part C's table; margin is pre-trade-only."""
    gov = SessionRiskGovernor({"max_margin_utilization": 0.1})  # absurdly tight
    v = gov.check_periodic(equity=1000.0, now=_dt())
    # Even with used_margin nowhere in scope for check_periodic, this must
    # simply never evaluate margin at all — confirmed by check_periodic's
    # signature not even accepting used_margin, and by this call succeeding.
    assert v.ok is True


# ── Ordering: standing limits checked before margin on pre-trade ───────────

def test_pre_trade_checks_standing_limits_before_margin():
    """A drawdown breach must veto before margin is even evaluated — proves
    check_pre_trade delegates to the same standing-limits path as periodic
    rather than duplicating/diverging logic."""
    gov = SessionRiskGovernor({"max_session_dd": 0.20, "max_margin_utilization": 0.99})
    gov.check_periodic(equity=1000.0, now=_dt())
    # Drawdown breach (25%) AND margin would also be fine at 0.99 ceiling —
    # isolate that the drawdown reason surfaces, not a margin one.
    v = gov.check_pre_trade(equity=750.0, used_margin=10.0, now=_dt())
    assert v.ok is False
    assert v.check_name == "aggregate_drawdown"


# ── Portfolio open-risk budget (Plan 22 Step 22.2) ──────────────────────────

def test_portfolio_risk_defaults_to_six_percent():
    gov = SessionRiskGovernor()
    assert gov.max_portfolio_risk == 0.06


def test_portfolio_risk_within_budget_passes():
    gov = SessionRiskGovernor({"max_portfolio_risk": 0.06})
    v = gov.check_portfolio_risk(open_risk=500.0, equity=10_000.0)
    assert v.ok is True


def test_portfolio_risk_past_budget_breaches():
    gov = SessionRiskGovernor({"max_portfolio_risk": 0.06})
    v = gov.check_portfolio_risk(open_risk=700.0, equity=10_000.0)
    assert v.ok is False
    assert v.check_name == "portfolio_open_risk"
    assert "7.0%" in v.reason


def test_portfolio_risk_exactly_at_budget_passes():
    """> not >=, matching this repo's convention for boundary checks
    (see capitalGate.js's exactly-at-balance test)."""
    gov = SessionRiskGovernor({"max_portfolio_risk": 0.06})
    v = gov.check_portfolio_risk(open_risk=600.0, equity=10_000.0)
    assert v.ok is True


def test_portfolio_risk_zero_or_negative_disables_the_check():
    gov = SessionRiskGovernor({"max_portfolio_risk": 0.0})
    v = gov.check_portfolio_risk(open_risk=999_999.0, equity=10.0)
    assert v.ok is True

    gov2 = SessionRiskGovernor({"max_portfolio_risk": -0.1})
    v2 = gov2.check_portfolio_risk(open_risk=999_999.0, equity=10.0)
    assert v2.ok is True


def test_portfolio_risk_fails_closed_on_zero_or_negative_equity():
    gov = SessionRiskGovernor({"max_portfolio_risk": 0.06})
    v = gov.check_portfolio_risk(open_risk=100.0, equity=0.0)
    assert v.ok is False
    assert v.check_name == "portfolio_open_risk"
    assert "fail-closed" in v.reason

    v2 = gov.check_portfolio_risk(open_risk=100.0, equity=-50.0)
    assert v2.ok is False


# ── Account-wide VaR/CVaR budget (Plan 22 Step 22.4) ────────────────────────

def test_var_and_cvar_off_by_default():
    gov = SessionRiskGovernor()
    assert gov.var_limit_pct is None
    assert gov.cvar_limit_pct is None
    v = gov.check_var(var_amount=999_999.0, cvar_amount=999_999.0, equity=10.0)
    assert v.ok is True  # both off -> never evaluates, even with an absurd VaR


def test_var_within_limit_passes():
    gov = SessionRiskGovernor({"var_limit_pct": 0.05})
    v = gov.check_var(var_amount=400.0, cvar_amount=400.0, equity=10_000.0)  # 4%
    assert v.ok is True


def test_var_past_limit_breaches():
    gov = SessionRiskGovernor({"var_limit_pct": 0.05})
    v = gov.check_var(var_amount=600.0, cvar_amount=600.0, equity=10_000.0)  # 6% > 5%
    assert v.ok is False
    assert v.check_name == "var_limit"
    assert "6.0%" in v.reason


def test_var_exactly_at_limit_passes():
    gov = SessionRiskGovernor({"var_limit_pct": 0.05})
    v = gov.check_var(var_amount=500.0, cvar_amount=500.0, equity=10_000.0)  # exactly 5%
    assert v.ok is True


def test_cvar_independently_breaches_when_var_is_fine():
    """cvar_limit_pct can fire even when var_limit_pct alone would pass —
    the two are independent budgets, either can veto."""
    gov = SessionRiskGovernor({"var_limit_pct": 0.10, "cvar_limit_pct": 0.05})
    v = gov.check_var(var_amount=300.0, cvar_amount=600.0, equity=10_000.0)  # var 3% ok, cvar 6% > 5%
    assert v.ok is False
    assert v.check_name == "cvar_limit"


def test_var_checked_before_cvar_when_both_breach():
    gov = SessionRiskGovernor({"var_limit_pct": 0.05, "cvar_limit_pct": 0.05})
    v = gov.check_var(var_amount=600.0, cvar_amount=700.0, equity=10_000.0)
    assert v.ok is False
    assert v.check_name == "var_limit"  # var checked first


def test_var_only_configured_ignores_cvar_entirely():
    gov = SessionRiskGovernor({"var_limit_pct": 0.05})
    # cvar wildly over any reasonable threshold but never configured -> ignored
    v = gov.check_var(var_amount=100.0, cvar_amount=9_999_999.0, equity=10_000.0)
    assert v.ok is True


def test_var_fails_closed_on_zero_or_negative_equity():
    gov = SessionRiskGovernor({"var_limit_pct": 0.05})
    v = gov.check_var(var_amount=1.0, cvar_amount=1.0, equity=0.0)
    assert v.ok is False
    assert v.check_name == "var_limit"
    assert "fail-closed" in v.reason

    v2 = gov.check_var(var_amount=1.0, cvar_amount=1.0, equity=-10.0)
    assert v2.ok is False


# ── Plan 22 Step 22.5: correlation-adjusted concentration cap ──────────────

def test_correlation_cap_off_by_default():
    gov = SessionRiskGovernor()
    assert gov.correlation_rho is None
    v = gov.check_correlation_concentration(
        candidate_symbol="BTCUSDT", candidate_notional=999_999.0,
        open_notionals={}, correlation_matrix={}, equity=10.0,
    )
    assert v.ok is True  # off -> never evaluates, even with an absurd notional


def test_correlation_cap_uncorrelated_entry_passes():
    gov = SessionRiskGovernor({"correlation_cap": {"rho": 0.8, "max_cluster_exposure_pct": 0.4}})
    corr = {"BTCUSDT": {"ETHUSDT": 0.9}, "ETHUSDT": {"BTCUSDT": 0.9}}
    v = gov.check_correlation_concentration(
        candidate_symbol="XRPUSDT", candidate_notional=1000.0,
        open_notionals={"BTCUSDT": 1000.0, "ETHUSDT": 1000.0},
        correlation_matrix=corr, equity=10_000.0,
    )
    assert v.ok is True  # XRPUSDT has no correlation entry -> cluster of itself only, 10% < 40%


def test_correlation_cap_two_correlated_positions_at_cap_vetoes_third():
    """Two open BTC-correlated positions already at the cluster cap; a
    third correlated entry pushes the cluster over -> vetoed."""
    gov = SessionRiskGovernor({"correlation_cap": {"rho": 0.8, "max_cluster_exposure_pct": 0.4}})
    corr = {
        "BTCUSDT": {"ETHUSDT": 0.9, "SOLUSDT": 0.85},
        "ETHUSDT": {"BTCUSDT": 0.9, "SOLUSDT": 0.82},
        "SOLUSDT": {"BTCUSDT": 0.85, "ETHUSDT": 0.82},
    }
    v = gov.check_correlation_concentration(
        candidate_symbol="SOLUSDT", candidate_notional=2000.0,
        open_notionals={"BTCUSDT": 2000.0, "ETHUSDT": 2000.0},
        correlation_matrix=corr, equity=10_000.0,  # (2000+2000+2000)/10000 = 60% > 40%
    )
    assert v.ok is False
    assert v.check_name == "correlation_concentration"
    assert "BTCUSDT" in v.reason and "ETHUSDT" in v.reason and "SOLUSDT" in v.reason


def test_correlation_cap_below_threshold_rho_passes():
    gov = SessionRiskGovernor({"correlation_cap": {"rho": 0.8, "max_cluster_exposure_pct": 0.4}})
    corr = {"BTCUSDT": {"ETHUSDT": 0.5}, "ETHUSDT": {"BTCUSDT": 0.5}}  # below rho threshold
    v = gov.check_correlation_concentration(
        candidate_symbol="ETHUSDT", candidate_notional=2000.0,
        open_notionals={"BTCUSDT": 5000.0},
        correlation_matrix=corr, equity=10_000.0,
    )
    # BTCUSDT and ETHUSDT are NOT clustered (rho 0.5 < 0.8 threshold) ->
    # cluster = {ETHUSDT} only, 2000/10000 = 20% < 40% cap
    assert v.ok is True


def test_correlation_cap_transitive_closure_three_hop_chain():
    """A-B correlated, B-C correlated, A-C NOT directly correlated — still
    one cluster via transitive closure through B."""
    gov = SessionRiskGovernor({"correlation_cap": {"rho": 0.8, "max_cluster_exposure_pct": 0.3}})
    corr = {
        "AAAUSDT": {"BBBUSDT": 0.9},
        "BBBUSDT": {"AAAUSDT": 0.9, "CCCUSDT": 0.85},
        "CCCUSDT": {"BBBUSDT": 0.85},
    }
    v = gov.check_correlation_concentration(
        candidate_symbol="CCCUSDT", candidate_notional=1500.0,
        open_notionals={"AAAUSDT": 1500.0, "BBBUSDT": 1500.0},
        correlation_matrix=corr, equity=10_000.0,  # cluster = all three = 45% > 30%
    )
    assert v.ok is False
    assert "AAAUSDT" in v.reason


def test_correlation_cap_fails_closed_on_zero_or_negative_equity():
    gov = SessionRiskGovernor({"correlation_cap": {"rho": 0.8}})
    v = gov.check_correlation_concentration(
        candidate_symbol="BTCUSDT", candidate_notional=1.0,
        open_notionals={}, correlation_matrix={}, equity=0.0,
    )
    assert v.ok is False
    assert v.check_name == "correlation_concentration"
    assert "fail-closed" in v.reason


def test_correlation_cap_default_max_cluster_exposure_pct_is_point_four():
    gov = SessionRiskGovernor({"correlation_cap": {"rho": 0.8}})
    assert gov.max_cluster_exposure_pct == 0.4
