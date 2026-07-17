"""Session Risk Governor (Plan 22 Step 22.1).

One engine component, owned by the session (not per-symbol, unlike the
five-model pipeline's per-symbol strategy instances) — the governor sees the
whole session's aggregate state, which is exactly what per-symbol risk
models structurally cannot: `AtrBracketRiskModel.can_trade()` and friends
only ever see one symbol's slice of capital (B-3's finding).

Evaluated at two points (Part C of `22_risk-management-industry-standard.md`):
  1. Pre-trade — inside `LiveAdapter.execute_entry`, after the existing
     A-001 (protections) / A-002 (trading_state) / A-003 (rate limit) gates.
     Can veto the entry.
  2. Periodic — on each `_push_stats` tick (already aggregates per-symbol
     state into session-level totals). A breach of a *standing* limit
     auto-transitions `trading_state` — the governor itself never flips
     state or places orders; it returns a verdict and the caller (
     `LiveBotManager`) acts on it, exactly like `ProtectionManager` already
     does for `check_entry()`.

22.1 ships three hard checks, all fail-closed by default (cannot compute the
metric -> block, never silently pass):
  - Aggregate session drawdown (periodic + pre-trade) — supersedes Plan 21
    step 21.6 / finding A-10 (per-symbol-slice-only drawdown was never
    aggregated). Tracks a session equity high-water mark; breach when
    current equity has drawn down more than `max_session_dd` from it.
  - Daily realized loss limit (periodic + pre-trade) — off by default
    (`max_daily_loss_pct=None`). UTC-midnight anchor (DECISIONS.md #23).
  - Margin utilization ceiling (pre-trade only) — vetoes an entry that would
    push total margin committed past `max_margin_utilization` of equity.

Portfolio open-risk budget, VaR, correlation, and liquidation-buffer checks
are 22.2/22.4/22.5's scope — deliberately not here yet (Part D: each step
independently shippable).

Auto-flatten (force-close everything on `halted`) is a per-user opt-in,
default off (DECISIONS.md #23) — `auto_flatten_on_halt` is exposed as a
config flag for the caller to read; the governor itself never places orders
(Part C's explicit design constraint) — flattening is `LiveBotManager`'s job.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone


@dataclass
class GovernorVerdict:
    """Result of a governor check — mirrors `ProtectionReturn`'s shape
    (`core/models/protections.py`) for consistency with the existing
    protections-stack pattern this repo already uses."""
    ok: bool = True
    reason: str = ""
    check_name: str = ""


class SessionRiskGovernor:
    """Session-scoped risk governor. One instance per live session, stored
    in `session["risk_governor"]` alongside `session["protection_manager"]`.

    Config keys (all optional, resolve through the existing Zone 2 cascade
    server-side before reaching here — 22.1 reads them as plain floats with
    engine-side defaults; full Zone 2 schema/UI wiring is 22.7's scope):
      max_session_dd         (float, default 0.20)   — existing knob, now session-scoped
      max_daily_loss_pct     (float|None, default None = off)
      max_margin_utilization (float, default 0.8)
      max_portfolio_risk     (float, default 0.06)   — 22.2: same field name
                              `core/models/portfolio.py` already reads per-symbol
                              (config compat); here it's the TRUE cross-symbol
                              aggregate, which per-symbol construct() structurally
                              cannot compute (Plan 21 audit finding). <= 0 disables.
      breach_action           ("reducing"|"halted", default "reducing")
      auto_flatten_on_halt   (bool, default False)   — DECISIONS.md #23
    """

    def __init__(self, config: dict | None = None) -> None:
        cfg = config or {}
        self.max_session_dd = float(cfg.get("max_session_dd", 0.20))
        raw_daily = cfg.get("max_daily_loss_pct")
        self.max_daily_loss_pct: float | None = (
            float(raw_daily) if raw_daily not in (None, "") else None
        )
        self.max_margin_utilization = float(cfg.get("max_margin_utilization", 0.8))
        self.max_portfolio_risk = float(cfg.get("max_portfolio_risk", 0.06))
        breach_action = cfg.get("breach_action", "reducing")
        self.breach_action = breach_action if breach_action in ("reducing", "halted") else "reducing"
        # DECISIONS.md #23: opt-in, off by default. The governor never acts
        # on this itself — it's a switch the caller reads when applying a
        # "halted" transition, to decide whether to also force-close.
        self.auto_flatten_on_halt = bool(cfg.get("auto_flatten_on_halt", False))

        self._session_peak_equity: float | None = None
        self._daily_anchor_date: date | None = None
        self._daily_realized_loss: float = 0.0

    # ── Daily-loss bookkeeping ───────────────────────────────────────────

    def _roll_daily_anchor_if_needed(self, now: datetime) -> None:
        """UTC-midnight anchor (DECISIONS.md #23, Part F Q2) — resets the
        realized-loss accumulator whenever the UTC calendar date rolls over,
        regardless of when the session itself started."""
        today = now.astimezone(timezone.utc).date()
        if self._daily_anchor_date != today:
            self._daily_anchor_date = today
            self._daily_realized_loss = 0.0

    def record_realized_pnl(self, pnl: float, now: datetime) -> None:
        """Feed the daily-loss tracker on every trade close. Only losses
        accumulate (a winning trade doesn't offset a prior loss within the
        same day — this is a loss *limit*, not a net-PnL floor, matching
        freqtrade's `max_daily_loss` semantics)."""
        self._roll_daily_anchor_if_needed(now)
        if pnl < 0:
            self._daily_realized_loss += abs(pnl)

    # ── Equity high-water mark ───────────────────────────────────────────

    def _update_peak(self, equity: float) -> None:
        if equity > 0 and (self._session_peak_equity is None or equity > self._session_peak_equity):
            self._session_peak_equity = equity

    # ── Standing limits (drawdown + daily loss) — periodic AND pre-trade ─

    def _check_standing_limits(self, equity: float, now: datetime) -> GovernorVerdict:
        self._update_peak(equity)

        if self._session_peak_equity and self._session_peak_equity > 0:
            drawdown = (self._session_peak_equity - equity) / self._session_peak_equity
            if drawdown > self.max_session_dd:
                return GovernorVerdict(
                    ok=False,
                    reason=(
                        f"aggregate session drawdown {drawdown:.1%} exceeds "
                        f"max_session_dd {self.max_session_dd:.1%} "
                        f"(peak equity ${self._session_peak_equity:.2f}, current ${equity:.2f})"
                    ),
                    check_name="aggregate_drawdown",
                )

        if self.max_daily_loss_pct is not None:
            self._roll_daily_anchor_if_needed(now)
            # Peak equity is the more stable denominator (a mid-day drawdown
            # shouldn't itself shrink the loss-limit base); fall back to
            # current equity only if no peak has been observed yet.
            base = self._session_peak_equity if self._session_peak_equity else equity
            if base > 0:
                daily_loss_pct = self._daily_realized_loss / base
                if daily_loss_pct > self.max_daily_loss_pct:
                    return GovernorVerdict(
                        ok=False,
                        reason=(
                            f"daily realized loss {daily_loss_pct:.1%} exceeds "
                            f"max_daily_loss_pct {self.max_daily_loss_pct:.1%} "
                            f"(${self._daily_realized_loss:.2f} realized loss since UTC midnight)"
                        ),
                        check_name="daily_loss_limit",
                    )

        return GovernorVerdict(ok=True)

    # ── Public checks ─────────────────────────────────────────────────────

    def check_pre_trade(self, *, equity: float, used_margin: float, now: datetime) -> GovernorVerdict:
        """Called from `execute_entry`, after A-001/A-002/A-003. Vetoes the
        entry (returns `ok=False`) on any hard-check breach."""
        standing = self._check_standing_limits(equity, now)
        if not standing.ok:
            return standing

        # Margin utilization ceiling — pre-trade only (Part C's table).
        # Fail-closed: cannot compute (equity <= 0) -> block, never silently pass.
        if equity <= 0:
            return GovernorVerdict(
                ok=False,
                reason="equity <= 0 — cannot compute margin utilization (fail-closed)",
                check_name="margin_utilization",
            )
        utilization = used_margin / equity
        if utilization > self.max_margin_utilization:
            return GovernorVerdict(
                ok=False,
                reason=(
                    f"margin utilization {utilization:.1%} exceeds ceiling "
                    f"{self.max_margin_utilization:.1%} (used ${used_margin:.2f} / equity ${equity:.2f})"
                ),
                check_name="margin_utilization",
            )
        return GovernorVerdict(ok=True)

    def check_periodic(self, *, equity: float, now: datetime) -> GovernorVerdict:
        """Called on each `_push_stats` tick. A breach here signals the
        caller to auto-transition `trading_state` (via `self.breach_action`)
        — this method itself only evaluates, never mutates session state."""
        return self._check_standing_limits(equity, now)

    def check_portfolio_risk(self, *, open_risk: float, equity: float) -> GovernorVerdict:
        """Plan 22 Step 22.2: true cross-symbol open-risk budget — pre-trade
        only, called from `execute_entry` once the candidate entry's own
        stop/qty are known. `open_risk` is the caller-computed sum of
        `|entry - stop| * qty` across every currently-open position PLUS the
        candidate entry being evaluated (this method takes the plain total,
        same separation-of-concerns as `check_pre_trade`'s equity/used_margin
        — the governor never reaches into session/strategy internals itself).

        This supersedes `DefaultPortfolioModel.construct()`'s `max_portfolio_risk`
        check (`core/models/portfolio.py`), which is structurally per-symbol
        only (each symbol's pipeline call has no visibility into other open
        symbols) despite the name suggesting a portfolio-wide budget — a Plan
        21 audit finding. That per-symbol check is left in place (backtest
        has no session-level governor to route to, and removing it would be
        a golden-master-risking behavior change for no live benefit); this is
        the actual cross-symbol enforcement point for live/chaos sessions.

        `max_portfolio_risk <= 0` disables this check entirely (matches
        `portfolio.py`'s own "0 disables" convention for the same field).
        Fails closed on equity <= 0 (cannot compute a percentage), same as
        the margin ceiling check.
        """
        if self.max_portfolio_risk <= 0:
            return GovernorVerdict(ok=True)
        if equity <= 0:
            return GovernorVerdict(
                ok=False,
                reason="equity <= 0 — cannot compute portfolio open-risk budget (fail-closed)",
                check_name="portfolio_open_risk",
            )
        risk_pct = open_risk / equity
        if risk_pct > self.max_portfolio_risk:
            return GovernorVerdict(
                ok=False,
                reason=(
                    f"aggregate open risk {risk_pct:.1%} (across all open positions + this "
                    f"candidate entry) exceeds max_portfolio_risk {self.max_portfolio_risk:.1%} "
                    f"(${open_risk:.2f} at risk / equity ${equity:.2f})"
                ),
                check_name="portfolio_open_risk",
            )
        return GovernorVerdict(ok=True)
