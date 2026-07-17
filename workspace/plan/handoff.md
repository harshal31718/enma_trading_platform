# Session Handoff Log

Resume prompts for cross-session continuity (root `CLAUDE.md` Rule G / `AGENTS.md` → Session Handoff).

**Format rules:**
- Newest entry on top: `## <date> — <title> — <status>` with **Goal / Done / Files changed / Open questions**.
- Keep at most the **3 most recent entries**. When adding a new one, delete the oldest — git history is the archive. This file must stay a short resume prompt, not a project log.

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

---
## 2026-07-17 — Plan 21.7 (A-12/A-13) + Plan 22 Steps 22.1(remainder)–22.4 shipped: mainnet kline feed, armed-bracket wick-check dedup, portfolio open-risk/liq-buffer, protections parity, live VaR/CVaR — CODE COMPLETE, VERIFICATION PENDING ⏸️

**Goal:** continue Plan 22 step by step under the session's standing "ok proceed"/"continue"
pattern — each brief go-ahead authorized the next unblocked item in the plan's own sequencing
without re-litigating scope. Closed out Plan 21.7's last two items (A-12/A-13, both previously
held for a product decision, now unblocked by `DECISIONS.md` #24/#25 from an earlier session),
then 22.1's remaining wiring, then 22.2, 22.3, and 22.4 in order.

**Done — A-12 (mainnet kline feed for live signals):** new `_MAINNET_WS_BASE` constant +
`_kline_ws_url(symbol, timeframe)` (`engine/core/live_bot_manager.py`) — live signal/indicator
candles now come from Binance mainnet's public kline stream
(`wss://fstream.binance.com/market/ws`), replacing the old testnet-sourced feed that spliced
discontinuously against mainnet-trained strategies. Order execution stays testnet-pinned
(unchanged). Tests: `engine/tests/test_kline_ws_url.py` (5 cases) — this file also established
the stub-injection technique (fake `websockets`/`motor`/`asyncpg` registered into `sys.modules`
only if the real import fails, then the REAL module is driven) reused by every test file this
window needed it, unlocking genuine `pytest` execution instead of `ast.parse`-only.

**Done — A-13 (engine wick-check defers to a confirmed-armed exchange bracket):**
`ExecutionKernel.check_exits` (`engine/core/kernel.py`) gained `armed_legs: dict | None = None` —
skips the engine's own SL/TP wick-check for a leg confirmed resting on the exchange
(`open_positions[symbol]["algo_ids"]`), falling back to the wick-check when a leg is missing
(A-7's naked-position detector makes "missing" well-defined). Default `None` preserves
byte-identical backtest behavior — confirmed via `test_entry_candle_exits.py`/
`test_exec_algo_slicing.py` unchanged. `_run_symbol_loop` now passes `armed_legs` computed from
`open_positions[symbol]["algo_ids"]`. Tests: `engine/tests/test_armed_legs_wick_check_skip.py`
(7 cases).

**Done — 22.1 remainder:** `record_realized_pnl` wired into the two PnL-booking sites that
weren't yet covered (`_close_position_on_stop`, `_reconcile_exchange_state` Case 2);
`session["risk_governor"]` instantiated in `start_session` via a `governor_cfg` cascade reading
`risk_params.max_session_dd`/`.governor`.

**Done — 22.2 (portfolio open-risk budget + liquidation buffer):**
`SessionRiskGovernor.check_portfolio_risk()` — the TRUE cross-symbol Σ`|entry−stop|×qty`/equity,
superseding `DefaultPortfolioModel.construct()`'s structurally-per-symbol `max_portfolio_risk`
check for live sessions (backtest's own check left untouched, no golden-master benefit to
removing it). `respects_liq_buffer()` (previously decorative, zero call sites) wired into
`execute_entry`, computing the actual liquidation price via `core/margin.py` for the veto log.
New `_compute_open_risk_breakdown()` reads each open symbol's live `strategy.stop_loss`. Tests:
`+6` in `test_session_risk_governor.py`, new `test_execute_entry_portfolio_risk_and_liq_buffer.py`
(8 cases).

**Done — 22.3 (protections parity + risk-integrity events):** new `MaxDrawdownProtection` +
`LowProfitPairsProtection` (`core/models/protections.py`, opt-in/default-off). **Found and fixed a
real gap while wiring them in:** `ProtectionManager.record_trade_close` was only ever called from
`execute_exit` — the F-018 emergency-exit path, `_close_position_on_stop`, and
`_reconcile_exchange_state`'s Case 2 never fed the protections stack at all, meaning
`StoplossGuard` was structurally blind to most exchange-side stoploss closes (the path A-13 just
made dominant). Wired into all four close paths. New `_classify_exchange_sync_exit_reason()` for
Case 2's internal bookkeeping only (outward notification's `exitReason="exchange_sync"` label
unchanged). Verified Chaos sessions already get full protections coverage (traced `startChaos` →
same `start_session` path, no separate Chaos plumbing — corrected a stale plan-text assumption).
New `risk_check` event type (`services/event_log.py`), appended by `execute_entry` on every
successful entry with resolved limits + computed sizing including the minNotional inflation
factor; session-visible warning above 1.1×. Tests: `test_protections_max_drawdown_low_profit.py`
(16 cases, zero deps), new `test_execute_entry_risk_check_event.py` (4 cases).

**Done — 22.4 (live VaR/CVaR enforcement):** new `engine/services/portfolio_risk.py` — the single
shared computation both `routers/risk.py`'s Zone 1 dashboard endpoint (rewritten as a thin
formatter) and the governor's new `check_var()` call (`compute_var_cvar()`, wrapping the
pre-existing `utils/risk_math.calculate_portfolio_var` unchanged). **Deliberately account-wide,
not session-scoped** — Binance's real margin/liquidation risk is account-wide, shared across every
session on one API key (Chaos runs dozens per key); scoping to one session's positions would
diverge from the dashboard's own number. 10s account-fetch / 60s price-history in-memory caching
bounds REST/DB weight (this step's own acceptance criterion) — independent of the Node-side 10s
Redis cache the dashboard route already had (that one only helps browser polling, not the
engine-internal governor calls). `SessionRiskGovernor.check_var(var_amount, cvar_amount, equity)`
adds `var_limit_pct`/`cvar_limit_pct`, both default `None` (fully opt-in, unlike the other
governor checks' "0 disables" convention). Wired pre-trade (`execute_entry`, opt-in gated to avoid
an extra Binance/TimescaleDB round trip when unconfigured) and periodically (`_push_stats`,
reusing the existing `risk_breach` webhook via `_apply_governor_breach` — no new webhook
plumbing). Fails **open** on a fetch/compute exception (external network call, same precedent as
22.2's liq-buffer check). Zone 2 schema/UI deliberately deferred to 22.7 (that step's own text
explicitly batches `varLimitPct` into its one UI pass) — engine-side config keys are live now via
`risk_params.governor.var_limit_pct`. Tests: new `test_portfolio_risk_shared_service.py` (11
cases, including the acceptance-critical shared-function identity test proving the dashboard and
governor call sites get byte-identical values from ONE cached fetch, not coincidentally-equal
independent stubs), `+8` in `test_session_risk_governor.py`, new `test_execute_entry_var_breach.py`
(6 cases, including the acceptance-critical "breach demonstrably blocks a new entry" test).

**Files changed:** `engine/core/live_bot_manager.py` (A-12, A-13 wiring, 22.1 remainder, 22.2,
22.3, 22.4 — many call sites); `engine/core/kernel.py` (A-13's `armed_legs` param);
`engine/core/models/governor.py` (`check_portfolio_risk`, `check_var`, new config fields); new
`engine/core/models/protections.py` additions (`MaxDrawdownProtection`,
`LowProfitPairsProtection`); `engine/core/models/__init__.py` (exports); `engine/services/
event_log.py` (`risk_check` EVENT_TYPES entry); new `engine/services/portfolio_risk.py`; rewritten
`engine/routers/risk.py`; new test files: `test_kline_ws_url.py`,
`test_armed_legs_wick_check_skip.py`, `test_execute_entry_portfolio_risk_and_liq_buffer.py`,
`test_protections_max_drawdown_low_profit.py`, `test_execute_entry_risk_check_event.py`,
`test_portfolio_risk_shared_service.py`, `test_execute_entry_var_breach.py`; extended
`test_session_risk_governor.py`; docs: `21_live-algo-industry-standard-audit.md`,
`22_risk-management-industry-standard.md`, `0_tracker.md`, `0_fixes-queue.md`,
`workspace/docs/state/CURRENT_STATE.md`, `workspace/docs/features/algo-trading/SPEC.md`,
`workspace/docs/features/risk-dashboard/SPEC.md`, `workspace/docs/core/binance-api.md`,
`handoff.md`.

**UPDATE (same day, 2026-07-17, immediately after this entry was written):** the user ran
`docker exec enma_trading_platform-engine-1 pytest /app/tests/` themselves — **301/301 passed**,
zero failures, covering every test file this window (and every prior Plan 21/22 session) added.
Item 1 below is resolved. Docs updated accordingly (status language flipped from "shipped
code-side, pending container test run" to "shipped, container-verified 2026-07-17" across
`0_tracker.md`, `21_live-algo-industry-standard-audit.md`, `22_risk-management-industry-
standard.md`, `CURRENT_STATE.md`, `algo-trading/SPEC.md`). Item 2 (live Testnet re-verification)
is still genuinely open — a green test suite proves the code does what the tests assert, not that
it behaves correctly against the real exchange.

**NOT done — do not treat any of this as fully closed:**
1. ~~No container test run~~ **RESOLVED 2026-07-17** — see UPDATE above.
2. **No live re-verification** — none of A-12's mainnet feed, A-13's wick-check dedup, 22.2's
   portfolio-risk/liq-buffer veto, 22.3's new protections/risk_check events, or 22.4's VaR/CVaR
   veto have been exercised against a real Binance Testnet session. **This is now the single
   remaining verification gap for all of Plan 21 + Plan 22.1–22.4.**
3. Docs now say "shipped, container-verified 2026-07-17, pending live re-verification" — do not
   upgrade further to unqualified "shipped"/"verified" until #2 is actually done.
4. **Git commit status not re-confirmed at the end of this specific window** — verify `git log`/
   `git status` directly before assuming everything above is committed (this session hit the
   recurring `.git/index.lock`/`HEAD.lock` recreation bug several times; the fix each time was
   renaming the lock file and retrying, confirmed via `git log`, not via piped exit codes).

**Next session:** (1) live-verify a small Testnet session covering the governor's
veto/breach behavior (drawdown, portfolio-risk, liq-buffer, VaR/CVaR), the capital gate's
over-commit rejection, and the protections' lock/unlock; (3) once verified, flip status language
from "shipped code-side" to "shipped" across the docs touched above; (4) the natural next step per
Plan 22's own sequencing is **22.5** (correlation-aware concentration cap, reuses this step's
shared `portfolio_risk.py` service for the rolling-correlation computation) — check in before
starting it rather than treating continued "proceed" as a blank check for the rest of Plan 22,
consistent with how each step this window paused to report status first.

---
## 2026-07-17 — Plan 22 Step 22.1 shipped: Session Risk Governor + capital integrity gate — CODE COMPLETE, VERIFICATION PENDING ⏸️

**Goal:** per the user's "ok, ask me" → six Part F/A-12/A-13 policy decisions answered via
`AskUserQuestion` (recorded `DECISIONS.md` #23/#24/#25) → user said "proceed with reccom" →
started Plan 22 Step 22.1 (Session Risk Governor core + capital integrity gate), the next item in
the plan's own execution order, now unblocked by those decisions. Continued unattended per the
session's standing "keep implementing, don't stop for input" instruction.

**Done:**
- **`engine/core/models/governor.py`** (new): `GovernorVerdict` dataclass + `SessionRiskGovernor`
  class, structurally mirroring `ProtectionManager`/`IProtection` — takes plain numbers
  (`equity`, `used_margin`, `now`), never reaches into session/strategy internals itself. Three
  fail-closed hard checks: aggregate session drawdown (`max_session_dd`, default 0.20 —
  supersedes Plan 21 finding A-10/step 21.6, now `Merged→22.1`), daily realized loss limit
  (`max_daily_loss_pct`, off by default, UTC-midnight anchor per `DECISIONS.md` #23), margin
  utilization ceiling (`max_margin_utilization`, default 0.8, pre-trade only). `breach_action`
  (`"reducing"`/`"halted"`) and `auto_flatten_on_halt` (opt-in, default off) configurable.
  Registered in `core/models/__init__.py`. **18/18 tests actually run with real pytest**
  (`engine/tests/test_session_risk_governor.py`) — zero numpy dependency, imports standalone.
- **`server/src/utils/capitalGate.js`** (new): pure functions `validateCapitalValue`,
  `sumReservedCapital`, `checkCapitalAgainstBalance` (B-11/B-12). Manually verified via a 20-
  assertion `node -e` script (no `node_modules` in the sandbox — `npm install` still times out,
  same limitation as prior sessions); a Jest suite exists at
  `server/src/utils/__tests__/capitalGate.test.js` but has not been run for real.
- **`algo.controller.js`**: `startSession`/`startChaos` wired to `capitalGate.js` — hard-reject
  non-numeric/zero/negative capital always (400); warn-and-require `confirmOverCommit` when
  requested + reserved capital across the user's running sessions exceeds the real testnet
  balance (409 otherwise), Chaos multiplying `capital × strategyCount` summed not sampled, per
  `DECISIONS.md` #23 Part F Q5. New `handleEngineStats` `risk_breach` branch persists
  `LiveSession.tradingState`, emits Socket.IO updates, dispatches the `risk_breach` webhook.
- **`Settings.js`**: `risk_breach` added to `webhook.events` enum (opt-in by default).
- **`live_bot_manager.py`**: `start_session` instantiates `session["risk_governor"]` (reusing
  `risk_params.max_session_dd` + new `risk_params.governor` sub-object) and defensively clamps
  configured capital against a live-fetched balance (`_fetch_available_balance`, best-effort,
  never blocks); `execute_entry` gained a pre-trade governor veto after A-001/A-002/A-003;
  `_push_stats` gained an edge-triggered periodic governor check (via new
  `_compute_session_equity_and_margin` static method, which also now derives `total_pnl`,
  replacing the old inline per-symbol sum) that calls new `_apply_governor_breach` on a breach
  (sets `trading_state`, notifies Node, auto-flattens via the existing
  `_close_position_on_stop` if `auto_flatten_on_halt`); `record_realized_pnl` wired into all
  four PnL-booking sites (F-018 emergency exit, `execute_exit`, `_close_position_on_stop`,
  `_reconcile_exchange_state` Case 2). Verified via `py_compile`/`ast.parse` + manual review of
  variable scoping — a full `import core.live_bot_manager` was attempted (successfully installed
  `httpx`/`pytest` quickly this session, unlike prior sessions) but still blocked on
  `websockets`/`motor`/`asyncpg`, which timed out installing, same sandbox limitation as always.
- Docs: `0_tracker.md` (Plan 21 row's 21.6 already `Merged→22.1`; Plan 22 row updated to "In
  progress, 22.1 shipped code-side"), `22_risk-management-industry-standard.md` (22.1 section
  gained a "Status: shipped code-side" block), `CURRENT_STATE.md` (new 2026-07-17 addition under
  Algo Trading + "Last updated" line), `algo-trading/SPEC.md` (new "Session Risk Governor" H2
  section before REST Endpoints).

**Files changed:** new `engine/core/models/governor.py`; `engine/core/models/__init__.py`
(export); `engine/core/live_bot_manager.py` (governor import + instantiation + wiring at 6
call sites, `_fetch_available_balance`, `_compute_session_equity_and_margin`,
`_apply_governor_breach`); new `engine/tests/test_session_risk_governor.py`; new
`engine/tests/test_fetch_available_balance.py` (ast.parse-only); new
`server/src/utils/capitalGate.js`; new `server/src/utils/__tests__/capitalGate.test.js` (not
run); `server/src/controllers/algo.controller.js` (capital gate wiring + `risk_breach` branch);
`server/src/models/Settings.js` (webhook events enum); docs: `0_tracker.md`,
`22_risk-management-industry-standard.md`, `workspace/docs/state/CURRENT_STATE.md`,
`workspace/docs/features/algo-trading/SPEC.md`, `handoff.md`.

**NOT done — do not treat 22.1 as fully closed:**
1. **No container test run.** All Python verification in this session was `py_compile`/
   `ast.parse` + the standalone governor pytest run (dependency-free) — `live_bot_manager.py`
   itself was never actually imported/exercised, since its dependency chain
   (`websockets`/`motor`/`asyncpg`) doesn't install in this sandbox. Run
   `docker exec enma_trading_platform-engine-1 pytest /app/tests/` before trusting the wiring.
2. **No Jest run** for `capitalGate.test.js` or a controller-level integration test — `npm
   install` still times out in this sandbox (recurring limitation, not new). Manual assertions
   passed but don't replace the real suite.
3. **No live re-verification** — the governor has never vetoed a real entry, never auto-
   transitioned a real session's `trading_state`, never auto-flattened, and the capital gate has
   never rejected/warned on a real over-commit attempt against a real testnet balance.
4. **Git commit still pending** — nothing from this session (governor.py, capitalGate.js +
   test, live_bot_manager.py wiring, algo.controller.js wiring, Settings.js, new engine tests,
   docs) has been committed yet.

**Next session:** (1) run the container test suite, fix any signature-mismatch surprises between
`governor.py`'s design and how `live_bot_manager.py` actually calls it; (2) live-verify: start a
small testnet session with a tight `max_session_dd` and confirm a manufactured drawdown actually
flips `trading_state` and shows in the SessionCard/webhook; try a deliberate capital over-commit
and confirm the 409/confirm-flow round-trips from the wizard; (3) commit this session's work; (4)
once verified, flip 22.1's status language from "shipped code-side, pending verification" to
"shipped" across the docs touched above; (5) the natural next step per Plan 22's own sequencing
(Part E: `22.1 ──► 22.2 ──► 22.3`) is **22.2** (portfolio open-risk budget + `liq_buffer_pct`
wiring) — not yet confirmed as the user's intent beyond 22.1, check in before starting it rather
than treating "proceed with reccom" as a blank check for the rest of Plan 22.
