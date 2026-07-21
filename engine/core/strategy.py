import logging
from abc import ABC
import numpy as np

# Five-Model Quant Architecture (see plan.md).
from core.models import (
    Signal,
    DefaultRiskModel,
    DefaultTransactionCostModel as DefaultCostModel,
    DefaultPortfolioModel,
    DefaultExecution,
)
from core.candle_columns import TIMESTAMP, OPEN, CLOSE, HIGH, LOW, VOLUME


class BaseStrategy(ABC):
    """
    Base class for all Enma trading strategies.
    Mirrors Jesse's strategy API for portability.
    All strategies must extend this class.
    """

    # ── Class-level constants ────────────────────────────────────────────────
    # Override in subclass to enforce a minimum warm-up window.
    # The runner uses max(50, strategy.MIN_WARMUP_CANDLES) so strategies that
    # need more than 50 bars (e.g. AdaptiveTrend's 200-bar trend EMA) get
    # enough history before the first signal fires.
    MIN_WARMUP_CANDLES: int = 50

    # Plan 13: informative / multi-timeframe contract. Opt-in — declare higher
    # timeframes here (e.g. ["1h"]) and call self.htf("1h") inside prepare()
    # (after super().prepare(candles)) to get an as-of aligned, lookahead-safe
    # base-length OHLCV array. Default [] is a no-op: no fetch, no alignment,
    # byte-identical to a strategy that never touches htf() at all.
    informative_timeframes: list[str] = []

    def __init__(self):
        # Candle data — set by the backtest/live engine before each call
        self.candles: np.ndarray = np.array([])
        self.exchange: str = ""
        self.symbol: str = ""
        self.timeframe: str = ""

        # Position state — set by the engine
        self.position = None
        self.balance: float = 0.0
        self.available_margin: float = 0.0
        self.leverage: int = 1
        self.fee_rate: float = 0.001
        self.exchange_type: str = "futures"  # "spot" | "futures"

        # Order setters — strategy writes to these, engine reads them
        self.buy = None        # (qty, price) or [(qty, price), ...]
        self.sell = None       # (qty, price) or [(qty, price), ...]
        self.stop_loss = None  # (qty, price) or [(qty, price), ...]
        self.take_profit = None  # (qty, price) or [(qty, price), ...]

        # Pending atomic flip — written only by flip_position(), consumed and
        # cleared by the engine. Never mutate directly from strategy code.
        self._pending_flip: dict | None = None

        # Plan 6 Step 6.3 phase (d1) — persisted typed mirror of the last
        # OrderPlan route() built (or the exec_algo-sliced replacement, when
        # configured), for EVERY path including exit/flip/maintain, not just
        # enter. Written by DefaultExecution.route() (core/models/execution.py)
        # additively, alongside (not instead of) the mutable tuples above —
        # this field has NO readers yet (d2+ migrates read sites one cluster
        # at a time per the phase (d) scoping doc; see DECISIONS.md). Engine-
        # internal; not documented as a strategy-facing property.
        self.active_bracket = None  # OrderPlan | None

        # Candle index counter — incremented by engine on each candle
        self.index: int = 0

        # Custom variables — strategy can store anything here
        self.vars: dict = {}

        # ── Plan 13: informative / multi-timeframe state ─────────────────────
        # _htf_raw: raw HTF candle arrays keyed by timeframe string, populated
        # by the runner/live manager BEFORE prepare() runs (never by the
        # strategy itself). _htf_base_candles / _htf_aligned_cache are set by
        # prepare() below and consumed by htf().
        self._htf_raw: dict = {}
        self._htf_base_candles: np.ndarray = np.array([])
        self._htf_aligned_cache: dict = {}

        # Mode flags — set by engine
        self.is_backtesting: bool = False
        self.is_livetrading: bool = False
        self.is_papertrading: bool = False

        # ── Risk Model — injected by runner from settings/risk_params ────────
        # D6: risk_pct is no longer a strategy PARAMS field. It is injected
        # from Tier 2 Risk settings. Strategies read self.risk_pct but never
        # declare it in PARAMS.
        self.risk_pct:         float = 0.01    # fraction of capital risked per trade
        self.rrr:              float = 2.0     # reward-to-risk ratio for TP calculation
        self.liq_buffer_pct:   float = 0.005  # minimum gap between SL and liquidation price
        self.max_session_dd:   float = 0.20   # session drawdown limit (halts new entries)
        self.slippage_pct:     float = 0.0005 # assumed adverse slippage on market fills
        # fee_rate already declared above

        # ── Risk Tracking — updated by runner each candle ────────────────────
        self.peak_equity:      float = 0.0   # highest equity seen this session
        self.session_drawdown: float = 0.0   # (peak - equity) / peak; checked by can_trade()
        self.available_capital: float = 0.0  # shared capital pool; decremented on open, credited on close
        # F-017 shared-wallet (multi-symbol portfolio backtest): margin locked by
        # OTHER symbols' open positions against the shared balance. Entry
        # affordability checks free capital = balance - this. Always 0.0 for
        # single-symbol runs, so single-symbol behaviour is unchanged.
        self._external_reserved_margin: float = 0.0

        # ── Execution ────────────────────────────────────────────────────────
        self._close_at_open:   bool  = False   # set by close_position(); consumed by runner step A1
        self.order_type:       str   = "market" # "market" | "limit"
        self.limit_offset:     float = 0.0      # price offset for limit entries

        # ── DCA / position adjustment (A-014) ──────────────────────────────
        self.qty_to_adjust: float = 0.0  # signed delta; positive=increase, negative=decrease
        self.adjust_tag: str = ""        # tag for the adjustment leg

        # ── Entry/exit tagging (A-015) ──────────────────────────────────────
        self.entry_tag: str = ""  # set by strategy forecast() to label the entry signal
        self.exit_tag: str = ""   # set by strategy forecast() to label the exit signal

        # ── Five-Model Quant Architecture (see plan.md) ──────────────────────
        # The strategy itself is the Alpha Model (forecast()/should_*). The other
        # four models are pluggable; defaults reproduce legacy behavior exactly.
        # Override per-strategy by reassigning any of these in the subclass.
        self.alpha_model     = self               # self IS the Alpha Model
        self.risk_model      = DefaultRiskModel()
        self.cost_model      = DefaultCostModel()
        self.portfolio_model = DefaultPortfolioModel()
        self.execution_model = DefaultExecution()

    # ─────────────────────────────────────────
    # Candle property accessors
    # ─────────────────────────────────────────

    @property
    def current_candle(self) -> np.ndarray:
        """Returns the current candle as [timestamp, open, close, high, low, volume]"""
        return self.candles[-1] if len(self.candles) > 0 else np.array([])

    @property
    def close(self) -> float:
        return float(self.current_candle[CLOSE]) if len(self.current_candle) > 0 else 0.0

    @property
    def price(self) -> float:
        return self.close

    @property
    def open(self) -> float:
        return float(self.current_candle[OPEN]) if len(self.current_candle) > 0 else 0.0

    @property
    def high(self) -> float:
        return float(self.current_candle[HIGH]) if len(self.current_candle) > 0 else 0.0

    @property
    def low(self) -> float:
        return float(self.current_candle[LOW]) if len(self.current_candle) > 0 else 0.0

    @property
    def volume(self) -> float:
        return float(self.current_candle[VOLUME]) if len(self.current_candle) > 0 else 0.0

    # ─────────────────────────────────────────
    # Position property accessors
    # ─────────────────────────────────────────

    @property
    def is_open(self) -> bool:
        return self.position is not None and self.position.is_open

    @property
    def is_close(self) -> bool:
        return not self.is_open

    @property
    def is_long(self) -> bool:
        return self.is_open and self.position.type == "long"

    @property
    def is_short(self) -> bool:
        return self.is_open and self.position.type == "short"

    @property
    def is_live(self) -> bool:
        return self.is_livetrading or self.is_papertrading

    @property
    def equity(self) -> float:
        """Wallet balance plus unrealized P&L of any open position."""
        unrealized = self.position.pnl if (self.position is not None and self.position.is_open) else 0.0
        return self.balance + unrealized

    @property
    def is_spot_trading(self) -> bool:
        return self.exchange_type == "spot"

    @property
    def is_futures_trading(self) -> bool:
        return self.exchange_type == "futures"

    # ─────────────────────────────────────────
    # Required methods — must be overridden
    # ─────────────────────────────────────────

    def should_long(self) -> bool:
        """Return True to open a long position. Called only when no position is open.

        Default: False. Override in legacy strategies; ported strategies implement
        forecast() instead and leave should_long/short at their defaults.
        """
        return False

    def should_short(self) -> bool:
        """Return True to open a short position. Called only when no position is open.

        Default: False. Override in legacy strategies; ported strategies implement
        forecast() instead and leave should_long/short at their defaults.
        """
        return False

    def should_cancel_entry(self) -> bool:
        """Return True to cancel a pending entry order before it fills."""
        return False

    def go_long(self) -> None:
        """Define entry, stop-loss, and take-profit for a long trade.

        Default: no-op (pass). Legacy strategies override this; ported strategies
        implement forecast() and let route() write the order state.
        """

    def go_short(self) -> None:
        """Define entry, stop-loss, and take-profit for a short trade.

        Default: no-op (pass). Legacy strategies override this; ported strategies
        implement forecast() and let route() write the order state.
        """

    # ─────────────────────────────────────────
    # Optional lifecycle methods — override as needed
    # ─────────────────────────────────────────

    def prepare(self, candles: np.ndarray) -> None:
        """One-time vectorized indicator pre-computation.

        Called ONCE by the backtest runner before the simulation loop, and once
        per closed candle in live trading (on the rolling candle window). Move
        every TA-Lib / pandas indicator call here, storing results as ``self._*``
        full-length arrays/scalars over the supplied ``candles``; ``before()``
        then becomes a pure index lookup at ``self.index`` (no TA-Lib calls).

        Default: no-op — strategies that still compute in ``before()`` keep
        working unchanged. Index alignment: the runner sets ``self.index`` to the
        absolute index into the same array passed here, so ``self._arr[self.index]``
        is always valid.

        Plan 13: also the base-class anchor for ``htf()`` — stashes ``candles``
        as the alignment target and clears the per-call HTF cache. A subclass
        using ``htf()`` must call ``super().prepare(candles)`` as its first
        line (same requirement live's rolling-window re-prepare already
        satisfies automatically, since it re-invokes the same ``prepare()``).
        """
        self._htf_base_candles = candles
        self._htf_aligned_cache = {}

    def before(self) -> None:
        """Called before each candle. Use for updating self.vars.

        For migrated strategies this is index-only: read pre-computed ``self._*``
        arrays at ``self.index`` and populate ``self.vars``. No TA-Lib calls.
        """
        pass

    def after(self) -> None:
        """Called after each candle. Use for cleanup or logging."""
        pass

    def update_position(self) -> None:
        """Called every candle when a position is open.
        Use to update stop-loss, take-profit, or add to position.
        """
        pass

    def before_terminate(self) -> None:
        """Called right before termination. Can submit orders."""
        pass

    def terminate(self) -> None:
        """Called on termination. Cannot submit orders. Use for logging."""
        pass

    # ─────────────────────────────────────────
    # Optional event methods — override as needed
    # ─────────────────────────────────────────

    def on_open_position(self, order) -> None:
        """Called right after an open-position order is executed."""
        pass

    def on_close_position(self, order) -> None:
        """Called when position is closed by stop-loss or take-profit."""
        pass

    def on_increased_position(self, order) -> None:
        """Called when position size is increased."""
        pass

    def on_reduced_position(self, order) -> None:
        """Called when position size is reduced (but not closed)."""
        pass

    def on_cancel(self) -> None:
        """Called after all active orders are canceled."""
        pass

    # ─────────────────────────────────────────
    # Risk-based sizing & stop/target helpers
    # ─────────────────────────────────────────
    #
    # These centralize the platform's risk rules so strategies don't each
    # reimplement (and get wrong) position sizing. All are additive — the
    # legacy ``self.buy = qty, price`` pattern still works untouched.

    def _atr(self, period: int = 14) -> float:
        """Latest ATR. Lazy-imports indicators to avoid an import cycle."""
        import indicators as ta
        return float(ta.atr(self.candles, period=period))

    # ─────────────────────────────────────────
    # Informative / multi-timeframe (Plan 13)
    # ─────────────────────────────────────────

    def htf(self, timeframe: str) -> np.ndarray:
        """As-of aligned, lookahead-safe higher-timeframe OHLCV, base-length.

        Requires ``timeframe`` in ``self.informative_timeframes`` and the
        engine to have populated ``self._htf_raw[timeframe]`` (raw HTF
        candles) before ``prepare()`` ran — the backtest runner and live bot
        manager both do this for every declared timeframe. Call only from
        ``prepare()``, after ``super().prepare(candles)``.

        Alignment rule (ported from freqtrade's ``merge_informative_pair``
        ffill+shift): for each base candle at open-time ``t``, the returned
        row is the most recent HTF candle whose CLOSE time (``open +
        timeframe_duration``) is ``<= t``. A base candle therefore only ever
        sees an HTF candle that had *fully closed* at or before that base
        candle's own open — never the in-progress HTF bar, never a bar that
        closes later. Base candles before the first HTF close get an all-NaN
        row (no meaningful value yet — same "not enough warmup" situation as
        any indicator with too few candles).

        Returns a ``(len(base_candles), 6)`` array in the same
        ``[timestamp_ms, open, close, high, low, volume]`` layout as
        ``self.candles``, so any ``ta.*(..., sequential=True)`` call indexes
        it identically to a base-timeframe series. Cached per timeframe for
        the lifetime of the current ``prepare()`` call — multiple indicators
        referencing the same HTF align once, not once per call.
        """
        if timeframe in self._htf_aligned_cache:
            return self._htf_aligned_cache[timeframe]

        from utils.timeframes import to_ms

        base = self._htf_base_candles
        aligned = np.full((len(base), 6), np.nan, dtype=np.float64)
        raw = self._htf_raw.get(timeframe)
        if raw is not None and len(raw) > 0 and len(base) > 0:
            htf_close_times = raw[:, TIMESTAMP] + to_ms(timeframe)
            base_times = base[:, TIMESTAMP]
            idx = np.searchsorted(htf_close_times, base_times, side="right") - 1
            valid = idx >= 0
            aligned[valid] = raw[idx[valid]]

        self._htf_aligned_cache[timeframe] = aligned
        return aligned

    def size_by_risk(
        self, stop_price: float, risk_pct: float | None = None, entry_price: float | None = None
    ) -> float:
        """Quantity such that hitting ``stop_price`` loses ``risk_pct`` of equity.

        Implements platform rule #6: ``(equity * risk_pct) / |entry - stop|``,
        capped by ``max_qty()`` so a tight stop can never demand more notional
        than the account's leverage allows. ``risk_pct`` defaults to
        ``self.risk_pct`` (else 1%).

        Delegates to the Risk Model (Phase 1: one owner of risk-budget sizing) so
        a custom ``risk_model`` can change sizing for every strategy at once; the
        default is byte-identical to the former inline computation.
        """
        return self.risk_model.risk_budget_qty(self, stop_price, risk_pct, entry_price)

    def size_by_notional(self, pct: float | None = None, entry_price: float | None = None) -> float:
        """Legacy sizing: allocate ``pct`` of equity as notional (qty = equity*pct/price).

        Kept for strategies that intentionally want fixed-fraction notional
        rather than risk-based sizing. Also capped by ``max_qty()`` and by
        what's actually affordable (Plan 24 finding S-1): at ``pct=1.0`` and
        leverage=1, the naive qty sits exactly on the equity boundary, so
        adverse slippage + the taker fee alone push `req_margin + fee` just
        over `free_balance` and every entry is rejected outright downstream
        (`execute_entry`'s `EntryFill.affordable()` check). Sizing DOWN to
        the true affordable notional (freqtrade-style stake adjustment)
        keeps a `pct=1.0` config functional instead of structurally dead.
        """
        entry = entry_price if entry_price is not None else self.price
        if pct is None:
            pct = float(getattr(self, "risk_pct", 0.1))
        if entry <= 0:
            return 0.0
        qty = (self.equity * pct) / entry
        qty = min(qty, self.max_qty(entry))

        leverage = max(float(getattr(self, "leverage", 1.0)), 1.0)
        fee_rate = float(getattr(self, "fee_rate", 0.0))
        slippage_pct = float(getattr(self, "slippage_pct", 0.0))
        free_balance = self.balance - float(getattr(self, "_external_reserved_margin", 0.0))
        # affordability: notional/leverage + notional*fee_rate <= free_balance
        # notional = qty * entry * (1+slippage_pct)  (conservative — same
        # (1+slip) bound for both buy/sell sides, per adverse_fill's buy case)
        denom = (1.0 / leverage + fee_rate) * (1.0 + slippage_pct)
        if denom > 0 and free_balance > 0:
            # Tiny safety margin (1e-6) so float rounding differences between
            # this formula and the downstream real fill/fee computation can
            # never flip an exact-boundary size back into "unaffordable".
            affordable_qty = (free_balance / (denom * entry)) * (1.0 - 1e-6)
            qty = min(qty, affordable_qty)
        return max(qty, 0.0)

    def max_qty(self, entry_price: float | None = None) -> float:
        """Max quantity affordable: full equity at current leverage as margin."""
        entry = entry_price if entry_price is not None else self.price
        if entry <= 0:
            return 0.0
        max_notional = self.equity * max(self.leverage, 1)
        
        symbol_max_exposure = float(getattr(self, "max_exposure_notional", float('inf')))
        max_notional = min(max_notional, symbol_max_exposure)
        
        return max_notional / entry

    def atr_stop(self, direction: str, mult: float = 2.0, period: int = 14,
                 entry_price: float | None = None) -> float:
        """ATR-based stop price. long: entry - mult*ATR, short: entry + mult*ATR.

        Delegates to the Risk Model (Phase 1: one owner of stop placement); the
        default is byte-identical to the former inline computation.
        """
        return self.risk_model.atr_stop(self, direction, mult, period, entry_price)

    def rr_target(self, direction: str, stop_price: float, rr: float = 2.0,
                  entry_price: float | None = None) -> float:
        """Take-profit at a risk:reward multiple of the stop distance."""
        entry = entry_price if entry_price is not None else self.price
        risk = abs(entry - stop_price)
        if direction == "long":
            return entry + rr * risk
        return entry - rr * risk

    def trail_stop(self, atr_mult: float = 2.0, period: int = 14) -> None:
        """Ratchet the stop-loss toward price by ``atr_mult`` ATR. Only ever
        tightens (moves up for longs, down for shorts) — never loosens.
        Call from ``update_position()`` while a position is open."""
        if not self.is_open:
            return
        qty = self.position.qty
        atr = self._atr(period)
        if self.is_long:
            new_sl = self.price - atr_mult * atr
            cur = self.stop_loss[1] if self.stop_loss else None
            if cur is None or new_sl > cur:
                self.stop_loss = qty, new_sl
        elif self.is_short:
            new_sl = self.price + atr_mult * atr
            cur = self.stop_loss[1] if self.stop_loss else None
            if cur is None or new_sl < cur:
                self.stop_loss = qty, new_sl

    def move_to_breakeven(self, buffer_pct: float = 0.0) -> None:
        """Move the stop to the entry price (plus a small buffer in the profit
        direction). No-op if it would loosen the existing stop."""
        if not self.is_open:
            return
        qty = self.position.qty
        entry = self.position.entry_price
        if self.is_long:
            be = entry * (1.0 + buffer_pct)
            cur = self.stop_loss[1] if self.stop_loss else None
            if cur is None or be > cur:
                self.stop_loss = qty, be
        elif self.is_short:
            be = entry * (1.0 - buffer_pct)
            cur = self.stop_loss[1] if self.stop_loss else None
            if cur is None or be < cur:
                self.stop_loss = qty, be

    # ─────────────────────────────────────────
    # Atomic flip (close-and-reverse)
    # ─────────────────────────────────────────

    def flip_position(self, qty: float, stop_loss: float | None = None,
                      take_profit: float | None = None) -> None:
        """Atomically close the open position and open the opposite side.

        Call from ``update_position()`` while a position is open. The engine
        executes both legs as one unit (Pine-Script ``strategy.entry()``
        reversal semantics): the old position is closed and the new opposite
        position is opened at the same execution point, with ``stop_loss`` /
        ``take_profit`` armed on the new position immediately — there is never
        a window where the reversed position runs unprotected.

        Do NOT combine this with writing ``self.buy`` / ``self.sell`` while a
        position is open — that legacy pattern corrupts the open position's
        exit plan and is exactly what this primitive replaces.

        If the new leg cannot be afforded (margin + fee exceeds balance) or
        any live order fails, the flip degrades to close-only: the engine
        never leaves a doubled or unprotected position.
        """
        if not self.is_open:
            raise RuntimeError("flip_position() requires an open position")
        self._pending_flip = {
            "direction": "short" if self.is_long else "long",
            "qty": float(qty),
            "stop_loss": stop_loss,
            "take_profit": take_profit,
        }

    @property
    def has_pending_flip(self) -> bool:
        return self._pending_flip is not None

    # ─────────────────────────────────────────
    # Utility methods
    # ─────────────────────────────────────────

    def adjust_trade_position(self) -> tuple[float, str] | None:
        """Override to scale in/out. Returns (qty_delta, tag) or None.

        Called every candle when a position is open. Positive qty_delta
        increases the position (scale in), negative decreases it (scale out).
        The tag is propagated to trade records for per-tag analytics (A-015).

        Example::

            def adjust_trade_position(self):
                if self.position.pnl_pct < -5.0 and self.position.qty < self.max_dca_qty:
                    return self.size_by_risk(self.stop_loss[1]), "dca_dip"
                return None
        """
        return None

    def liquidate(self) -> None:
        """[DEPRECATED] Close the open position at market price.

        Prefer ``close_position()`` — it guarantees a next-open market exit
        that cannot be pre-empted by SL/TP checks (BUG-03 fix). This method
        is kept for backward compatibility only.
        """
        if self.is_open:
            if self.is_long:
                self.take_profit = self.position.qty, self.price
            else:
                self.stop_loss = self.position.qty, self.price

    def log(self, msg: str) -> None:
        """Log a message during strategy execution."""
        logging.getLogger("BaseStrategy").info("[%s] %s", self.symbol, msg)

    # ─────────────────────────────────────────
    # Model hooks — override for advanced control
    # ─────────────────────────────────────────

    def forecast(self) -> Signal:
        """Alpha Model output: direction + conviction for this candle.

        Default derives a unit-conviction Signal from should_long()/should_short()
        so every existing strategy is an Alpha Model with no changes. Override to
        emit continuous conviction in [0, 1]. Consumed by the shared decision
        pipeline; alpha() is kept as the legacy signed-float view.
        """
        if self.should_long():
            return Signal(direction=1, conviction=1.0, ref_price=self.price)
        if self.should_short():
            return Signal(direction=-1, conviction=1.0, ref_price=self.price)
        return Signal(direction=0, conviction=0.0, ref_price=self.price)

    def alpha(self) -> float:
        """Signal strength: +1.0 long, -1.0 short, 0.0 flat.

        Legacy signed-float view over forecast() — preserves the boolean-hook
        behavior so existing call sites (backtest runner step C) are unchanged.
        """
        return float(self.forecast().direction)

    def can_trade(self) -> bool:
        """Risk circuit breaker. Returns False to halt new entries.

        Delegates to the Risk Model. Position management (update_position) still
        runs even when False. Default: halt when session drawdown exceeds the
        max_session_dd threshold. Override risk_model to customize.
        """
        return self.risk_model.can_trade(self)

    def alpha_beats_cost(self, signal: float) -> bool:
        """TCM gate. Return False to veto the entry after alpha() fires.

        Strategies can override to skip entries when expected edge < cost.
        Default: always trade (no veto).
        """
        return True

    def target_weight(self) -> float:
        """PCM: desired equity weight for this strategy (0.0–1.0).

        0.0 means use the qty from go_long()/go_short() directly.
        Non-zero values are for portfolio-level capital allocation.
        """
        return 0.0

    def close_position(self) -> None:
        """Guaranteed market exit at the next candle's open price.

        Unlike liquidate(), this flag is checked in runner step A1 *before*
        SL/TP, so the exit cannot be pre-empted by the SL leg firing at a
        worse price (BUG-03 fix). Use this for all strategy-driven exits.
        """
        if self.is_open:
            self._close_at_open = True

    def validate_params(self) -> None:
        """Override to raise ValueError for invalid cross-param constraints.

        Called by the runner after alpha_params are injected (D13). Raising
        ValueError here aborts the backtest with a clear error message.
        Example::

            if self.fast_period >= self.slow_period:
                raise ValueError("fast_period must be < slow_period")
        """
        pass
