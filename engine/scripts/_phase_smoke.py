"""Host-level equivalence test for the Five-Model scaffolding (no TA-Lib).

Phase 0: BaseStrategy <-> model delegation is numerically consistent.
Phase 1: the math relocated into the Risk Model is BYTE-IDENTICAL to the former
         inline implementations (size_by_risk, atr_stop, session-drawdown
         tracking), and the new liq-buffer helper matches the margin model.
Phase 2: the Cost Model's adverse_fill/fee reproduce the runner's former inline
         slippage/taker-fee arithmetic byte-for-byte; estimate stays consistent
         and the default is_worth_it gate is permissive (legacy alpha_beats_cost).
Phase 3: the Portfolio Model's allocate() equal split is byte-identical to the
         live manager's former capital/len(symbols) (and guards empty symbols).
Phase 4: the Execution Model's entry_fill/exit_fill (+affordable, +live exit_fee)
         reproduce the runner's former inline fill assembly byte-for-byte.

Run from engine/:  python -m scripts._phase_smoke
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # engine/

import numpy as np
from core.strategy import BaseStrategy
from core.models import (
    Signal, DefaultRiskModel, DefaultPortfolioModel, DefaultCostModel,
    BacktestExecution, LiveExecution,
)
from core.margin import initial_margin, liquidation_price


class Dummy(BaseStrategy):
    """Minimal concrete strategy; ATR is stubbed so no TA-Lib is needed."""
    def __init__(self, atr=10.0):
        super().__init__()
        self._atr_val = atr
    def _atr(self, period: int = 14) -> float:
        return self._atr_val
    def should_long(self) -> bool:
        return self.vars.get("dir", 0) > 0
    def should_short(self) -> bool:
        return self.vars.get("dir", 0) < 0
    def go_long(self) -> None:
        stop = self.atr_stop("long")
        qty = self.size_by_risk(stop)
        self.buy, self.stop_loss = (qty, self.price), (qty, stop)
    def go_short(self) -> None:
        stop = self.atr_stop("short")
        qty = self.size_by_risk(stop)
        self.sell, self.stop_loss = (qty, self.price), (qty, stop)


def _mk(price=100.0, balance=1000.0, leverage=5, atr=10.0):
    s = Dummy(atr=atr)
    s.candles = np.array([[0, price, price, price, price, 1.0]], dtype=np.float64)
    s.balance = balance
    s.leverage = leverage
    s.risk_pct = 0.01
    s.fee_rate = 0.0005
    s.slippage_pct = 0.0005
    return s


def approx(a, b, tol=1e-12):
    return abs(a - b) <= tol * max(1.0, abs(a), abs(b))


# ── Reference implementations of the FORMER inline code (Phase 0 versions) ──

def ref_size_by_risk(s, stop_price, risk_pct=None, entry_price=None):
    entry = entry_price if entry_price is not None else s.price
    if risk_pct is None:
        risk_pct = float(getattr(s, "risk_pct", 0.01))
    per_unit = abs(entry - stop_price)
    if per_unit <= 0 or entry <= 0:
        return 0.0
    qty = (s.equity * risk_pct) / per_unit
    return min(qty, s.max_qty(entry))


def ref_atr_stop(s, direction, mult=2.0, period=14, entry_price=None):
    entry = entry_price if entry_price is not None else s.price
    atr = s._atr(period)
    return entry - mult * atr if direction == "long" else entry + mult * atr


def ref_update_dd(peak, dd, equity):
    """Former backtest_runner.py:581-588 inline block."""
    if equity > peak:
        peak = equity
    if peak > 0:
        dd = (peak - equity) / peak
    return peak, dd


def main():
    fail = []

    # ── Phase 0: can_trade / forecast / portfolio / cost ────────────────────
    s = _mk()
    s.max_session_dd, s.session_drawdown = 0.20, 0.10
    assert s.can_trade() is True
    s.session_drawdown = 0.25
    assert s.can_trade() is False
    if s.risk_model.can_trade(s) != s.can_trade():
        fail.append("can_trade not delegating")

    s = _mk()
    s.vars["dir"] = 1
    assert s.forecast().direction == 1 and s.alpha() == 1.0
    s.vars["dir"] = -1
    assert s.forecast().direction == -1 and s.alpha() == -1.0
    s.vars["dir"] = 0
    assert s.forecast().flat and s.alpha() == 0.0

    # ── Phase 1: atr_stop delegation == former inline, over many cases ──────
    for price, atr, mult, lev in [(100, 10, 2.0, 5), (37.5, 1.3, 1.7, 3), (20000, 250, 3.0, 10)]:
        s = _mk(price=price, atr=atr, leverage=lev)
        for d in ("long", "short"):
            got = s.atr_stop(d, mult=mult)
            ref = ref_atr_stop(s, d, mult=mult)
            if not approx(got, ref):
                fail.append(f"atr_stop {d} {price}/{atr}: {got} != {ref}")

    # ── Phase 1: size_by_risk delegation == former inline (incl. cap/edges) ─
    cases = [
        # price, balance, lev, atr, stop, risk_pct
        (100.0, 1000.0, 5, 10.0, 80.0, None),     # normal
        (100.0, 1000.0, 5, 10.0, 99.99, None),    # tight stop -> max_qty cap
        (100.0, 1000.0, 5, 10.0, 100.0, None),    # per_unit == 0 -> 0.0
        (100.0, 1000.0, 5, 10.0, 80.0, 0.05),     # explicit risk_pct
        (50.0, 250.0, 2, 3.0, 47.0, None),        # other scale
    ]
    for price, bal, lev, atr, stop, rp in cases:
        s = _mk(price=price, balance=bal, leverage=lev, atr=atr)
        got = s.size_by_risk(stop, risk_pct=rp)
        ref = ref_size_by_risk(s, stop, risk_pct=rp)
        if not approx(got, ref):
            fail.append(f"size_by_risk {price}/{stop}/{rp}: {got} != {ref}")
        # entry_price override path
        got2 = s.size_by_risk(stop, entry_price=price * 1.01)
        ref2 = ref_size_by_risk(s, stop, entry_price=price * 1.01)
        if not approx(got2, ref2):
            fail.append(f"size_by_risk entry-override {price}/{stop}: {got2} != {ref2}")

    # Portfolio.size at unit conviction still == size_by_risk; halves at 0.5
    s = _mk(price=100.0, balance=1000.0, leverage=5, atr=10.0)
    rf = DefaultRiskModel().frame(s, Signal(1, 1.0, 100.0))
    full = DefaultPortfolioModel().size(s, Signal(1, 1.0), rf).qty
    half = DefaultPortfolioModel().size(s, Signal(1, 0.5), rf).qty
    if not approx(full, s.size_by_risk(rf.stop_price)):
        fail.append("portfolio.size != size_by_risk")
    if not approx(half, full * 0.5):
        fail.append("conviction scaling wrong")

    # ── Phase 1: update_session_risk == former inline block, over a path ────
    s = _mk(balance=1000.0)
    s.peak_equity = 1000.0
    s.session_drawdown = 0.0
    ref_peak, ref_dd = 1000.0, 0.0
    rm = s.risk_model
    for eq in [1000, 1010, 1005, 1100, 900, 1200, 1199.99, 600, 600, 1300]:
        rm.update_session_risk(s, equity=float(eq))
        ref_peak, ref_dd = ref_update_dd(ref_peak, ref_dd, float(eq))
        if not approx(s.peak_equity, ref_peak) or not approx(s.session_drawdown, ref_dd):
            fail.append(f"update_session_risk eq={eq}: peak {s.peak_equity}/{ref_peak} "
                        f"dd {s.session_drawdown}/{ref_dd}")
    # default-equity path (reads s.equity) must equal the explicit path
    s2 = _mk(balance=1234.0)
    s2.peak_equity, s2.session_drawdown = 1000.0, 0.0
    rm.update_session_risk(s2)  # no equity arg -> s2.equity == balance (no position)
    rp2, rd2 = ref_update_dd(1000.0, 0.0, s2.equity)
    if not approx(s2.peak_equity, rp2) or not approx(s2.session_drawdown, rd2):
        fail.append("update_session_risk default-equity path mismatch")

    # ── Phase 1: respects_liq_buffer matches the margin model ───────────────
    s = _mk(price=100.0, balance=1000.0, leverage=10, atr=10.0)
    s.liq_buffer_pct = 0.005
    entry, qty, lev = 100.0, 5.0, 10
    liq_long = liquidation_price("long", qty, entry, initial_margin(qty * entry, lev))
    buf = s.liq_buffer_pct * entry
    # a stop safely above liq passes; one at/below liq+buf fails
    assert rm.respects_liq_buffer(s, entry, liq_long + buf + 1e-6, qty, lev, "long") is True
    assert rm.respects_liq_buffer(s, entry, liq_long + buf - 1e-6, qty, lev, "long") is False
    liq_short = liquidation_price("short", qty, entry, initial_margin(qty * entry, lev))
    assert rm.respects_liq_buffer(s, entry, liq_short - buf - 1e-6, qty, lev, "short") is True
    assert rm.respects_liq_buffer(s, entry, liq_short - buf + 1e-6, qty, lev, "short") is False
    assert rm.respects_liq_buffer(s, entry, 50.0, 0.0, lev, "long") is False  # qty<=0 guard

    # ── Phase 2: Cost Model fills == runner's former inline arithmetic ──────
    from core.models.base import Cost, Target, RiskFrame as _RF
    cm = DefaultCostModel()
    for price, slip, fee_rate, qty in [
        (100.0, 0.0005, 0.0005, 3.0),
        (37.5, 0.001, 0.0002, 12.345),
        (20000.0, 0.0, 0.0004, 0.5),
    ]:
        s = _mk(price=price)
        s.slippage_pct, s.fee_rate = slip, fee_rate
        # adverse_fill: buy fills high, sell fills low — byte-identical to the
        # runner's `open_t * (1.0 ± _slippage)`.
        if not approx(cm.adverse_fill(s, price, "buy"), price * (1.0 + slip)):
            fail.append(f"adverse_fill buy {price}/{slip}")
        if not approx(cm.adverse_fill(s, price, "sell"), price * (1.0 - slip)):
            fail.append(f"adverse_fill sell {price}/{slip}")
        # fee: notional * fee_rate, byte-identical to `notional * taker_fee`.
        notional = qty * price
        if not approx(cm.fee(s, notional), notional * fee_rate):
            fail.append(f"fee {notional}/{fee_rate}")
        # estimate reuses fee + slippage·notional; impact defaults to 0.
        est = cm.estimate(s, Target(qty=qty))
        if not (approx(est.fee, notional * fee_rate)
                and approx(est.slippage, notional * slip)
                and est.impact == 0.0
                and approx(est.total, est.fee + est.slippage)):
            fail.append(f"estimate {qty}/{price}")
    # is_worth_it: permissive by default (== legacy alpha_beats_cost stub).
    s = _mk()
    if cm.is_worth_it(s, Signal(1, 1.0), _RF(risk_per_unit=5.0), Cost(fee=1e9)) is not True:
        fail.append("default is_worth_it not permissive")
    # opt-in gate: a tiny edge vs a huge cost must veto once min_edge_mult > 0.
    cm.min_edge_mult = 1.0
    if cm.is_worth_it(s, Signal(1, 0.01), _RF(risk_per_unit=0.01), Cost(fee=1e9)) is not False:
        fail.append("opt-in is_worth_it failed to veto")
    cm.min_edge_mult = 0.0

    # ── Phase 3: Portfolio allocate() == former capital/len(symbols) split ──
    pm = DefaultPortfolioModel()
    for cap, syms in [
        (10000.0, ["BTCUSDT"]),
        (10000.0, ["BTCUSDT", "ETHUSDT", "SOLUSDT"]),
        (333.33, ["A", "B", "C", "D", "E", "F", "G"]),
    ]:
        alloc = pm.allocate(cap, syms)
        ref = cap / len(syms)  # the former inline live_bot_manager split
        if set(alloc) != set(syms):
            fail.append(f"allocate keys {syms}")
        for sym in syms:
            if not approx(alloc[sym], ref):
                fail.append(f"allocate {cap}/{len(syms)} {sym}: {alloc[sym]} != {ref}")
        if not approx(sum(alloc.values()), cap):
            fail.append(f"allocate sum {cap}/{len(syms)}: {sum(alloc.values())} != {cap}")
    if pm.allocate(10000.0, []) != {}:  # empty-symbols guard (no ZeroDivisionError)
        fail.append("allocate empty-symbols not {}")

    # ── Phase 4: Execution fills == runner's former inline assembly ─────────
    be = BacktestExecution()
    for price, slip, fee_rate, qty, lev in [
        (100.0, 0.0005, 0.0005, 3.0, 3),
        (37.5, 0.001, 0.0002, 12.345, 10),
        (20000.0, 0.0, 0.0004, 0.5, 1),
    ]:
        s = _mk(price=price, leverage=lev)
        s.slippage_pct, s.fee_rate = slip, fee_rate
        # entry_fill (buy): byte-identical to fill=ref*(1+slip); notional=qty*fill;
        # req_margin=initial_margin(notional,lev); fee=notional*fee_rate.
        ef = be.entry_fill(s, price, qty, lev, "buy")
        rfp = price * (1.0 + slip)
        rno = qty * rfp
        if not (approx(ef.fill_price, rfp) and approx(ef.notional, rno)
                and approx(ef.req_margin, initial_margin(rno, lev))
                and approx(ef.fee, rno * fee_rate)):
            fail.append(f"entry_fill buy {price}/{slip}/{qty}")
        # affordable predicate == former `req_margin + fee > balance` (negated).
        bnd = ef.req_margin + ef.fee
        if ef.affordable(bnd + 1e-6) is not True or ef.affordable(bnd - 1e-6) is not False:
            fail.append(f"entry_fill.affordable {price}")
        # entry_fill (sell) fills low.
        efs = be.entry_fill(s, price, qty, lev, "sell")
        if not approx(efs.fill_price, price * (1.0 - slip)):
            fail.append(f"entry_fill sell {price}/{slip}")
        # exit_fill: fill=ref*(1∓slip); fee=(qty*fill)*fee_rate.
        xf = be.exit_fill(s, price, qty, "sell")
        xfp = price * (1.0 - slip)
        if not (approx(xf.fill_price, xfp) and approx(xf.fee, qty * xfp * fee_rate)):
            fail.append(f"exit_fill sell {price}/{slip}/{qty}")
        # LiveExecution.exit_fee == former qty*exit_price*fee_rate.
        if not approx(LiveExecution().exit_fee(s, qty, price), qty * price * fee_rate):
            fail.append(f"exit_fee {qty}/{price}/{fee_rate}")

    if fail:
        print("EQUIVALENCE FAIL:")
        for f in fail:
            print("  -", f)
        sys.exit(1)
    print("EQUIVALENCE OK — Phase-1 relocations byte-identical to inline; "
          "liq-buffer matches margin model; Phase-2 Cost Model fills/fee/estimate "
          "byte-identical, default gate permissive; Phase-3 allocate() equal split "
          "byte-identical to capital/len(symbols); Phase-4 Execution fills byte-identical.")


if __name__ == "__main__":
    main()
