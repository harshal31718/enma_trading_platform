"""Decimal money helpers (Plan 5 Step 5.5, ENG-11).

Scope decision (2026-07-18): a full float->Decimal conversion of every price/
qty touch point across the engine would ripple into the hot candle-replay
loop (kernel.py, risk/portfolio/cost models) for no accounting-correctness
benefit — a single float arithmetic op on a price or qty already carries far
more precision (~15-17 significant digits) than any realistic instrument
needs, and Decimal there would only add cost (Decimal ops are roughly two
orders of magnitude slower than float) without fixing anything.

The actual bug ENG-11 describes only manifests in REPEATED accumulation —
`balance += pnl` executed thousands of times across a backtest/session lets
each addition's tiny binary-representation noise silently compound (the
classic `0.1 + 0.2 + 0.3 + ...` drift). That only happens to running totals:
`strategy.balance`, `BacktestAdapter.total_fees`/`total_funding`, and the
live engine's `session["pnl"]`. `add_money()` below is the fix: quantize to a
fixed precision via Decimal at every accumulation step instead of letting
float `+=` noise compound unchecked. Everything else (Position.pnl/margin,
candle prices, qty, liquidation_price) is unchanged — those are one-shot
computations from real exchange/candle data, not running totals, so they
have no accumulation-drift problem to fix.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

# 8dp — the ceiling of Binance's own USDT-margined-futures internal
# precision (commission/PnL fields on real Binance responses never exceed
# this). Quantizing here, not at display time, is what actually stops noise
# from compounding across many additions.
QUANT_USDT = Decimal("0.00000001")


def to_decimal(value) -> Decimal:
    """Convert a float/int/str/Decimal/None to Decimal.

    Always routes through str() for a float input — Decimal(float) would
    import the float's own binary-representation noise verbatim (e.g.
    Decimal(0.1) == Decimal('0.1000000000000000055511151231257827021181583404541015625')),
    exactly the noise this module exists to stop propagating.
    """
    if isinstance(value, Decimal):
        return value
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def add_money(current, delta) -> float:
    """Accumulate a money delta with exact Decimal rounding at each step.

    Drop-in replacement for `current += delta` on any running total (session
    balance, cumulative fees, cumulative funding, cumulative session PnL).
    Returns float — the accumulator's stored type is unchanged, so every
    existing reader of e.g. `strategy.balance` keeps working unmodified; only
    the update site changes from `+=` to `strategy.balance = add_money(strategy.balance, delta)`.
    """
    result = (to_decimal(current) + to_decimal(delta)).quantize(QUANT_USDT, rounding=ROUND_HALF_UP)
    return float(result)


def quantize_str(value, places: int = 2) -> str:
    """Format a money value as a decimal string without a float round-trip.

    Prefer this over f"{value:.2f}" for persisted/serialized money fields —
    Python's float formatting rounds the float's OWN binary-repr noise
    (still usually fine for a one-shot value, but exact and free via Decimal
    when the value in hand is already a Decimal from add_money()).
    """
    quant = Decimal(1).scaleb(-places)
    return str(to_decimal(value).quantize(quant, rounding=ROUND_HALF_UP))
