# 21 — Live Algo-Trading Industry-Standard Audit (signals → orders → SL/TP → monitoring)

**Status:** In progress (21.1 shipped 2026-07-17; 21.2–21.5, 21.7 not started) · **Created:** 2026-07-16
**Scope:** the full autonomous live-trading path — signal generation (five-model pipeline),
order placement, SL/TP bracket placement, fill detection, reconciliation, monitoring, and
session stop — audited against industry-standard failproof expectations (freqtrade /
nautilus-trader conventions, Binance USDⓈ-M futures API semantics).
**Method:** full read of `engine/core/live_bot_manager.py`, `engine/core/kernel.py`,
`engine/core/pipeline.py`, `engine/services/user_data_stream.py`,
`engine/services/binance_testnet.py`, `engine/utils/rate_limiter.py`,
`engine/utils/symbols.py` (targeted), `engine/core/models/risk.py` (targeted), plus
`algo-trading/SPEC.md`, `binance-api.md`, `CURRENT_STATE.md`, `0_fixes-queue.md`, `handoff.md`.
**Rule D:** this file is docs-only. No code was changed in this pass.

**Relationship to existing debt:** F7 (fixes-queue) already tracks the confirmed ~60s
fill-detection lag, the TP `400` failures, and the FXSUSDT stuck-open anomaly. This audit does
NOT re-catalog those — it found **the likely root causes of F7 item 1** (findings A-1, A-2, A-3,
A-8 below) plus several independent defects the live Chaos run never surfaced.

Confidence tags per root CLAUDE.md Rule J: `[Certain]` = read directly from code,
`[Likely]` = strong inference, `[Guessing]` = gap-filling.

---

## Part A — Findings (defects and gaps)

### A-1 · `_query_real_exit_from_user_trades()` is broken — missing credentials · [Certain] · **Critical**

`live_bot_manager.py` ~line 2337:

```python
trades = await _signed(
    "GET", "/fapi/v1/userTrades",
    params={"symbol": symbol, "limit": 20},
    mode="testnet",
)
```

`send_signed_request(method, path, api_key, api_secret, ...)` has **no defaults** for
`api_key`/`api_secret` (`binance_testnet.py:93-99`). This call omits both → `TypeError` on
every invocation → swallowed by the surrounding `except Exception` → returns `None` → the
caller (reconcile Case 2) falls back to the candle/SL-TP **estimate**.

**Impact:** the Plan 5.2 "reconstruct the real close from Binance's own trade history" path has
**never executed**. Every `exchange_sync` close (i.e. every SL/TP that fired exchange-side —
the majority of closes for a bracket strategy) books estimated exit price and locally-recomputed
PnL, not Binance's authoritative `realizedPnl`. This also silently negates the
`CURRENT_STATE.md` Known-Debt claim that a `userTrades` call "would be needed (not yet
implemented)" — it *was* implemented, and it has been dead on arrival.

**Fix:** pass `api_key, api_secret` (already available at the call site — Case 2 fetches them
two lines above the call). Add a unit test that drives Case 2 against a stubbed Binance layer
and asserts the userTrades result is actually consumed.

### A-2 · `_on_fill` raises `AttributeError` on every fill event — the event-driven path is dead code · [Certain] · **Critical — likely F7 item-1 root cause**

`live_bot_manager.py` ~line 1389:

```python
client_algo_id = order_data.get("clientOrderId", "") or order_data.get("i", "")
...
if status in ("FILLED", "PARTIALLY_FILLED") and client_algo_id.startswith("tpsl_"):
```

Two compounding bugs:
1. The `ORDER_TRADE_UPDATE` `o` payload has **no `clientOrderId` key** — Binance uses `c`
   (see `user_data_stream.py`'s own docstring field list, which lists `s, X, z, Z, l, L, p, q,
   Y, T, S, o, f, ap, sp` — and `c` in the real payload). `.get("clientOrderId", "")` is
   always `""`.
2. The fallback `order_data.get("i", "")` returns Binance's `orderId` — an **int** in the JSON.
   `int.startswith(...)` raises `AttributeError`.

So for every genuinely-delivered FILLED/PARTIALLY_FILLED frame, `_on_fill` crashes at the
`startswith` call. The exception is caught by `_handle_order_trade_update`'s per-callback
`try/except` and logged as `callback error` — and critically, **the
`_reconcile_exchange_state()` call at the end of `_on_fill` never runs.** The event-driven fill
path (F-020) is therefore dead even when Binance *does* emit the event; the system always waits
for the next candle-close REST poll. This exactly reproduces F7's observed ~50-55s lag —
check the engine logs from the 2026-07-16 Chaos run for
`callback error: 'int' object has no attribute 'startswith'` to confirm.

**Fix:** read `order_data.get("c", "")`, coerce with `str(...)`, and restructure `_on_fill` so
the reconcile call is not skippable by a peer-cancel failure (wrap the OUO block in its own
`try/except`). Note even after this fix the `tpsl_` match may still miss algo-order fills —
the conditional order was placed with `clientAlgoId`, and the order Binance creates on trigger
may carry a *generated* client id, not the `tpsl_*` one. That's what the F7 WS-frame logging
will settle. The reconcile-on-any-fill behavior (which needs no id match) is the part that must
be made unconditional.

### A-3 · `LISTEN_KEY_EXPIRED` permanently kills the user-data stream · [Certain] · **High**

`user_data_stream.py` ~line 243:

```python
elif etype == _Event.LISTEN_KEY_EXPIRED:
    logger.warning("[UserDataStream] Listen key expired — reconnecting")
    self._listen_key = await self._create_listen_key()
    ws_url = f"{_BINANCE_FUTURES_WS}/{self._listen_key}"
    return  # Reconnect loop picks up the new URL
```

The comment is wrong: `return` exits the `_run_ws` **coroutine**, not the inner `async for`.
There is no outer loop after the return — the task ends, silently. A listen key expires at most
24h after creation (keep-alives extend the 60-min idle timeout, not the 24h hard cap on some
deployments) — so any session running long enough loses its user-data stream **permanently**,
with only a warning log. Combined with A-2 this means long sessions degrade to pure 60s REST
polling with no operator-visible signal.

**Fix:** replace `return` with `break` out of the message loop so the outer `while
self._running` reconnect loop re-enters with the refreshed URL. Add a keep-alive failure
escalation (N consecutive keep-alive failures → recreate the key proactively).

### A-4 · Engine-initiated closes never cancel the resting SL/TP conditional orders · [Certain] · **High — live trading hazard**

`DELETE /fapi/v1/algoOrder` is called from exactly two places in the live bot (both OUO
peer-cancel paths: `_on_fill` and reconcile section 6). **No close path cancels the brackets:**

- `execute_exit` (reasons: `strategy_exit`, engine-side `stop_loss`/`take_profit` wick-checks
  from `kernel.check_exits`, `flip`, full `scale_out`) — closes the position via reduceOnly
  MARKET, leaves **both** `closePosition:"true"` conditionals armed.
- `_close_position_on_stop` (session stop) — closes every position, cancels **nothing**.
- The emergency-exit path (A-6) — market-closes, leaves the just-placed TP (if it landed) armed.

Because these are `closePosition:"true"` orders, a stale trigger will market-close **whatever
position exists on that symbol later**: the same session re-entering, a later bot session, or a
user manually trading the symbol after the Redis lock is released. This is a genuine
wrong-money-outcome bug, not hygiene. Industry standard is unambiguous: contingent orders are
cancelled atomically with any close (freqtrade cancels exchange stoploss on every exit;
nautilus `ContingencyType` semantics tie bracket lifecycle to the position).

**Fix:** one helper — `_cancel_symbol_algo_orders(session, symbol, algo_ids | all)` — called
from: `execute_exit` success path, `_close_position_on_stop` (cancel before or after close,
plus a cancel-all for symbols with no tracked ids), the emergency-exit path, and reconcile
Case 2 (see A-5). Acceptance: after any close, `GET /fapi/v1/openAlgoOrders?symbol=X` is empty.

### A-5 · Reconcile Case 2 leaves the surviving bracket leg armed · [Certain] · **Medium** (same hazard class as A-4)

When reconcile finds "local position open, exchange flat" (Case 2 — the exchange SL/TP fired),
the peer leg is supposed to die via OUO peer-cancel. But: the WS peer-cancel path is dead (A-2),
and the reconcile peer-cancel (section 6) is guarded by
`if open_orders and has_local_position and has_exchange_position:` — which is **False in the
very case where the position just closed**. Net: after every exchange-side SL/TP close detected
by polling, the surviving leg stays armed until manually cancelled. Fold into the A-4 helper —
Case 2 must cancel all tracked algo ids for the symbol.

### A-6 · Emergency-exit path fabricates its close and can silently leave a naked position · [Certain] · **High**

`execute_entry`'s F-018 block (SL placement failed after entry filled):
1. It books the trade with `exit_price = fill_price` (the **entry** price) — never reads the
   emergency close order's real `avgPrice`. PnL is fabricated as exactly `-fee` — contradicts
   Plan 5.2's "real fills, not fabricated closes" invariant, which was applied to `execute_exit`
   but not here.
2. If the emergency MARKET close **itself fails**, the code logs an error and still records the
   trade as closed and returns — locally flat, exchange still holding a position **with no SL**
   (SL placement is what just failed). Reconcile Case 1 will restore it next candle, but
   restore re-arms brackets only from *existing open algo orders* — there are none. The
   position then runs unprotected indefinitely (see A-7). No banner/webhook alert fires.

**Fix:** confirm the emergency close fill (same `_extract_fill_price` → `_query_real_fill_price`
ladder as `execute_exit`), book the real price; on close failure do NOT record a close — leave
local state open (matching 5.2's contract), emit a loud `error` notification + webhook, and let
a retry ladder (e.g. 3 attempts with backoff) run before surrendering to reconciliation.

### A-7 · No naked-position detection or stop re-arming · [Certain] · **Medium**

Nothing in the loop verifies that an open position has a live protective stop on the exchange.
Restored orphans (Case 1) with no open algo orders, TP/SL-placement 400s (the F7 item-2 class),
and A-6 leftovers all produce positions that run naked forever, silently. freqtrade re-places a
missing exchange stoploss on every iteration; that safety loop is absent here.

**Fix:** in reconcile Case 3 (both sides have the position), if `strategy.stop_loss` is set but
no tracked/open SL algo order exists on the exchange → re-place it (with the same rounding path
as entry) and log/notify; after N consecutive re-place failures → force-close (configurable).
This also converts the F7 TP-400 class from "TP skipped" (permanent) to self-healing.

### A-8 · `ACCOUNT_UPDATE` is received and ignored — the event-type-agnostic fix for the 60s window · [Certain] · **High (enabler)**

`_handle_account_update` only logs. Binance emits `ACCOUNT_UPDATE` with a `P[]` position delta
for **every** position change — including closes executed by conditional/algo orders,
liquidations, and manual closes — regardless of whether `ORDER_TRADE_UPDATE` fires for algo
orders (the open F7 question). Driving an immediate per-symbol reconcile off "position amount
changed vs local view" closes the ~60s staleness window without needing to resolve Binance's
algo-order event semantics at all.

**Fix:** on `ACCOUNT_UPDATE`, for each `P[]` entry with a registered symbol: if `pa` (position
amount) disagrees with the local view, schedule `_reconcile_exchange_state` under the existing
per-symbol lock (debounced, e.g. skip if one is already queued). This supersedes the fragile
per-order-id matching as the primary fill-detection mechanism; keep `ORDER_TRADE_UPDATE`
handling as enrichment.

### A-9 · No 429/418/ban handling and no weight budgeting on signed calls · [Certain] · **Medium**

`send_signed_request` retries only `-1021` (timestamp). There is no handling for HTTP 429
(`-1003 TOO_MANY_REQUESTS`), 418 (IP auto-ban), no `Retry-After` respect, and no reading of the
`X-MBX-USED-WEIGHT-1M` response header. Meanwhile reconcile costs ≥3 signed calls per symbol per
candle (`positionRisk` w5 + `openOrders?symbol` w1 + `openAlgoOrders`), so a 100-symbol 1m Chaos
run burns a large fraction of the shared 2400w/min budget with zero backpressure — and a
rate-limit event would surface as generic per-symbol exceptions, potentially cascading into the
5-consecutive-errors loop-kill. `utils/rate_limiter.py` limits *orders* only.

**Fix:** (a) parse and track `X-MBX-USED-WEIGHT-1M`; above a threshold (e.g. 75%) defer
reconcile polls (orders always pass); (b) on 429/418 honor `Retry-After` and pause non-order
calls globally; (c) batch reconcile — one un-parametered `positionRisk` call (w5 total) per
session per candle wave covers all symbols instead of N×w5, same for `openAlgoOrders`.

### A-10 · No automatic session-level kill-switch — `max_session_dd` is per-symbol-slice only · [Likely] · **Medium**

Each symbol gets its own strategy instance holding `capital/n`; `max_session_dd` is enforced by
`SessionRiskMixin.can_trade()` per instance. Aggregate session drawdown (sum of slices +
realized `session["pnl"]`) is never computed for control purposes, and nothing automatically
trips the existing `trading_state` kill-switch. A session bleeding uniformly across symbols
halts each slice at its own threshold but no one watches the whole book — and `halted` is only
ever set manually via the API.

**Fix:** compute aggregate session equity in `_push_stats` (most inputs already there); when
drawdown from session peak crosses `max_session_dd` → auto-set `trading_state = "reducing"` (or
`halted`), notify + webhook. This is the freqtrade `max_drawdown` protection at session scope —
the protections framework already exists, it's just not wired at this level.

### A-11 · minNotional bump-up silently inflates risk up to +30% · [Certain] · **Low**

`clamp_and_round_qty` rounds quantity UP to satisfy minNotional and accepts up to a +30%
inflation (F-013) before skipping. SL distance is unchanged, so the realized risk-per-trade can
exceed the risk model's `risk_pct` by the same factor, unlogged. Documented behavior, but
industry practice is skip-or-log: either lower the tolerance for risk-sized entries, or log a
`warning` with the effective risk multiplier so sessions aren't quietly running 1.3x risk on
small accounts / low-priced symbols.

### A-12 · Indicator series splices mainnet history onto testnet live candles · [Likely] · **Low (document at minimum)**

Warmup candles come from mainnet data (TimescaleDB via the importer, REST fallback
`fapi.binance.com`), HTF updates also mainnet; live candles come from the **testnet** kline WS
(`fstream.binancefuture.com`); triggers fire on testnet MARK_PRICE. On illiquid testnet symbols
the price series can step discontinuously at the splice and diverge intra-session — spurious
signals follow. Options: accept + document (testnet-only today), or source live klines from the
mainnet public WS for signal purposes (client already does this pattern) while executing on
testnet. Becomes a real decision the day mainnet trading is considered.

### A-13 · Engine-side wick-check exits duplicate the exchange conditionals · [Certain] · **Low**

`kernel.check_exits` (live) market-closes on a candle high/low touch of SL/TP using last-price
wicks, while the exchange conditional triggers on MARK_PRICE. The overlap is mostly benign
(reconcile runs first; a lost race produces a failed reduceOnly close that 5.2 handles safely)
but it produces double-execution semantics, occasional spurious close attempts, and books
`exit_reason="stop_loss"` for what may fill at a very different price. Consider: while exchange
brackets are armed and confirmed open, skip the engine-side SL/TP wick-check (keep it as
fallback when brackets are missing — which A-7's detector makes explicit).

### A-14 · No slippage guard on market entries · [Certain] · **Info / improvement**

Entries are MARKET at next-tick after candle close with `ref_price` = closed candle's close; no
max-deviation check between `ref_price` and fill, no order-book depth consult (book-ticker cache
exists and is already used by SpreadFilter). Standard practice: log slippage per fill (data is
already booked — real fill vs ref), and optionally reject/alert when |fill−ref|/ref exceeds a
configurable bound. Low urgency on testnet; required before any mainnet conversation.

---

## Part A2 — Five-model pipeline audit addendum (2026-07-16, user question: "do all 5 models work fine?")

Full read of `models/base.py`, `cost.py`, `portfolio.py`, `execution.py`, `risk.py` (already read),
`pipeline.py`, plus wiring greps. Verdict per model: **Alpha** — contract sound (boundary-test
enforced, no state reads/writes). **Risk** — math sound; gaps already filed (Plan 22 B-2/B-10,
plus M-4 below). **Cost/TCM** — fill/fee math sound; the predictive gate is broken (M-1/M-2/M-3).
**Portfolio** — sizing variants sound and golden-master-verified; cross-symbol layer missing
(Plan 22 B-8). **Execution** — `route()` five-path diff sound; live bracket maintenance has a
real gap (M-4/M-5).

### M-1 · The "default-on" cost gate is dead — wired to the wrong model object · [Certain] · **High (doc+code defect)**
`live_bot_manager.py:1262` and `backtest_runner.py:905` both set
`strategy.cost_model.min_edge_mult = 0.05` ("active by default" per `CURRENT_STATE.md`). But the
gate that actually runs is `DefaultPortfolioModel._edge_beats_cost()` (`portfolio.py:96`), which
reads `self.min_edge_mult` — the **portfolio model's** attribute (class default `0.0`; no seeded
strategy overrides it). The only consumer of `cost_model.min_edge_mult` is the deprecated
`is_worth_it()`, which nothing in the new pipeline calls. **The edge-vs-cost veto has never
fired, live or backtest.** `CURRENT_STATE.md`'s "default cost gate (min_edge_mult=0.05) active
by default" claim is false (corrected same day with a pointer here).

### M-2 · The edge-vs-cost formula is dimensionally inconsistent · [Certain] · **Medium (latent — activates if M-1 is naively fixed)**
`edge = |conviction| × risk_per_unit × rrr` is a **per-unit price distance**;
`cost.total` is the **whole-position quote-currency cost** (fee+slippage on full estimated
notional). Comparing them makes the gate a function of the symbol's absolute price level:
on a BTC-priced symbol edge ≫ cost·mult always passes; on a sub-cent symbol edge ≪ cost·mult
always vetoes — regardless of actual economics. If M-1's wiring were fixed without fixing this,
the gate would systematically block low-priced symbols. Correct form: multiply the edge side by
the same `qty_est` the estimate uses (both sides in quote currency):
`edge_total = |conviction| × risk_per_unit × qty_est × rrr ≥ mult × cost.total`.

### M-3 · `Signal.magnitude` is a dead field with a lying docstring · [Certain] · **Low**
Documented as "predicted move… feeds the PCM edge-vs-cost veto"; grep shows it is never read
anywhere in the engine. The gate uses `conviction` instead. Either wire magnitude into the M-2
formula (it's the natural edge term) or delete the field and fix the docstring.

### M-4 · Trailing/breakeven stops never amend the exchange SL order · [Certain] · **Medium-High (live semantics gap)**
The risk models' maintain path tightens `constraints.stop_price` every candle;
`DefaultExecution.route()` Path 5 writes it to the **local** `s.stop_loss` only. No code path
amends/replaces the resting `/fapi/v1/algoOrder` SL (grep: the only DELETEs are the two OUO
peer-cancels; there is no cancel+replace on tighten). Net effect when `trail_atr_mult`/
`breakeven_r`/Chandelier are active: the exchange safety net stays at the **original, widest**
stop for the position's whole life; the tightened stop is enforced only by the engine's
candle-close wick check (up to 1 candle late, and it market-closes while both stale conditionals
stay armed — compounding A-4). Between candles, only the stale wide SL protects. Industry
pattern (freqtrade `stoploss_on_exchange` adjustment): on tighten ≥ 1 tick, cancel+replace the
SL leg. Fix belongs with 21.4's bracket-integrity work.

### M-5 · Entries proceed even when their protective stop is invalid against the fill · [Certain] · **Low-Medium**
`LiveAdapter.execute_entry` drops an SL/TP that lands on the wrong side of the fill price
(gap between signal close and market fill) — logs "dropping SL" and **places the entry anyway,
naked on that leg**, and does not clear the invalid `strategy.stop_loss` tuple, so the next
candle's `check_exits` can read the wrong-side stop as instantly triggered and market-close at
whatever the price is (`reason="stop_loss"`, wrong bookkeeping). Industry behavior: reject the
entry outright when the bracket is invalid vs current price (freqtrade does not enter without
its stop). Fold into 21.4's acceptance criteria; also clear local bracket state on any drop.

### M-6 · Portfolio-abstraction stubs are dead code awaiting Plan 22.6 · [Certain] · **Info**
`TargetPortfolio.weight` is computed but consumed by nothing; `BaseStrategy.target_weight()`
exists and is never called. Not defects — but Plan 22.6 should either use them or remove them
rather than leaving two parallel half-abstractions.

### Five-model remediation routing
| Fix | Route | Why there |
|-----|-------|-----------|
| M-1 + M-2 + M-3 together (rewire gate to PCM config, fix dimensions, wire or delete magnitude) | **Plan 9, new step 9.11** — golden-master-gated | Activating a dead gate changes backtest outputs by definition; needs the re-baseline + sign-off protocol, and a decision: fix-and-activate at 0.05, or fix-and-default-off (opt-in). Recommendation: fix-and-default-off first (golden-master-inert), activation as its own baselined step. |
| M-4 + M-5 (exchange SL amend-on-tighten; reject entry on invalid bracket; clear local state on drop) | **21.4** (scope extended) | Same bracket-integrity surface as the naked-position detector. |
| M-6 | **22.6** | Portfolio layer either consumes or deletes the stubs. |

---

## Part B — What was audited and found sound

Entry idempotency (deterministic `newClientOrderId` + query-before-retry on ambiguous failure);
close-path integrity (failure → position stays open, no fabricated close — A-6's path excepted);
flip composition safety (verified by tests, delegation reasoning holds); per-(session,symbol)
`asyncio.Lock` serializing candle-loop vs fill-callback; direction-aware tick rounding for SL
(away) and TP (away, I-11) at both kernel and adapter level; stepSize/minQty flooring incl.
reduceOnly semantics; leverage clamping via `leverageBracket` with defensive 125 cap; testnet-
invalid symbol blacklist with pre-WS abort; kline + UDS reconnect backoff with jitter; bounded-
concurrency session stop that only reports confirmed closes; append-only execution event log
with Node-side seq guard; trade recording before Node notification; risk hard-limit floors
(risk_pct ≤ 0.20, max_session_dd ≤ 0.90); protections framework (cooldown, stoploss-guard);
warmup gating on `_get_min_candles_required` before any signal evaluation.

---

## Part C — Remediation plan (ordered)

All steps are live-adapter/UDS-only — zero backtest-path import overlap, **no golden-master
re-baseline needed** (same reasoning as Plans 5.2/5.4/20). Each step is independently shippable
and testable; per-step engine tests against a stubbed Binance layer follow the
`test_execute_flip_idempotency.py` pattern.

| Step | Fixes | Size | Priority | Notes |
|------|-------|------|----------|-------|
| 21.1 | A-1 (userTrades creds), A-2 (`c` key + `str()` + unconditional reconcile), A-3 (`break` not `return`) | S | **P0** | **Shipped 2026-07-17** — three surgical diffs in `engine/core/live_bot_manager.py` (A-1, A-2 + new `_extract_fill_client_id()` helper) and `engine/services/user_data_stream.py` (A-3). Regression tests: `engine/tests/test_query_real_exit_from_user_trades.py`, `engine/tests/test_on_fill_client_id_extraction.py`, `engine/tests/test_uds_listen_key_expired_reconnect.py`. **Still open:** the container test run (no Docker access from the editing session — only a dependency-free `ast.parse` syntax check was done) and a live small-session reproduction to confirm F7's ~60s staleness symptom is gone. Do the container run + live verification before starting 21.2. |
| 21.2 | A-8 (ACCOUNT_UPDATE-driven reconcile) | M | **P0** | Closes the ~60s window regardless of the F7 answer on algo-order `ORDER_TRADE_UPDATE`. Debounce under the per-symbol lock. |
| 21.3 | A-4 + A-5 (cancel brackets on every close path) | M | **P1** | One `_cancel_symbol_algo_orders()` helper, four call sites. Acceptance: `openAlgoOrders` empty after any close, incl. session stop. |
| 21.4 | A-6 + A-7 + **M-4 + M-5** (emergency-exit truth; naked-position detector/re-arm; exchange-SL amend-on-tighten; reject entry on invalid bracket + clear local state on drop) | M | **P1** | Extends 5.2's real-fill contract to the emergency path; adds the freqtrade-style missing-stop re-placement loop **and** cancel+replace on trailing tighten. Also self-heals the F7 TP-400 class. |
| 21.5 | A-9 (weight tracking, 429/418 handling, batched reconcile) | M | **P2** | Batched `positionRisk`/`openAlgoOrders` per candle wave is the big weight win for Chaos runs. |
| 21.6 | A-10 (automatic session-drawdown kill-switch) | S–M | **Merged→22.1** | Absorbed by Plan 22's Session Risk Governor (`22_risk-management-industry-standard.md`) — same scope, better home. Do not implement twice. |
| 21.7 | A-11/A-12/A-13/A-14 (risk-inflation logging, data-provenance decision, wick-check dedup, slippage guard) | S each | P3 | A-12 and A-13 need a decision note in DECISIONS.md more than code. |

**Sequencing vs existing plans:** 21.1/21.2 fold naturally into the F7 follow-up (`0_fixes-queue.md`
priority item) — they should be treated as *the* next live-trading session's work, ahead of F8.
21.3/21.4 are independent of Plan 5.5/5.6 but should land before Plan 6's `LiveBotManager`
decomposition so the correctness fixes move with the code. Nothing here blocks or is blocked by
the Decimal (5.5) or restart-recovery (5.6) work, though A-8's reconcile-trigger design should be
an input to 5.6's projection design (same as the handoff already notes for the F7 lag).

**Docs to update when steps ship:** `algo-trading/SPEC.md` (SL/TP & OCO Safety + Reconciliation
sections), `CURRENT_STATE.md` Known Technical Debt (the userTrades line is wrong today — the
call exists but is broken, A-1), `binance-api.md` (UDS event-handling notes), `0_fixes-queue.md`
(fold 21.1 into F7's closure), DECISIONS.md (A-12/A-13 decisions).
