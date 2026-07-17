# Plan 5 — Live-trading state integrity

**Status:** In progress 2026-07-16 — Steps 5.1 (scoped), 5.2, 5.3, 5.4 shipped · **Priority:** P0 (highest-value correctness work) · **Depends on:** 2, 3 · **Related:** 6

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

**Remaining (5.5, 5.6) not yet done; 5.1 shipped in scoped form, 5.3 now fully shipped:**
- **5.1 (event log) — Shipped in scoped form** (see Progress log above): the append-only
  collection, engine write paths at every state-mutating site, and a Node-side seq-ordering
  guard are done. **Still not done**: turning `LiveSession`/engine memory into *pure* derived
  views rebuilt from the log — they remain the live read path, the log is additive alongside
  them. That migration is Step 5.6's job (it depends on this step existing, which it now does).
- **5.3 (order idempotency) — Shipped 2026-07-16** (see the dedicated paragraph above this list).
- **5.5 (Decimal money)** — not started. Correctly the largest, riskiest remaining piece:
  touches nearly every arithmetic operation across position/PnL/balance math in both engine
  Python and Node, and per the plan's own acceptance criteria needs a *documented* golden-master
  diff (float-precision differences are expected once quantities go through `Decimal`
  rounding) — a deliberate, reviewed change, not something to rush.
- **5.6 (restart recovery)** — depended on 5.1 by design (rebuilds session memory from the event
  log on engine restart); 5.1's log + `fold_events()` now exist, so 5.6 is unblocked. Not started.

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
- Money math is Decimal; accounting invariants exact.
- Engine recovers session state after restart.
- Golden-master identical for the backtest path; live-path diffs explained.

## Open questions
- Event log store: Mongo collection vs Timescale table? (Timescale already holds candles; PnL
  events are relational/time-series — lean Timescale, but Mongo is simpler operationally.)
- Do we backfill an event log for currently-running sessions, or require a drain+restart at
  cutover? Recommend drain+restart.

## Handoff note template
`Next session: [steps done 5.x], [next step], [golden-master result], [files changed]`
