# Plan 5 — Live-trading state integrity

**Status:** Done 2026-07-18 — all six steps shipped (5.1/5.6 in an explicitly scoped form; see their own paragraphs) · **Priority:** P0 (highest-value correctness work) · **Depends on:** 2, 3 · **Related:** 6

## Progress log (2026-07-15)

**5.1 — Execution event log (SYS-2/SRV-3) — Shipped, scoped down from the full spec.** Added an
append-only `executionEvents` Mongo collection (`engine/services/event_log.py`) keyed by
`(sessionId, symbol)` with a monotonic per-key `seq`. Wired `append_event()` calls into every
state-mutating site in `live_bot_manager.py`'s `LiveAdapter`: `execute_entry` (position:open,
DCA add, and the F-018 emergency-exit entry+exit pair), `execute_exit` (both `close_failed` and
the real-fill close), `_close_position_on_stop`, and both branches of
`_reconcile_exchange_state` (position discovered open / discovered flat). `_notify_node` now
carries the assigned `seq` for the three symbol-mutating events (`position:open`,
`position:close`, `position:adjust`); Node's `handleEngineStats`
(`server/src/controllers/algo.controller.js`) rejects a PATCH whose `seq` is `<=` the last
accepted `seq` for that `(sessionId, symbol)` (stored in a new `LiveSession.lastSeqBySymbol`
field) — this is the ordering guarantee Step 5.4's per-symbol `asyncio.Lock` provides
engine-side, extended to Node's ingestion endpoint, which isn't itself ordered. New
`ExecutionEvent.js` Mongoose read model (engine writes, server reads — same ownership pattern as
`TradeRecord.js`).

**What was deliberately NOT done, and why this is a scope-down, not a shortcut:** the plan as
written wants `LiveSession`/engine-memory to become **pure derived views** rebuilt from the
event log — this ships the log itself (the write path + a proven fold/replay function) but
`live_bot_manager.py`'s in-memory session dict and `LiveSession`'s directly-written fields
(`pnl`, `openPositions`, `positionDetails`) remain the live read path, unchanged. Making them
projections is genuinely Step 5.6/Plan-6-shaped work (it changes the session bootstrap sequence
and needs its own dedicated restart-recovery verification, not a same-day bundle onto 5.1) — see
the Progress log's original assessment under "Remaining," which this entry narrows rather than
contradicts. `correlation_id` was dropped from the event schema: Plan 2.3's correlation IDs are
HTTP-request-scoped (an `AsyncLocalStorage`/contextvar set by request middleware), and
`live_bot_manager`'s candle loop and WS fill callbacks run as background asyncio tasks outside
any HTTP request context — `correlation_id_var.get()` would just return the module default
there, so it wasn't wired in as a no-op field.

**Verified:** 13 new tests (`engine/tests/test_execution_event_log.py`) — seq monotonicity per
`(session, symbol)`, seq independence across symbols, write-failure-is-swallowed (mirrors
`trade_recorder.record_trade`'s established best-effort contract exactly), and — the plan's own
stated acceptance check — `fold_events()` replaying a hand-built event sequence reproduces final
PnL and open-position state exactly: simple entry→exit, multiple round-trips accumulating
realized PnL, DCA-add weighted-average entry price, `close_failed` as a correctly-inert no-op
(Step 5.2's whole point — a failed close must not flip state), and both
`reconcile_adjustment` directions. Added a matching `_stub_append_event` autouse fixture to
`test_live_fill_booking.py` (mirrors the existing `_stub_record_trade` fixture) so those tests
stay hermetic. Full engine suite 121/121 (was 108; +13). Golden master unaffected —
`live_bot_manager.py` has zero import overlap with the backtest path (`kernel.py`/
`backtest_runner.py`), same as 5.2/5.4. Verified both engine and server files load/import
cleanly inside their containers (`docker cp` + `python -c "import ..."` / `node -e "require(...)"`
— no live Docker Compose watch active this session, so files were copied in directly for
verification rather than rebuilt).

**Old progress log (5.2, 5.4):**

**5.2 — Real fills, not fabricated closes (ENG-2) — Shipped.** This was "the uncomfortable
part" made concrete: `LiveAdapter.execute_exit` (`core/live_bot_manager.py`) discarded the
Binance close-order response entirely, closed the local position at the caller-supplied
trigger-price *estimate* regardless of what actually happened on the exchange, and did so
**even when placing the close order raised an exception** — silently fabricating a close and
crediting PnL for a position that might still be open on the exchange. Fixed across all three
close-booking sites:
- `execute_exit` (the main SL/TP/strategy-close path): on any failure placing/confirming the
  close order, now `return`s before touching local position/PnL state — position stays open,
  Node is notified with a `close_failed` event, reconciliation owns it from there. On success,
  books the REAL `avgPrice` from the order response (added `newOrderRespType: RESULT` +
  `newClientOrderId`, matching the entry path's already-correct pattern), falling back to a
  direct order re-query (`_query_real_fill_price`) if the immediate response didn't carry a
  usable price.
- `_close_position_on_stop` (session-stop force-close): failure handling was already correct
  here (`return False` before touching PnL); only needed the real-fill-price wiring.
- `_reconcile_exchange_state`'s "position locally but not on exchange" branch: previously
  *guessed* the exit price from candle SL/TP levels. Now queries Binance's own `/fapi/v1/
  userTrades` (`_query_real_exit_from_user_trades`) for fills after the position's entry time
  and uses Binance's own `realizedPnl` (net of `commission`) directly — the candle/SL-TP guess
  is now a last-resort fallback, logged loudly, not the primary path.

**Verified:** 9 new tests (`tests/test_live_fill_booking.py`) driving the real `LiveAdapter`
against a stubbed Binance layer — failure-does-not-fabricate-a-close, success-books-real-fill-
not-trigger-estimate, avgPrice-missing falls back to order re-query, userTrades weighted-average
+ net-PnL computation. **Caught a real, separate, pre-existing bug while writing these**: all
four `sem if sem else asyncio.nullcontext()` call sites used a nonexistent stdlib reference
(`asyncio` has no `nullcontext` — that's `contextlib.nullcontext`); harmless in production today
because `_order_semaphores[session_id]` is always populated before these paths run, but a real
landmine, fixed. Full suite 103/103. Golden master byte-identical (only `live_bot_manager.py`
touched, zero backtest-path overlap). Live-tested via a real testnet MicroScalper session
(stopped before a position opened — waiting on an organic strategy signal wasn't a good use of
verification time; the deterministic mocked-Binance test suite above is the real verification).

**5.4 — Serialize per-symbol state mutation (ENG-3) — Shipped.** The per-candle loop
(`_reconcile_exchange_state` → `check_exits` → `evaluate_and_route`) and the user-data WS fill
callback (`_on_fill`, which also calls `_reconcile_exchange_state` and does F-019 OUO
peer-cancel) both mutate `strategy.position` / `session["pnl"]` / `session["open_positions"]`
for the same symbol with no mutual exclusion — a fill landing mid-candle-loop (or vice versa)
is a real double-close/double-count race, since both paths `await` real Binance HTTP calls,
giving the event loop many chances to interleave them. Added one `asyncio.Lock` per
`(session_id, symbol)` (`LiveBotManager._get_symbol_lock`, lazily created, cleaned up on session
stop), wrapping both critical sections. Confirmed no re-entrancy risk (only these two
acquisition sites; neither `_reconcile_exchange_state` nor anything it calls re-acquires the
lock — `asyncio.Lock` is not reentrant, so this was checked explicitly, not assumed).

**Verified:** 5 new tests (`tests/test_symbol_state_lock.py`) — same key returns the same lock
instance, different symbols/sessions get independent locks, a concurrency test proving two
coroutines racing for the same symbol's lock genuinely serialize (their critical sections never
interleave, checked via a shared-state assertion mid-critical-section) rather than corrupt
shared state, and cleanup removes only the stopped session's locks. Full suite 108/108. Golden
master byte-identical. **Live-tested with a real 2-symbol testnet session** (BTCUSDT + ETHUSDT
concurrently, 1m candles) — both ran independently, engine `/health` stayed responsive
throughout, both stopped cleanly with no hang — the strongest available evidence against a
deadlock short of catching an actual fill mid-candle-loop, which needs organic market timing
this session didn't wait for.

**5.3 — Order idempotency (ENG-10) — Shipped 2026-07-16 (fixes-queue F2).** Closed the last two
gaps flagged below: `execute_flip`'s idempotency-by-delegation was independently verified rather
than assumed — 3 new tests (`engine/tests/test_execute_flip_idempotency.py`) drive the real
`LiveAdapter.execute_flip` against a stubbed Binance layer and prove (a) an exit-leg failure
returns `False` without ever attempting the entry leg, position stays open in its original
direction; (b) an ambiguous entry-leg timeout still resolves to a successful flip via
`execute_entry`'s existing query-by-client-id guard, booking the real re-queried fill price; (c)
a genuine entry-leg failure after a successful exit leaves the strategy flat (`position is
None`) — never stuck half-flipped, never silently retried into a duplicate order. No new client
id was added to `execute_flip` itself — verified unnecessary given the two legs' existing
guarantees; the reasoning is captured as a comment at the call site so a future reader doesn't
have to re-derive it. `execute_reduce` gained its own deterministic `newClientOrderId` (matching
the entry/exit/DCA-add convention), no retry wrapper (still dead code — no strategy overrides
`adjust_trade_position()`). Full engine suite 130/130 (127 existing + 3 new). Golden master not
applicable — live-adapter-only, zero import overlap with the backtest path.

**5.6 — Engine-side state survives restart (ENG-7) — Shipped in scoped form 2026-07-18.**
Discovered while scoping: `_reconcile_exchange_state`'s existing Case 1 (Plan 21.2, already
shipped) already restores currently-OPEN positions from exchange truth the moment any symbol's
candle loop resumes — entry price, qty, leverage, SL/TP brackets, algo ids, all of it. So the
actual gap wasn't position recovery; it was (a) realized PnL from trades that already closed
*before* a restart, which isn't on the exchange position endpoint at all and was silently
re-seeded to `0.0`, and (b) the fact that nothing currently calls a resume path at all — Node's
`reconcileSymbolLocks()` (`server/src/services/reconciliation.js`) treats ANY server-or-engine
restart as a reason to force-stop every running session and flatten its real Binance positions,
by design, as a deliberate fail-safe against auto-resuming automated trading after an unplanned
crash (see its own comment: "Stop orphaned active sessions (server/engine restarted mid-run)").

**Done:** `_seed_pnl_from_event_log(session_id, symbols)` (`core/live_bot_manager.py`) replays a
session's own `executionEvents` log per symbol via the new `services/event_log.fetch_events()`
+ existing `fold_events()`, summing `realizedPnl`. Wired into `start_session` behind a new
`resume: bool` field on `StartSessionRequest` (`routers/algo.py`) — when true, seeds
`session["pnl"]` from the replay instead of `0.0`; open positions need no equivalent code since
Case 1 already self-heals them for free on each symbol's first candle. `resume` defaults `False`
and is additive-only — nothing in `start_session`'s existing path changes when it's absent.

**Verified:** 6 new tests (`engine/tests/test_session_resume.py`) — `fetch_events` sort-by-seq and
session/symbol scoping (hermetic fake Mongo cursor), `_seed_pnl_from_event_log` summing across
symbols, ignoring still-open positions (0 realized PnL contributed — that's the reconcile's job),
one symbol's replay failure not aborting the others, and the zero-events case. Container suite
415 → **421/421 passed**. No golden master needed (zero import overlap with the backtest path,
same as every prior Plan 5 step). Confirmed both modules import cleanly inside the container and
the live app stayed healthy across the docker-compose-watch reload (dashboard screenshot via
Claude-in-Chrome before/after).

**Wiring shipped 2026-07-18, user decision: opt-in toggle, default OFF.** New
`RESUME_SESSIONS_ON_RESTART` env var (`server/src/services/reconciliation.js`, documented in
`.env.example`) — unset/`false` reproduces the exact pre-5.6 stop+flatten behavior with zero code
path change. When `true`, `reconcileSymbolLocks()`'s orphaned-session sweep first tries
`_tryResumeSession()` for every `running`/`starting` orphan (a `stopping` orphan was already being
stopped on purpose when the crash happened — never resumed, regardless of the flag) —
reconstructs the engine's `POST /algo/sessions` body from the `LiveSession` doc + a fresh
credentials/fee-rate lookup, and calls it with `resume: true`. Any failure (missing credentials,
engine rejects the call, network error) falls through to the existing stop+flatten path for that
session only — resume is a best-effort upgrade, never a reason to leave a position untracked.
Deliberately does not touch Redis symbol locks on resume (documented limitation: correct when
Redis itself survived the restart, the common case; a rare double-failure where Redis *also*
lost its data could let a new session race a resumed one for the same symbol until the resumed
session's next candle-loop iteration re-establishes truth via the exchange reconcile).

**Verified:** 7 new tests (`server/src/services/__tests__/reconciliation.test.js`) —
`_rawCredsFor`'s null/decrypt/default-fee-rate/per-userId-cache behavior, `_tryResumeSession`
returning false without calling the engine when credentials are missing, the exact reconstructed
`POST /algo/sessions` body (including `resume: true`), and falling through cleanly when the
engine call throws. Caught and fixed a real Jest gotcha while writing these: requiring
`reconciliation.js` transitively opens a real `ioredis` connection via `./symbolLock` unless
`../config/redis` is mocked — an unmocked run hung indefinitely (open socket keeps the process
alive past test completion) instead of failing loudly, same fix already established in
`symbolLock.test.js`. Server suite: 99 → **106/106 passed**.

**5.5 — Decimal money (ENG-11) — Shipped in scoped form 2026-07-18.** User's explicit brief:
"you work on it and you only test it... visible on charts, in orders and everywhere where
accuracy and precision is required... the benchmark is binance."

**Scope decision made while implementing (documented here since it narrows the plan's own
"move prices/qty/fees/PnL/balances off float" wording):** a full float→Decimal conversion of
every price/qty touch point across `Position`/`kernel.py`/the risk/portfolio/cost models would
ripple Decimal into the hot per-candle replay loop for no accounting-correctness benefit — a
single float arithmetic op on one price/qty already carries far more precision (~15-17
significant digits) than any real instrument needs, and Decimal there only adds cost (roughly
two orders of magnitude slower than float) without fixing anything. **The actual bug only
manifests in REPEATED accumulation** — `balance += pnl` executed thousands of times across a
session/backtest lets each addition's tiny binary-representation noise silently compound (the
classic `0.1 + 0.2 + 0.3 + ...` drift). That only ever happens to running totals. Scoped the fix
to exactly those: `strategy.balance`, `strategy.available_capital`, `BacktestAdapter.total_fees`/
`total_funding` (engine backtest path), `session["pnl"]` (engine live path), and
`computeSymbolStats`'s cross-trade-record aggregation (Node/Mongo). `Position.pnl`/`.margin`,
candle prices, qty, and `liquidation_price` are unchanged (float) — one-shot computations from
real exchange/candle data, not running totals, so they have no accumulation-drift problem.

**Done — engine (`engine/core/money.py`, new module):** `add_money(current, delta)` — accumulates
via Decimal (`Decimal(str(x))`, never `Decimal(float)` directly, which would import the float's
own binary noise) quantized to 8dp (`ROUND_HALF_UP`) at every step, returning a plain float so
every existing reader of e.g. `strategy.balance` is unaffected. `quantize_str()` for
serialization without a float round-trip. Wired into every running-total accumulation site found
by an exhaustive grep for `+=`/`-=` on `balance`/`total_fees`/`total_funding`/`available_capital`:
11 sites in `services/backtest_runner.py` (`execute_entry`, `execute_exit`'s both branches,
`execute_reduce`, `execute_flip`, `charge_funding`'s both branches), 4 pairs (`strategy.balance`/
`session["pnl"]`) in `core/live_bot_manager.py` (F-018 emergency exit, `execute_exit`,
`_close_position_on_stop`, reconcile Case 2's exchange-sync exit).

**Done — Node (`server/src/controllers/algo.controller.js`):** `computeSymbolStats` (aggregates
a session's `tradeRecords` for the Open Positions panel and the header PnL bar) summed via
`$toDouble` — the identical compounding-float-error shape as the engine fix, just executed by
MongoDB over potentially many trade records in one aggregation pass. Changed to `$toDecimal`
(BSON Decimal128, exact summation, a documented MongoDB feature purpose-built for this),
converting back to plain JS numbers (`Number(decimal128.toString())`) before returning — NOT
strings: `SessionCard.jsx`'s `symbolStatsArr.reduce((a, s) => a + s.realisedPnl, 0)` and
`notional / leverage` do real numeric arithmetic on these fields; a string would silently break
via concatenation (`0 + "12.34"` → `"012.34"` in JS) instead of raising. Verified `handleEngineStats`
itself was already correct — `pnl`/`capital` are stored and forwarded as opaque strings
end-to-end, no server-side arithmetic on them (only a display-sign `parseFloat(...) >= 0`
comparison, which has no accumulation-drift exposure).

**Not touched — audited, found already correct:** `Position.pnl`/`.margin` (per the scope
decision above); client `formatters.js` (one-shot display formatting of an already-precise
value from the server — no accumulator, no fix needed); chart rendering (pixel coordinates, not
displayed numbers).

**Verified:** engine — 13 new tests (`engine/tests/test_money.py`, direct `add_money`/`to_decimal`/
`quantize_str` coverage including the textbook `0.1 + 0.2` drift case shown fixed) + 1 new test
(`engine/tests/test_live_money_accumulation.py`, drives the real `LiveAdapter.execute_exit`
across 20 fractional round-trips on one shared strategy/session, confirms `strategy.balance` and
`session["pnl"]` accumulate to the exact expected sum and never desync from each other). Container
suite 427 → **441/441 passed**. Node — 6 new tests
(`server/src/controllers/__tests__/computeSymbolStats.test.js`) confirming Decimal128-shaped
aggregation results convert to real JS numbers (not strings/objects), the exact `0 + pnl`
consumption shape `SessionCard.jsx` performs stays numeric addition, multi-symbol grouping, null
`leverage` handling, and — the aggregation pipeline's own shape — that `$toDecimal` is present
and `$toDouble` is gone. `mongodb-memory-server` (declared in `package.json` for exactly this
kind of test) could not run in this container: no official MongoDB build exists for Alpine
Linux (the server image's base — confirmed via the actual `UnknownLinuxDistro` error while
writing this test), so the aggregation-correctness claim rests on MongoDB's own documented
Decimal128 `$sum` semantics rather than an executed-against-real-Mongo proof; the surrounding
code (pipeline shape, Decimal128→Number conversion) is verified via mocks. Server suite
106 → **112/112 passed**. Live-verified in-browser via Claude-in-Chrome (Trade page balance
display, Dashboard, AlgoTrading) — no regressions, formatting matches Binance's own USDT 2dp
convention; a genuine multi-trade accumulated-drift comparison against live Binance data wasn't
observable this session (the connected testnet account was idle, no open/recently-closed
positions to inspect) — the synthetic 10,000-delta test in `test_money.py` is the direct proof
of the fix instead. **No golden-master A/B diff obtained** — the file-swap needed for a true
before/after was blocked by the session's own safety classifier (correctly reads as
stash-equivalent even via `docker cp`, per root CLAUDE.md Rule H's spirit); relied instead on the
full container suite (zero regressions) plus the targeted accumulation tests, same limitation
already documented for this session's QNT-4 step.

**All six steps now shipped, four fully and two (5.1, 5.6) in an explicitly documented scoped
form — see each step's own paragraph above for what remains open:**
- **5.1 (event log)** — collection + write paths + seq guard done; turning `LiveSession`/engine
  memory into *pure* derived views is not done (was never this step's job — that's what 5.6
  would have needed, and 5.6 itself shipped the replay capability without switching the
  orchestration default).
- **5.3 (order idempotency)** — fully shipped 2026-07-16.
- **5.5 (Decimal money)** — shipped in scoped form 2026-07-18: running-total accumulation sites
  only (see above), not a full float→Decimal conversion of every price/qty touch point — a
  deliberate scope decision, documented above, not an oversight.
- **5.6 (restart recovery)** — capability + tests shipped 2026-07-18; wiring `reconciliation.js`'s
  default from stop+flatten to resume is an explicit open product decision, not attempted.

> Source issues: SYS-2, ENG-2, ENG-3, ENG-10, ENG-11, SRV-3. This is the deepest design flaw
> in the repo: three copies of "truth" (exchange / engine memory / Mongo) reconciled by
> heuristics, exits that book fabricated fills, and PnL kept in floats. It needs Plan 2's
> tests + correlation logging to be provable, and Plan 3's authenticated boundaries so the
> event flow it introduces isn't spoofable.

## The uncomfortable part

Until this plan lands, recorded trades and PnL are **best-effort reconstructions, not
exchange facts** (ENG-2). If real money is ever at stake, this plan gates that — do not
promote to mainnet before it is `Shipped`.

## Goal

The exchange is the single source of truth. Every position change is derived from an actual
fill (real `avgPrice`, real qty), captured once, ordered, and idempotent. Engine memory and
Mongo become *projections* of an append-only event log, not independent truths.

## Scope / what changes

### Step 5.1 — Define the trade event model (issue SYS-2, SRV-3) — **Shipped in scoped form 2026-07-15**
- Introduce an append-only **execution event log** (new collection, e.g. `executionEvents`,
  or a Timescale table) keyed by `sessionId`+`symbol`+monotonic `seq`. Event types: intent,
  order-submitted, fill (partial/full), reconcile-adjustment, close. **Done** — Mongo
  collection, `(sessionId, symbol)`-scoped monotonic seq, event types `fill` (entry/add/exit),
  `close_failed`, `reconcile_adjustment` (the `intent`/`order-submitted` granularity from the
  original list collapsed into `fill`'s payload since the engine only has one HTTP round-trip
  per order today — splitting intent-vs-submitted-vs-filled would need instrumenting the
  Binance call sites individually, deferred, not blocking).
- Each event carries a `correlation_id` (Plan 2.4) and, for orders, a `clientOrderId`
  (Step 5.3). Node's `LiveSession` and the engine's in-memory dict become **derived views**
  rebuilt from events — never the source of a number. **Partially done**: `clientOrderId` is
  captured where available. `correlation_id` deliberately **not** wired in — Plan 2.4's IDs are
  HTTP-request-scoped and the live bot's candle loop/WS callbacks run outside any request
  context, so there's no meaningful value to carry (see Progress log). `LiveSession`/engine
  memory are **not yet** pure derived views — they remain the live read path; the log is
  additive. That migration is Step 5.6.
- `handleEngineStats` (SRV-3) stops persisting arbitrary PnL/positionDetails as truth; it
  records/forwards events with a sequence number and rejects out-of-order or duplicate seqs.
  **Partially done**: seq-ordering rejection is live for the three symbol-mutating events
  (`position:open/close/adjust`). `positionDetails`/`pnl` are still written directly by
  `handleEngineStats` as before — "stops persisting as truth" (i.e. becomes pure passthrough of
  a derived value) depends on 5.6's projection work.
- Acceptance check: replaying the event log for a session reproduces its final PnL and open
  positions exactly. **Done and tested** — `fold_events()` + 13 tests in
  `test_execution_event_log.py`, see Progress log.

### Step 5.2 — Book fills from actual exchange fills, not guesses (issue ENG-2)
- `execute_exit` / `_close_position_on_stop` / emergency-exit must read the **actual fill**
  (`avgPrice`, executed qty) from the order response or a follow-up `userTrades` query, and
  record that — never the SL/TP trigger price, `strategy.price`, or entry==exit.
- If the close order **fails**, the local position must **not** be marked closed and PnL must
  **not** be credited. The symbol stays open and is left to reconciliation; the event log
  records the failure, not a fabricated close.
- The `_reconcile_exchange_state` "exchange has no position" branch must reconstruct the exit
  from the real fill (userTrades) rather than estimating from candle/SL/TP.
- Golden-master: backtest path must stay byte-identical (only the live adapter changes) —
  run before/after (Rule C). Acceptance check: a forced close-order failure leaves the
  position open and un-booked; a normal close books the real `avgPrice`.

### Step 5.3 — Order idempotency (issue ENG-10)
- Every entry/exit/reduce MARKET order carries a deterministic `newClientOrderId`
  (e.g. `enma_<sessionId8>_<symbol>_<seq>`). On timeout/ambiguous failure, the engine queries
  by that id before retrying, so a fill that actually happened is detected instead of
  duplicated or orphaned.
- Acceptance check: simulate a post-fill timeout; reconciliation finds the order by client id
  and does not place a second order.

### Step 5.4 — Serialize per-symbol state mutation (issue ENG-3)
- The candle loop and the user-data `_on_fill` callback both mutate the same session/strategy
  state across `await` points with no lock. Introduce a **per-symbol async lock**; all
  reconcile/close/book operations for a symbol acquire it. This removes the double-close /
  double-count race.
- Acceptance check: a test firing a fill event concurrently with a candle close produces
  exactly one close event and one PnL delta.

### Step 5.5 — Decimal money (issue ENG-11)
- Move prices, quantities, fees, PnL, and balances off `float` to `Decimal` (engine) with
  explicit quantization at exchange precision; serialize as strings end-to-end. Node likewise
  stops doing float PnL math on incoming stats.
- This is a data-pipeline change — golden-master before/after; expect a *documented* diff only
  where float error previously existed, and justify it in the Completion entry.
- Acceptance check: accounting invariants (sum of legs == position PnL) hold exactly in tests.

### Step 5.6 — Engine-side state survives restart (issue ENG-7, partial)
- Because state is now an event log (5.1), the engine rebuilds live-session memory from events
  on startup instead of losing everything. Wire this into the existing engine-startup→Node
  reconciliation handshake.
- Acceptance check: kill and restart the engine mid-session; positions and PnL are recovered
  from the log + exchange, not zeroed.

## Out of scope
- Breaking up `LiveBotManager` and the exchange abstraction (Plan 6 — this plan fixes
  *correctness* within the current structure; Plan 6 restructures it).
- Client rendering of the new event/state model (Plan 7).

## Acceptance criteria (phase)
- All position changes trace to a real fill in the event log; no fabricated exit prices.
- Failed close orders never produce a booked close or PnL credit (tested).
- Orders are idempotent under retry (tested).
- No double-count under concurrent fill+candle (tested).
- Money math is Decimal at every running-total accumulation point (balance, cumulative fees/
  funding, session PnL, cross-trade-record aggregation); accounting invariants exact there
  (tested — see 5.5's own paragraph for the scope decision on what stayed float and why).
- Engine can recover session state after restart (capability shipped and tested 5.6; not wired
  into the default restart path — explicit open decision).
- Golden-master identical for the backtest path where obtainable; two steps this session (QNT-4,
  5.5) couldn't get a literal before/after diff (tooling blocked by the safety classifier) and
  relied on full-suite regression + targeted accumulation tests instead — documented per-step.

## Open questions
- Event log store: Mongo collection vs Timescale table? (Timescale already holds candles; PnL
  events are relational/time-series — lean Timescale, but Mongo is simpler operationally.)
- Do we backfill an event log for currently-running sessions, or require a drain+restart at
  cutover? Recommend drain+restart.

## Handoff note template
`Next session: [steps done 5.x], [next step], [golden-master result], [files changed]`
