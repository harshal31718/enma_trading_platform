# Session Handoff Log

Resume prompts for cross-session continuity (root `CLAUDE.md` Rule G / `AGENTS.md` → Session Handoff).

**Format rules:**
- Newest entry on top: `## <date> — <title> — <status>` with **Goal / Done / Files changed / Open questions**.
- Keep at most the **3 most recent entries**. When adding a new one, delete the oldest — git history is the archive. This file must stay a short resume prompt, not a project log.

---
## 2026-07-17 — Plan 9.11 Step B decided (stays opt-in) + Plan 9.9 fail-loud metric registry shipped (QNT-13, one of four sub-items)

**Goal:** user said "proceed with next logical step." Step B (activate the now-fixed cost gate by
default vs. leave opt-in) was explicitly called out in the prior turn as needing the user's own
sign-off — asked via AskUserQuestion rather than deciding unilaterally. User chose "leave opt-in."
With that resolved (no code, no re-baseline), picked the next decision-free, well-scoped item:
QNT-13's fail-loud metric registry finding, one of 9.9's four sub-items, matching this session's
established pattern (small `[Certain]` audit finding, golden-master-inert fix, not a new feature).

**Done — 9.11 Step B:** no code change. `min_edge_mult` stays `0.0` everywhere (already shipped
this way by Step A) — the gate exists and is correct but is inert unless a strategy or
`risk_params.governor.min_edge_mult` explicitly opts in.

**Done — 9.9 fail-loud metric registry (QNT-13):** `StatisticRegistry.compute_all()`
(`engine/services/metrics.py`) previously swallowed EVERY exception from ANY registered
`Statistic.compute()` into a silent `"0.00"` fallback (`except Exception: ... # never poison the
result doc`) — a genuinely broken metric was indistinguishable from a legitimately-zero one. Now
logs `logger.error(f"[metrics] stat '{stat.name}' failed to compute — {e}", exc_info=True)` before
falling back — the fallback VALUE is unchanged (a broken stat still shouldn't fail the whole
backtest), only the failure is now diagnosable. Same "log-only, zero happy-path output change"
pattern as Plan 24 S-3 / Plan 21.7 A-11/A-14.

**Verification:** new tests in `engine/tests/test_metrics_fixes.py` (+3, using a `_BrokenStat`
subclass that raises): fallback value unchanged and a healthy sibling stat unaffected, the failure
is logged with the stat name + exception message, a fully-healthy registry produces zero log
noise. **Golden master run before/after per root CLAUDE.md Rule C**: `compare --a pre_qnt13 --b
post_qnt13` → `GOLDEN-MASTER OK` (5/5 seeded strategies, tol 1e-6) — confirms byte-identical (none
of the 5 seeded strategies' stats currently throw, so this is purely an observability addition on
a path the default baseline never exercises). Container suite: **377/377 passed** (up from
374/374 at session start).

**Files changed:** `engine/services/metrics.py` (`StatisticRegistry.compute_all`, new module
logger); `engine/tests/test_metrics_fixes.py` (+3 cases); docs:
`9_backtest-and-optimizer-correctness.md`, `0_tracker.md`,
`workspace/docs/state/CURRENT_STATE.md`, `handoff.md`. Committed (`119e171`).

**NOT done — audited but deliberately out of scope:** the other three 9.9 sub-items —
`"inf"`-string persistence (`ProfitFactorStat`/`ExpectancyRatioStat`/`PayoffRatioStat` return the
literal string `"inf"`; audited client-side and found ZERO current `parseFloat`/`Number()`
consumption of these fields anywhere in `client/src` — real per the audit but currently dormant,
not an active bug to fix speculatively), QNT-14 (leg-vs-round-trip trade-statistics separation —
a materially larger structural change: scale-out legs are counted as independent trades in
`totalTrades`/`winRate`/SQN's √N term/Monte Carlo's resample pool today), and the block-bootstrap
Monte Carlo rework (already absorbed by Plan 10 Phase 1, not this plan's scope). Plan 9's other
steps — 9.7 (funding ledger), 9.8 (intrabar sim), 9.10 (fill-model ladder) — are all larger,
new-mechanism work, not scoped this session.

**Next session:** either (a) scope one
of 9.7/9.8/9.10 as a real design task (each needs its own golden-master re-baseline once a default
changes, per this plan's standing protocol — larger than this session's three items), or (b)
revisit QNT-14/inf-strings if a concrete downstream consumer appears. Plan 22/24's live Testnet
re-verification remain the standing genuinely-blocked items across the whole plan set.

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
