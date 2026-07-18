# Session Handoff Log

Resume prompts for cross-session continuity (root `CLAUDE.md` Rule G / `AGENTS.md` → Session Handoff).

**Format rules:**
- Newest entry on top: `## <date> — <title> — <status>` with **Goal / Done / Files changed / Open questions**.
- Keep at most the **3 most recent entries**. When adding a new one, delete the oldest — git history is the archive. This file must stay a short resume prompt, not a project log.

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

---
## 2026-07-17 — Plan 9 fully shipped (9.1–9.11): 9.9 QNT-14 round-trip stats, 9.10 fill-model ladder, 9.8 intrabar detail resolution, 9.7 historical funding ledger — **PLAN 9 COMPLETE within its own defined scope** ✅

**Goal:** user said "complete all 9.1..." — asked once up front (via AskUserQuestion) whether each
remaining mechanism should ship opt-in/default-off (matching this session's established pattern)
or activate-by-default with a re-baseline+sign-off per item; got no response within the wait
window, so proceeded on the recommended default (opt-in/default-off, zero behavior change until
explicitly activated) per the tool's own guidance to use best judgment. Worked through the four
remaining Plan 9 steps in size order: 9.9's leftover half, 9.10, 9.8, 9.7 (largest, done last).

**Done — 9.9 (QNT-14 leg-vs-round-trip separation):** new
`services.metrics.aggregate_legs_to_round_trips()` groups a DCA/scale-out position's partial
`"scale_out"` legs + final close into one synthetic round-trip record for STATISTICS only (pnl
summed, qty reconstructed as original position size). Opt-in via
`run_backtest_simulation(round_trip_stats=True)`, default `False`. Persisted `backtestTrades`/
`tradeCount` unchanged either way — only `MetricContext`, `bySide`, returns histogram, MFE/MAE
scatter get the round-trip view when opted in. `"inf"`-string persistence re-audited and left
alone (genuinely dormant, zero client/server consumption).

**Done — 9.10 (fill-model ladder, QNT-11):** new opt-in `LadderedTransactionCostModel`
(`core/models/cost.py`) — volatility-scaled slippage (`vol_slip_mult × ATR%`) + square-root market
impact (`impact_mult × sqrt(notional/ADV)`, ADV approximated from the strategy's own candle
history). Spread half-cost deliberately NOT modeled — backtesting has zero historical bid/ask
spread data. Widened `DefaultTransactionCostModel.adverse_fill()`'s signature with an optional
`qty` param (both `execution.py` call sites already had it in scope). Opt-in via
`self.cost_model = LadderedTransactionCostModel()` — golden-master-safe by construction, no seeded
strategy uses it. **Liquidation fee (QNT-4) deliberately NOT implemented** — `engine/CLAUDE.md`
documents the current "-margin only, no fee on top" behavior as the INTENDED contract, not a bug;
changing it needs a `DECISIONS.md` product call, left for the user. Warmup fail-loud (QNT-16)
deferred — this step's own text ties it to Plan 8 coordination.

**Done — 9.8 (intrabar detail resolution, QNT-3 residual/ENG-18):** `ExecutionKernel` gained opt-in
`intrabar_detail`/`detail_candles_by_symbol`/`base_timeframe_ms`. When both SL and TP wicks hit
one base candle (the genuinely ambiguous case, previously always resolved SL-first by code order
alone), `_resolve_intrabar_winner()` scans 1m sub-candles within that candle's window in
chronological order — whichever level actually triggers first wins, falling back to the SL-first
default when detail data is missing/doesn't cover the window. `check_exits()` refactored to a
candidate-then-decide structure, behavior-preserving by construction for the default (off) path.
`backtest_runner.py` fetches 1m candles only when opted in and the base timeframe isn't already
1m. **No 1m-fetch size/cost guardrail added** — a long backtest opting in would fetch a very large
candle set (e.g. ~525k candles for a 1-year 1h backtest), left as a known limitation.

**Done — 9.7 (historical funding ledger, QNT-5), the largest item:** per root `CLAUDE.md` Rule A,
verified the endpoint against official Binance docs FIRST (`WebFetch` against the official API
reference) before writing any code — `GET /fapi/v1/fundingRate`, public/no signing,
`symbol`/`startTime`/`endTime`/`limit` (max 1000), ascending order, rows
`{symbol, fundingRate, fundingTime, markPrice}`. Documented in `binance-api.md` §2. New
TimescaleDB `funding_rates` hypertable — added to `docker/timescale/init.sql` for future fresh
deployments AND applied directly to the LIVE running database (confirmed via `\dt` before/after —
init.sql only runs on a fresh volume, so a schema-only edit wouldn't have taken effect). New
`services/funding_importer.py` (idempotent `ON CONFLICT DO NOTHING` upsert, mirrors
`candle_importer.py` exactly, paginates via Binance's own `fundingTime` cursor since funding has
no fixed interval) and `services/funding_manager.py` (`ensure_funding_available()`, the single
entry point, mirrors `candle_manager.py`'s contract). **Manually verified end-to-end against real
Binance mainnet data**: fetched 22 real BTCUSDT funding events for 2024-01-01..08 (3/day, matching
expected ~8h cadence, real signed rates and mark prices), confirmed idempotent re-fetch (second
call hit the cache, zero duplicate rows). Wired into `backtest_runner.py` via a new opt-in
`historical_funding` param — `BacktestAdapter.charge_funding()` gained an event-driven branch that
charges each REAL event's own signed rate against its own mark price (not the flat-rate/
fixed-8h-boundary fallback's one constant rate and assumed-fixed schedule). Default `None`
reproduces the exact pre-9.7 code path.

**Verification (cumulative across all 4 steps):** golden master re-confirmed byte-identical after
EVERY step individually (Rule C, not just once at the end) — 5/5 seeded strategies, tol 1e-6 each
time. New test files: `test_round_trip_aggregation.py` (9 cases), `test_laddered_cost_model.py`
(11 cases), `test_intrabar_detail_resolution.py` (10 cases), `test_historical_funding.py` (8
cases) — 38 new tests this arc. Container suite climbed 386 → 397 → 407 → **415/415 passed**.

**Files changed:** `engine/services/metrics.py` (`aggregate_legs_to_round_trips`),
`engine/services/backtest_runner.py` (all four steps' wiring — `stats_trades`, `intrabar_detail`
param + kernel construction, `historical_funding` param + `BacktestAdapter` construction),
`engine/core/models/cost.py` (`LadderedTransactionCostModel`, `adverse_fill` signature widening),
`engine/core/models/execution.py` (pass `qty` through), `engine/core/models/__init__.py` (export),
`engine/core/kernel.py` (`_resolve_intrabar_winner`, `check_exits` refactor); new
`engine/services/funding_importer.py`, `engine/services/funding_manager.py`; new TimescaleDB table
`funding_rates` (`docker/timescale/init.sql` + applied live); new test files listed above; docs:
`9_backtest-and-optimizer-correctness.md`, `0_tracker.md`, `CURRENT_STATE.md`, `engine/CLAUDE.md`,
`binance-api.md`, `handoff.md`. Committed across 4 commits (`1b2779e`, `7430c26`, `2d732a6`,
`d72d70a`), one per step.

**NOT done — 3 items deliberately deferred, not attempted:** liquidation fee (QNT-4, contradicts a
documented `engine/CLAUDE.md` contract — genuinely needs the user's product call, not a mechanical
fix); warmup-insufficiency fail-loud (QNT-16, needs Plan 8 coordination per 9.10's own text);
`"inf"`-string metric persistence (QNT-13's other half, re-audited, still dormant). None of these
three block calling Plan 9 "complete" — they were always explicitly out of this plan's committed
scope, not overlooked.

**Next session:** Plan 9 is done. Remaining work across the whole plan set: Plan 22/24's standing
live-Testnet-verification gap (genuinely blocked, needs a human-observed session), and whatever the
user picks next from `0_tracker.md`'s Active work table — nothing else was investigated this
session beyond Plan 9's own four steps.
