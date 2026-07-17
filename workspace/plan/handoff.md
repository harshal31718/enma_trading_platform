# Session Handoff Log

Resume prompts for cross-session continuity (root `CLAUDE.md` Rule G / `AGENTS.md` → Session Handoff).

**Format rules:**
- Newest entry on top: `## <date> — <title> — <status>` with **Goal / Done / Files changed / Open questions**.
- Keep at most the **3 most recent entries**. When adding a new one, delete the oldest — git history is the archive. This file must stay a short resume prompt, not a project log.

---
## 2026-07-17 — Plan 9.11 Step A shipped: PCM edge-vs-cost gate rewired to the object it actually reads, formula fixed to quote-vs-quote, `Signal.magnitude` wired in — **golden-master-inert, no live-verification gap** ✅

**Goal:** with Plan 24 fully shipped and only live Testnet re-verification left pending (same
genuinely-blocked status as Plan 22), surveyed `0_tracker.md`'s Active work table fresh for the
next unblocked, decision-free item per the prior handoff's own suggestion. Compared Plan 13
(multi-timeframe `htf()` contract — a new contract spanning 3 files, real design surface) against
Plan 9.11 Step A (cost-gate resurrection — three `[Certain]` audit findings, explicitly scoped by
the plan's own text as "Step A: golden-master-inert", no decisions needed). Chose 9.11 Step A —
same shape as what made Plan 24 tractable in one session.

**Done:** `engine/core/models/portfolio.py`'s `DefaultPortfolioModel._edge_beats_cost()` — the
PCM edge-vs-cost veto that Plan 21's five-model audit found was dead on arrival:
- **M-1 (wired to the wrong object):** `backtest_runner.py`/`live_bot_manager.py` both injected
  `min_edge_mult` onto `strategy.cost_model`, but the gate reads `self.min_edge_mult` where `self`
  is the **portfolio model** instance. Both injection sites now write
  `strategy.portfolio_model.min_edge_mult` instead.
- **M-2 (dimensionally inconsistent):** the old formula compared a bare per-unit price distance
  (`conviction × risk_per_unit × rrr`) against a whole-position quote-currency cost, making the
  veto boundary a function of the symbol's absolute price level (always-pass on BTC, always-veto
  on sub-cent symbols). Fixed to quote-vs-quote: `edge_total = edge_frac × risk_per_unit ×
  qty_est × rrr`, using the same `qty_est = min(budget/risk_per_unit, max_notional/price)` the
  Cost Model already computes internally for `cost.total`.
- **M-3 (dead field):** `Signal.magnitude` was documented as feeding this gate but read by
  nothing. `edge_frac` now uses `sig.magnitude` when the alpha model provides one (nonzero),
  falling back to `abs(sig.conviction)` otherwise.
- **Also fixed both injection sites' default** from `0.05` to `0.0` per the plan's own Step A
  instruction — since the `0.05` never reached the gate under the M-1 bug, this is a no-op, not a
  behavior change (confirmed by golden master below).

**Verification:** new `engine/tests/test_edge_beats_cost_gate.py` (5 cases) — gate-off always
passes regardless of cost; a scaled-edge boundary case flips on cost; **the veto boundary is
price-level invariant** (identical relative risk/cost setup on a BTC-priced vs. a sub-cent symbol
produces the identical verdict — the concrete regression test for M-2's fix); magnitude overrides
conviction when provided; the alpha-level veto still short-circuits regardless of `min_edge_mult`.
**Golden master run before/after per root CLAUDE.md Rule C** (extracted pre-change file contents
from `git show HEAD:...` since the container has `volumes: []` and the working files were already
edited — `docker cp`'d the pre-change versions in, captured `pre_9_11_stepA`, `docker cp`'d the
fixed versions back in, captured `post_9_11_stepA`): `compare --a pre_9_11_stepA --b
post_9_11_stepA` → `GOLDEN-MASTER OK` (5/5 seeded strategies, tol 1e-6). Container suite:
**358/358 passed** (up from 353/353 at session start).

**Files changed:** `engine/core/models/portfolio.py` (`_edge_beats_cost`),
`engine/services/backtest_runner.py` (injection site), `engine/core/live_bot_manager.py`
(injection site); new `engine/tests/test_edge_beats_cost_gate.py`; docs:
`9_backtest-and-optimizer-correctness.md`, `21_live-algo-industry-standard-audit.md` (M-1/M-2/M-3
marked fixed), `0_tracker.md`, `handoff.md`. Committed (`8454072`).

**NOT done:** Step B (deciding whether to activate the gate at `min_edge_mult=0.05` by default) is
untouched — the plan's own text requires this be a separate, re-baselined product decision, not
bundled with Step A. The gate exists and is correct now, but is still opt-in/inert by default.

**Next session:** either (a) bring Step B to the user as an explicit product decision (activate at
0.05 default-on vs. leave opt-in), or (b) continue surveying `0_tracker.md` — Plan 13
(multi-timeframe `htf()` contract, P2, self-contained) remains a plausible next candidate, not yet
investigated beyond the initial survey this session.

---
## 2026-07-17 — Plan 24 (S-1 through S-5) shipped: BestSupertrend "never trades at defaults" fixed — **PLAN 24 FULLY SHIPPED**, live Testnet re-verification still pending ⏸️

**Goal:** with Plan 22 fully shipped (see the entry below) and a partial live-verification attempt
made, user asked to proceed to the next plan with my recommendations. Surveyed `0_tracker.md`'s
Active work table and recommended Plan 24 (BestSupertrend fixes) over Plan 9 (larger,
open-ended quant-core work) and Plan 5 (Decimal-money migration, needs a design pass) — Plan 24 is
fully scoped, decision-free, and fixes a real trust bug (a seeded strategy silently never trades at
its own default settings). User agreed implicitly by not redirecting; proceeded through all five
findings (S-1 → S-2 → S-3 → S-4 → S-5) in the plan's own stated order.

**Done — S-1 (root cause, `size_by_notional()` in `core/strategy.py`):** at `position_size_pct=1.0`
(strategy default) and `leverage=1` (platform default), the naive `qty = equity*pct/price` sits
exactly on the equity boundary, so adverse slippage + the taker fee alone push
`req_margin + fee` just over `free_balance`, rejecting every entry (`backtest_runner.py`'s
`EntryFill.affordable()` check) with only a debug log line. Fixed: `size_by_notional()` now sizes
DOWN to the true affordable notional (accounting for leverage/slippage/fee headroom, with a tiny
1e-6 safety margin against float-rounding at the exact boundary) instead of letting the runner
reject the entry outright. Also dropped `position_size_pct` default 1.0→0.9 (belt and braces).
**Golden master re-baselined**: checked the actual `golden_master.py` baseline first (per the
plan's own instruction) — it runs at `leverage=3` (not the platform's `leverage=1` default), so
BestSupertrend already had 61 non-zero trades in the baseline; the fix's diff is entirely from the
`position_size_pct` default change (same 61 trades, same win/loss counts, PnL scaled ~10% smaller),
confirming the fix doesn't touch already-affordable entries. Other 4 strategies byte-identical
(`size_by_notional` has no other caller). New `test_size_by_notional_affordability.py` (7 cases)
exercises the actual bug scenario (leverage=1) the golden-master harness never touches.

**Done — S-2 (live HTF one bar too stale):** `prepare()`'s live/constant path read
`self._htf_tsl[-2]`, but `_fetch_htf_candles` (`live_bot_manager.py`) already excludes the
in-progress HTF bar, so the injected `_htf_candles` array's last row IS the last completed bar —
`[-1]` is correct, matching backtest's bucket path (`htf_tsl[k-1]`). Fixed; warmup guard loosened
from requiring 2 trailing elements to 1. New parity test (5 cases) drives the real class through
both paths against the same underlying supertrend series. Golden master confirmed byte-identical
(live-only branch, never exercised by backtest).

**Done — S-3 (unsatisfiable tf/timeframe combos fail loud):** new
`required_base_candles_for_htf()` (`engine/utils/timeframes.py`) estimates the base-candle count
needed for `pd+2` completed HTF buckets. Wired into `backtest_runner.py` (logs an error, log-only,
zero simulation-output change) and `live_bot_manager.py` (HTF-fetch failure and
on-success-but-insufficient-data are both now session-visible errors, not just a debug-level
warning; a new one-time warning fires once the live rolling candle window hits its 500-candle cap
with the HTF value still unresolved). 8 new unit tests for the shared helper. Golden master
confirmed byte-identical (log-only additions).

**Done — S-4 (`order_type` param collision):** renamed to `direction_filter` — the old name
collided with `OrderPlan.order_type` (`DefaultExecution.route()` builds
`OrderPlan(order_type=getattr(s, "order_type", "market"))`), silently carrying the filter string
instead of `"market"`. Decorative today (both adapters hardcode MARKET) but would have detonated
the moment any consumer honored `OrderPlan.order_type`. Renamed the PARAMS key and all 4 usage
sites; confirmed via direct instantiation that `BaseStrategy`'s own `order_type="market"` default
now shows through correctly. 3 new tests. Golden master confirmed byte-identical (same default
value under a new key name).

**Done — S-5 (docs):** the `SignalExitRiskModel` doc-drift half was already fixed in an earlier
session (confirmed while surveying, before this window started). Updated
`workspace/docs/strategies/BestSupertrend.md` for all of S-1/S-2/S-3/S-4's user-visible changes
(param rename, new default, `tsl[-1]` correction, tf/timeframe warmup note). The weekly-resample
(`W-MON`) off-by-one TODO is intentionally left as a documentation comment only, per the plan's own
instruction — S-3's generic warmup-sufficiency check covers it without touching resample math.

**Files changed:** `engine/core/strategy.py` (`size_by_notional`), `engine/strategies/
BestSupertrend/__init__.py` (S-1 default, S-2 index fix, S-4 rename — all sites), new
`engine/services/backtest_runner.py`/`engine/core/live_bot_manager.py` S-3 wiring, new
`engine/utils/timeframes.py` (`required_base_candles_for_htf`); new test files:
`test_size_by_notional_affordability.py`, `test_bestsupertrend_htf_parity.py`,
`test_required_base_candles_for_htf.py`, `test_bestsupertrend_direction_filter_rename.py`; docs:
`24_bestsupertrend-fixes.md`, `0_tracker.md`, `CURRENT_STATE.md`,
`workspace/docs/strategies/BestSupertrend.md`, `handoff.md`. All committed (4 commits, one per
step S-1–S-4; S-5 folded into this doc-update pass).

**Verification:** container suite **353/353 passed** (up from 337/337 at the start of Plan 24's
work this session). Golden master run before every code change and re-compared after each step —
only S-1 shows an expected, reviewed diff (BestSupertrend only); S-2/S-3/S-4 all byte-identical.

**NOT done — the one item left across Plan 24:** live Testnet re-verification (the plan's own
"Sequencing / verification" section: one 1-symbol testnet session at leverage 2–3, default params,
confirming ≥1 real entry and HTF-value parity against a parallel backtest window). Same standing
"needs a human-observed session" caveat as every other live-verification item across this
codebase's plans (Plan 21, Plan 22) — genuinely blocked, not attempted this session.

**Next session:** live-verify Plan 24 per the paragraph above, OR continue surveying
`0_tracker.md` for the next unblocked item — Plan 9 (backtest/optimizer correctness, P1, larger
and more open-ended) and Plan 13 (multi-timeframe `self.htf()` contract, P2, self-contained) are
both plausible next candidates; neither was investigated this session beyond the initial survey
that picked Plan 24.

---
## 2026-07-17 — Plan 22 Steps 22.5–22.7 shipped: correlation cap, inverse-vol allocation, Zone 2 platform surface — **PLAN 22 FULLY SHIPPED (22.1–22.7)**, live Testnet re-verification still pending ⏸️

**Goal:** user said "proceed non-stop... test via claude in code... if critical input required
mark it pending and jump to a different task" while stepping away. Continued Plan 22 from where
the prior session left off (22.1–22.4 shipped) straight through 22.5, 22.6, 22.7 without stopping
to check in, since each was the plan's own next unblocked item. Live Testnet re-verification is
the one genuinely blocked item (needs a human-observed session) — left explicitly pending rather
than guessed at, per the user's own instruction.

**Done — 22.5 (correlation-aware concentration cap):** `SessionRiskGovernor.
check_correlation_concentration()` (`engine/core/models/governor.py`) — transitive-closure
clustering (BFS) over pairwise `|correlation| > rho` among open positions + the candidate entry,
vetoing when the cluster's combined notional exceeds `max_cluster_exposure_pct` (default 0.4) of
equity. Off by default (`correlation_cap.rho=None`). New `services/portfolio_risk.
fetch_correlation_matrix()` reuses the existing 60s close-price cache. Wired into `execute_entry`
right after the 22.4 VaR/CVaR block, opt-in gated, fails open on a TimescaleDB fetch exception.
Tests: `+8` in `test_session_risk_governor.py`, new `test_execute_entry_correlation_cap.py`
(5 cases). Container suite: 313/313 passed.

**Done — 22.6 (inverse-volatility portfolio allocation layer, golden-master-gated):**
`InverseVolatilityPortfolio`/`compute_realized_volatility()` (`core/models/portfolio.py`) —
weights ∝ 1/realized-vol, an **iterative clamp-and-renormalize** enforcing per-symbol floor/cap
(found and fixed a real bug in this step's own test suite: a single clamp-then-renormalize pass
can push a previously-capped weight back OVER the cap once freed-up mass redistributes — fixed
with an alternating-projection loop). Config-gated via `risk_params["allocation"] ==
"inverse_vol"` (default `"equal"`, byte-identical to prior behavior). Wired into
`backtest_runner.py` (recomputes `capital_splits` after candles load — default path's original
pre-candle-load call left untouched) and `live_bot_manager.py`'s `start_session` (fetches recent
closes via the shared `portfolio_risk.py` cache). **Golden master run before/after per root
CLAUDE.md Rule C**: `python -m scripts.golden_master compare --a pre_22_6 --b post_22_6_v2` →
`GOLDEN-MASTER OK` (5/5 seeded strategies, tol 1e-6) — confirms zero diff for the default case.
Tests: `test_inverse_vol_portfolio.py` (10 cases). Container suite: 323/323 passed.

**Done — 22.7 (Zone 2 platform surface — the last step, Plan 22 is now fully shipped):**
Zone 2 UI (`RiskDashboard.jsx` gained a "Session Risk Governor" form section — 6 optional numeric
inputs + allocation/breach-action selects + auto-flatten checkbox), server schema
(`Settings.js globalHardLimits`: `maxDailyLossPct`, `maxMarginUtilization`, `varLimitPct`,
`cvarLimitPct`, `correlationCap`, `allocation`, `breachAction`, `autoFlattenOnHalt`), server
validation (`risk.controller.js`), and the resolver (`resolveStrategyRiskParams()` in
`utils/risk.js`, global-only pass-through except `allocation` which is also wizard-overridable).
`NewSessionWizard.jsx`/`RiskParamsFields.jsx` gained an allocation dropdown (opt-in
`showAllocation` prop, shown only for 2+ symbols). `SessionCard.jsx` gained a governor state badge
(amber "Reducing" / red "Halted", `GOVERNOR_STYLES`/`GOVERNOR_LABELS`).

**Critical bug found and fixed while wiring 22.7:** `risk_params` as sent by Node is shaped
`{symbol: {...}, "default": {...}}` (one `resolveStrategyRiskParams()` call per symbol) — NOT a
flat dict. But `live_bot_manager.py`'s `start_session` governor_cfg cascade (added 22.1, extended
by every step since) read `risk_params.get("max_session_dd")` etc. directly on that WRAPPER dict.
Those keys never exist at that level, so **every governor knob (`max_session_dd`,
`max_portfolio_risk`, `var_limit_pct`, `cvar_limit_pct`, `correlation_cap`, `allocation`, and
22.7's own new fields) had silently fallen through to `None` since 22.1 shipped** — Zone 2
configuration never actually reached the governor, for the entire history of Plan 22 up to this
point. Fixed via `default_risk_params = risk_params.get("default") or {}`, mirroring the correct
pattern `_setup_strategy_instance` already used elsewhere in the same file. Proven with a new test
(`test_start_session_risk_params_shape.py`, 7 cases) driving the REAL `start_session()` against
the actual Node-shaped payload — deliberately not a flattened stand-in that would hide the same
bug again.

**Two smaller gaps also found and fixed:** (1) `AlgoTrading.jsx`'s `algo:session:update` socket
handler merged `status`/`pnl`/`openPositions`/`symbolStats` but silently dropped `tradingState` —
so even with the new SessionCard badge, a real-time governor breach would never have updated it
live, only on the next full refetch; fixed with the same merge-if-present pattern. (2)
`server/src/utils/webhook.js`'s `VALID_EVENTS` (validates a webhook-config PUT) was missing
`risk_breach` — present in `Settings.js`'s schema enum and dispatched since 22.1, but never added
to this separate list, so a user saving `risk_breach` via the UI got a silent 400; fixed.

**Verification this session:** container pytest **330/330 passed** (up from 301/301 at session
start); server Jest **88/88 passed** (up from the untested-in-sandbox baseline — this ALSO
confirms `capitalGate.test.js`, flagged unverified since 22.1, genuinely passes with 100%
coverage, since `node_modules` now exists in the server container). **Live-verified in-browser via
Claude in Chrome** against the user's own running `docker compose watch` stack (not a mock):
Dashboard/Risk Dashboard/Algo Trading pages all load with zero console errors; the new governor
form section's save→reload round-trip genuinely persists through MongoDB (typed a value, saved,
reloaded the page, confirmed it survived — then cleared it back to blank/off); the New Bot
wizard's allocation dropdown renders correctly once 2+ symbols are selected. No real bot/session
was started during verification.

**Files changed:** `engine/core/models/governor.py` (`check_correlation_concentration`),
`engine/core/models/portfolio.py` (`InverseVolatilityPortfolio`, `compute_realized_volatility`),
`engine/core/models/__init__.py` (exports), `engine/services/portfolio_risk.py`
(`fetch_correlation_matrix`), `engine/services/backtest_runner.py` (22.6 opt-in allocation
recompute), `engine/core/live_bot_manager.py` (22.5 wiring, 22.6 wiring, the `default_risk_params`
bug fix, 22.7's new flat-key fallbacks); new engine tests: `test_execute_entry_correlation_cap.py`,
`test_inverse_vol_portfolio.py`, `test_start_session_risk_params_shape.py`; extended
`test_session_risk_governor.py`; `server/src/models/Settings.js` (governor fields on
`globalHardLimits`), `server/src/utils/risk.js` (pass-through + allocation wizard-override),
`server/src/controllers/risk.controller.js` (validation), `server/src/utils/webhook.js`
(`VALID_EVENTS` fix); extended `server/src/utils/__tests__/risk.test.js`,
`server/src/utils/__tests__/webhook.test.js`; `client/src/pages/RiskDashboard.jsx` (governor form
section), `client/src/components/RiskParamsFields.jsx` (`showAllocation`),
`client/src/components/algo/NewSessionWizard.jsx` (allocation dropdown wiring),
`client/src/components/algo/SessionCard.jsx` (governor badge), `client/src/pages/AlgoTrading.jsx`
(`tradingState` socket-merge fix); docs: `22_risk-management-industry-standard.md`, `0_tracker.md`,
`workspace/docs/state/CURRENT_STATE.md`, `workspace/docs/features/algo-trading/SPEC.md`,
`workspace/docs/features/risk-dashboard/SPEC.md`, `handoff.md`. All committed this session (3
commits: 22.5, 22.6, 22.7 + the webhook fix + the risk_params-shape bug fix bundled with 22.7).

**NOT done — do not treat any of Plan 22 as fully closed:**
1. **No live Testnet re-verification of ANYTHING in Plan 22** — this is now the single remaining
   item across the entire plan (22.1–22.7). None of the governor's vetoes/breaches, the capital
   gate's over-commit rejection, the protections' lock/unlock, the correlation-cluster veto, the
   inverse-vol allocation's real weight computation, or a real governor breach flipping the
   SessionCard badge live have been exercised against an actual running Binance Testnet session.
2. Docs say "shipped, container/Jest-verified, live-verified in-browser, pending live Testnet
   re-verification" — do not upgrade further to unqualified "shipped"/"verified" until a real
   Testnet session is actually run and observed.
3. The `default_risk_params` fix (item 1 above) means every PRIOR session's claim that "Zone 2
   configuration flows into the governor" was never actually true until this session — if a past
   handoff entry or doc line implies otherwise, this entry supersedes it.

**Next session:** the only substantive Plan 22 work left is live Testnet re-verification — start a
small session with a tight `max_session_dd`/`varLimitPct`/`correlationCap.rho` and confirm each
governor check actually vetoes/breaches against real exchange data, confirm the SessionCard badge
updates live on a real breach, confirm a deliberate capital over-commit round-trips the 409/confirm
flow from the wizard. Outside Plan 22: survey `0_tracker.md`'s Active work table fresh for the next
genuinely decision-free, golden-master-free item — Plan 21's 21.5(c) (batched reconcile,
concurrency restructure) and Plan 24 (BestSupertrend fixes) are both plausible candidates but
neither was investigated this session.

**UPDATE (same day, 2026-07-17, immediately after this entry was written) — partial live
verification attempted:** user authorized live Testnet verification directly. Set Zone 2's
`correlationCap` to `rho=0.5, maxClusterExposurePct=1` (deterministic single-entry veto — any
first entry alone exceeds a 1% cluster cap) via the UI, then started two real sessions via the New
Bot wizard: (1) MicroScalper/BTCUSDT/1m/$50/1x, (2) after the user asked for more symbols to
increase order frequency, MicroScalper across 15 symbols/1m/$500/1x. **Confirmed working:** both
sessions started cleanly with zero crashes/errors (proving the `default_risk_params` bugfix holds
against the real Node payload end-to-end, not just in the unit test), UDS connected, per-symbol WS
klines connected, leverage set via real Binance Testnet calls, clean stop with no orphaned locks.
**Not confirmed:** MicroScalper (3/9 EMA crossover) did not fire a single entry signal on any of
the ~16 symbols tried across ~10 minutes of live 1m Testnet data (174 positionRisk polls, zero
entries) — the correlation-cap veto itself was never actually exercised, since no entry was ever
attempted. This is a real-market-timing limitation, not a code issue on either side. Cleaned up:
stopped both sessions, reverted `correlationCap` back to `rho` blank / `maxClusterExposurePct=40`.
**Still the single open item across Plan 22.** A future attempt should either run much longer,
use Chaos Mode (many strategies → far more entry attempts per minute) instead of a single strategy,
or pick a strategy with looser entry conditions to get an actual entry to test the veto against.

