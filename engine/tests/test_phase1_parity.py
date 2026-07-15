import pytest
from decimal import ROUND_DOWN, ROUND_UP
from utils.symbols import round_price, clamp_and_round_qty, _rules_cache, Decimal

def test_direction_aware_price_rounding() -> None:
    # Seed rules cache for a mock symbol
    _rules_cache[("Binance Futures", "MOCKUSDT")] = {
        "tickSize": Decimal("0.01"),
        "stepSize": Decimal("0.1"),
        "minQty": Decimal("0.1"),
        "minNotional": Decimal("5.0"),
    }
    
    # ROUND_DOWN mode (default or long SL/TP)
    assert round_price("MOCKUSDT", "Binance Futures", 1.234, rounding=ROUND_DOWN) == 1.23
    assert round_price("MOCKUSDT", "Binance Futures", 1.239, rounding=ROUND_DOWN) == 1.23

    # ROUND_UP mode (short SL/TP)
    assert round_price("MOCKUSDT", "Binance Futures", 1.231, rounding=ROUND_UP) == 1.24
    assert round_price("MOCKUSDT", "Binance Futures", 1.239, rounding=ROUND_UP) == 1.24

def test_clamp_and_round_qty_reserve_and_tolerance() -> None:
    # rules cache for mock symbol: minNotional = 50.0
    _rules_cache[("Binance Futures", "MOCKUSDT")] = {
        "tickSize": Decimal("0.1"),
        "stepSize": Decimal("0.001"),
        "minQty": Decimal("0.001"),
        "minNotional": Decimal("50.0"),
    }
    
    # 1. No bump needed: large quantity
    # qty = 2.0, price = 100.0, notional = 200.0 > 50 * 1.05 = 52.5
    qty1 = clamp_and_round_qty("MOCKUSDT", "Binance Futures", 2.0, 100.0)
    assert qty1 == 2.0
    
    # 2. Bump needed, within tolerance:
    # qty = 0.5, price = 100.0, target notional = 50.0.
    # minNotional = 50.0, reserve_factor = 1.05. Buffered min notional = 52.5.
    # req_qty = 52.5 / 100.0 = 0.525.
    # 0.525 / 0.5 = 1.05 <= 1.30 (within +30% tolerance).
    qty2 = clamp_and_round_qty("MOCKUSDT", "Binance Futures", 0.5, 100.0)
    assert qty2 == 0.525
    
    # 3. Bump needed, exceeds tolerance (skip):
    # qty = 0.1, price = 100.0, target notional = 10.0.
    # minNotional = 50.0, reserve_factor = 1.05. Buffered min notional = 52.5.
    # req_qty = 52.5 / 100 = 0.525.
    # 0.525 / 0.1 = 5.25 > 1.30 (exceeds tolerance).
    # Expected: return 0.0 (skip).
    qty3 = clamp_and_round_qty("MOCKUSDT", "Binance Futures", 0.1, 100.0)
    assert qty3 == 0.0

    # 4. Stop loss reserve adjustment:
    # stop_loss_pct = 10% (0.10)
    # reserve_factor = 1.05 / 0.90 = 1.1666...
    # minNotional = 50.0. Buffered min notional = 50.0 * 1.1666... = 58.333...
    # For target qty = 0.55, price = 100.0, target notional = 55.0.
    # req_qty = 58.333... / 100 = 0.584 (rounded up to 0.001 stepSize).
    # 0.584 / 0.55 = 1.06 <= 1.30 (within tolerance).
    qty4 = clamp_and_round_qty("MOCKUSDT", "Binance Futures", 0.55, 100.0, stop_loss_pct=0.10)
    assert qty4 == 0.584


def test_clamp_and_round_qty_reduce_only_floors_without_notional_bump() -> None:
    """Plan 5 Step 5.3 / Plan 20 (ENG-10): reduceOnly orders are exempt from
    Binance's MIN_NOTIONAL filter (error -4164's own message says so) but
    NOT from stepSize alignment (-4023/-1111). reduce_only=True must floor
    to stepSize/minQty and skip the notional bump-up and tolerance abort
    entirely — a reduce should shrink, never grow, what the strategy asked for."""
    _rules_cache[("Binance Futures", "MOCKUSDT")] = {
        "tickSize": Decimal("0.1"),
        "stepSize": Decimal("0.001"),
        "minQty": Decimal("0.001"),
        "minNotional": Decimal("50.0"),
    }

    # A tiny reduce (notional=1.0, far below minNotional=50.0) must NOT be
    # bumped up or skipped — reduceOnly is exempt from MIN_NOTIONAL.
    qty = clamp_and_round_qty("MOCKUSDT", "Binance Futures", 0.01, 100.0, reduce_only=True)
    assert qty == 0.01  # floored to stepSize (already aligned), not bumped, not skipped

    # A non-stepSize-aligned delta must be floored, not rejected raw.
    qty2 = clamp_and_round_qty("MOCKUSDT", "Binance Futures", 0.1234567, 100.0, reduce_only=True)
    assert qty2 == 0.123

    # Below minQty still floors up to minQty (LOT_SIZE.minQty is NOT exempted for reduceOnly).
    _rules_cache[("Binance Futures", "MOCKUSDT")] = {
        "tickSize": Decimal("0.1"),
        "stepSize": Decimal("0.001"),
        "minQty": Decimal("0.01"),
        "minNotional": Decimal("50.0"),
    }
    qty3 = clamp_and_round_qty("MOCKUSDT", "Binance Futures", 0.001, 100.0, reduce_only=True)
    assert qty3 == 0.01
