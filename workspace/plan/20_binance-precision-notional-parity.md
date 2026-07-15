# Plan 20 — Binance Precision/Notional Parity Gap in DCA Scale-Out

**Status:** Shipped 2026-07-15 · **Priority:** P1 · **Phase:** 9 · **Depends on:** none · **Related:** 5, 9

**Goal:** Close a real order-rejection risk: the DCA scale-out (partial reduce) path never rounds
its exit quantity to the symbol's Binance `LOT_SIZE`/`MARKET_LOT_SIZE` `stepSize`, unlike every
other order-placement path in the engine, which routes through `clamp_and_round_qty()`.

## Shipped summary (2026-07-15)

Implemented essentially as designed below, same session as the audit. `clamp_and_round_qty()`
(`engine/utils/symbols.py`) gained a `reduce_only: bool = False` kwarg that floors to
`stepSize`/`minQty` and skips the notional bump-up + tolerance-abort branches entirely when
`True` — default `False` keeps every existing call site byte-identical. Wired into both
adapters' `execute_reduce()`: `engine/core/live_bot_manager.py` (live) and
`engine/services/backtest_runner.py` (backtest), both calling
`clamp_and_round_qty(symbol, "Binance Futures", qty, exit_price, reduce_only=True)` right after
the existing pre-clamp `qty <= 0 or qty >= position.qty` guard, with a second post-clamp guard
that skips the reduce (logs a warning, live-side) rather than sending a malformed order if
clamping pushes the qty to 0 or past the open position size — a simpler, safer fallback than the
design's "fall through to a full exit" idea, appropriate given this is dead code today (see
below) and not worth the cross-method plumbing that "fall through" would require.

**Also fixed while in the area (Plan 5 Step 5.3, ENG-10 — found during the same pass, not part of
the original Plan 20 scope):** `execute_entry` in `live_bot_manager.py` previously had NO
`newClientOrderId` on the entry MARKET order and no idempotency handling — if the entry call
itself raised (e.g. a real network timeout after Binance had already accepted the order), the
code just logged "Order failed" and returned `False`, with nothing to stop the strategy from
retrying next candle and opening a genuine duplicate position. Fixed: entry orders now carry a
deterministic `enma_<sessionId8>_<symbol>_<hex8>` client id; on a raised exception during entry
placement, the engine queries by that id (reusing 5.2's `_query_real_fill_price` helper) before
concluding the entry failed — if a real fill is found, the entry proceeds as successful, booked
at the REAL fill price (previously the position was always booked at the pre-trade `ref_price`
estimate, never the real `avgPrice`, even on a normal non-exceptional entry — this fix also
corrects that for the success path, matching 5.2's "book real fills" principle on the entry side
for the first time). DCA scale-in orders also gained a deterministic client id for consistency
(no retry-query wrapper added there — lower-priority, smaller race window).

**Verified:** 3 new tests — `test_clamp_and_round_qty_reduce_only_floors_without_notional_bump`
(`engine/tests/test_phase1_parity.py`: floors non-step-aligned deltas, doesn't bump toward
minNotional, still floors up to minQty), `test_entry_order_timeout_then_actually_filled_does_not_report_failure`
and `test_entry_order_genuine_failure_still_reports_failure`
(`engine/tests/test_live_fill_booking.py`). Full engine suite 124/124 (was 121; +3). Golden
master: MicroScalper byte-identical against the session's last surviving baseline
(`post_5_4_lock.json` vs `post_plan5_reduceonly_fix.json`); the other 4 seeded strategies had no
surviving prior-session baseline to diff against (lost to a container restart earlier this
session, same known issue), but the change is provably inert for all 5 by construction — the new
`clamp_and_round_qty` kwarg defaults `False` (every existing call site unaffected) and
`execute_reduce` remains dead code for the seeded set (confirmed: none override
`adjust_trade_position()`); the `execute_entry` idempotency wrapper only activates on the
exception path, which none of the deterministic golden-master runs exercise.

**Not done (correctly out of scope):** the "fall through to full exit" edge case the design
sketched for a clamp pushing reduce-qty to ≥ position size — simplified to a safe skip instead,
noted above. Manual testnet verification of an actual step-misaligned DCA scale-out order (the
design's own "noted for whoever picks it up" item) — still not done; requires a strategy that
overrides `adjust_trade_position()`, none exist yet.

---

## Current state (audited)

**Every other order-placement path clamps correctly.** `engine/utils/symbols.py:363–436` defines
`round_price()` (quantizes to `tickSize`, `ROUND_DOWN`/`ROUND_UP` selectable) and
`clamp_and_round_qty()` (floors to `stepSize`, then bumps up to satisfy `minQty` and a
buffered `minNotional`, capped by a +30% tolerance check). These are called at every other
order-placement site:

- Entry (fresh position): `engine/core/live_bot_manager.py:158` and
  `engine/services/backtest_runner.py:303` both call `clamp_and_round_qty()` inside
  `execute_entry()`.
- DCA scale-**in** (`intent="add"`, positive `qty_to_adjust`): routes through the same
  `execute_entry()` in both adapters (`engine/core/kernel.py:400–407`), so it is clamped too.
- Flip (`execute_flip`): closes the old leg at its already-clamped `position.qty`
  (`engine/core/live_bot_manager.py:774`, `engine/services/backtest_runner.py:438+`), then opens
  the new leg via `execute_entry()`, which clamps `new_qty` again.
- Full exit (`execute_exit`): closes `abs(pos.qty)`, which was clamped at entry time
  (`engine/core/live_bot_manager.py:642`).
- SL/TP prices: `round_price()` is called at `engine/core/live_bot_manager.py:164–165`,
  `engine/services/backtest_runner.py:516–517`, and `engine/core/kernel.py:492,498`.

**DCA scale-**out** is the one exception.** `strategy.adjust_trade_position()`
(`engine/core/strategy.py:453–467`) is a user-overridable hook that returns an arbitrary
`(qty_delta, tag)` — e.g. `self.position.qty * 0.5` or any other float a strategy author computes.
When `qty_delta` is negative, `engine/core/kernel.py:408–416` (live) and the backtest-loop
equivalent at `engine/core/kernel.py:144–156` compute `reduce_qty = min(abs(delta),
strategy.position.qty)` and pass it **directly** to `execute_reduce()` — with no call to
`clamp_and_round_qty()` anywhere in that chain:

- `engine/core/live_bot_manager.py:496–527` (`execute_reduce`, live adapter): builds
  `reduce_params["quantity"] = _fmt_num(qty)` (line 518) and POSTs straight to `/fapi/v1/order`.
  `_fmt_num()` (`engine/core/live_bot_manager.py:2156–2159`) only formats to 8 decimal places and
  strips trailing zeros/dot — it has no knowledge of the symbol's `stepSize` at all.
- `engine/services/backtest_runner.py:219–281` (`execute_reduce`, backtest adapter): uses `qty`
  as-is for `execution.exit_fill()` — also never quantized.

Both adapters skip rounding identically, so backtest and live stay in **parity with each other**
(no divergence in simulated numbers) — but both are out of parity with **what Binance will
actually accept on the live path**, which is the failure mode this audit is scoped to.

**exec_algo slicing is fine, by contrast.** TWAP/VWAP/Iceberg (`engine/core/models/exec_algo.py`)
only ever slice entries/adds (`"Exits should NOT be sliced"`, `exec_algo.py:53`), and continuation
slices into an already-open position route through `qty_to_adjust` with a **positive** delta
(`engine/core/kernel.py:379–381`), which lands in `execute_entry()`'s `intent="add"` branch — the
clamped path. Slicing never reaches `execute_reduce()`. No gap there.

## Upstream reference (Binance's actual behavior — confirmed live, not assumed)

Fetched from `developers.binance.com/docs/derivatives/usds-margined-futures` (filters +
error-code references, 2026-07-15):

- **`LOT_SIZE`/`MARKET_LOT_SIZE`**: `(quantity - minQty) % stepSize == 0` is enforced by Binance
  itself. **Binance rejects, it does not auto-round**, a quantity that fails this check — error
  `-4023 QTY_NOT_INCREASED_BY_STEP_SIZE` ("Qty not increased by step size"), or `-1111
  BAD_PRECISION` ("Precision is over the maximum defined for this asset").
- **`MIN_NOTIONAL`**: error `-4164`, whose message is explicit — *"Order's notional must be no
  smaller than [X] **unless you choose reduce only**."* Binance exempts `reduceOnly=true` orders
  from the min-notional check. `execute_reduce()`'s orders are `reduceOnly=true`
  (`engine/core/live_bot_manager.py:519`), so the missing `minNotional` check on this path is
  **not** a real gap — Binance wouldn't enforce it here regardless.
- The **`stepSize`/`LOT_SIZE` check is not exempted for `reduceOnly` orders** — only `MIN_NOTIONAL`
  is. So the scale-out path's missing `clamp_and_round_qty()` call is a genuine live-rejection risk:
  any `qty_delta` a strategy computes that isn't already an exact multiple of the symbol's
  `stepSize` (e.g. a percentage-of-position calculation, which is not guaranteed to land on a
  step boundary) will be rejected by Binance with `-4023`/`-1111` on the live path. This is exactly
  the failure mode `round_price()`'s own comment already documents for prices
  (`engine/utils/symbols.py:367–372`, referencing `-1111`) — the same class of bug, just on the one
  qty path that was missed.

## Design

Route `execute_reduce()`'s quantity through the existing `clamp_and_round_qty()` helper in both
adapters, mirroring what `execute_entry()` already does — no new logic, just closing the one gap.

1. **`engine/core/live_bot_manager.py` `execute_reduce()`** (~line 506, before building
   `reduce_params`): call
   `qty = clamp_and_round_qty(symbol, "Binance Futures", qty, exit_price)` — omit
   `stop_loss_pct` (reduce orders don't carry a fresh SL) so the function falls back to its default
   1.05x buffer branch. Since this is a `reduceOnly` order, the `minNotional` bump inside
   `clamp_and_round_qty()` is harmless but unnecessary; the function's return value should be
   floored, not bumped, for a reduce — the important part is the `stepSize` floor, not the
   notional bump. Concretely: after floor-to-stepSize, if the reduce **also** needs a `minQty`
   floor, keep it (Binance's `LOT_SIZE.minQty` still applies to reduce orders); but the notional-
   bump-up branch (`clamp_and_round_qty`'s step 3) should be skipped for reduce calls, since
   bumping a reduce qty upward against `minNotional` makes no sense when Binance itself doesn't
   check notional on `reduceOnly` orders — a reduce-specific variant or an added `reduce_only:
   bool` kwarg on `clamp_and_round_qty()` that skips step 3 when `True` is the cleanest fix.
   Re-derive `reduce_qty` after clamping and re-check `reduce_qty < strategy.position.qty` (the
   existing guard at `kernel.py:410`) — a clamp could theoretically push `reduce_qty` up to equal
   or exceed the open qty, in which case the call site should fall through to `execute_exit()`
   (full close) instead, exactly like the existing `else` branch at `kernel.py:417-425` already
   does for the un-clamped case.
2. **`engine/services/backtest_runner.py` `execute_reduce()`** (~line 223, right after the
   existing `if qty <= 0 or qty >= strategy.position.qty: return` guard): apply the same
   `clamp_and_round_qty(..., reduce_only=True)` call for backtest/live parity, so a backtest never
   reports a scale-out fill at a qty precision live could not have achieved.
3. Since the clamp now happens **inside** the adapters (not in `engine/core/kernel.py`'s
   `execute_reduce` call sites), the `reduce_qty < strategy.position.qty` re-check described in
   step 1 must happen inside each adapter after its own clamp call — `kernel.py`'s dispatch logic
   (`kernel.py:408–416` live, `kernel.py:144–156` backtest-pending) stays unchanged; it only ever
   decides "reduce vs. full exit" based on the **pre-clamp** delta, which is still directionally
   correct (a clamp can only shrink or hold the reduce qty except in the rare up-bump-to-minQty
   case, which the adapter-level fallback in step 1 handles).

## Files to create / modify

| Action | File | Change |
|--------|------|--------|
| Modify | `engine/utils/symbols.py` | Add `reduce_only: bool = False` kwarg to `clamp_and_round_qty()`; when `True`, skip the minNotional bump-up (step 3) and the +30% tolerance abort (step 4) — only floor to `stepSize` and floor-clamp to `minQty` |
| Modify | `engine/core/live_bot_manager.py` | `execute_reduce()`: clamp `qty` via `clamp_and_round_qty(..., reduce_only=True)` before building `reduce_params`; fall through to a full-exit if the clamped qty now equals/exceeds `position.qty` |
| Modify | `engine/services/backtest_runner.py` | `BacktestAdapter.execute_reduce()`: same clamp call for backtest/live parity |
| Modify | `engine/tests/test_phase1_parity.py` | Add a case: `clamp_and_round_qty(..., reduce_only=True)` floors to `stepSize`/`minQty` without bumping for notional |
| Create/modify | `engine/tests/test_exec_algo_slicing.py` or a new `test_dca_reduce_precision.py` | Unit: a scale-out `qty_delta` that is not `stepSize`-aligned produces a floored, step-aligned `execute_reduce` call |

## Verification gate

- **Golden master byte-identical** for all 5 seeded strategies — none currently define
  `adjust_trade_position()`, so this path is presently dead code for the seeded set and the change
  is a no-op for the golden-master baseline. Run `python engine/scripts/golden_master.py` before
  and after per root `CLAUDE.md` Rule C anyway, since the change touches a shared
  `engine/core/kernel.py`-adjacent adapter file.
- New unit test proves: a `qty_delta` like `0.123456789` on a symbol with `stepSize=0.001` is
  floored to `0.123`, not sent raw.
- Manual/testnet check (not required for this plan's merge, but noted for whoever picks it up):
  place a real DCA scale-out on Binance Testnet with a strategy whose `adjust_trade_position()`
  returns a deliberately step-misaligned delta, confirm no `-4023`/`-1111` before the fix and a
  clean fill after.

## Sequencing & risks

- Low blast radius: `adjust_trade_position()` is currently unused by any of the 5 seeded
  strategies (confirmed via `engine/CLAUDE.md`'s seeded-strategy list and no override found in
  `engine/strategies/`), so this is a **latent** bug — it will only bite the first strategy author
  who implements DCA scale-out, but it will bite them with a live order rejection (or, worse, a
  cascading failure if the exception handling around the order call doesn't cleanly recover the
  local position/PnL state — that recovery behavior is out of scope for this plan and should be
  checked separately when this is picked up).
- Risk: adding `reduce_only` to `clamp_and_round_qty()`'s signature is a shared-helper change —
  grep all call sites (`engine/core/live_bot_manager.py`, `engine/services/backtest_runner.py`,
  `engine/tests/test_phase1_parity.py`) before merging to confirm the new kwarg defaults safely
  and doesn't change behavior for existing (non-reduce) callers.
- Not urgent from a user-facing-loss perspective today (no live strategy exercises this path yet),
  but it is a real gap that should be closed before DCA scale-out ships in any user-facing
  strategy or wizard.
