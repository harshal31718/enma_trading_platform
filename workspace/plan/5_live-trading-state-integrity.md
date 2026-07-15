# Plan 5 — Live-trading state integrity

**Status:** In progress 2026-07-15 — Steps 5.2, 5.4 shipped · **Priority:** P0 (highest-value correctness work) · **Depends on:** 2, 3 · **Related:** 6

## Progress log (2026-07-15)

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

**Remaining (5.1, 5.3 [partial], 5.5, 5.6) not yet done:**
- **5.1 (event log)** — not started. This is the largest remaining piece: a new append-only
  collection, Node/engine write paths, and turning `LiveSession`/engine memory into pure derived
  views. Steps 5.2/5.4 delivered real correctness value without it by fixing the specific
  bugs directly — the event log is more Plan-6-shaped (structural) than a same-day addition.
- **5.3 (order idempotency) — partially covered as a side effect of 5.2**: close orders now
  carry a deterministic `newClientOrderId` and 5.2's re-query fallback already demonstrates the
  "detect via client id instead of blindly retrying" pattern. **Not done**: entry orders
  (`execute_entry`, `execute_flip`) still have no client id / idempotency, and there's no
  explicit "query by client id before retrying on ambiguous timeout" retry wrapper anywhere —
  the current re-query is only wired into the close path's fill-price lookup, not as a general
  retry-safety mechanism.
- **5.5 (Decimal money)** — not started. Correctly the largest, riskiest remaining piece:
  touches nearly every arithmetic operation across position/PnL/balance math in both engine
  Python and Node, and per the plan's own acceptance criteria needs a *documented* golden-master
  diff (float-precision differences are expected once quantities go through `Decimal`
  rounding) — a deliberate, reviewed change, not something to rush.
- **5.6 (restart recovery)** — blocked on 5.1 by design (rebuilds session memory from the event
  log on engine restart); not started.

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

### Step 5.1 — Define the trade event model (issue SYS-2, SRV-3)
- Introduce an append-only **execution event log** (new collection, e.g. `executionEvents`,
  or a Timescale table) keyed by `sessionId`+`symbol`+monotonic `seq`. Event types: intent,
  order-submitted, fill (partial/full), reconcile-adjustment, close.
- Each event carries a `correlation_id` (Plan 2.4) and, for orders, a `clientOrderId`
  (Step 5.3). Node's `LiveSession` and the engine's in-memory dict become **derived views**
  rebuilt from events — never the source of a number.
- `handleEngineStats` (SRV-3) stops persisting arbitrary PnL/positionDetails as truth; it
  records/forwards events with a sequence number and rejects out-of-order or duplicate seqs.
- Acceptance check: replaying the event log for a session reproduces its final PnL and open
  positions exactly.

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
