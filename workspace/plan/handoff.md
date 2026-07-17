# Session Handoff Log

Resume prompts for cross-session continuity (root `CLAUDE.md` Rule G / `AGENTS.md` → Session Handoff).

**Format rules:**
- Newest entry on top: `## <date> — <title> — <status>` with **Goal / Done / Files changed / Open questions**.
- Keep at most the **3 most recent entries**. When adding a new one, delete the oldest — git history is the archive. This file must stay a short resume prompt, not a project log.

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

**NOT done — do not treat any of this as fully closed:**
1. **No container test run for any of it.** Every test file this window was verified with real
   `pytest` via the stub-injection technique (genuine execution, not `ast.parse`) — 100+ tests
   green across the full touched-file surface, backtest-path regression files unaffected — but
   this sandbox has never had Docker access. Run
   `docker exec enma_trading_platform-engine-1 pytest /app/tests/` before trusting any of it.
2. **No live re-verification** — none of A-12's mainnet feed, A-13's wick-check dedup, 22.2's
   portfolio-risk/liq-buffer veto, 22.3's new protections/risk_check events, or 22.4's VaR/CVaR
   veto have been exercised against a real Binance Testnet session.
3. All touched docs say "shipped code-side, pending container test run + live re-verification" —
   do not silently upgrade that language without actually running #1 and #2.
4. **Git commit status not re-confirmed at the end of this specific window** — verify `git log`/
   `git status` directly before assuming everything above is committed (this session hit the
   recurring `.git/index.lock`/`HEAD.lock` recreation bug several times; the fix each time was
   renaming the lock file and retrying, confirmed via `git log`, not via piped exit codes).

**Next session:** (1) run the container test suite — single highest-leverage action outstanding
across this entire window; (2) live-verify a small Testnet session covering the governor's
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

---
## 2026-07-17 — Plan 21.1–21.4 + 21.5a/b + 21.7 (A-11/A-14) shipped: F7-root-cause fixes, bracket-integrity hardening, rate-limit backpressure, risk/slippage observability — CODE COMPLETE, VERIFICATION PENDING ⏸️

**Goal:** ship Plan 21 step 21.1 — the three surgical diffs identified by the 2026-07-16 audit as
the likely root causes of F7 (algo-order fill detection lag): A-1 (broken userTrades credentials),
A-2 (`_on_fill` AttributeError killing the event-driven fill path), A-3 (`LISTEN_KEY_EXPIRED`
killing the user-data stream permanently). Per `0_tracker.md`'s "Next session" pointer, this was
the top P0 item and a prerequisite for a meaningful F7 reproduction. Same session, continued into
**21.2** (A-8, ACCOUNT_UPDATE-driven reconcile) per 21.1's own "next session" pointer below.

**Done:**
- **A-1** (`engine/core/live_bot_manager.py`, `_query_real_exit_from_user_trades()`): the
  `send_signed_request` call omitted the required `api_key`/`api_secret` positionals — now passed.
  The Plan 5.2 "reconstruct the real close from Binance's own trade history" path can now actually
  execute instead of silently TypeError-ing and falling back to the estimate.
- **A-2** (`engine/core/live_bot_manager.py`, `_on_fill` closure inside `_run_symbol_loop`): the
  client-id lookup read a non-existent `clientOrderId` key and fell back to the numeric `orderId`
  (an int), crashing `.startswith("tpsl_")` with `AttributeError` on every genuinely-delivered
  FILLED/PARTIALLY_FILLED frame — caught by the outer per-callback try/except, so the
  `_reconcile_exchange_state()` call at the end of `_on_fill` never ran. Extracted the fix into a
  new module-level `_extract_fill_client_id()` helper (reads `"c"`, str-coerced, falls back to
  `"i"`) so it's independently unit-testable without driving the whole embedded closure. Also
  wrapped the OUO peer-cancel block in its own try/except so the reconcile call is structurally
  unconditional — no failure earlier in the callback can skip it anymore.
- **A-3** (`engine/services/user_data_stream.py`, `_run_ws`): `LISTEN_KEY_EXPIRED` handler did
  `return` (exits the whole `_run_ws` coroutine — no caller re-invokes it, so the comment claiming
  "reconnect loop picks it up" was simply wrong) — changed to `break` (exits only the inner
  `async for`, so the outer `while self._running` reconnect loop re-enters with the refreshed
  `ws_url`).
- **Tests** (new files, following this repo's own convention of testing extracted/standalone units
  rather than driving deeply-embedded methods — see `test_symbol_state_lock.py`'s precedent):
  `engine/tests/test_query_real_exit_from_user_trades.py` (3 tests — creds reach the signed call,
  a multi-fill response is genuinely consumed into avg price/net PnL, exceptions still degrade to
  `None`), `engine/tests/test_on_fill_client_id_extraction.py` (5 tests on the new
  `_extract_fill_client_id()` helper, including the exact int-orderId-`.startswith()` crash
  shape), `engine/tests/test_uds_listen_key_expired_reconnect.py` (2 tests driving the real
  `_run_ws` against a fake `websockets.connect` — confirms a second connection attempt happens
  with the refreshed key, proving the old `return` would have prevented it).
- Docs updated per Plan 21's own "docs to update when steps ship" list: `0_tracker.md` (Plan 21 row
  + Notes), `0_fixes-queue.md` (F7 entry), `21_live-algo-industry-standard-audit.md` (status
  header + Part C 21.1 row), `CURRENT_STATE.md` (both the userTrades Known-Debt line and the F7
  ~60s-staleness entry corrected to reflect the code fix), `algo-trading/SPEC.md` ("Open issues
  found in a live Chaos run" item 1).

**Done — 21.2 (A-8, same session):**
- **A-8** (`engine/core/live_bot_manager.py`, `_run_symbol_loop`): new `_on_account_update`
  callback registered per symbol alongside `_on_fill`, via `_uds.register_account_callback(symbol,
  _on_account_update)` (and unregistered in the existing `finally` block). Reconciles immediately
  under the per-symbol lock whenever a Binance `ACCOUNT_UPDATE` `P[]` position delta disagrees with
  the local `strategy.position` open/flat state — event-type-agnostic, so it closes the staleness
  window independent of whatever A-2's `ORDER_TRADE_UPDATE`/`tpsl_` fix does or doesn't catch.
  Debounced by checking `self._get_symbol_lock(session_id, symbol).locked()` first — skip rather
  than queue if a reconcile is already in flight (candle loop or `_on_fill`), since it'll observe
  the same fresh exchange state. Decision logic (does this delta actually disagree with the local
  view) extracted into `_account_update_needs_reconcile(pos_data, has_local_position)` for direct
  unit testing, same pattern as A-2's `_extract_fill_client_id()`.
- **Correction to the original A-8 finding while implementing it:** the audit's "`_handle_account_
  update` only logs" claim was stale — `engine/services/user_data_stream.py` already had a
  `register_account_callback`/`_account_callbacks`/dispatch mechanism (added sometime before this
  session, per `git log` — not by this session, and not reflected in any tracker entry) that
  `_handle_account_update` already called into. It just had zero registered consumers. 21.2
  registered the missing consumer rather than building new UDS-side plumbing — smaller diff than
  the audit implied.
- **Tests:** `engine/tests/test_account_update_reconcile_decision.py` (6 tests — both disagreement
  directions trigger reconcile, both agreement directions don't, negative `pa` for shorts handled
  correctly, missing/malformed `pa` degrades to flat rather than crashing).
- Docs updated: `0_tracker.md` (Plan 21 row + Notes), `0_fixes-queue.md` (F7 entry),
  `21_live-algo-industry-standard-audit.md` (status header, A-8 finding, Part C 21.2 row),
  `CURRENT_STATE.md`, `algo-trading/SPEC.md`.

**Done — 21.3 (A-4/A-5, same session, continued unattended per user instruction — see below):**
- New `LiveBotManager._cancel_symbol_algo_orders(session, symbol, algo_ids=None)`
  (`engine/core/live_bot_manager.py`): cancels tracked SL/TP algo ids directly via `DELETE
  /fapi/v1/algoOrder` if `algo_ids` has at least one non-None value; otherwise discovers open
  algo orders via `GET /fapi/v1/openAlgoOrders` and cancels everything found. Best-effort — a
  cancel failure is logged (info-level for "already gone", warning for a failed discovery GET)
  and never raised, since the position is already closed by the time this runs.
- Wired into all four close paths the finding named: `execute_exit`'s success path (captures
  `algo_ids` before popping `open_positions`), `_close_position_on_stop` (passes `_pos_info`'s
  tracked ids, falls back to discovery for symbols the engine never fully tracked),
  the F-018 emergency-exit path in `execute_entry` (defensive — nothing is actually resting there
  today given SL-before-TP placement order, but kept so a future reordering can't silently reopen
  the gap), and reconcile Case 2 in `_reconcile_exchange_state` (A-5's specific finding: section
  6's existing OUO peer-cancel is guarded by `has_exchange_position`, which is false by definition
  in Case 2, so it structurally never fires there — Case 2 now captures and cancels the tracked
  ids itself before dropping local tracking).
- Tests: `engine/tests/test_cancel_symbol_algo_orders.py` (7 cases, driving the real method
  directly — it's a proper `LiveBotManager` method, not an embedded closure, so no extraction
  workaround needed): tracked-ids-direct-cancel, partial-tracked-ids, both-None-triggers-fallback,
  discovery-fallback, no-credentials-noop, one-DELETE-failure-doesn't-block-the-other,
  GET-failure-caught-not-raised.
- Docs: `0_tracker.md` (Plan 21 row + Notes), `21_live-algo-industry-standard-audit.md` (A-4/A-5
  fixed headers + Shipped notes + Part C 21.3 row), `algo-trading/SPEC.md` (new bullet in "SL/TP &
  OCO Safety").

**Done — 21.4 (A-6/A-7 + M-4/M-5, same session, continued unattended per user instruction — see
below):**
- **A-6** (`execute_entry`'s F-018 emergency-exit block, `engine/core/live_bot_manager.py`): the
  emergency MARKET close (fires when entry filled but SL placement failed) now retries up to 3
  attempts with `1s × attempt` backoff instead of a single try. On success, books the trade at the
  REAL fill price (`_extract_fill_price()` → `_query_real_fill_price()` fallback ladder, identical
  to `execute_exit`'s existing contract) instead of the old fabricated `exit_price = fill_price`
  (entry price, which manufactured exactly `-fee` as PnL regardless of the actual close). On total
  failure across all 3 attempts, records nothing and leaves `strategy.position` exactly as it was
  (still `None` at this point in the entry flow) rather than falsely marking a still-open, still-
  naked position as closed — matches Plan 5.2's real-fills-not-fabricated-closes invariant, now
  extended to the emergency path. Also folds in A-4: calls `_cancel_symbol_algo_orders` defensively
  after the emergency-close attempts regardless of outcome.
- **A-7** (`_reconcile_exchange_state` Case 3, same file): new naked-position detector — whenever
  `strategy.stop_loss` is set but no live SL-looking order (`type` containing `STOP` or
  `clientOrderId` ending in `sl`) rests on the exchange, attempts a direction-aware re-arm via the
  same rounding path `execute_entry` uses. Tracks consecutive failures per symbol
  (`session["_naked_position_rearm_attempts"]`); after `_NAKED_POSITION_MAX_REARM_ATTEMPTS` (3)
  consecutive failures across separate reconcile passes, force-closes via `execute_exit` instead of
  letting the position run naked indefinitely (mirrors freqtrade's per-iteration missing-stoploss
  re-placement, bounded). Success or a live SL both reset the counter.
- **M-4** (new `LiveBotManager._maybe_amend_exchange_sl(session, session_id, strategy, symbol)`,
  wired into `_run_symbol_loop` right after `kernel.evaluate_and_route(...)`): the risk models'
  trailing/breakeven/Chandelier maintain path (`DefaultExecution.route()` Path 5) tightens
  `strategy.stop_loss` locally every candle, but previously never pushed that to the resting
  exchange SL order — it stayed at its original, widest trigger for the position's entire life.
  This method now cancels+replaces the exchange SL whenever the new stop is a genuine
  direction-aware tighten; records a first-pass baseline (`armed_sl_price`) without calling Binance
  on a fresh/restored position; is a pure no-op on a widening or unchanged stop; and catches+logs
  any amend failure without corrupting the tracked `algo_ids`/falling back to the engine's own
  wick-check.
- **M-5** (`execute_entry`'s SL/TP validity check, same file): an SL that lands on the wrong side
  of the reference price (long: `sl_price >= fill_price`; short: `sl_price <= fill_price`) now
  rejects the entry outright — `strategy.buy`/`sell`/`stop_loss`/`take_profit` all cleared, returns
  `False`, no order ever placed — instead of the old silent-drop-and-enter-naked behavior with no
  future re-check. TP-invalid stays lower-stakes: dropped, entry still proceeds on its valid SL.
- **Tests:** `engine/tests/test_reconcile_naked_position_rearm.py` (5 cases, driving the real
  `_reconcile_exchange_state` method directly), `engine/tests/test_maybe_amend_exchange_sl.py` (8
  cases, driving the real `_maybe_amend_exchange_sl` method directly), `engine/tests/
  test_execute_entry_bracket_safety.py` (7 cases, driving the real `LiveAdapter.execute_entry`
  against a stubbed Binance layer, same harness shape as `test_execute_flip_idempotency.py`: both
  invalid-SL-rejection directions, valid-SL/invalid-TP drop-and-enter, emergency-close success on
  first try, retry-then-succeed, total-failure records nothing, A-4 cancel-integration). All three
  new files syntax-checked cleanly via `ast.parse` (new files, unaffected by this session's
  bash-sandbox stale-cache bug — see the note further down).
- Docs: `0_tracker.md` (Plan 21 row + Notes), `21_live-algo-industry-standard-audit.md` (status
  header + A-6/A-7/M-4/M-5 fixed headers + Shipped paragraphs + Part C 21.4 row + remediation
  table), `CURRENT_STATE.md` (new Known-Debt bullet summarizing 21.3+21.4, TP-400 item annotated
  with the A-7 self-heal note), `algo-trading/SPEC.md` (F-018 bullet rewritten, new bullets for
  naked-position re-arm, exchange-SL amend-on-tighten, and invalid-SL rejection).

**Files changed:** `engine/core/live_bot_manager.py` (A-1, A-2, A-4, A-5, A-6, A-7, A-8, M-4, M-5,
new `_extract_fill_client_id()`, `_account_update_needs_reconcile()`,
`_cancel_symbol_algo_orders()`, `_maybe_amend_exchange_sl()`,
`_NAKED_POSITION_MAX_REARM_ATTEMPTS`), `engine/services/user_data_stream.py` (A-3); new
`engine/tests/test_query_real_exit_from_user_trades.py`, new
`engine/tests/test_on_fill_client_id_extraction.py`, new
`engine/tests/test_uds_listen_key_expired_reconnect.py`, new
`engine/tests/test_account_update_reconcile_decision.py`, new
`engine/tests/test_cancel_symbol_algo_orders.py`, new
`engine/tests/test_reconcile_naked_position_rearm.py`, new
`engine/tests/test_maybe_amend_exchange_sl.py`, new
`engine/tests/test_execute_entry_bracket_safety.py`; docs: `0_tracker.md`, `0_fixes-queue.md`,
`21_live-algo-industry-standard-audit.md`, `workspace/docs/state/CURRENT_STATE.md`,
`workspace/docs/features/algo-trading/SPEC.md`, `handoff.md`.

**Done — 21.5a/b (A-9, same session, continued unattended per user instruction):**
- **A-9 (a)+(b)** (`engine/services/binance_testnet.py`): `send_signed_request` now tracks
  `X-MBX-USED-WEIGHT-1M` per base_url (`_record_used_weight`) and defers any non-order-critical
  call (raises `BinanceBackpressureError` *before* dispatching) once the last-seen weight is
  at/above a 1800 (75% of the shared 2400/min) soft limit, only while that reading is still inside
  a 60s freshness window. On an actual 429/418, `_handle_rate_limit_response` reads `Retry-After`
  (60s default if absent) and pauses non-order-critical calls on that base_url until it expires.
  `/fapi/v1/order` and `/fapi/v1/algoOrder` are exempt from both guards by design — a skipped
  stop-loss/emergency-close is worse than a rate-limit warning.
- **Not shipped — 21.5(c)**: batching `positionRisk`/`openAlgoOrders` into one un-parametered call
  per session per candle wave (instead of one per symbol) needs a session-level fan-out/fan-in
  restructure of `_run_symbol_loop` — today each symbol is an independent `asyncio` task. Materially
  larger and riskier than (a)/(b) without a way to live-verify it this session; deliberately left
  as 21.5's remaining scope rather than rushed.
- **Found and fixed A-15 (new, High) while wiring backpressure in:**
  `_reconcile_exchange_state`'s Case 2 ("exchange has no position, close locally") derived
  `has_exchange_position` purely from `exchange_amt`, which defaulted to `0.0` whenever the
  `positionRisk` query *failed* for any reason — network blip, timeout, missing credentials, or
  now a deliberate A-9 backpressure defer — and read that identically to a confirmed-flat
  exchange, fabricating a real close on a position that might still be open. This is the same
  real-fills-not-fabricated-closes invariant A-6 already fixed for the emergency-exit path,
  just via the query-failure route. A-9's backpressure defers would have made this measurably
  more likely to fire, so it had to be fixed as part of shipping A-9. Fix: new
  `position_query_ok` flag, set `True` only when the `positionRisk` call itself returns without
  raising; Case 2 now requires `has_local_position and not has_exchange_position and
  position_query_ok`. An unconfirmed query falls into a new branch that logs and leaves local
  state untouched, retrying next candle. Case 1 (restore) and Case 3 (both open) were already
  safe by construction — both require `exchange_pos` to have actually been populated.
- **Tests:** `engine/tests/test_binance_backpressure.py` (18 cases: weight parsing, soft-limit
  defer, stale-reading-doesn't-gate, order-critical-paths-exempt, 429/418 pause + `Retry-After`
  parsing + default fallback, non-rate-limit statuses don't pause, pause-expiry, plus
  `send_signed_request` end-to-end against a fake httpx client). **These were actually executed
  with real `pytest` in this session's sandbox** (a venv with `pytest`+`httpx` installed) — not
  just `ast.parse` — since `binance_testnet.py` has no TA-Lib/numpy dependency chain, unlike the
  rest of the engine test suite. All 18 passed. (Attempted the same for the other new test files
  by installing `numpy` too, but the sandbox's `pip install numpy` consistently timed out —
  those remain `ast.parse`-only + manual-review verified, same as 21.1–21.4.)
- Docs: `0_tracker.md` (Plan 21 row + Notes), `21_live-algo-industry-standard-audit.md` (status
  header, A-9 partial-fix + new A-15 finding, Part C 21.5 row), `CURRENT_STATE.md` (new Known-Debt
  bullet), `algo-trading/SPEC.md` (new bullets in Reconciliation and SL/TP sections).

**Files changed (21.5 additions):** `engine/services/binance_testnet.py` (weight tracking,
`BinanceBackpressureError`, `_check_backpressure`, `_record_used_weight`,
`_handle_rate_limit_response`, `_is_order_critical_path`), `engine/core/live_bot_manager.py`
(A-15: `position_query_ok` flag + gated Case 2); new
`engine/tests/test_binance_backpressure.py`.

**Done — 21.7 code portion (A-11 + A-14, same session, continued unattended):** both logging-only,
matching Plan 21's own no-golden-master scope. **A-11**: `clamp_and_round_qty`
(`engine/utils/symbols.py`) now logs a `warning` with the effective multiplier whenever its
minNotional bump-up actually inflates a sized quantity (silently-inflated risk-per-trade,
previously unlogged); skipped trades and `reduce_only` calls correctly never warn. **A-14**:
`execute_entry` now measures `|fill_price - ref_price| / ref_price` on every entry — `info` below
1%, `warning` + a session notification at/above it. Neither changes any returned value, rejects an
entry, or touches backtest output. A-12/A-13 intentionally NOT started — both are framed by the
audit itself as needing a `DECISIONS.md`-style product decision, not code (data-provenance choice;
wick-check-dedup-while-brackets-armed choice) — held per the user's "hold critical decisions"
instruction rather than guessed at. Tests: `engine/tests/test_clamp_qty_risk_inflation_log.py` (5
cases, **actually run with real pytest**, no TA-Lib/numpy dependency) and
`engine/tests/test_execute_entry_slippage_log.py` (3 cases, `ast.parse`-only — needs
`core.live_bot_manager`'s numpy chain). Docs: `0_tracker.md`, `21_live-algo-industry-standard-audit.md`
(A-11/A-14 fixed + Shipped notes, Part C 21.7 row, status header), `CURRENT_STATE.md`,
`algo-trading/SPEC.md`.

**Files changed (21.7 additions):** `engine/utils/symbols.py` (A-11 warning log in
`clamp_and_round_qty`), `engine/core/live_bot_manager.py` (A-14 slippage log +
`_SLIPPAGE_ALERT_THRESHOLD_PCT`); new `engine/tests/test_clamp_qty_risk_inflation_log.py`, new
`engine/tests/test_execute_entry_slippage_log.py`.

**Session note:** the user stepped away mid-session and explicitly instructed continuing
unattended through the rest of the P0 track — use the plan's own recommended next step at each
point, hold anything genuinely requiring a user decision rather than guessing, and keep working on
adjacent tasks instead of idling. All of 21.1–21.4 and 21.5a/b shipped code-side under that
instruction. 21.5(c) is a genuinely larger architectural decision (concurrency restructure) best
left for a session that can live-verify it — picking up other unblocked P0/P1 work next instead of
guessing at that redesign.

**NOT done — do not treat 21.1–21.4 or 21.5a/b as fully closed:**
1. **The engine test suite has not been run inside the Docker container**, for any of these steps.
   This editing session never had Docker access. `test_binance_backpressure.py` (21.5) is the one
   exception — it was actually run with real `pytest` in a sandbox venv (18/18 passed), since
   `binance_testnet.py` has no TA-Lib/numpy dependency chain. Every other new/changed test file got
   only a dependency-free `python3 -c "import ast; ast.parse(...)"` check plus manual Read-tool
   review — attempted to extend real-pytest verification to those too by installing `numpy` in the
   sandbox venv, but `pip install numpy` consistently timed out (network/sandbox limitation, not a
   code issue). **Run before trusting any of this:**
   `docker exec enma_trading_platform-engine-1 pytest /app/tests/` and fix anything that surfaces —
   a plausible failure class is a signature mismatch between the test harness's fake strategy/
   session shapes and what the real code actually reads.
2. **No live re-verification** of any behavioral claim — the F7 ~60s staleness symptom, the
   `openAlgoOrders`-empty-after-close acceptance criterion (21.3), the naked-position re-arm/
   force-close path (A-7), the exchange-SL amend-on-tighten (M-4), the emergency-close retry
   ladder (A-6), or the weight-tracking/429-pause behavior (21.5a/b) and the A-15 fix — none have
   been exercised against a real Binance Testnet session yet.
3. `CURRENT_STATE.md`/`algo-trading/SPEC.md`/`0_tracker.md` are all written to say "code-shipped,
   pending verification" — do not silently upgrade that language to "confirmed fixed" without
   actually running #1 and #2.
4. **This session hit a bash-sandbox file-caching bug** (unrelated to the engine code): the bash
   tool's mounted view of this repo intermittently serves stale, frozen copies of files that were
   just edited heavily in-place (`0_tracker.md`, `handoff.md`, and `live_bot_manager.py` all hit
   this — `stat` showed mtimes frozen well before the actual last edit time). The Read/Write/Edit
   file tools were unaffected and always showed correct content. If a future session sees a git
   diff or `ast.parse` failure that looks like truncation/corruption on a heavily-edited file,
   check the file via the Read tool before assuming real data loss — cross-reference `stat` mtime
   against the actual edit time first. New files are unaffected — this bug only hit files edited
   repeatedly in place within the same session.
5. **21.5(c)** (batched reconcile) genuinely not started — see the "Not shipped" note above; needs
   a deliberate concurrency-restructure design pass, not a same-session bolt-on.
6. **A-12/A-13 (21.7 remainder)** intentionally not started — both need a `DECISIONS.md`-style
   product decision from the user, not code (see the 21.7 Done section above).

**Next session (or continuing unattended):** (1) run the container test suite — fix any failures
before trusting any of 21.1–21.4/21.5a/b/21.7; (2) run the small live-session reproduction
described in the 21.1 section above, now also checking `GET /fapi/v1/openAlgoOrders` is empty
after closes (21.3), a tightened trailing stop actually shows up as a replaced order on Binance
(M-4), a deliberately-broken SL placement exercises the A-6 retry ladder and A-7 re-arm/
force-close path, a 429/418 response actually pauses subsequent reconcile polls without blocking
order placement (21.5a/b), and a minNotional-bumped entry / an abnormal-slippage fill both surface
in the logs as expected (21.7); (3) once all pass, flip status language from "code-shipped,
pending verification" to "shipped" across `0_tracker.md`, `0_fixes-queue.md`'s F7 row, and the doc
files, and close F7's item 1 properly. **Everything code-shippable on the P0/P1 live-correctness
track without a user decision is now done** — remaining Plan 21 items (21.5c, A-12/A-13) either
need a design pass or a product decision; Plan 22's 22.1–22.3 (Session Risk Governor) is
**NOT actually unblocked** despite landing after 21.1–21.4 in the execution order — Part F of
`22_risk-management-industry-standard.md` has open questions (auto-flatten opt-in, daily-loss
window anchor, Chaos governor defaults, reject-vs-warn on capital over-commit) that want user
answers before implementation, per that plan's own text. A genuinely unblocked next candidate for
a future unattended session: **Plan 24** (BestSupertrend fixes) S-5 (docs-drift-only, no code risk)
— S-1/S-2 need a golden-master re-baseline this sandbox cannot run (no Docker), so hold those; or
survey `0_tracker.md`'s Active work table fresh for anything else genuinely decision-free and
golden-master-free. Git commit for 21.5/21.7's `binance_testnet.py` + `live_bot_manager.py` +
`utils/symbols.py` + new test file changes is still pending as of this handoff entry — same
lock-file-rename workaround as before, verify files aren't stale in bash before trusting `git add`.

