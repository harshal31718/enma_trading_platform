"""Risk Models — stop placement, budget, trailing, drawdown breaker.

DefaultRiskModel    — ATR stop at entry, can_trade() circuit breaker.
AtrBracketRiskModel — ATR bracket with optional trailing (trail_atr_mult),
                      breakeven move (breakeven_r), and ATR percentile filter
                      (atr_percentile_min). All three default to 0 / disabled.
ChandelierRiskModel — chandelier trailing stop with per-trade state.
SignalExitRiskModel — no bracket; exit is signal-driven (BestSupertrend).
"""
from __future__ import annotations
import bisect

from .base import RiskModel, RiskConstraints, RiskFrame, Signal


class DefaultRiskModel(RiskModel):
    """Legacy-equivalent risk model: ATR stop at entry, drawdown circuit breaker.

    assess() replaces frame() as the primary contract; frame() is kept as a
    deprecated shim for any call sites not yet updated to the new pipeline.
    """

    def can_trade(self, s) -> bool:
        return s.session_drawdown < s.max_session_dd

    def assess(self, s, sig: Signal, current_holding: float = 0.0) -> RiskConstraints:
        can = self.can_trade(s)
        if sig.direction == 0:
            return RiskConstraints(vetoed=not can, max_drawdown_hit=not can)
        direction = "long" if sig.direction > 0 else "short"
        stop = self.atr_stop(s, direction)
        risk_per_unit = abs(s.price - stop)
        budget = s.equity * float(getattr(s, "risk_pct", 0.01))
        max_notional = s.equity * max(int(getattr(s, "leverage", 1)), 1)
        vetoed = (not can) or risk_per_unit <= 0
        return RiskConstraints(
            vetoed=vetoed,
            max_drawdown_hit=not can,
            stop_price=stop,
            risk_per_unit=risk_per_unit,
            budget=budget,
            max_notional=max_notional,
        )

    def frame(self, s, sig: Signal) -> RiskConstraints:
        """Deprecated shim → assess(s, sig, 0.0). Remove in Phase 6."""
        return self.assess(s, sig, 0.0)

    def respects_liq_buffer(
        self, s, entry: float, stop: float, qty: float, leverage: float, direction: str
    ) -> bool:
        """True when the stop triggers before the isolated-margin liquidation price.

        The stop must sit at least ``liq_buffer_pct`` of price clear of the
        liquidation price so the engine can always fire the stop before the
        exchange force-liquidates the position.
        """
        try:
            from engine.core.margin import liquidation_price, initial_margin
        except ImportError:  # pragma: no cover - top-level module root
            from core.margin import liquidation_price, initial_margin
        qty = abs(qty)
        if qty <= 0 or entry <= 0:
            return False
        margin = initial_margin(qty * entry, leverage)
        liq = liquidation_price(direction, qty, entry, margin)
        if liq <= 0:
            return True
        buf = float(getattr(s, "liq_buffer_pct", 0.0)) * entry
        if direction == "long":
            return stop >= liq + buf
        return stop <= liq - buf


class AtrBracketRiskModel(DefaultRiskModel):
    """ATR bracket: computed at entry; optionally trails/moves-to-breakeven.

    Used by MicroScalper, MicroMacroRSIDivergence, MultiDivergence.

    Golden-master guarantee: trail_atr_mult and breakeven_r both default to 0 →
    maintain path reads s.stop_loss[1] unchanged → byte-identical to prior static
    behavior. Per-trade state is only used when either param is non-zero.
    """

    def __init__(self):
        self._current_stop: float | None = None
        self._entry_price: float = 0.0
        self._initial_risk: float = 0.0
        self._signal_price: float = 0.0
        self._initialized: bool = False
        self._atr_history: list = []   # session-level; never reset between trades

    def _reset(self) -> None:
        self._current_stop = None
        self._entry_price = 0.0
        self._initial_risk = 0.0
        self._signal_price = 0.0
        self._initialized = False
        # _atr_history intentionally not cleared — accumulates across the session

    def assess(self, s, sig: Signal, current_holding: float = 0.0) -> RiskConstraints:
        can = self.can_trade(s)
        is_holding = current_holding != 0.0

        # Accumulate ATR for percentile filter (session-level; O(1) — reads s.vars set by before())
        _atr_now = s.vars.get("atr")
        if _atr_now and _atr_now > 0:
            self._atr_history.append(float(_atr_now))
        same_dir = (
            (sig.direction > 0 and current_holding > 0) or
            (sig.direction < 0 and current_holding < 0)
        )

        # ── Path: maintain bracket while holding same direction ───────────────
        if is_holding and same_dir:
            trail_mult  = float(getattr(s, "trail_atr_mult", 0.0))
            breakeven_r = float(getattr(s, "breakeven_r", 0.0))

            if trail_mult > 0 or breakeven_r > 0:
                if not self._initialized:
                    self._current_stop = float(s.stop_loss[1]) if s.stop_loss else None
                    self._entry_price  = self._signal_price if self._signal_price > 0 else s.price
                    self._initial_risk = (
                        abs(self._entry_price - self._current_stop)
                        if self._current_stop is not None else 0.0
                    )
                    self._initialized = True

                stop = self._current_stop

                # Trailing: ratchet stop toward price
                if trail_mult > 0 and stop is not None:
                    atr = s.vars.get("atr") or s._atr(int(getattr(s, "atr_period", 14)))
                    if atr and atr > 0:
                        if sig.direction > 0:
                            candidate = s.price - trail_mult * atr
                            if candidate > stop:
                                stop = candidate
                        else:
                            candidate = s.price + trail_mult * atr
                            if candidate < stop:
                                stop = candidate

                # Breakeven: floor stop at entry once price moves breakeven_r * initial_risk
                if breakeven_r > 0 and stop is not None and self._initial_risk > 0:
                    if (sig.direction > 0 and
                            s.price >= self._entry_price + breakeven_r * self._initial_risk):
                        stop = max(stop, self._entry_price)
                    elif (sig.direction < 0 and
                            s.price <= self._entry_price - breakeven_r * self._initial_risk):
                        stop = min(stop, self._entry_price)

                self._current_stop = stop
            else:
                stop = s.stop_loss[1] if s.stop_loss else None

            tp   = s.take_profit[1] if s.take_profit else None
            rpu  = abs(s.price - stop) if stop is not None else 0.0
            budget      = s.equity * float(getattr(s, "risk_pct", 0.01))
            max_notional = s.equity * max(int(getattr(s, "leverage", 1)), 1)
            return RiskConstraints(
                vetoed=False,
                max_drawdown_hit=not can,
                stop_price=stop,
                take_profit_price=tp,
                risk_per_unit=rpu,
                budget=budget,
                max_notional=max_notional,
            )

        # ── Path: new entry or flip — reset state, store signal price, compute fresh ATR bracket
        self._reset()
        if sig.direction == 0:
            return RiskConstraints(max_drawdown_hit=not can)

        atr = s.vars.get("atr") or s._atr(int(getattr(s, "atr_period", 14)))
        if not atr or atr <= 0:
            return RiskConstraints(vetoed=True, max_drawdown_hit=not can)

        # ATR percentile filter: veto if current ATR is in the bottom N% of session history.
        # atr_percentile_min=0 (default) disables the filter → golden-master safe.
        atr_pct_min = float(getattr(s, "atr_percentile_min", 0.0))
        if atr_pct_min > 0 and len(self._atr_history) >= 20:
            rank = bisect.bisect_left(sorted(self._atr_history), atr)
            if rank / len(self._atr_history) < atr_pct_min:
                return RiskConstraints(vetoed=True, max_drawdown_hit=not can)

        sl_mult = float(getattr(s, "sl_atr_mult", 2.0))

        # Stop: prefer precomputed vars → custom_sl_pct → ATR formula
        if sig.direction > 0:
            stop = s.vars.get("atr_stop_long")
            if stop is None:
                if getattr(s, "use_custom_sl", False):
                    sl_pct = float(getattr(s, "custom_sl_pct", 1.0))
                    stop = s.price * (1.0 - sl_pct / 100.0)
                else:
                    stop = s.price - sl_mult * atr
        else:
            stop = s.vars.get("atr_stop_short")
            if stop is None:
                if getattr(s, "use_custom_sl", False):
                    sl_pct = float(getattr(s, "custom_sl_pct", 1.0))
                    stop = s.price * (1.0 + sl_pct / 100.0)
                else:
                    stop = s.price + sl_mult * atr

        # TP: prefer precomputed vars → tp_atr_mult → rr_target with rrr
        tp_mult = float(getattr(s, "tp_atr_mult", 0.0))
        if sig.direction > 0:
            tp = s.vars.get("atr_tp_long")
            if tp is None:
                if tp_mult > 0:
                    tp = s.price + tp_mult * atr
                else:
                    rrr = float(getattr(s, "rrr", 2.0))
                    tp = s.price + rrr * abs(s.price - stop)
        else:
            tp = s.vars.get("atr_tp_short")
            if tp is None:
                if tp_mult > 0:
                    tp = s.price - tp_mult * atr
                else:
                    rrr = float(getattr(s, "rrr", 2.0))
                    tp = s.price - rrr * abs(s.price - stop)

        risk_per_unit = abs(s.price - stop)
        budget       = s.equity * float(getattr(s, "risk_pct", 0.01))
        max_notional = s.equity * max(int(getattr(s, "leverage", 1)), 1)
        vetoed = (not can) or risk_per_unit <= 0

        # Capture signal price so the first holding candle can initialize entry state.
        self._signal_price = s.price

        return RiskConstraints(
            vetoed=vetoed,
            max_drawdown_hit=not can,
            stop_price=stop,
            take_profit_price=tp,
            risk_per_unit=risk_per_unit,
            budget=budget,
            max_notional=max_notional,
        )


class ChandelierRiskModel(DefaultRiskModel):
    """Chandelier trailing stop. Used by AdaptiveTrend.

    Per-trade state (owned entirely by this model — not the strategy):
      _extreme       : highest close (long) or lowest close (short) since entry
      _entry_price   : close at signal candle (not fill price) — matches the
                       old _reset_trade_state() which used self.price at entry
      _initial_risk  : |entry - initial_stop| used for breakeven gate
      _current_stop  : ratcheted chandelier stop; only ever tightens
      _initialized   : True once we've read the position on the first holding candle

    Golden-master notes
    -------------------
    _entry_price is initialized from self._signal_price (the close at the candle
    when forecast() fired), NOT from s.position.entry_price (the next-open fill),
    so the chandelier extreme baseline matches the old _reset_trade_state() exactly.
    """

    def __init__(self):
        self._extreme: float       = 0.0
        self._entry_price: float   = 0.0
        self._initial_risk: float  = 0.0
        self._current_stop: float  = 0.0
        self._signal_price: float  = 0.0
        self._initialized: bool    = False

    def _reset(self) -> None:
        self._extreme      = 0.0
        self._entry_price  = 0.0
        self._initial_risk = 0.0
        self._current_stop = 0.0
        self._signal_price = 0.0
        self._initialized  = False

    def assess(self, s, sig: Signal, current_holding: float = 0.0) -> RiskConstraints:
        can = self.can_trade(s)
        is_holding  = current_holding != 0.0
        same_dir = (
            (sig.direction > 0 and current_holding > 0) or
            (sig.direction < 0 and current_holding < 0)
        )

        max_lev      = float(getattr(s, "max_leverage", float(max(int(getattr(s, "leverage", 1)), 1))))
        actual_lev   = float(max(int(getattr(s, "leverage", 1)), 1))
        max_notional = s.equity * min(max_lev, actual_lev)
        budget       = s.equity * float(getattr(s, "risk_pct", 0.01))

        # ── Maintain: update chandelier trailing while holding same direction ─
        if is_holding and same_dir:
            if not self._initialized:
                # First holding candle — initialize from signal price (close[N]).
                self._entry_price  = self._signal_price if self._signal_price > 0 else s.price
                self._current_stop = float(s.stop_loss[1]) if s.stop_loss else self._entry_price
                self._initial_risk = abs(self._entry_price - self._current_stop)
                self._extreme      = self._entry_price
                self._initialized  = True

            atr = s.vars.get("atr") or s._atr(int(getattr(s, "atr_period", 14)))
            if atr and atr > 0:
                trail_mult  = float(getattr(s, "trail_atr_mult", 2.0))
                breakeven_r = float(getattr(s, "breakeven_r", 0.0))

                if sig.direction > 0:  # long
                    if s.price > self._extreme:
                        self._extreme = s.price
                    candidate = self._extreme - trail_mult * atr
                    if breakeven_r > 0 and \
                            s.price >= self._entry_price + breakeven_r * self._initial_risk:
                        candidate = max(candidate, self._entry_price)
                    new_stop = max(self._current_stop, candidate)
                    if new_stop > self._current_stop:
                        self._current_stop = new_stop
                else:  # short
                    if s.price < self._extreme:
                        self._extreme = s.price
                    candidate = self._extreme + trail_mult * atr
                    if breakeven_r > 0 and \
                            s.price <= self._entry_price - breakeven_r * self._initial_risk:
                        candidate = min(candidate, self._entry_price)
                    new_stop = min(self._current_stop, candidate)
                    if new_stop < self._current_stop:
                        self._current_stop = new_stop

            tp_price = s.take_profit[1] if s.take_profit else None
            return RiskConstraints(
                vetoed=False,
                max_drawdown_hit=not can,
                stop_price=self._current_stop,
                take_profit_price=tp_price,
                risk_per_unit=self._initial_risk,
                budget=budget,
                max_notional=max_notional,
            )

        # ── New entry or flip: reset state and compute initial bracket ────────
        self._reset()

        if sig.direction == 0:
            return RiskConstraints(max_drawdown_hit=not can, budget=budget, max_notional=max_notional)

        atr = s.vars.get("atr") or s._atr(int(getattr(s, "atr_period", 14)))
        if not atr or atr <= 0:
            return RiskConstraints(
                vetoed=True, max_drawdown_hit=not can, budget=budget, max_notional=max_notional
            )

        sl_mult      = float(getattr(s, "sl_atr_mult", 2.0))
        risk_per_unit = sl_mult * atr

        if sig.direction > 0:
            stop = s.price - risk_per_unit
            tp_r = float(getattr(s, "tp_r_mult", 0.0))
            tp   = (s.price + tp_r * risk_per_unit) if tp_r > 0 else None
        else:
            stop = s.price + risk_per_unit
            tp_r = float(getattr(s, "tp_r_mult", 0.0))
            tp   = (s.price - tp_r * risk_per_unit) if tp_r > 0 else None

        # Store signal price so first-holding-candle init replicates old
        # _reset_trade_state(entry, ...) where entry = self.price at signal time.
        self._signal_price = s.price

        vetoed = (not can) or risk_per_unit <= 0
        return RiskConstraints(
            vetoed=vetoed,
            max_drawdown_hit=not can,
            stop_price=stop,
            take_profit_price=tp,
            risk_per_unit=risk_per_unit,
            budget=budget,
            max_notional=max_notional,
        )


class SignalExitRiskModel(DefaultRiskModel):
    """No bracket — entry and exit are signal-driven. Used by BestSupertrend.

    Returns stop_price=None, take_profit_price=None. Only vetoed=True when
    the drawdown circuit breaker fires on a NEW entry; existing holdings are
    not force-closed (Phase 1 behavior).
    """

    def assess(self, s, sig: Signal, current_holding: float = 0.0) -> RiskConstraints:
        can = self.can_trade(s)
        is_holding = current_holding != 0.0
        # Veto new entries only; maintain existing holdings even over-drawdown.
        vetoed = (not can) and not is_holding
        budget       = s.equity * float(getattr(s, "risk_pct", 0.01))
        max_notional = s.equity * max(int(getattr(s, "leverage", 1)), 1)
        return RiskConstraints(
            vetoed=vetoed,
            max_drawdown_hit=not can,
            stop_price=None,
            take_profit_price=None,
            risk_per_unit=0.0,
            budget=budget,
            max_notional=max_notional,
        )
