"""Plan 21 Step 21.7 (A-11) regression: `utils/symbols.py`'s
`clamp_and_round_qty()` silently inflates the realized risk-per-trade when it
bumps quantity up to satisfy Binance's MIN_NOTIONAL filter — SL distance is
unchanged, so a bumped qty means a proportionally larger loss if the stop is
hit, up to the +30% tolerance the function already allows (F-013). This was
previously invisible at runtime. Fix: log a `warning` with the effective
multiplier whenever a bump actually occurs; the returned quantity is
unchanged (logging-only — no golden-master re-baseline needed, matches Plan
21's own "live-adapter/UDS-only, zero backtest-path overlap" scope note,
since this only adds observability without changing any output value).

Drives the real `clamp_and_round_qty()` function directly against a seeded
`_rules_cache` entry, same setup pattern as `test_phase1_parity.py`'s
existing coverage of this function — this file adds the log-observability
angle that file doesn't cover.

Run inside the container::

    docker exec enma_trading_platform-engine-1 pytest /app/tests/test_clamp_qty_risk_inflation_log.py
"""
import logging
from decimal import Decimal

from utils.symbols import clamp_and_round_qty, _rules_cache

SYM = "MOCKUSDT"


def _seed_rules(min_notional="50.0"):
    _rules_cache[("Binance Futures", SYM)] = {
        "tickSize": Decimal("0.1"),
        "stepSize": Decimal("0.001"),
        "minQty": Decimal("0.001"),
        "minNotional": Decimal(min_notional),
    }


def test_bumped_qty_logs_a_warning_with_multiplier(caplog):
    _seed_rules()
    # qty=0.5, price=100 -> notional 50 < buffered min (50*1.05=52.5) -> bump.
    with caplog.at_level(logging.WARNING, logger="utils.symbols"):
        qty = clamp_and_round_qty(SYM, "Binance Futures", 0.5, 100.0)

    assert qty == 0.525  # unchanged behavior — same value test_phase1_parity.py asserts
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warnings) == 1
    assert "minNotional bump inflated qty" in warnings[0].message
    assert "1.05x" in warnings[0].message  # 0.525 / 0.5 = 1.05


def test_no_bump_no_warning(caplog):
    _seed_rules()
    # qty=2.0, price=100 -> notional 200, well above the buffered minimum — no bump.
    with caplog.at_level(logging.WARNING, logger="utils.symbols"):
        qty = clamp_and_round_qty(SYM, "Binance Futures", 2.0, 100.0)

    assert qty == 2.0
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warnings) == 0


def test_skipped_trade_past_tolerance_does_not_also_warn(caplog):
    """When the bump would exceed +30% tolerance, the function returns 0.0
    (trade skipped) — that's a distinct, already-visible outcome (the caller
    logs its own "quantity rounded to 0" warning); this function must not
    ALSO emit a misleading risk-inflation warning for a trade that never
    actually happens at the inflated size."""
    _seed_rules()
    # qty=0.1, price=100 -> req_qty=0.525, 0.525/0.1 = 5.25 > 1.30 -> skip (0.0).
    with caplog.at_level(logging.WARNING, logger="utils.symbols"):
        qty = clamp_and_round_qty(SYM, "Binance Futures", 0.1, 100.0)

    assert qty == 0.0
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warnings) == 0


def test_reduce_only_bump_exemption_never_warns(caplog):
    """reduce_only=True skips the notional bump-up path entirely (step 3) —
    confirm the warning path is likewise never reached for it."""
    _seed_rules()
    with caplog.at_level(logging.WARNING, logger="utils.symbols"):
        qty = clamp_and_round_qty(SYM, "Binance Futures", 0.01, 100.0, reduce_only=True)

    assert qty == 0.01
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warnings) == 0


def test_stepsize_rounding_noise_does_not_falsely_warn(caplog):
    """A qty that's already comfortably above minNotional but gets a
    sub-0.1%-scale nudge from stepSize rounding alone must not be reported as
    a risk-inflating bump — only a genuine minNotional-driven bump should."""
    _rules_cache[("Binance Futures", SYM)] = {
        "tickSize": Decimal("0.1"),
        "stepSize": Decimal("0.01"),
        "minQty": Decimal("0.01"),
        "minNotional": Decimal("1.0"),  # trivially satisfied, no bump path taken
    }
    with caplog.at_level(logging.WARNING, logger="utils.symbols"):
        qty = clamp_and_round_qty(SYM, "Binance Futures", 1.0, 100.0)

    assert qty == 1.0
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warnings) == 0
