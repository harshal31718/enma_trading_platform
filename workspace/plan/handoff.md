# Session Handoff Log

Resume prompts for cross-session continuity (root `CLAUDE.md` Rule G / `AGENTS.md` → Session Handoff).

**Format rules:**
- Newest entry on top: `## <date> — <title> — <status>` with **Goal / Done / Files changed / Open questions**.
- Keep at most the **3 most recent entries**. When adding a new one, delete the oldest — git history is the archive. This file must stay a short resume prompt, not a project log.

---
## 2026-07-17 — Plan 21.1 shipped: the three F7-root-cause fixes (A-1, A-2, A-3) — CODE COMPLETE, VERIFICATION PENDING ⏸️

**Goal:** ship Plan 21 step 21.1 — the three surgical diffs identified by the 2026-07-16 audit as
the likely root causes of F7 (algo-order fill detection lag): A-1 (broken userTrades credentials),
A-2 (`_on_fill` AttributeError killing the event-driven fill path), A-3 (`LISTEN_KEY_EXPIRED`
killing the user-data stream permanently). Per `0_tracker.md`'s "Next session" pointer, this was
the top P0 item and a prerequisite for a meaningful F7 reproduction.

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

**NOT done — do not treat 21.1 as fully closed:**
1. **The engine test suite has not been run inside the Docker container.** This editing session
   had no Docker access (sandboxed environment, no `docker` binary, no access to the user's
   running containers) — only a dependency-free `python3 -c "import ast; ast.parse(...)"` syntax
   check was run on the five changed/new files (all passed). Run before anything else next
   session: `docker exec enma_trading_platform-engine-1 pytest /app/tests/` (or at minimum the
   three new files) and fix anything that surfaces.
2. **No live re-verification.** The original F7 symptom (BSBUSDT/ESPORTSUSDT closing on Binance in
   single-digit seconds but showing open in Enma's UI for ~50-55s) needs to be reproduced again
   with this fix in place — a small 1-3 symbol live/testnet session, watching for the conditional
   SL/TP close to reflect in session state within a few seconds instead of waiting for the next
   candle close. Also grep the resulting engine logs for the old crash signature (`'int' object
   has no attribute 'startswith'`) — it should no longer appear.
3. `CURRENT_STATE.md`/`algo-trading/SPEC.md`/F7's row are all written to say "code-fixed, not
   live-verified" — do not silently upgrade that language to "confirmed fixed" without actually
   running the session in #2.

**Files changed:** `engine/core/live_bot_manager.py` (A-1, A-2, new `_extract_fill_client_id()`),
`engine/services/user_data_stream.py` (A-3); new `engine/tests/test_query_real_exit_from_user_trades.py`,
new `engine/tests/test_on_fill_client_id_extraction.py`, new
`engine/tests/test_uds_listen_key_expired_reconnect.py`; docs: `0_tracker.md`, `0_fixes-queue.md`,
`21_live-algo-industry-standard-audit.md`, `workspace/docs/state/CURRENT_STATE.md`,
`workspace/docs/features/algo-trading/SPEC.md`, `handoff.md`.

**Next session:** (1) run the container test suite — fix any failures before trusting this fix is
real; (2) run the small live-session reproduction described above; (3) once both pass, flip 21.1's
status language from "code-shipped, pending verification" to "shipped" in `0_tracker.md`,
`0_fixes-queue.md`'s F7 row, and the two doc files, and close F7's item 1 properly (it currently
stays open per its own "answered, escalated, NOT closed" convention until the fix is verified, not
just written). Then move to **21.2** (ACCOUNT_UPDATE-driven reconcile, closes the ~60s window
regardless of Binance's algo-order event semantics) — it's next on the P0 live-correctness track
per `0_tracker.md`'s Execution order, ahead of 22.1's Session Risk Governor which explicitly
depends on 21.1–21.4 landing first.

---
## 2026-07-16 — Live algo industry-standard audit (Plan 21) + risk-management plan (Plan 22), docs-only — COMPLETE ✅

**Goal:** audit the full autonomous algo-trading path (signal → order → SL/TP → fill detection →
reconciliation → monitoring → stop) against industry-standard failproof expectations and mark
required changes in `workspace/plan` (Rule D, docs only — zero code touched).

**Done:** full read of `live_bot_manager.py` (all 2372 lines), `kernel.py`, `pipeline.py`,
`user_data_stream.py`, `binance_testnet.py`, `rate_limiter.py`, targeted reads of
`utils/symbols.py` / `models/risk.py`, cross-checked against `algo-trading/SPEC.md`,
`binance-api.md`, `CURRENT_STATE.md`, `0_fixes-queue.md`. Deliverable:
**`21_live-algo-industry-standard-audit.md`** — 14 findings (A-1…A-14) + 7-step remediation plan
(21.1–21.7), wired into `0_tracker.md` (new row 21) and `0_plans.md` (catalog entry).

**Headline findings — three `[Certain]` defects that are the likely F7 item-1 root causes:**
1. **A-1 (critical):** `_query_real_exit_from_user_trades()` calls `send_signed_request` without
   `api_key`/`api_secret` (required positionals) → TypeError swallowed → returns None → every
   `exchange_sync` close books the estimate. Plan 5.2's userTrades path has never executed.
2. **A-2 (critical):** `_on_fill` reads `order_data.get("clientOrderId")` (key doesn't exist —
   Binance uses `c`), falls back to `i` (an int) → `int.startswith()` AttributeError on every
   FILLED frame, caught upstream → the reconcile call at the end of `_on_fill` never runs. The
   F-020 event-driven path is dead code. Check existing Chaos-run logs for
   `callback error: 'int' object has no attribute 'startswith'` to confirm against F7.
3. **A-3 (high):** `LISTEN_KEY_EXPIRED` handler `return`s out of `_run_ws` — kills the UDS task
   permanently (comment claims the reconnect loop picks it up; it doesn't).
   Also high: **A-4/A-5** — no close path cancels the resting `closePosition:true` SL/TP algo
   orders (stale triggers can market-close future positions on the symbol, incl. after session
   stop); **A-6/A-7** — emergency-exit fabricates its close and a failed emergency close leaves
   a naked position that reconcile restores without any stop, no naked-position detector;
   **A-8** — `ACCOUNT_UPDATE` is logged but unused (it's the event-type-agnostic fix for the
   ~60s window); **A-10** — no automatic session-level drawdown kill-switch (`max_session_dd`
   is per-symbol-slice only, `trading_state` is only ever tripped manually).

**Second deliverable (same session) — Plan 22, industry-standard risk management:** reviewed
the rest of `workspace/plan` (gap matrix §1.6, `ref_future-paths.md` Track B/D + forks,
risk-dashboard SPEC, audit_2, plans 12/14) and consolidated the user's scattered risk plans into
**`22_risk-management-industry-standard.md`**: an engine-side **Session Risk Governor**
(pre-trade + periodic checks: aggregate drawdown auto-kill-switch, daily loss limit, true
cross-symbol open-risk budget, margin ceiling, enforced VaR/CVaR, correlation concentration cap)
plus a config-gated inverse-vol allocation layer. **User decisions recorded:** fork #3 = yes
(portfolio layer), fork #2 = rule-based only (no GARCH/ML), VaR enforcement = yes (Zone 1
graduates from display-only). Two new `[Certain]` findings while grounding it: `liq_buffer_pct`
is decorative (`respects_liq_buffer()` has zero pipeline call sites — smoke-tested only), and
`max_portfolio_risk` is per-symbol despite its name (no cross-symbol risk budget exists).
Plan 21 step 21.6 marked `Merged→22.1`; `ref_future-paths.md` forks #2/#3 marked resolved.

**Third deliverable (same session) — workspace/plan restructure, completed work factored out:**
- `0_tracker.md` **rewritten**: split into an **Active work** table (10 rows with an explicit
  "Remaining scope" column — 21, 5, 22, 9, 10, 13, 17, 6, 7, 8) and a **Completed/merged** table
  (1, 2, 3, 4, 11, 12, 14, 15, 16, 18, 19, 20); fixed stale rows (14/15 said "Ready" — they
  shipped 2026-07-16 as F3/F4); Notes trimmed to active plans only (shipped detail lives in each
  plan file's Shipped summary, per convention); Execution order rewritten as three parallel
  tracks with the live-correctness track (21.1→21.4→22.1-3→5.5/5.6) leading.
- `0_fixes-queue.md` **rewritten**: struck-through F1–F6 rows dropped per the file's own
  "drop on next edit" rule; F7 updated from "investigation" to "root-caused — fix = 21.1/21.2"
  with the three Plan 21 findings inline; Not-in-queue table gained Plan 21-remainder and
  Plan 22 rows.
- `0_roadmap.md`: added a **Status snapshot** table (phase-by-phase done/partial/pending);
  shipped/partial tags on Phase 0/1/2/3/9 headers; new **Phase 3b — Live Fill-Path Correctness
  & Risk Governor** (Plans 21+22, the current P0 track) with its own exit gate; sequencing
  table + mainnet gate updated (mainnet now gated on Phase 3 AND 3b).
- `0_plans.md`: stale catalog statuses corrected (2, 3, 4, 5, 11, 14, 15).

**Fourth deliverable (same session) — capital-control audit (user question: "is capital per bot
run controlled by parameter, risk %, per-trade, per-bot, new-bot limits?"):** traced
`algo.controller.js` (start + chaos paths), `Settings.js` limits schema, `utils/risk.js`
resolver + its tests, and the engine's `start_session`. **Controlled and sound:** risk-% per
trade (wizard → `utils/risk.js` clamp → Zone 2 cascade clamp → engine F-014 `min(0.20)` floor →
`size_by_risk`); per-bot `maxSymbolsPerBot` (15); `maxConcurrentBots` (10) enforced on both
start paths; chaos symbol caps; optional per-session `maxOpenPositions`. **NOT controlled:**
`capital` is presence-checked only — no numeric bounds (non-numeric crashes the engine's
`float()`), never validated against the real Binance balance (only "balance" ref in the
controller is equity-curve math), no cross-session capital reservation (10 bots × capital each,
unchecked), and Chaos multiplies `capital × strategyCount`. The engine's entry-time notional
guard checks against the *configured* fiction, not the wallet. Recorded as **B-11/B-12** in
Plan 22 Part B; 22.1 extended with a two-layer **capital integrity gate** (server validate +
reserve across running sessions incl. the Chaos multiplier; engine wallet-clamp backstop);
Part F gained Q5 (hard-reject vs warn-and-confirm on over-commit; proposal: warn on testnet,
reject if mainnet ever arrives). Part A gained rows documenting the launch-limit and risk-%
chains as audited-sound so the next reader doesn't re-audit them.

**Fifth deliverable (same session) — five-model pipeline audit (user question: "do all 5 models
work fine?"):** full read of `models/base.py`/`cost.py`/`portfolio.py`/`execution.py` (+ risk.py
and pipeline.py from earlier). Verdict: Alpha contract sound; Risk math sound (gaps already
filed); Portfolio sizing variants sound; Execution `route()` sound. Six new findings recorded as
**Part A2 (M-1…M-6) in Plan 21**: **M-1 [Certain/High]** — the "default-on" cost gate has NEVER
fired: both injection sites set `cost_model.min_edge_mult=0.05` but the live gate reads
`portfolio_model.min_edge_mult` (0.0) — dead code, and `CURRENT_STATE.md`'s "active by default"
claim was false (corrected same day, pointer to M-1/M-2); **M-2** — gate formula compares
per-unit price distance to whole-position quote cost (would always-veto sub-cent symbols if
naively activated); **M-3** — `Signal.magnitude` documented as feeding the gate, read by
nothing; **M-4 [Certain/Med-High]** — trailing/breakeven stops never amend the exchange SL
(local-only; exchange net stays at the original widest stop; enforcement is candle-close
engine checks); **M-5** — entries proceed when their SL/TP is dropped as invalid-vs-fill, and
the invalid local tuple isn't cleared (instant false stop-out risk); **M-6** —
`TargetPortfolio.weight`/`target_weight()` are dead stubs. Fixes routed: M-1/M-2/M-3 → **new
Plan 9 step 9.11** (Step A golden-master-inert rewire+dimension fix defaulting to 0.0, Step B
separate re-baselined activation decision); M-4/M-5 → **21.4** (scope extended); M-6 → 22.6.

**Sixth deliverable (same session) — Plan 23, user-requested high-risk strategy design:**
`23_high-risk-leverage-strategy.md` ("MarginSurge") — the "fixed to give high returns" ask
reframed honestly (§0: leverage scales both tails; validation gates are allowed to kill the
strategy). Concrete design: 5m/15m compression-breakout (Donchian-20 shifted, BB-bandwidth
squeeze, ADX≥25 rising, MFI flow, EMA-200 alignment, ATR-percentile floor), 0.75×ATR SL with a
hard liquidation-clearance invariant, 2R TP + breakeven at 1R + 1×ATR trail + 24-candle time
stop, leverage 20–50x **selected by** leverage-sensitivity + MC ruin curves (P(dd>50%)<10%,
P(ruin)<2%), `risk_pct` 3–5%, margin-heavy = concurrent positions + utilization (not notional
YOLO). Uses only existing models/indicators. Backtest gates startable now; live phase
hard-gated on 21.1–21.4 (M-4 especially — its trailing is engine-side only until then).
Registered in tracker + catalog. Open Q3 asks the user to pre-accept a "don't ship" verdict if
the cost-realism/regime gates fail.

**Seventh deliverable (same session) — BestSupertrend "never trades" root-caused (Plan 24):**
user-reported; confirmed by full strategy read + arithmetic. **S-1 [Certain], the primary
cause:** at platform defaults (`Settings.js` `defaultLeverage: 1` / `defaultBotLeverage: 1`;
strategy `position_size_pct: 1.0`), `size_by_notional` produces notional = equity×(1+slippage)
→ req_margin > balance at leverage 1 → `EntryFill.affordable()` rejects **every** entry
(backtest logs one hidden warning; live gets Binance `-2019` per attempt). Chaos (50x default)
can trade, default backtests cannot — matching the user's observation exactly. Also found:
**S-2** live HTF constant path takes `tsl[-2]` on an array that already excludes the open bar
(one full HTF bar staler than backtest's `htf_tsl[k-1]`); **S-3** unsatisfiable tf/timeframe
combos (weekly/monthly on ≤4h base under the 500-candle live cap; any HTF-fetch failure on
sub-1h base) return `None` from `_htf_st_at` forever → all signals False, silently; **S-4**
the `order_type` param collides with `OrderPlan.order_type` via `route()`'s
`getattr(s, "order_type", "market")` (latent until anyone honors the field); **S-5** docs say
`SignalExitRiskModel`, code binds `AtrBracketRiskModel`. All in
`24_bestsupertrend-fixes.md` (fix order S-1→S-5; S-1/S-2 need a cheap BestSupertrend
re-baseline — verify the stored baseline's trade count first; live verify after 21.1–21.2).
Registered in tracker (P1) + catalog.

**Files changed (docs only):** new `21_live-algo-industry-standard-audit.md`, new
`22_risk-management-industry-standard.md`, new `23_high-risk-leverage-strategy.md`, new
`24_bestsupertrend-fixes.md`; rewritten `0_tracker.md`, `0_fixes-queue.md`; edited
`0_roadmap.md`, `0_plans.md`, `ref_future-paths.md`, `9_backtest-and-optimizer-correctness.md`
(new 9.11), `workspace/docs/state/CURRENT_STATE.md` (cost-gate correction), `handoff.md`.

**Next session:** ship **21.1** (three surgical diffs: A-1 creds, A-2 `c`-key + str + reconcile
made unconditional, A-3 break-not-return) — it is the prerequisite for a meaningful F7
reproduction — then **21.2** (ACCOUNT_UPDATE-driven reconcile). Then re-run the small live
session from the F7 plan with the improved logging. 21.3/21.4 (bracket-cancel-on-close,
naked-position re-arm) next; they should land before Plan 6 decomposition and are the
prerequisite for starting Plan 22 (a governor over a wrong-state fill path enforces limits
against fiction). Then 22.1–22.3. `CURRENT_STATE.md`'s Known-Debt userTrades line ("not yet
implemented") needs correcting when 21.1 ships — the call exists but has been broken since it
shipped. Plan 22 Part F open questions (auto-flatten opt-in, daily-loss window anchor, Chaos
governor defaults) want user answers before 22.1 implementation, not blocking the earlier steps.

---
## 2026-07-16 — Fixes queue F2–F6 shipped; F7 answered live and escalated (2 new bugs found) — IN PROGRESS ⏸️

**Goal:** work the fixes queue (`0_fixes-queue.md`) top-down starting at F2.

**Done — F2 (Plan 5.3 order idempotency tail), fully shipped:** `execute_flip`'s idempotency-by-
delegation was independently verified (previously assumed-but-unchecked, per the prior entry's
handoff) with 3 new tests in `engine/tests/test_execute_flip_idempotency.py`, driving the real
`LiveAdapter.execute_flip` against a stubbed Binance layer: (a) an exit-leg failure returns
`False` without the entry leg ever being attempted, position stays open in its original
direction; (b) an ambiguous entry-leg timeout still resolves to a successful flip via
`execute_entry`'s existing query-by-client-id guard, booking the real re-queried fill price; (c)
a genuine entry-leg failure after a successful exit leaves the strategy flat, never half-flipped
or silently double-entered. Concluded no new client id is needed on `execute_flip` itself — a
comment at the call site captures the reasoning for future readers. `execute_reduce` gained its
own deterministic `newClientOrderId` (still no retry wrapper — remains dead code, no strategy
does DCA scale-out). Full engine suite 130/130 (127 existing + 3 new), run inside the container
by the user. Golden master not applicable (live-adapter-only, zero backtest-path import overlap).
Plan 5 status is now 5.1 (scoped)/5.2/5.3/5.4 shipped; only 5.5 (Decimal money) and 5.6 (restart
recovery) remain, both correctly kept off the fixes queue (see `5_live-trading-state-integrity.md`).

**Done — F3 (Plan 14, webhook notifications), fully shipped:** per-user `Settings.webhook`
sub-schema (enabled/url/format/events/retries/timeoutMs) + new `server/src/utils/webhook.js`
(`dispatchWebhook` — fire-and-forget, bounded retries, NEVER throws; `sendTestWebhook` — single
attempt, surfaces errors for the test button) wired into `algo.controller.js`'s `startSession`
(session_start) and `handleEngineStats` (entry_fill, exit_fill + conditional liquidation, session_
error, session_stop). `settings.controller.js` validates the nested `webhook` object (same
dot-path partial-update pattern as `limits`) and exposes `testWebhook` on `POST /api/v1/settings/
webhook/test`. Client: Settings page gained a "Notifications" card (enable toggle, URL, format,
retries/timeout, per-event checkboxes, Save + Send Test buttons) via `useTestWebhook` in
`useExchangeSettings.js`. **Verified two ways:** (1) 14 new Jest tests in `server/src/utils/
__tests__/webhook.test.js` — caught and fixed a real bug where an empty `events: []` array was
treated as "unfiltered" instead of "opted into nothing" (fixed the filter condition); full server
suite 63/63 green after the fix. (2) Live browser verification via Claude in Chrome against the
actual running stack: Notifications panel renders, "Send Test" round-trips a real HTTP POST
end-to-end (confirmed both a failure — httpbin.org 503 — and a success — postman-echo.com 200 —
surfaced correctly as toasts), and the saved config survives a full page reload (confirmed via
GET `/api/v1/settings/exchange`). Test config was cleaned up back to disabled/empty afterward —
nothing left live pointing at a test URL. No golden master needed (server-only, no engine touch).

**Done — F4 (Plan 15, data conversion CLI), fully shipped:** new `engine/scripts/enma_cli.py`
(argparse, `python -m scripts.enma_cli <cmd>`, must run inside the container) — `list-data`
(reuses `get_cached_candles_summary()` verbatim, so it's guaranteed to match `GET /candles/
cached`), `export-candles`/`import-candles` (CSV or JSON, format inferred from the file
extension or explicit `--format`), `export-trades` (read-only dump of `backtestTrades` for a
`--job-id`). `import-candles` reuses `candle_importer.py`'s exact `INSERT ... ON CONFLICT DO
NOTHING` SQL, so re-importing is always a safe no-op — genuinely local-data-only, never calls
Binance. New `engine/scripts/_io_formats.py` holds the pure CSV/JSON <-> DB-record transforms
(stdlib `csv`/`json` only, no new deps), kept separate so they're unit-testable without a live
DB connection. **Verified three ways:** (1) 12 new hermetic tests in `engine/tests/
test_cli_roundtrip.py` (fake asyncpg pool replicating the real unique index for ON CONFLICT
semantics, fake Mongo collection for trades) — full engine suite 142/142 (130 + 12). (2) A real
round trip against the live stack's actual TimescaleDB data: exported BTCUSDT/1d (565 rows) to
CSV, re-imported it into the same live table, confirmed the cached-candle count stayed at
exactly 565 (no duplication) via `list-data`. (3) `list-data`'s real output inspected directly
against production data, confirming the acceptance criterion "matches `GET /candles/cached`"
(same underlying function, so structurally guaranteed, but ran for real regardless). No golden
master needed (engine-only, zero import overlap with the backtest/live-adapter paths).

**Done — F5 (wire the Dashboard sparkline/calendar), fully shipped:** `Dashboard.jsx` now
composes the three previously-unwired components with real data — `EquitySparkline`/
`DrawdownSparkline` fed by `useBacktestResult(stats.latestRunId)`'s `equityCurve` (gated on
`stats.latestRunId` existing, since Dashboard is a cross-strategy overview, not tied to one
backtest), and `DashboardCalendar` fed by `useDashboardCalendar()` with a 30D/90D/All timeframe
toggle. First attempt at the toggle used an absolute-positioned overlay — a live screenshot
caught it visually colliding with `DashboardCalendar`'s own internal "X days" badge ("90D"
overlapping "0 days"). Fixed properly, not with a z-index/repositioning hack: added a
`headerActions` prop slot to `DashboardCalendar.jsx` itself (rendered in a flex row before the
day-count badge), and pass the toggle buttons through that prop from `Dashboard.jsx`. Re-verified
live via Claude in Chrome after the fix — toggle and badge now sit cleanly side by side, no
overlap. `client/CLAUDE.md`'s stale "unused component" note on `DashboardCalendar.jsx` cleared.
No client test harness exists for `Dashboard.jsx` yet, so verification was live-browser only (no
new unit tests). No golden master needed (client-only UI composition, zero backend/engine touch).

**Done — F6 (Plan 8.1, docs truth-telling pass), fully shipped:** spawned an audit subagent
(general-purpose, since no `drift-reviewer` agent type exists in this environment) to trace the
doc/code boundary rather than trust the plan's own originating premise. Finding: **the premise was
wrong** — Plan 8's SYS-4 claim that "Node's internal handlers place orders" / Rule 2 is "already
false" doesn't hold against the real call graph; `algo.controller.js`'s internal-route handlers
only decrypt credentials and forward back to the engine via `engineClient`, never call Binance
directly. `CLAUDE.md`/`AGENTS.md` Rule 2 was already literally true — no edit needed there beyond
a phrasing tightening (see below). Six genuine drift items were found and fixed instead: (1)
Binance-isolation rule phrasing didn't carve out the client's direct public WebSocket for market
data — qualified to "no *signed/authenticated* calls" in `CLAUDE.md` and `AGENTS.md`; (2)
`.claude/GOVERNANCE.md`'s source-of-truth hierarchy never mentioned Plan 5's `executionEvents`
log — added a note; (3) `ARCHITECTURE.md` still said "invite-only" (Plan 1 shipped open login
2026-07-14) — corrected, and its Mongo collection list was missing `executionEvents`; (4)
`ARCHITECTURE.md`'s Binance Environment Model table still said Mainnet "not yet implemented" (it's
read-only balance/verify since Plan 4/20) — corrected, `AGENTS.md` tightened to match; (5)
`strategy-management/SPEC.md`'s "Key Invariants" section still asserted live code-editing
validation — Plan 3.2 removed the feature 2026-07-15 but this one bullet was missed in that pass,
now struck through with a pointer to the removal; (6) `client/CLAUDE.md` documented a stale
`binanceWS.js` path (`/ws`/`/stream`) that doesn't match the real code (`/public/ws`, `/market/ws`)
— corrected to match `binance-api.md`'s already-accurate reference; (7) `DECISIONS.md` §6 never
got an entry for the invite-only→open-login transition — appended. **Not done:** the SYS-3
named-volume-divergence documentation item — genuinely new documentation, not a truth-telling fix,
carried forward into Plan 8 proper (not F6's scope). No golden master needed (docs-only, zero code
touch).

**Files changed:** `engine/core/live_bot_manager.py`, new `engine/tests/test_execute_flip_
idempotency.py` (F2); `server/src/models/Settings.js`, new `server/src/utils/webhook.js`, new
`server/src/utils/__tests__/webhook.test.js`, `server/src/controllers/settings.controller.js`,
`server/src/routes/settings.routes.js`, `server/src/controllers/algo.controller.js`,
`client/src/hooks/useExchangeSettings.js`, `client/src/pages/Settings.jsx` (F3); new
`engine/scripts/enma_cli.py`, new `engine/scripts/_io_formats.py`, new `engine/tests/
test_cli_roundtrip.py` (F4); `client/src/pages/Dashboard.jsx`,
`client/src/features/dashboard/DashboardCalendar.jsx` (F5); `CLAUDE.md`, `AGENTS.md`,
`.claude/GOVERNANCE.md`, `workspace/docs/core/ARCHITECTURE.md`, `workspace/docs/core/DECISIONS.md`,
`workspace/docs/features/strategy-management/SPEC.md`, `client/CLAUDE.md` (F6); docs:
`0_fixes-queue.md` (F2–F6 struck through, live queue now starts at F7), `0_tracker.md`,
`5_live-trading-state-integrity.md`, `14_webhook-notifications.md`, `15_data-conversion-cli.md`,
`8_governance-correctness-and-cleanup.md`, `engine/CLAUDE.md`, `handoff.md`.

**F7 (confirm algo-order `ORDER_TRADE_UPDATE` emits live) — attempted live, answered, escalated,
NOT closed:** user ran a live MicroScalper Chaos session (15 auto-selected symbols, 1m, 50x,
Binance Testnet) specifically to answer this. Findings:

1. **Confirmed: the event-driven fill path (F-020) does not reliably catch algo/conditional
   TP-SL fills.** BSBUSDT and ESPORTSUSDT both closed via their conditional SL/TP within
   single-digit seconds of opening — verified against Binance's own Order History (entry
   `19:54:04` IST, conditional sell filled `19:54:08` for BSBUSDT; similar for ESPORTSUSDT) — but
   Enma's session UI kept showing both as open `LONG` positions for another ~50-55 seconds, until
   the next 1m candle-close drove `_reconcile_exchange_state()`'s per-loop REST poll, which is
   what actually caught and closed them. This matches the fixes-queue's anticipated "falls back
   to poll" case, but it's worse in practice than "just staleness" — the UI and the strategy's
   own in-memory position state actively say a symbol is open when Binance has already closed it,
   for up to ~60s. Root cause not isolated (candidate: per-symbol fill 