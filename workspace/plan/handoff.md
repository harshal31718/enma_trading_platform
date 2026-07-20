# Session Handoff Log

Resume prompts for cross-session continuity (root `CLAUDE.md` Rule G / `AGENTS.md` → Session Handoff).

**Format rules:**
- Newest entry on top: `## <date> — <title> — <status>` with **Goal / Done / Files changed / Open questions**.
- Keep at most the **3 most recent entries**. When adding a new one, delete the oldest — git history is the archive. This file must stay a short resume prompt, not a project log.

---
## 2026-07-20 — Plan 6: Step 6.1 (4/5 extractions), 6.2 (Exchange interface half), 6.4 (LiveAdapter half), 6.5 (pooled-client half) shipped; F9 (PUT-dispatch bug) fixed — golden-master-verified throughout

**Goal:** user said "update and then start 6" (Plan 6 was stale-`Blocked` on already-shipped Plan
5/21.3/21.4), then kept saying "proceed"/"yes"/"keep going" across the session. Golden-master
baseline `before_plan6.json` captured once at the start, per Rule C, then re-verified
byte-identical after every single change below (9 successive after-snapshots, 5/5 strategies,
`MultiDivergence` exact match every time: trades=55/netProfit=-1784.02/winRate=0.36/cagr=-71.32/
sqn=-2.08).

**Step 6.1 — extracted 4 of `LiveBotManager`'s 5 planned collaborators** (3830→2783 lines):
`MarketDataFeed` (candle fetching, call sites rewritten directly), `NodeNotifier` (Node stats/
event transport — 11 test files had to be fixed for monkeypatching the old names, first pass was
49 failed/5 errored, lesson: **check tests for direct monkeypatching before declaring an
extraction done**), `SessionRegistry` (lifecycle state — kept old attribute names as delegating
`@property`s rather than rewriting ~150 call sites, "typed state" half deferred to pair with
6.3), `Reconciler` (the 943-line reconcile/cancel/amend/governor-breach cluster — same
delegating-facade trick, zero test breakage this time). Only **OrderRouter** remains, and it's
scoped as materially harder (execute_entry/reduce/exit/flip, ~1,260 lines tangling order
placement with risk/governor logic) — needs its own design pass, not a mechanical move.

**Step 6.4 — partial (`LiveAdapter`'s manager-leak half only).** Re-read the acceptance text and
found a genuinely separable achievable slice: `LiveAdapter.__init__` now resolves `self._registry`/
`self._notifier`/`self._reconciler` from `manager` ONCE; all 33 internal `self.manager.<attr>`
chains rewritten to use those directly. Constructor signature deliberately unchanged (still takes
`manager`, not injected deps) — this file has zero golden-master coverage and 19 tests construct
it directly, so a signature change is separate, riskier work. Caught a stale class-level
monkeypatch in `test_execute_entry_bracket_safety.py` via the full suite run, fixed. Kernel
`is_live` branching (7 sites in `core/kernel.py`, the ONE piece of Plan 6 touching the
golden-master-protected backtest path) is untouched — needs its own dedicated pass.

**Step 6.5 — partial (pooled-client half only).** `NodeNotifier` was opening a fresh
`httpx.AsyncClient()` per call — found `services/binance_testnet.py` already has the exact lazy-
singleton pattern to mirror (`get_client()`/`close_client()`), copied it, wired `close_client`
into `main.py`'s shutdown lifespan. Verified via the running dev container's actual logs (not
just pytest) since this touches app startup/shutdown — `/health` still 200, a real live testnet
session kept trading normally. Redis-stream ordered/at-least-once delivery (needs new Node-side
consumer code) is the real remaining half, cross-service, own session.

**F9 (fixes-queue) — found and fixed while scoping 6.2, not bundled into it:** `send_signed_
request`'s `_dispatch` had no PUT branch, so `user_data_stream.py`'s listen-key keepalive (fires
every 30 min, calls with `method="PUT"`) silently failed every single time — self-healed via a
full WS reconnect every ~60 min instead of ever actually renewing the key. One-line fix (add the
PUT branch), 2 new tests in `test_binance_backpressure.py`.

**Step 6.2 — Exchange interface shipped, NOT wired to any call site yet (deliberate).** New
`engine/core/exchange.py`: `Exchange` ABC + `BinanceFuturesTestnet`/`BinanceFuturesMainnet`,
every method (`place_order`/`cancel_order`/`query_order`, algo-order place/cancel/query, position/
account/user-trades queries, `set_leverage`/`set_margin_type`, listen-key lifecycle,
`user_data_ws_url`) routes through `send_signed_request` using the INSTANCE's own `mode` — a call
site can no longer accidentally cross-wire testnet/mainnet via a stray literal. Surface sized by
grepping every real call site first (24 sites, 9 endpoints), not guessed. Deliberately excludes
the kline WS (always mainnet-sourced per DECISIONS.md #24, a documented decision not a gap).
19 parametrized contract tests. **Real remaining scope, and the larger/riskier half**: migrating
the ~24 existing `send_signed_request(..., mode="testnet")` call sites in `live_bot_manager.py`/
`reconciler.py`/`user_data_stream.py` to actually use this, and wiring per-session `Exchange`
selection from config — live-trading-critical, zero golden-master coverage, deliberately left for
its own pass rather than rushed same-session.

**Verified across everything:** engine pytest 567→578→582→587→593→595→598→600→619 (each piece's
new tests, zero regressions ever left unresolved). Golden-master byte-identical at every step.
Container health/logs checked directly for the two changes that touch paths no test suite
exercises (`main.py` shutdown, F9's live WS keepalive).

**Files changed:** `engine/core/market_data_feed.py`, `node_notifier.py`, `session_registry.py`,
`reconciler.py`, `exchange.py` (all new); `engine/core/live_bot_manager.py` (3830→2783 + internal
6.4 rewrite); `engine/main.py` (shutdown wiring); `engine/services/binance_testnet.py` (PUT
branch); `engine/tests/test_market_data_feed.py`/`test_node_notifier.py`/
`test_session_registry.py`/`test_reconciler.py`/`test_live_adapter_dependency_wiring.py`/
`test_exchange.py` (all new, 47 cases total) + `test_binance_backpressure.py` (+2 cases); 12
existing test files fixed for the NodeNotifier/6.4 renames (`test_live_fill_booking.py`,
`test_execute_entry_portfolio_risk_and_liq_buffer.py`, `test_entry_unconfirmed_fill.py`,
`test_execute_entry_risk_check_event.py`, `test_reconcile_fixes.py`,
`test_execute_entry_correlation_cap.py`, `test_execute_entry_var_breach.py`,
`test_execute_flip_idempotency.py`, `test_execute_entry_bracket_safety.py` (twice),
`test_execute_entry_slippage_log.py`, `test_reconcile_naked_position_rearm.py`,
`test_live_money_accumulation.py`). Docs: `engine/CLAUDE.md`, `6_engine-decomposition-and-
exchange-abstraction.md`, `0_tracker.md`, `0_fixes-queue.md` (F9), this file.

**Open questions:** none blocking. **Next session — everything remaining is now scoped, not
unknown:** Step 6.1's OrderRouter (hardest — real design pass); Step 6.2's call-site migration
(largest remaining mechanical risk — 24 live-trading sites, no golden-master net); Step 6.4's
kernel `is_live` removal (the one piece touching the backtest-protected path); Step 6.5's
Redis-stream channel (cross-service, needs Node work); Steps 6.3/6.6 not started. **Patterns that
held all session, worth repeating:** re-read each step's actual acceptance text before assuming
it's monolithic — most had a separable easy half (ship now) and a hard half (cross-cutting/
cross-service/design-needed — document, don't rush); check test files for direct monkeypatching
before declaring a rename done; a thin delegating-facade beats a risky full rewrite once
something has too many call sites; for anything touching app startup/shutdown or other
untested paths, check the running container's real logs, not just pytest green; when a scoping
pass surfaces an unrelated real bug (F9), surface it to the user explicitly rather than silently
fixing-or-ignoring it.

---
## 2026-07-20 — Plan 10 SHIPPED IN FULL — PBO (Probability of Backtest Overfitting) implemented, verified, closes the plan out

**Goal:** user said "move and implement" on PBO — the one remaining Plan 10 item, previously
scoped-but-not-started (see `10_monte-carlo-strategy-lab.md`'s "Scoping notes" section). Design
first (resolve the two open architectural questions it flagged), then implement.

**Design resolved both open questions by reading the actual code, not guessing:** (1) subsample
source is PBO's OWN independent block scheme — `run_lab_pbo()` calls `optimizer.run_optimization`/
`run_bayesian_optimization` DIRECTLY over the full date range (no walk-forward fold splitting) to
get N candidates, each backtested once, then partitions the range into `nBlocks` CSCV blocks
itself; (2) per-trial trade data already existed (confirmed via code reading) — every combo's
trades are already persisted to `backtestTrades` under `{job_id}_c{idx:04d}`/`_t{idx:04d}`, the
only real gap was the returned trial dict not carrying that job_id (lost on re-sort by loss) —
fixed at the source in `optimizer.py` (both search functions now include `"jobId"` in every scored
trial dict, small/additive/backward-compatible).

**This avoids the "3,500 extra backtests" cost the scoping notes flagged**: only the initial N
candidates are ever backtested; every `C(nBlocks, nBlocks/2)` train/test combination is scored by
slicing each candidate's already-fetched trades in memory (numpy) — zero extra backtests.

**A real bug caught during design, before trusting the implementation**: CSCV's OOS ranking must
be ascending (rank 1 = worst, matching the paper's own convention) for `P(logit<=0)` to mean what
PBO's definition says — an initial descending-rank draft would have silently INVERTED the whole
statistic. Caught by hand-deriving two exact-value test scenarios (perfectly anti-correlated
IS/OOS -> `pbo==1.0` exactly; strictly-ordered candidates -> `pbo==0.0` exactly) before trusting
the code, not just asserting a plausible-looking range.

**Shipped:** `engine/services/pbo.py` (new — `compute_pbo()` pure CSCV combinatorics,
`run_lab_pbo()` orchestrator), `optimizer.py` (`jobId` field addition), `routers/simulate.py`
(`POST /simulate/pbo`). Server: `buildPBOConfig()` (`labConfig.js`, deliberately no
mode/nFolds/trainRatio — not a walk-forward variant), `pboQueue.js`/`pbo.worker.js`,
`lab.controller.js` (`runPBO`/`getPBO`/`listPBO`), `lab.routes.js`, `LabResult.type` enum gained
`'pbo'`, `config/socket.js`/`socketEmitter.js` gained the `pbo:` room prefix. Client: new
"Overfitting (PBO)" third tab on `/lab` — `PBOWizard.jsx`, `PBOVerdictCard.jsx` (severity card,
<20%/20-50%/≥50% thresholds, a documented judgment call), `PBOCandidatesTable.jsx`,
`PBOHistoryRail.jsx`, `useLab.js` gained `useRunPBO`/`usePBO`/`usePBOList`.

**Verified with real Docker access, this session:** engine pytest 567/567 (551 + 16 new
`test_pbo.py` — pure unit tests plus the two hand-derived exact-value CSCV scenarios plus 6
`run_lab_pbo` wiring tests), server jest 181/181 (169 + 12 new `buildPBOConfig` cases), client
`vite build` clean, `vitest` 11/11. Live-verified end-to-end in a real browser session against the
actual `/lab` PBO tab: a real run (MicroScalper/BTCUSDT/1h/2023, 6 candidates, 4 CSCV blocks)
completed through the full BullMQ→engine→MongoDB pipeline, inspected the persisted `labResults`
doc directly to confirm shape (`pbo: 0.0`, 5/6 combos evaluated), `PBOVerdictCard`/
`PBOCandidatesTable` rendered the real result correctly with zero console errors. One real copy
bug (missing space in a JSX line-wrap, `"4-vs-4train/test split"`) found and fixed during this same
live pass, re-verified after the fix.

**Files changed:** `engine/services/pbo.py` (new), `engine/services/optimizer.py`,
`engine/routers/simulate.py`, `engine/tests/test_pbo.py` (new), `server/src/services/pboQueue.js`
(new), `server/src/workers/pbo.worker.js` (new), `server/src/controllers/lab.controller.js`,
`server/src/routes/lab.routes.js`, `server/src/models/LabResult.js`, `server/src/utils/labConfig.js`,
`server/src/utils/__tests__/labConfig.test.js`, `server/src/config/socket.js`,
`server/src/services/socketEmitter.js`, `server/src/server.js`, `client/src/components/lab/
PBOWizard.jsx`/`PBOVerdictCard.jsx`/`PBOCandidatesTable.jsx`/`PBOHistoryRail.jsx` (all new),
`client/src/pages/StrategyLab.jsx`, `client/src/hooks/useLab.js`. Docs: `CURRENT_STATE.md`,
`10_monte-carlo-strategy-lab.md`, `engine/CLAUDE.md`, `server/CLAUDE.md`, `client/CLAUDE.md`,
`0_tracker.md`, this file.

**Open questions:** none blocking — Plan 10 is fully shipped. The TimescaleDB candle gap found
during the prior session's golden-master investigation (BTCUSDT/1h only partially cached for some
historical windows) is still real and worth a full backfill before the next golden-master baseline
capture, but is an infra/data task separate from Plan 10. Untouched backlog unchanged: 21.5c
(batched reconcile, P2/small), Plan 6/7 (engine/server decomposition, P2), Plan 23 (MarginSurge
strategy), Plan 8 (governance cleanup, P3), Plans 5/22/24 (shipped, waiting on human-observed live
Testnet re-verification).

---
## 2026-07-19 — Plan 10 Phase 4a/4b real-Docker verification — closes out every gap the sandbox session below flagged

**Goal:** a concurrent session (same repo, different account — this session's own token limit had
been hit) built Phase 4a (MC-scored trial selection) and Phase 4b (risk_pct/leverage search +
copy-to-backtest + MC summary strip) from a sandbox with no Docker access, disclosing several
verification gaps (see the entry below this one for full detail). This session had real
`docker exec` access and closed every one of those gaps.

**Verified for real:** engine container `pytest /app/tests/` — **551/551** (the 4 failures the
sandbox saw were confirmed environment-only, don't reproduce inside the real docker-compose
network). Server container `npm test` — **169/169**, including all new `mcScoring`/`mcTopK`/
`riskLeverageGrid` `labConfig.test.js` cases. Client `vite build` clean, `vitest run` 11/11.

**Golden master investigated, not just run:** flagged real drift on 3 seeded strategies vs the
`after_dsr` baseline. Root-caused rather than assumed-broken: two independent golden-master
re-runs against the CURRENT code are byte-identical to each other (determinism intact), and
TimescaleDB's `candles` table for BTCUSDT/1h has a real gap — only 1,440 of ~8,760 candles cached
for the golden harness's fixed 2024-01-01→2025-01-01 window — a data-availability change between
when `after_dsr.json` was captured and now, not a Phase 4 code regression (neither Phase 4a nor 4b
touches `backtest_runner.py`/strategies/indicators, and the drifted strategies' default runs never
exercise either phase's opt-in code path). Not chased further — the gap's root cause (partial
candle backfill vs. a container/volume reset) is flagged for whoever needs full historical data.

**Live-verified in a real logged-in browser session** against the actual `/lab` Optimizer wizard:
mcScoring toggle + top-K input render and correctly extend the cost estimate; a real walk-forward
job (MicroScalper/BTCUSDT/1h/2023, mcScoring on) completed through the full BullMQ→engine→Mongo
pipeline; `RobustPickPanel.jsx` correctly rendered the honest "insufficient OOS trades, no
fabricated percentile" guard path (this run's candidates all had 0-1 OOS trades) with zero console
errors — the "robust pick differs from raw pick" happy path is covered by the sandbox session's own
deliberate `test_walk_forward.py` fixture instead, which controls trade counts directly rather than
depending on what a real market window happens to produce.

**Files changed:** `engine/services/monte_carlo.py`/`walk_forward.py` (independently-written, later
found to already match the concurrent session's own implementation of the same design — reconciled,
no conflict). Docs: `workspace/docs/state/CURRENT_STATE.md` (new changelog entry + Strategy Lab
section), `10_monte-carlo-strategy-lab.md` (new "Real Docker verification" section), `engine/
CLAUDE.md` (services-table entries for `monte_carlo.py`/`walk_forward.py`/`optimizer.py`/
`test_risk_leverage_search.py`), this file.

**Open questions:** PBO remains the only unshipped Plan 10 item — still needs its own design pass
(does real per-trial OOS trade data exist anywhere to resample over, or does it need new
persistence — see the scoping notes in `10_monte-carlo-strategy-lab.md`). The TimescaleDB candle
gap found during golden-master investigation is real and worth a full backfill before the next
golden-master baseline capture, but is an infra/data task, not a code task — separate from Plan 10.

