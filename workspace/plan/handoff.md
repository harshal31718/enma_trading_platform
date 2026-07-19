# Session Handoff Log

Resume prompts for cross-session continuity (root `CLAUDE.md` Rule G / `AGENTS.md` → Session Handoff).

**Format rules:**
- Newest entry on top: `## <date> — <title> — <status>` with **Goal / Done / Files changed / Open questions**.
- Keep at most the **3 most recent entries**. When adding a new one, delete the oldest — git history is the archive. This file must stay a short resume prompt, not a project log.

---
## 2026-07-19 — F7 LIVE-VERIFIED (container 450/450 + live testnet chaos): TP/SL-400 root cause = -2021 (not PERCENT_PRICE); fill-staleness fixed to ~0.5s; found+fixed TWO bugs — a platform-breaking governor coercion (server) and the -4015 emergency-close clientOrderId overflow (engine)

**Goal:** user picked "clear verification debt" — run F7's blocked steps (container pytest + a
live testnet reproduction through a TP/SL trigger) now that Docker is available. Mid-session the
user went out and said to continue in **auto mode** (no input), leaving anything genuinely critical
pending. All work is Binance **Testnet (paper)**; all sessions stopped at the end.

**Done — F7 fully verified on the diagnostic front:**
1. **Container pytest: 444/444** (`docker exec enma_trading_platform-engine-1 python -m pytest
   /app/tests/`, up from last-recorded 441). F7's 3 `test_entry_unconfirmed_fill.py` cases pass,
   incl. the FXSUSDT zero-avgPrice phantom-fill guard. Closes the "two sessions shipped F7 code
   with zero container runs" risk.
2. **TP/SL-placement 400 real cause = `-2021 Order would immediately trigger`** — captured live via
   the shipped `_binance_error_detail()` logging (KAITOUSDC/others at 50x, SL sits ~0.03% from
   entry → within immediate-trigger range). **The prior session's `PERCENT_PRICE` hypothesis is
   DISPROVEN — drop it.** Self-heals via the A-7 naked-position re-arm next candle (verified).
3. **Fill-staleness (F7's core symptom) FIXED and live-verified: ~0.5s, not ~60s.** KAITOUSDC SL
   filled 08:11:02.177 → `_on_account_update` (Plan 21.2 A-8) fired *immediately* ("account update
   reports position FLAT but local view says OPEN — reconciling now") → closed 08:11:02.677.
4. Also live-verified working: real-fill entry confirmation + slippage log (A-14), naked-position
   detect+re-arm (A-7), emergency-close retry ladder (A-6), reconcile-from-exchange (21.1 Case 1),
   `-2011 Unknown order sent` handled gracefully on cancel-of-already-gone (A-4), governor-state
   "Reducing" badge on SessionCard (22.7), StoplossGuard cooldown protection block (22.3), clean
   `_close_position_on_stop` using live positionRisk (no orphans).

**Done — a real platform-breaking bug found live AND fixed (server, tested):** at 50x, EVERY chaos
entry was vetoed by the correlation-concentration governor (`entry blocked by risk governor —
candidate ... correlation cluster ... rho > 0.0`), 28 blocks / 0 clean entries. Root cause:
`server/src/utils/risk.js:103` used `isFinite(Number(hardLimits.correlationCap?.rho))` — but the
client sends `rho: null` for a blank "off" field (RiskDashboard.jsx:132), and `Number(null)===0`
(same for `''`) slips past `isFinite`, arming the cap at `rho=0` ("cluster everything"). Same
coercion silently armed `var_limit_pct`/`cvar_limit_pct`/`max_margin_utilization` at 0 too (engine
treats 0 as a real limit, only `None`/`""` as off). **Fixed** risk.js with an `_optNum` guard that
treats null/undefined/'' as unset (explicit 0 still honored). Added 5 regression tests. **Server
jest 116/116** (was 111). **Live-confirmed the fix**: a fresh post-fix chaos = 0 correlation
blocks, entries flow normally.

**Also done later same session (user returned, green-lit the fix) — `-4015` FIXED:** the emergency-
close `newClientOrderId` `enma_<sess8>_<symbol>_<uuid8>_emrg` = 37 chars for KAITOUSDC (>36), so the
F-018 emergency close FAILED with `-4015` on every symbol ≥8 chars (mitigated by the A-7 re-arm, not
catastrophic). Systemic: the base scheme (23+len(symbol) chars) also risked 36 for ~13-char symbols.
First confirmed nothing parses the symbol back out of the id (only `.startswith("enma_"/"tpsl_"/
"oco_")` matters; re-query treats it as opaque) — so shortening is safe. Added a central
`_make_client_id(session_id, symbol, suffix="")` (engine `live_bot_manager.py`) that budgets ≤35
chars, keeping as much of the (cosmetic) symbol as fits; applied to all 6 `enma_…` sites
(660/726/894[emrg]/1212/1335/2837). `tpsl_…` algo ids (~15 chars) untouched. New
`engine/tests/test_make_client_id.py` (6 cases incl. the exact KAITOUSDC+`_emrg` regression). **Full
engine suite 450/450.** Not separately live-re-verified — the fix is a pure length guarantee
(unit-proven, `-4015` is deterministically a length error, new ids are still valid Binance
clientOrderIds) and launching more unattended 50x chaos had more downside than value; exchange
confirmed clean/flat + engine healthy post-edit.

**Files changed (uncommitted, in working tree for review):** `server/src/utils/risk.js` (`_optNum`
guard) + `server/src/utils/__tests__/risk.test.js` (+5 tests) — governor fix, jest 116/116;
`engine/core/live_bot_manager.py` (`_make_client_id` + 6 call sites) + new
`engine/tests/test_make_client_id.py` (6 tests) — `-4015` fix, pytest 450/450. Docs:
`CURRENT_STATE.md`, `0_tracker.md`, `0_fixes-queue.md`, `handoff.md`.

**Next session:** (1) **commit** the two fixes (governor + `-4015`) — user hadn't explicitly said
commit, so both are staged in the working tree; (2) F7 is now closed on the diagnostic side (the
`-2021` residual is expected-and-handled at extreme leverage). Plan 22/24 got substantial incidental
live re-verification this session (governor "Reducing" badge, protections cooldown, correlation cap,
clean stop) — worth noting in their rows. Optional: a live chaos smoke of the `-4015` fix if you
want belt-and-braces confirmation, though the unit proof is conclusive.

---
## 2026-07-18 — F7 continued: error-visibility logging verified, one real entry-fill-confirmation gap found and fixed (FXSUSDT hypothesis) — TP-400 root cause still open, live verification still blocked

**Goal:** continue F7 (fixes-queue) from a prior session that added `_binance_error_detail()`
logging but never verified it in-container or exercised a live reproduction. **This session had no
Docker access at all** (host proxy blocks it) — user explicitly said to focus on logic/code and not
attempt docker/live steps; asked to keep working non-stop with no user input required. Read order
followed: `AGENTS.md` → `CURRENT_STATE.md` (Known Technical Debt) → `CLAUDE.md` →
`0_fixes-queue.md` F7 → `algo-trading/SPEC.md`'s Chaos-run open-issues section → prior `handoff.md`
top entry.

**Done:**
1. Confirmed `_binance_error_detail()` (`engine/core/live_bot_manager.py`) is syntactically sound
   and correctly wired at every entry/SL/TP/close failure log site (`python -c "import ast;
   ast.parse(...)"` on host — container-level confirmation still needs the user).
2. **TP-400 root cause**: read `utils/symbols.py`'s `load_exchange_rules()` + `main.py`'s periodic
   refresh (`EXCHANGE_RULES_REFRESH_INTERVAL_S = 30*60`, added by the 2026-07-03 fix) — this
   fetches ALL exchangeInfo symbols on every call/refresh, not a fixed "warm set", which makes the
   stale-tick-size-cache hypothesis unlikely for BCHUSDT/ETHUSDT specifically (long-listed majors,
   cached since first startup). More plausible unconfirmed candidate: a `PERCENT_PRICE` filter
   rejection on the TP/SL `triggerPrice` — `symbols.py` never validates against that filter before
   submission. **Still needs the real Binance `{code, msg}` from a live reproduction to confirm** —
   this is a code-read hypothesis only.
3. **FXSUSDT-stuck-open**: read `stop_session()` + `_close_position_on_stop()` — both correct by
   inspection (force-close every session symbol against live `positionRisk`, independent of local
   state; the unconditional `.pop()` at the end only runs on a non-exception path, so a real close
   failure correctly leaves the symbol tracked-open rather than falsely reporting success). Then
   read `execute_entry()`'s market-order fill-confirmation and found a real, fixable gap: `if
   entry_result.get("avgPrice"): fill_price = float(...)` treats the *string* `"0.00000000"` as
   truthy, so a market order whose RESULT response carried a not-yet-settled or genuinely-zero
   avgPrice silently kept `fill_price == ref_price` and opened a local position never confirmed
   against a real Binance fill — the one order-placement site that hadn't been brought under the
   ENG-2 "never fall back to an estimate silently" contract (`_extract_fill_price()` +
   `_query_real_fill_price()` re-query) already applied to every close path. **Fixed** to re-query
   by `clientOrderId` and reject the entry (no `Position`, no `open_positions` entry) if still
   unconfirmed, instead of silently proceeding on a phantom fill.
4. Confirmed the WS frame-level diagnostic logging for item 4 of this session's brief (ORDER_TRADE_
   UPDATE vs ACCOUNT_UPDATE arrival, `_on_fill`/`_on_account_update` registration timing) was
   **already shipped** by a prior session (`services/user_data_stream.py` — frame-type logging on
   every message, full-frame dump on unrecognized event types, INFO-level account-update logging) —
   nothing new needed there; the registration-timing question (line ~1353-1409 referenced in the
   task brief; actual current location ~2133-2254) is sound — callbacks register at symbol-loop
   startup, before the kline WS connects, so no exploitable gap found by inspection.

**Verified:** syntax-only (`ast.parse`, host Python) on `live_bot_manager.py` and the new test file
— **NOT run against real pytest** (host lacks `asyncpg`/engine deps by AGENTS.md Rule B design;
confirmed by attempting it and getting `ModuleNotFoundError: asyncpg`). New tests:
`engine/tests/test_entry_unconfirmed_fill.py` (3 cases — real fill unchanged, zero-avgPrice
recovered via re-query, zero-avgPrice + failed re-query correctly rejects the entry with no
phantom position) — written against the same harness pattern as
`test_execute_entry_slippage_log.py`, not yet executed anywhere.

**Files changed:** `engine/core/live_bot_manager.py` (`execute_entry`'s fill-confirmation block);
new `engine/tests/test_entry_unconfirmed_fill.py`; docs: `0_fixes-queue.md` (F7 entry),
`algo-trading/SPEC.md` (open-issues section), `CURRENT_STATE.md` (Known Technical Debt),
`0_tracker.md`, `handoff.md`.

**NOT done — explicitly still blocking F7 closure, all need the user's Docker access:** (1)
`docker exec enma_trading_platform-engine-1 python -c "import ast; ast.parse(...)"` to confirm the
container has the same file host `ast.parse` already validated; (2) `docker exec
enma_trading_platform-engine-1 pytest /app/tests/` full suite — confirm the 3 new tests pass and
nothing regressed; (3) a small (1-3 symbol) live/chaos session against Binance Testnet through a
TP/SL trigger, to capture the real Binance error body for the TP-400 and confirm/deny the
`PERCENT_PRICE` hypothesis; (4) if the FXSUSDT-class symptom reproduces again, check whether the
new "entry order ... returned no confirmed fill price" log line fires for that symbol — that would
confirm today's fix as the actual root cause rather than just a defensible hardening.

**Next session: ⚠️ FIRST PRIORITY, before anything else on `0_tracker.md`.** Resume exactly at the
four "NOT done" items above once Docker/live access is available. If they confirm, close F7 out per
its own acceptance criteria (strike in `0_fixes-queue.md`, "Shipped summary" in the relevant plan
file, update `0_tracker.md` + `CURRENT_STATE.md`). If the TP-400 reproduction shows a different
`{code, msg}` than `PERCENT_PRICE`, that hypothesis should be dropped, not forced. Reason for the
priority bump: two sessions in a row have now shipped F7 code-side fixes without a single container
test run or live reproduction — the verification gap itself is the standing risk.

---
## 2026-07-18 — Plan 5 Step 5.6 shipped in scoped form (restart recovery, ENG-7) — one open product decision left pending

**Goal:** user asked to work through `workspace/plan` non-stop, taking the recommended path
without stopping for confirmation, and to leave anything genuinely critical pending rather than
either blocking or unilaterally deciding it. Tracker's top unblocked P0 item was Plan 5's two
unstarted steps (5.5 Decimal money, 5.6 restart recovery); asked once which to start on (5.5 is
explicitly flagged in the plan/tracker as needing deliberate sign-off, not a same-day task) — user
picked the recommended 5.6.

**Discovery that reshaped scope:** read `_reconcile_exchange_state` (`core/live_bot_manager.py`)
before designing anything and found Plan 21.2's Case 1 (already shipped) already restores
currently-OPEN positions from exchange truth — entry price, qty, leverage, SL/TP brackets, algo
ids — the moment any symbol's candle loop runs, restart or not. So position recovery was already
solved. The real gap: realized PnL from trades that closed *before* a restart isn't on the
exchange position endpoint at all (Binance has no per-bot running PnL counter) and
`start_session` always re-seeded `session["pnl"]` to `0.0`. Bigger discovery:
`server/src/services/reconciliation.js`'s `reconcileSymbolLocks()` treats ANY server-or-engine
restart as a reason to force-**stop and flatten** every running session's real Binance
positions — a deliberate existing fail-safe, not a bug. Plan 5.6's acceptance wording ("kill and
restart the engine mid-session; positions and PnL are recovered... not zeroed") was written
without accounting for that fail-safe. Flipping "stop+flatten on restart" to "resume on restart"
is a real risk-posture product decision (auto-resuming live trading after an unattended crash vs.
staying conservative) — genuinely the user's call, not mine to make silently. Per the user's own
"keep it pending if critical" instruction: shipped the tested capability, did NOT wire a caller
into `reconciliation.js`'s default behavior, and flagged the decision explicitly in the plan doc,
tracker, and here.

**Done:** `services/event_log.fetch_events(session_id, symbol=None)` — new Mongo query helper
(sorted by `seq` ascending, matching `fold_events()`'s precondition), the one missing piece
5.1 didn't need at the time. `core/live_bot_manager._seed_pnl_from_event_log(session_id, symbols)`
replays each symbol's event log and sums `realizedPnl`; best-effort per symbol (one failure
doesn't zero the others). Wired into `start_session` via a new `resume: bool = False` field on
`StartSessionRequest` (`routers/algo.py`) — when true, seeds `session["pnl"]` from the replay
instead of `0.0` right after the session dict is built, before symbol tasks spawn. Open positions
need no equivalent wiring — Case 1 already self-heals them for free. `resume` defaults `False`
and nothing sets it yet, so `start_session`'s existing path is byte-identical when absent.

**Verified:** 6 new tests (`engine/tests/test_session_resume.py`) — `fetch_events` sort-by-seq +
session/symbol scoping (hermetic fake Mongo cursor mirroring `test_execution_event_log.py`'s
established stubbing pattern), `_seed_pnl_from_event_log` summing across symbols, correctly
contributing 0 for a still-open position, one symbol's replay failure not aborting the others,
and the zero-events case. Ran inside the container (`docker exec
enma_trading_platform-engine-1 pytest`, root CLAUDE.md Rule B): container suite **415 → 421/421
passed**. Both touched modules (`core.live_bot_manager`, `routers.algo`, `services.event_log`)
confirmed importing cleanly post-change; docker-compose-watch picked up the file changes and
reloaded the engine container without error (checked `docker logs`); re-verified the live app in
the browser via Claude-in-Chrome before and after (dashboard loads, testnet balance/positions
queries succeed) — no regression. No golden-master check needed (root CLAUDE.md Rule C) — zero
import overlap with the backtest path, same as every prior Plan 5 step.

**Files changed:** `engine/services/event_log.py` (`fetch_events`), `engine/core/live_bot_manager.py`
(`_seed_pnl_from_event_log`, resume-seed call site in `start_session`), `engine/routers/algo.py`
(`resume` field on `StartSessionRequest`); new `engine/tests/test_session_resume.py` (6 cases);
docs: `5_live-trading-state-integrity.md`, `0_tracker.md`, `handoff.md`.

**NOT done — the standing open decision:** no caller sets `resume=True` anywhere.
`reconciliation.js` still always stops+flattens on restart. Whether to change that default is
for the user to decide explicitly — arguments both ways (resuming preserves uptime and avoids
needless flattening of real positions; but auto-resuming after a crash whose cause is unknown
carries its own risk) are the user's call, not a mechanical follow-on to this step.

**Next session:** either (a) get the user's decision on whether/how to wire `resume=True` into
`reconciliation.js` (and if yes, likely gate it — e.g. only resume if the crash-to-restart gap
was short, or require the session's `tradingState` wasn't already `halted`), or (b) move to 5.5
(Decimal money) — the plan's own text calls it out as needing deliberate scoping + an explicit
golden-master sign-off owner, not a rush. Plan 22/24's live-Testnet re-verification remain the
standing genuinely-blocked items across the whole plan set.
