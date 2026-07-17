"""Backtest fill realism (F-011 / F-012).

Two corrections to the inline ``exit_fill`` SL/TP branch in
``backtest_runner.run_backtest_simulation``:

* **F-011 (HIGH)** — gap-through stops.  When a candle's range fully skips
  the stop (long: ``low > stop_price`` / short: ``high < stop_price``), the
  stop would have to be filled *through the gap*, so realistic fill price is
  the candle OPEN (worst case).  Mirrors freqtrade's
  ``_get_close_rate_for_stoploss``.  Without this, backtests understate
  gap-down loss and overstate stop precision.

* **F-012 (MEDIUM)** — candle-bounded fills.  Even when the stop sits
  inside the candle range, a market exit at exactly the stop price is
  optimistic — the actual fill sits somewhere between stop and open
  depending on slippage.  We bound the exit to the candle's [low, high]
  range using an adverse slippage parameter, replacing the current
  "exact stop price" semantic with "bounded + slippage-adjusted".

The pure functions here are called from the runner.  Kept stateless and
side-effect-free so unit tests can exercise every branch.
"""
from __future__ import annotations

import numpy as np


def gap_through_stop_price(
    *,
    is_long: bool,
    stop_price: float,
    candle_open: float,
    candle_low: float,
    candle_high: float,
) -> float | None:
    """Return the fill price if the candle gaps THROUGH the stop, else ``None``.

    Logic (mirrors freqtrade's ``_get_close_rate_for_stoploss``):
        * Long  stop fired at ``low_t <= stop_price``.  If the candle OPENED
          below the stop (``open_t < stop_price``), the price skipped from
          above to below the stop without trading at the stop level — fill
          at the candle OPEN (worst case).
        * Short stop fired at ``high_t >= stop_price``.  If the candle OPENED
          above the stop (``open_t > stop_price``), gap-through — fill at the
          candle OPEN.

    The ``None`` return means "no gap detected; the regular bounded exit fill
    handles this."
    """
    if is_long:
        if candle_open < stop_price:
            return candle_open
    else:
        if candle_open > stop_price:
            return candle_open
    return None


def bounded_exit_price(
    *,
    is_long: bool,
    proposed_price: float,
    candle_open: float,
    candle_low: float,
    candle_high: float,
) -> float:
    """Clamp a proposed exit (stop / TP / F-011 gap-open) into the candle's
    realised ``[low, high]`` range — NO slippage applied here.

    A triggered stop/TP already lies inside the candle range, so this is a
    no-op in the common case; it only guards a proposed price that sits
    outside the bar (e.g. a stop beyond the high/low).  Adverse slippage is
    applied SEPARATELY, and in the correct direction, by
    ``execution.exit_fill`` (the cost model) on the price returned here.

    ``is_long`` is accepted for call-site symmetry but does not change the
    bound: clamping to ``[low, high]`` is side-independent.  The slippage
    direction is the cost model's job via its ``side`` argument.

    NOTE: this MUST NOT nudge the price toward a more favourable level. The
    prior implementation floored long exits at ``candle_open`` (and capped
    shorts at it), which filled every stop-loss at the OPEN instead of the
    stop — strictly better for the trade and the cause of the inflated
    backtest P&L. Clamping to ``[low, high]`` only is the correction.
    """
    return min(max(proposed_price, candle_low), candle_high)


def bounded_entry_price(
    *,
    is_long: bool,
    candle_open: float,
    candle_low: float,
    candle_high: float,
    slippage_pct: float,
) -> float:
    """Bound an entry market fill to the candle range (F-012).

    Entries in Enma fill at the next candle's OPEN (Phase 1 invariant).
    Apply adverse slippage, then clamp into the realised ``[low, high]`` band
    so the fill never lands outside the candle that actually traded.

    Long entry (buy):  open * (1 + slippage), capped at the candle HIGH (pay more).
    Short entry (sell): open * (1 - slippage), floored at the candle LOW (receive less).

    NOTE: this is a forward-looking helper. The runner's entry path currently
    fills via ``execution.entry_fill`` (next-open + cost-model slippage); this
    function is NOT yet wired into that path, so changing it does not alter
    backtest output. Wiring it in is a separate, golden-master-gated change.
    """
    if is_long:
        return min(candle_open * (1.0 + slippage_pct), candle_high)
    return max(candle_open * (1.0 - slippage_pct), candle_low)