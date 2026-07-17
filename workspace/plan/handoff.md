# Session Handoff Log

Resume prompts for cross-session continuity (root `CLAUDE.md` Rule G / `AGENTS.md` → Session Handoff).

**Format rules:**
- Newest entry on top: `## <date> — <title> — <status>` with **Goal / Done / Files changed / Open questions**.
- Keep at most the **3 most recent entries**. When adding a new one, delete the oldest — git history is the archive. This file must stay a short resume prompt, not a project log.

---
## 2026-07-17 — Plan 17 shipped: recursive-formula / warmup-insufficiency analysis (`engine/scripts/recursive.py`) — **no live-vs-backtest drift risk found at w=500 for any seeded strategy**

**Goal:** user said "ok proceed with it" after Plan 13 shipped — Plan 13's own tracker note named
Plan 17 as the natural next step ("sequences after 13 so it also sweeps multi-TF indicators"),
fully scoped and self-contained per the plan doc, so proceeded without re-surveying from scratch.

**Done:** `engine/scripts/recursive.py` — for each seeded strategy, picks a fixed anchor candle,
runs `prepare()` once over the full available history (baseline) and once per warmup size in
`[200, 400, 500, 1000, 2000]`, diffs every `prepare()`-computed indicator column's value at the
anchor (`pct_change = (partial - full) / full * 100`), and flags any column still drifting beyond
`0.01%` at `w=500` — live's rolling re-prepare window cap (workstream #1, P7) — as an operational
live-vs-backtest drift risk. Columns are discovered **generically**: any float `ndarray` on the
strategy instance whose length matches the window, since there's no shared naming convention
across the 5 seeded strategies (`_trend_ema_seq`, `_rsi`, `_ph`/`_pl`, `_sma_fast`/`_sma_slow`).
Int/bool arrays excluded via dtype check (loop-index bookkeeping, boolean cross signals aren't
"recursive value" candidates). `_load_candles()` reuses `ensure_candles_available()`, never
bypasses it.

**Real finding (run against all 5 seeded strategies, BTCUSDT/1h, 1440 cached candles):** **no
column drifts beyond 0.01% at w=500 for any strategy.** AdaptiveTrend's `_trend_ema_seq`
(`EMA(200)` trend filter — the exact case this plan's own audit flagged as high-relevance) shows
real recursive drift: `-2.56%` at `w=200`, but has already converged to `-0.0007%` by `w=500`.
**Live's 500-candle rolling warmup is sufficient for every seeded strategy today — no
`live_bot_manager.py` warmup-length change needed.** Recorded in `CURRENT_STATE.md`.

**Verification:** new `engine/tests/test_recursive.py` (10 cases) — the plan's own self-test gate,
using the real TA-Lib backend over synthetic sinusoidal+trend data (discovered while building this
that a straight-line series converges too fast to exercise seed-bias at all): `EMA(50)` drifts
`>1%` at `w=60`, converges to `<0.01%` by `w=250` (`~5x` period), `~0%` by `w=500`; `SMA(50)` is
exactly stable (`<1e-6%`) at any `w>=50` — proving the tool itself correctly distinguishes
recursive from non-recursive formulas. Plus unit coverage for the near-zero-baseline guard,
both-NaN/one-sided-NaN cases, and column discovery's shape/dtype filtering. Container suite:
**374/374 passed** (up from 364/364 at session start). No golden-master check needed — a
standalone diagnostic script that never touches the sim pipeline.

**Files changed:** new `engine/scripts/recursive.py`, new `engine/tests/test_recursive.py`; docs:
`17_recursive-analysis.md`, `0_tracker.md`, `workspace/docs/state/CURRENT_STATE.md`, `handoff.md`.
Committed (`0378bd5`).

**NOT done — deliberately out of scope:** the report only covers the currently-cached candle range
(1440 candles — enough for `w<=1000`; `w=2000` skipped for lack of history, script warns about
this explicitly rather than silently truncating). Not required since `w=500`, the operationally
important threshold, was already fully exercised. This tool is diagnostic-only — it doesn't gate
anything in CI (unlike the golden master / S5 lookahead sentinel); re-run it manually whenever a
new strategy or a live warmup-length change is considered.

**Next session:** all three of this session's plans (9.11-A, 13, 17) are now shipped. Survey
`0_tracker.md` fresh — Plan 9.11 Step B (cost-gate activation decision, needs explicit user
sign-off) and Plan 9's other steps (9.7–9.10, funding ledger / intrabar sim / stats / fill-model
ladder) remain open, all requiring a golden-master re-baseline rather than being decision-free like
this session's three items. Plan 22/24's live Testnet re-verification also remain the standing
genuinely-blocked items across the whole plan set.

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
`0_tracker.md`, `handoff.md`. Committed (`3ba5d32`).

**NOT done — deliberately out of scope:** no seeded strategy adopts `htf()` yet; this ships the
primitive only, not a consumer. Per the plan's own verification gate, **any real strategy that
adopts `htf()` must be run through S5 (Plan 9's lookahead sentinel,
`engine/scripts/lookahead_sentinel.py`)** before shipping — this session's unit tests prove the
alignment primitive itself is causal, not that a specific future strategy uses it correctly.

**Next session:** either (a) build a real `htf()` consumer (e.g. Plan 17's recursive/
warmup-insufficiency analysis explicitly sequences after 13 "so it also sweeps multi-TF
indicators"), or (b) survey `0_tracker.md` fresh — Plan 9.11 Step B (cost-gate activation decision)
and Plan 9's other steps (9.7–9.10) remain open, all requiring a golden-master re-baseline +
sign-off rather than being decision-free.

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

