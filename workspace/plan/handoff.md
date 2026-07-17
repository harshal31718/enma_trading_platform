# Session Handoff Log

Resume prompts for cross-session continuity (root `CLAUDE.md` Rule G / `AGENTS.md` → Session Handoff).

**Format rules:**
- Newest entry on top: `## <date> — <title> — <status>` with **Goal / Done / Files changed / Open questions**.
- Keep at most the **3 most recent entries**. When adding a new one, delete the oldest — git history is the archive. This file must stay a short resume prompt, not a project log.

---
## 2026-07-17 — Plan 13 shipped: informative/multi-timeframe contract (`informative_timeframes` + `self.htf()`) — **primitive shipped, no seeded strategy adopts it yet**

**Goal:** user said "move to plan 13" after Plan 9.11 Step A shipped — implement the plan as
designed rather than re-litigating scope.

**Done:** `BaseStrategy.informative_timeframes: list[str] = []` (opt-in class attr) +
`self.htf(timeframe)` (`engine/core/strategy.py`) — as-of aligns a raw HTF candle array onto base
timestamps: for each base candle at open-time `t`, returns the most recent HTF candle whose CLOSE
time (`open + utils.timeframes.to_ms(tf)`) is `<= t`, via `np.searchsorted` — ported from
freqtrade's `merge_informative_pair` ffill+shift guarantee. Cached per timeframe per `prepare()`
call, invalidated on the next `prepare()` (live rolling-window parity). Requires
`super().prepare(candles)` as a subclass's first line (mirrors the plan's own contract example) —
base `prepare()` now stashes `candles` for `htf()`'s alignment target and clears the cache; this
is a no-op for all 5 existing seeded strategies since none call `super().prepare()`.

**Wiring:** `services/backtest_runner.py` fetches each declared informative timeframe over the
same date range as the base fetch (via the existing `ensure_candles_available()` single entry
point, same pattern, into a new `htf_raw_by_sym` dict) and assigns `strategy._htf_raw` right
before `strategy.prepare(candles_np)` runs. `core/live_bot_manager.py` fetches via the existing
`_fetch_htf_candles` mainnet-REST helper (same source as A-12's mainnet feed) before the warmup
replay loop, and refreshes on every closed base candle inside the main WS loop — deliberately
separate from BestSupertrend's own `tf`/`pd`/`_htf_candles` duck-typing (Plan 24 S-2/S-3), which
predates this contract and is left untouched.

**Verification:** golden master byte-identical (5/5 seeded strategies — none declare
`informative_timeframes`). Boundary suite 20/20 unaffected (`htf()` only callable from
`prepare()`). New `engine/tests/test_informative_alignment.py` (6 cases): correct as-of pick
across one HTF bar's lifetime, no-lookahead swept across multiple HTF bars (every base candle's
assigned bar checked against every bar's close time), all-NaN degrade on missing/failed fetch,
per-`prepare()`-call caching + invalidation on re-prepare, default-`[]` no-op. Container suite:
**364/364 passed** (up from 358/358 at session start). DECISIONS.md #26 records the design;
`engine/CLAUDE.md`'s previously-aspirational `get_candles()` example (flagged stale by the plan's
own audit — never implemented) replaced with the real `htf()` contract.

**Files changed:** `engine/core/strategy.py` (`informative_timeframes`, `htf()`, `prepare()`
anchor), `engine/services/backtest_runner.py` (HTF fetch + wiring), `engine/core/live_bot_manager.py`
(HTF fetch + refresh wiring); new `engine/tests/test_informative_alignment.py`; docs:
`workspace/docs/core/DECISIONS.md` (#26), `engine/CLAUDE.md`, `13_informative-multi-timeframe.md`,
`0_tracker.md`, `handoff.md`. Not yet committed as of this entry — see next session note.

**NOT done — deliberately out of scope:** no seeded strategy adopts `htf()` yet; this ships the
primitive only, not a consumer. Per the plan's own verification gate, **any real strategy that
adopts `htf()` must be run through S5 (Plan 9's lookahead sentinel,
`engine/scripts/lookahead_sentinel.py`)** before shipping — this session's unit tests prove the
alignment primitive itself is causal, not that a specific future strategy uses it correctly.

**Next session:** commit this work (not yet committed as of this entry). Then either (a) build a
real `htf()` consumer (e.g. Plan 17's recursive/warmup-insufficiency analysis explicitly sequences
after 13 "so it also sweeps multi-TF indicators"), or (b) survey `0_tracker.md` fresh — Plan 9.11
Step B (cost-gate activation decision) and Plan 9's other steps (9.7–9.10) remain open, all
requiring a golden-master re-baseline + sign-off rather than being decision-free.

## 2026-07-17 — Plan 9.11 Step A shipped: PCM edge-vs-cost gate rewired to the object it actually reads, formula fixed to quote-vs-quote, `Signal.magnitude` wired in — **golden-master-inert, no live-verification gap** ✅

**Goal:** with Plan 24 fully shipped and only live Testnet re-verification left pending (same
genuinely-blocked status as Plan 22), surveyed `0_tracker.md`'s Active work table fresh for the
next unblocked, decision-free item per the prior handoff's own suggestion. Compared Plan 13
(multi-timeframe `htf()` contract — a new contract spanning 3 files, real design surface) against
Plan 9.11 Step A (cost-gate resurrection — three `[Certain]` audit findings, explicitly scoped by
the plan's own text as "Step A: golden-master-inert", no decisions needed). Chose 9.11 Step A —
same shape as what made Plan 24 tractable in one session.

**Done:** `engine/core/models/portfolio.py`'s `DefaultPortfolioModel._edge_beats_cost()` — the
PCM edge-vs-cost veto that Plan 21's five-model audit found was dead on arrival:
- **M-1 (wired to the wrong object):** `backtest_runner.py`/`live_bot_manager.py` both injected
  `min_edge_mult` onto `strategy.cost_model`, but the gate reads `self.min_edge_mult` where `self`
  is the **portfolio model** instance. Both injection sites now write
  `strategy.portfolio_model.min_edge_mult` instead.
- **M-2 (dimensionally inconsistent):** the old formula compared a bare per-unit price distance
  (`conviction × risk_per_unit × rrr`) against a whole-position quote-currency cost, making the
  veto boundary a function of the symbol's absolute price level (always-pass on BTC, always-veto
  on sub-cent symbols). Fixed to quote-vs-quote: `edge_total = edge_frac × risk_per_unit ×
  qty_est × rrr`, using the same `qty_est = min(budget/risk_per_unit, max_notional/price)` the
  Cost Model already computes internally for `cost.total`.
- **M-3 (dead field):** `Signal.magnitude` was documented as feeding this gate but read by
  nothing. `edge_frac` now uses `sig.magnitude` when the alpha model provides one (nonzero),
  falling back to `abs(sig.conviction)` otherwise.
- **Also fixed both injection sites' default** from `0.05` to `0.0` per the plan's own Step A
  instruction — since the `0.05` never reached the gate under the M-1 bug, this is a no-op, not a
  behavior change (confirmed by golden master below).

**Verification:** new `engine/tests/test_edge_beats_cost_gate.py` (5 cases) — gate-off always
passes regardless of cost; a scaled-edge boundary case flips on cost; **the veto boundary is
price-level invariant** (identical relative risk/cost setup on a BTC-priced vs. a sub-cent symbol
produces the identical verdict — the concrete regression test for M-2's fix); magnitude overrides
conviction when provided; the alpha-level veto still short-circuits regardless of `min_edge_mult`.
**Golden master run before/after per root CLAUDE.md Rule C** (extracted pre-change file contents
from `git show HEAD:...` since the container has `volumes: []` and the working files were already
edited — `docker cp`'d the pre-change versions in, captured `pre_9_11_stepA`, `docker cp`'d the
fixed versions back in, captured `post_9_11_stepA`): `compare --a pre_9_11_stepA --b
post_9_11_stepA` → `GOLDEN-MASTER OK` (5/5 seeded strategies, tol 1e-6). Container suite:
**358/358 passed** (up from 353/353 at session start).

**Files changed:** `engine/core/models/portfolio.py` (`_edge_beats_cost`),
`engine/services/backtest_runner.py` (injection site), `engine/core/live_bot_manager.py`
(injection site); new `engine/tests/test_edge_beats_cost_gate.py`; docs:
`9_backtest-and-optimizer-correctness.md`, `21_live-algo-industry-standard-audit.md` (M-1/M-2/M-3
marked fixed), `0_tracker.md`, `handoff.md`. Committed (`8454072`).

**NOT done:** Step B (deciding whether to activate the gate at `min_edge_mult=0.05` by default) is
untouched — the plan's own text requires this be a separate, re-baselined product decision, not
bundled with Step A. The gate exists and is correct now, but is still opt-in/inert by default.

**Next session:** either (a) bring Step B to the user as an explicit product decision (activate at
0.05 default-on vs. leave opt-in), or (b) continue surveying `0_tracker.md` — Plan 13
(multi-timeframe `htf()` contract, P2, self-contained) remains a plausible next candidate, not yet
investigated beyond the initial survey this session.

---
## 2026-07-17 — Plan 24 (S-1 through S-5) shipped: BestSupertrend "never trades at defaults" fixed — **PLAN 24 FULLY SHIPPED**, live Testnet re-verification still pending ⏸️

**Goal:** with Plan 22 fully shipped (see the entry below) and a partial live-verification attempt
made, user asked to proceed to the next plan with my recommendations. Surveyed `0_tracker.md`'s
Active work table and recommended Plan 24 (BestSupertrend fixes) over Plan 9 (larger,
open-ended quant-core work) and Plan 5 (Decimal-money migration, needs a design pass) — Plan 24 is
fully scoped, decision-free, and fixes a real trust bug (a seeded strategy silently never trades at
its own default settings). User agreed implicitly by not redirecting; proceeded through all five
findings (S-1 → S-2 → S-3 → S-4 → S-5) in the plan's own stated order.

**Done — S-1 (root cause, `size_by_notional()` in `core/strategy.py`):** at `position_size_pct=1.0`
(strategy default) and `leverage=1` (platform default), the naive `qty = equity*pct/price` sits
exactly on the equity boundary, so adverse slippage + the taker fee alone push
`req_margin + fee` just over `free_balance`, rejecting every entry (`backtest_runner.py`'s
`EntryFill.affordable()` check) with only a debug log line. Fixed: `size_by_notional()` now sizes
DOWN to the true affordable notional (accounting for leverage/slippage/fee headroom, with a tiny
1e-6 safety margin against float-rounding at the exact boundary) instead of letting the runner
reject the entry outright. Also dropped `position_size_pct` default 1.0→0.9 (belt and braces).
**Golden master re-baselined**: checked the actual `golden_master.py` baseline first (per the
plan's own instruction) — it runs at `leverage=3` (not the platform's `leverage=1` default), so
BestSupertrend already had 61 non-zero trades in the baseline; the fix's diff is entirely from the
`position_size_pct` default change (same 61 trades, same win/loss counts, PnL scaled ~10% smaller),
confirming the fix doesn't touch already-affordable entries. Other 4 strategies byte-identical
(`size_by_notional` has no other caller). New `test_size_by_notional_affordability.py` (7 cases)
exercises the actual bug scenario (leverage=1) the golden-master harness never touches.

**Done — S-2 (live HTF one bar too stale):** `prepare()`'s live/constant path read
`self._htf_tsl[-2]`, but `_fetch_htf_candles` (`live_bot_manager.py`) already excludes the
in-progress HTF bar, so the injected `_htf_candles` array's last row IS the last completed bar —
`[-1]` is correct, matching backtest's bucket path (`htf_tsl[k-1]`). Fixed; warmup guard loosened
from requiring 2 trailing elements to 1. New parity test (5 cases) drives the real class through
both paths against the same underlying supertrend series. Golden master confirmed byte-identical
(live-only branch, never exercised by backtest).

**Done — S-3 (unsatisfiable tf/timeframe combos fail loud):** new
`required_base_candles_for_htf()` (`engine/utils/timeframes.py`) estimates the base-candle count
needed for `pd+2` completed HTF buckets. Wired into `backtest_runner.py` (logs an error, log-only,
zero simulation-output change) and `live_bot_manager.py` (HTF-fetch failure and
on-success-but-insufficient-data are both now session-visible errors, not just a debug-level
warning; a new one-time warning fires once the live rolling candle window hits its 500-candle cap
with the HTF value still unresolved). 8 new unit tests for the shared helper. Golden master
confirmed byte-identical (log-only additions).

**Done — S-4 (`order_type` param collision):** renamed to `direction_filter` — the old name
collided with `OrderPlan.order_type` (`DefaultExecution.route()` builds
`OrderPlan(order_type=getattr(s, "order_type", "market"))`), silently carrying the filter string
instead of `"market"`. Decorative today (both adapters hardcode MARKET) but would have detonated
the moment any consumer honored `OrderPlan.order_type`. Renamed the PARAMS key and all 4 usage
sites; confirmed via direct instantiation that `BaseStrategy`'s own `order_type="market"` default
now shows through correctly. 3 new tests. Golden master confirmed byte-identical (same default
value under a new key name).

**Done — S-5 (docs):** the `SignalExitRiskModel` doc-drift half was already fixed in an earlier
session (confirmed while surveying, before this window started). Updated
`workspace/docs/strategies/BestSupertrend.md` for all of S-1/S-2/S-3/S-4's user-visible changes
(param rename, new default, `tsl[-1]` correction, tf/timeframe warmup note). The weekly-resample
(`W-MON`) off-by-one TODO is intentionally left as a documentation comment only, per the plan's own
instruction — S-3's generic warmup-sufficiency check covers it without touching resample math.

**Files changed:** `engine/core/strategy.py` (`size_by_notional`), `engine/strategies/
BestSupertrend/__init__.py` (S-1 default, S-2 index fix, S-4 rename — all sites), new
`engine/services/backtest_runner.py`/`engine/core/live_bot_manager.py` S-3 wiring, new
`engine/utils/timeframes.py` (`required_base_candles_for_htf`); new test files:
`test_size_by_notional_affordability.py`, `test_bestsupertrend_htf_parity.py`,
`test_required_base_candles_for_htf.py`, `test_bestsupertrend_direction_filter_rename.py`; docs:
`24_bestsupertrend-fixes.md`, `0_tracker.md`, `CURRENT_STATE.md`,
`workspace/docs/strategies/BestSupertrend.md`, `handoff.md`. All committed (4 commits, one per
step S-1–S-4; S-5 folded into this doc-update pass).

**Verification:** container suite **353/353 passed** (up from 337/337 at the start of Plan 24's
work this session). Golden master run before every code change and re-compared after each step —
only S-1 shows an expected, reviewed diff (BestSupertrend only); S-2/S-3/S-4 all byte-identical.

**NOT done — the one item left across Plan 24:** live Testnet re-verification (the plan's own
"Sequencing / verification" section: one 1-symbol testnet session at leverage 2–3, default params,
confirming ≥1 real entry and HTF-value parity against a parallel backtest window). Same standing
"needs a human-observed session" caveat as every other live-verification item across this
codebase's plans (Plan 21, Plan 22) — genuinely blocked, not attempted this session.

**Next session:** live-verify Plan 24 per the paragraph above, OR continue surveying
`0_tracker.md` for the next unblocked item — Plan 9 (backtest/optimizer correctness, P1, larger
and more open-ended) and Plan 13 (multi-timeframe `self.htf()` contract, P2, self-contained) are
both plausible next candidates; neither was investigated this session beyond the initial survey
that picked Plan 24.

