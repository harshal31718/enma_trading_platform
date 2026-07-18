# 0 — Plan Tracker

Live status board. One row per plan. Catalog + conventions live in [`0_plans.md`](0_plans.md);
the phase column maps to [`0_roadmap.md`](0_roadmap.md). The small, ship-any-time punch-list
that cuts across these plans lives in [`0_fixes-queue.md`](0_fixes-queue.md).

Statuses: `Draft` · `Ready` · `Blocked` · `Verify` · `Shipped` · `Merged→N` · `Split→N,M` ·
`Dropped` (defined in `0_plans.md`). **Restructured 2026-07-16:** active work first; completed
and merged plans in their own table below (detail lives in each plan file's "Shipped summary" —
this board no longer duplicates it).

## Active work (top-down = suggested order within each track)

| ID | Title | Remaining scope | Status | Priority | Depends on | Updated |
|----|-------|-----------------|--------|----------|------------|---------|
| 21 | Live algo industry-standard audit — **fixes** | 21.5c (batched reconcile) (21.1–21.4 + 21.5a/b + all of 21.7 [A-11/A-12/A-13/A-14] shipped, container-verified 2026-07-17 [301/301 pytest], pending live re-verification only; 21.6 → Merged→22.1) | In progress (21.1–21.4, 21.5a/b, 21.7 all shipped + container-verified 2026-07-17) | P2 (21.5c) | — | 2026-07-17 |
| 5  | Live-trading state integrity | ALL SHIPPED (5.1–5.6, container-verified 2026-07-18 [engine 441/441, server 112/112]) — 5.5 scoped to running-total accumulation sites (documented scope decision, not full float→Decimal); 5.6's resume capability shipped but not wired into the default restart path (explicit open decision) | **Done** | — | 21.1–21.2 informed 5.6 | 2026-07-18 |
| 22 | Industry-standard risk management (Session Risk Governor) | ALL SHIPPED (22.1–22.7, container/Jest-verified 2026-07-17 [330/330 pytest, 88/88 jest], 22.6 golden-master-verified, 22.7 live-verified in-browser) — pending live Testnet re-verification only | **Done** (pending live re-verification) | — | 21 (21.1–21.4, shipped) | 2026-07-17 |
| 9  | Backtest & optimizer correctness (quant core) | ALL STEPS SHIPPED (9.1–9.11, container-verified 2026-07-18 [427/427 pytest]) — liquidation fee (QNT-4) shipped opt-in 2026-07-18 per user decision; 2 deliberately deferred sub-items remain: warmup fail-loud (needs Plan 8 coordination), `"inf"`-string persistence (dormant, no active consumer) | **Done** | — | — | 2026-07-18 |
| 10 | Monte Carlo Optimiser & Strategy Lab | Phases 1b–4 (job plumbing, `labResults`, UI, optimizer w/ walk-forward + Optuna) | Ready | P1 | 9 (9.1/9.3, shipped) | 2026-07-16 |
| 13 | Informative / multi-timeframe contract (`self.htf()`) | Shipped — primitive only, no seeded strategy adopts it yet | **Done** | — | — | 2026-07-17 |
| 17 | Recursive-formula / warmup-insufficiency analysis | Shipped — no live-vs-backtest drift risk found at w=500 for any seeded strategy | **Done** | — | — | 2026-07-17 |
| 6  | Engine decomposition & exchange abstraction | All | Blocked | P2 | 5 fully shipped; 21.3/21.4 should land first | 2026-07-16 |
| 7  | Server & client structure | All | Blocked | P2 | 2 (done), 5 | 2026-07-16 |
| 8  | Governance, correctness & cleanup | 8.2–8.5, 8.7 (8.3/8.4 golden-master; SYS-3 doc item carried from F6) — 8.6 verified-already-shipped 2026-07-18, no code needed | In progress | P3 | 3 (done), 5, 6 | 2026-07-18 |
| 23 | New strategy: high-risk/high-leverage breakout scalper ("MarginSurge") | All — backtest gates can start now; live gated on 21.1–21.4 | Draft | P2 | 21 (live phase), 22.1–22.2 (liq-buffer + governor, soft) | 2026-07-16 |
| 24 | BestSupertrend fixes (never trades at defaults) | ALL SHIPPED (S-1 through S-5, container-verified 2026-07-17 [353/353 pytest], golden-master re-baselined for S-1 — only BestSupertrend diverges, other 4 strategies byte-identical) — pending live Testnet re-verification only | **Done** (pending live re-verification) | — | — | 2026-07-17 |

**Plus the fixes queue:** F7 (algo-fill detection — 21.1+21.2 shipped, container-verified
2026-07-17; 2026-07-18 added error-visibility logging + an entry-fill-confirmation hardening fix
for the FXSUSDT anomaly, code-sound but NOT container-tested or live-verified this session — no
Docker access — pending both) — **⚠️ FIRST PRIORITY next session: container pytest run + a small
live/chaos Testnet reproduction (see `0_fixes-queue.md`'s F7 entry). Two sessions have now shipped
F7 code without either — do this before any other tracker item.** — and F8 (Redis `requirepass`,
wants a full-stack-restart window) — see `0_fixes-queue.md`.

## Completed / merged (reference only — detail in each plan file)

| ID | Title | Outcome | Date |
|----|-------|---------|------|
| 1  | Public access + admin-gated algo start | Shipped (`ddce1c1`/`efa8cd5`) | 2026-07-14 |
| 2  | Safety net & guardrails | Shipped — test harnesses, fail-closed encryption, correlation IDs, CI | 2026-07-15 |
| 3  | Service-to-service trust | Shipped — `/internal/*` auth, RCE path removed, tiered rate limits | 2026-07-15 |
| 4  | Credential & config topology | Mostly shipped — residual Redis `requirepass` tracked as **F8** | 2026-07-15 |
| 11 | Current-state reconciliation (V0) | Verified live (verify-only gate — complete) | 2026-07-15 |
| 12 | Max position per asset | Shipped — 1a pre-existing, 1b `max_open_positions` | 2026-07-15 |
| 14 | Webhook notifications | Shipped (fixes-queue F3) | 2026-07-16 |
| 15 | Data conversion CLI | Shipped (fixes-queue F4) | 2026-07-16 |
| 16 | Lookahead-bias analysis | Merged→9 (superseded by shipped 9.5 sentinel) | 2026-07-15 |
| 18 | Walk-forward analysis | Merged→10 (Phase 3 design input) | 2026-07-15 |
| 19 | Bayesian hyperopt (Optuna) | Merged→10 (Phase 3 design input) | 2026-07-15 |
| 20 | Binance precision/notional parity | Shipped — DCA scale-out stepSize floor + entry idempotency | 2026-07-15 |

Partially-shipped steps inside active plans (5.1–5.4, 8.1, 9.1–9.5 + QNT-15, 10 Phase 1a) are
recorded in those plans' own Shipped summaries — the Remaining-scope column above is the
authoritative "what's left".

---

## Execution order

Three tracks, workable in parallel:

1. **Live-correctness track (P0):** 21.1/21.2 (fill-path fixes, unblocks the F7 reproduction)
   → 21.3/21.4 (bracket cancel-on-close, naked-position re-arm — shipped 2026-07-17) → 21.5a/b
   (weight tracking, 429/418 handling — shipped 2026-07-17) → 22.1–22.3 (Session Risk Governor
   hard checks) → 5.5/5.6 → 22.4–22.7 → then 6 → 7 unblock. 21.5c (batched reconcile) and 21.7
   are P2/P3, workable any time after but not gating the P0 chain.
2. **Quant track:** 9.7–9.10 (each needs its own golden-master re-baseline + sign-off) and
   10 Phases 1b–4 — independent of the live track.
3. **Feature track:** 13 → 17 — independent of both.

Plan 8 trails everything (docs/cleanup only makes sense once 5/6 land).

**Session protocol:** pick the top unblocked item on your track, set it to a working status,
follow its Steps, meet its Acceptance criteria, update this row, write a `handoff.md` entry
(CLAUDE.md Rule G). Never mark `Shipped` without acceptance criteria met and (for
pipeline-touching steps) a golden-master check per Rule C.

## Notes (active plans only)

- **21** — Audit complete 2026-07-16 (`21_live-algo-industry-standard-audit.md`, findings
  A-1…A-14). **21.1 shipped 2026-07-17**: broken userTrades credentials (A-1), `_on_fill`
  AttributeError killing the event-driven fill path (A-2), LISTEN_KEY_EXPIRED killing the UDS
  task (A-3) — all three fixed with regression tests (`test_query_real_exit_from_user_trades.py`,
  `test_on_fill_client_id_extraction.py`, `test_uds_listen_key_expired_reconnect.py`).
  **21.2 shipped 2026-07-17** (A-8, ACCOUNT_UPDATE-driven reconcile): a per-symbol
  `_on_account_update` callback registered alongside `_on_fill` (both live in `_run_symbol_loop`,
  `engine/core/live_bot_manager.py`) — on any OPEN<->FLAT disagreement between Binance's `P[]`
  position delta and the local `strategy.position` view, triggers `_reconcile_exchange_state`
  immediately under the existing per-symbol lock, debounced by skipping if that lock is already
  held (a reconcile already in flight will observe the same fresh state). This is the
  event-type-agnostic backstop A-8 called for — it doesn't depend on Binance's algo-order
  `ORDER_TRADE_UPDATE`/client-id semantics at all, unlike `_on_fill`. Decision logic extracted into
  `_account_update_needs_reconcile()` for direct unit testing (repo convention — see
  `test_account_update_reconcile_decision.py`); found and reused an already-existing but
  never-wired `register_account_callback`/`_handle_account_update` dispatch mechanism in
  `user_data_stream.py` (present since before this session, never invoked from
  `live_bot_manager.py` — the audit's A-8 finding that `_handle_account_update` "only logs" was
  stale by the time 21.2 started; it already dispatched to callbacks, just to none). **Still
  outstanding before 21.1/21.2 are fully closed:** run the engine test suite inside the container
  (no Docker access from the session that made these edits) and re-run a small live session to
  confirm F7's ~60s staleness symptom is actually gone. **21.3 shipped 2026-07-17** (A-4/A-5,
  bracket-cancel-on-close): new `LiveBotManager._cancel_symbol_algo_orders(session, symbol,
  algo_ids)` — cancels tracked SL/TP algo ids directly if known, else discovers + cancels via
  `GET /fapi/v1/openAlgoOrders` — wired into all four close paths: `execute_exit` success,
  `_close_position_on_stop`, the F-018 emergency-exit path (defensive; nothing rests there today
  given SL-before-TP placement order, but future-proofed), and reconcile Case 2 (the exchange-
  side-SL/TP-fired case that section 6's existing OUO peer-cancel structurally can't reach, since
  it's guarded by `has_exchange_position` which is False in Case 2 by definition — this was A-5's
  exact finding). Tests: `test_cancel_symbol_algo_orders.py` (7 cases: tracked-id direct cancel,
  partial-tracked, discovery fallback, both-ids-None triggers fallback, no-credentials no-op,
  one-DELETE-failure doesn't block the other, GET-failure caught not raised). **21.4 shipped
  2026-07-17** (A-6/A-7 + M-4/M-5): F-018 emergency-exit path rewritten with a 3-attempt retry
  ladder (1s/2s backoff) around the emergency MARKET close, real fill price booked via
  `_extract_fill_price` → `_query_real_fill_price` (never the fabricated entry price), and on
  total failure records nothing and leaves `strategy.position` untouched for the next reconcile
  pass to restore (A-6). `_reconcile_exchange_state` Case 3 gained a naked-position detector —
  when both sides agree a position is open but no live STOP_MARKET/`*sl` algo order rests on the
  exchange, attempts a direction-aware re-arm; after `_NAKED_POSITION_MAX_REARM_ATTEMPTS` (3)
  consecutive failures across separate reconcile passes, force-closes the position via
  `execute_exit` rather than leave it running naked indefinitely (A-7). New
  `_maybe_amend_exchange_sl()` cancels+replaces the resting exchange SL algo order whenever
  Path 5's trailing/breakeven stop tightens `strategy.stop_loss` — previously a tightened stop
  was local-only and the exchange-side stop stayed at its original, widest trigger for the
  position's entire life (M-4), wired into `_run_symbol_loop` right after
  `kernel.evaluate_and_route(...)`. `execute_entry`'s SL validity check now rejects the entry
  outright (`strategy.buy/sell/stop_loss/take_profit` all cleared, returns False) when the
  computed SL lands on the wrong side of the reference price, instead of silently dropping the
  SL and entering naked with no future re-check — TP-invalid stays lower-stakes (drop TP, still
  enter) (M-5). Tests: `test_reconcile_naked_position_rearm.py` (5 cases),
  `test_maybe_amend_exchange_sl.py` (8 cases), `test_execute_entry_bracket_safety.py` (7 cases:
  long/short invalid-SL rejection, valid-SL/invalid-TP drop-and-enter, emergency-close success
  first try, retry-then-succeed, total-failure records nothing, A-4 cancel-integration). All
  three files syntax-checked via `ast.parse`; container `pytest` run and live re-verification
  still outstanding for 21.1–21.4 as a batch (no Docker access this session). 21.6 merged
  into 22.1. **21.5 (A-9) partially shipped 2026-07-17**: `engine/services/binance_testnet.py`
  tracks `X-MBX-USED-WEIGHT-1M` per base_url and defers non-order-critical signed calls
  (`BinanceBackpressureError`) once at/above a 1800 (75% of 2400/min) soft limit while the reading
  is fresh; on 429/418 it honors `Retry-After` (60s default fallback) and pauses non-order-critical
  calls until it expires. `/fapi/v1/order`/`/fapi/v1/algoOrder` are exempt from both guards.
  Found and fixed **A-15** while wiring this in: `_reconcile_exchange_state`'s Case 2 was
  fabricating a close on ANY `positionRisk` query failure, not just a confirmed-flat exchange — a
  new `position_query_ok` flag gates Case 2 so an unconfirmed query leaves local state untouched
  instead. 21.5's part (c), batching `positionRisk`/`openAlgoOrders` into one call per session per
  candle wave, is deliberately deferred — needs a session-level fan-out/fan-in restructure of
  `_run_symbol_loop` (today each symbol is an independent `asyncio` task), materially larger than
  (a)/(b), left as remaining scope. Tests: `engine/tests/test_binance_backpressure.py` (18 cases)
  — **actually executed with real pytest in-session** (not just `ast.parse`), since
  `binance_testnet.py` has no TA-Lib/numpy dependency chain, unlike the rest of the suite.
  **21.7's A-11 + A-14 shipped 2026-07-17** (both logging-only, no golden master needed):
  `clamp_and_round_qty` (`utils/symbols.py`) logs a warning with the effective risk multiplier
  when its minNotional bump-up actually inflates qty (A-11); `execute_entry` logs slippage
  (`|fill-ref|/ref`) on every entry, escalating to a warning + session notification at/above 1%
  (A-14). Neither changes any returned/booked value — observability only. Tests:
  `test_clamp_qty_risk_inflation_log.py` (5 cases, actually run with real pytest) and
  `test_execute_entry_slippage_log.py` (3 cases, `ast.parse`-only — needs `core.live_bot_manager`'s
  numpy chain the sandbox couldn't install). A-12/A-13 remain: both need a DECISIONS.md-style
  product decision (data-provenance choice; wick-check-dedup-while-brackets-armed choice) rather
  than code, left for the user.
- **5** — 5.5 (Decimal) is the largest, riskiest remaining piece: needs a deliberate
  golden-master re-baseline with sign-off, never a same-day bundle. **5.6 shipped in scoped
  form 2026-07-18**: discovered that Plan 21.2's `_reconcile_exchange_state` Case 1 (already
  shipped) already restores currently-open positions from exchange truth on restart — the real
  gap was realized PnL from trades that closed *before* a restart (not on the exchange position
  endpoint at all) always re-seeding to `0.0`. New `_seed_pnl_from_event_log()` replays the
  session's own event log to recover it, wired behind a new opt-in `resume: bool` on
  `StartSessionRequest` (default `False`, additive-only). **Standing open decision, not
  attempted**: nothing calls `resume=True` yet — `reconciliation.js` still always stops+flattens
  every running session on any server/engine restart, by design (a deliberate fail-safe against
  auto-resuming live trading after an unattended crash). Flipping that default to "resume
  instead of flatten" is a real product/risk decision for the user to make explicitly, separate
  from this step's job of shipping the tested capability.
- **22** — Scope decisions taken 2026-07-16: portfolio layer yes (fork #3), rule-based only
  (fork #2), VaR/CVaR enforced (Zone 1 graduates from display-only). Found while grounding:
  `liq_buffer_pct` is decorative (no pipeline call site) and `max_portfolio_risk` is per-symbol
  despite its name — **both resolved 2026-07-17 by 22.2**: `respects_liq_buffer()` is now wired
  into `execute_entry` (with the computed liq price in the veto log), and the governor's new
  `check_portfolio_risk()` is the true cross-symbol enforcement point (the per-symbol
  `DefaultPortfolioModel` check is left as-is for backtest, not removed — no golden-master
  benefit to touching it). **Capital-control audit (user question, 2026-07-16):** risk-% per trade is
  genuinely parameter-controlled (3 clamp layers: `utils/risk.js` → Zone 2 cascade → engine
  F-014 floor) and per-bot/new-bot launch limits exist (`maxSymbolsPerBot`, `maxConcurrentBots`,
  chaos caps, `maxOpenPositions`) — but session `capital` itself is honor-system: presence-check
  only, no numeric bounds, never compared to the wallet, no cross-session reservation, and Chaos
  commits `capital × strategyCount` unchecked (findings B-11/B-12, fixed 2026-07-17 by 22.1's
  capital integrity gate). **22.1–22.5 all shipped, container-verified 2026-07-17 (313/313
  pytest)** — 22.3 added `MaxDrawdownProtection`/`LowProfitPairsProtection` (opt-in), fixed a real
  gap where `record_trade_close` only fired from `execute_exit` (missing the F-018 emergency path,
  `_close_position_on_stop`, and reconcile Case 2 — the last of which is now the MOST common
  stoploss path post-A-13), verified Chaos already gets full protections coverage (same
  `start_session` path, no separate Chaos plumbing — the plan's "live-only wiring" caution was
  stale, not a traced finding), and added a per-entry `risk_check` event + 1.1x inflation warning.
  22.4 shipped a shared `services/portfolio_risk.py` (one computation for both the Zone 1
  dashboard and the governor's new `check_var()`) and live VaR/CVaR enforcement, account-wide by
  design, 10s/60s cached. 22.5 shipped the correlation-aware concentration cap (transitive-closure
  clustering over pairwise correlation, pre-trade only, off by default) reusing 22.4's price-history
  cache via new `fetch_correlation_matrix()`. 22.6 shipped the inverse-volatility portfolio
  allocation layer (`InverseVolatilityPortfolio`, config-gated `allocation: "equal"|"inverse_vol"`,
  default unchanged) — golden-master re-run confirmed byte-identical for the default case (5/5
  strategies). **22.7 shipped 2026-07-17 — Plan 22 is now fully complete (22.1–22.7).** Zone 2
  UI/schema batch for every governor field, SessionCard governor-state badge, wizard allocation
  dropdown. Found and fixed a real bug spanning back to 22.1: `live_bot_manager.py`'s
  `start_session` governor cascade read `risk_params` at the wrong dict level (Node sends
  `{symbol: {...}, "default": {...}}`, not flat) — every Zone-2-configured governor knob had
  silently never reached the governor since 22.1. Also fixed two smaller gaps: the
  `algo:session:update` socket handler dropped `tradingState` (badge would never update live), and
  `webhook.js`'s `VALID_EVENTS` was missing `risk_breach` (silent 400 on save). Container/Jest
  suites: 330/330 pytest (up from 323), 88/88 jest (up from 79, also confirms `capitalGate.test.js`
  genuinely passes). Live-verified in-browser via Claude in Chrome against the running dev stack.
  **Only remaining item across all of Plan 22: real live Testnet re-verification** — genuinely
  blocked, needs a human-observed session, marked pending (see `handoff.md`).
- **9** — Remaining steps 9.7–9.10 change backtest outputs **by design** → per-step golden-master
  re-baseline with sign-off (Rule C). Who signs off is still an open question. **9.11 Step A
  shipped 2026-07-17**: fixed M-1 (the injected `min_edge_mult` now lands on
  `strategy.portfolio_model`, the object `_edge_beats_cost()` actually reads, not the dead
  `strategy.cost_model`), M-2 (formula is now quote-vs-quote, scaled by the same `qty_est` the
  Cost Model uses — previously price-level-dependent), and M-3 (`Signal.magnitude` now feeds the
  gate when provided, falling back to conviction). Both injection sites default to `0.0` (was
  `0.05`, but the old value never reached the gate, so this is a no-op) — golden-master confirmed
  byte-identical. **9.11 Step B decided 2026-07-17: user chose to leave the gate opt-in/off by
  default** — no code change, zero re-baseline risk; the gate exists and is correct (Step A) but
  stays inert unless a strategy or `risk_params.governor.min_edge_mult` explicitly opts in.
  **9.9 shipped 2026-07-17 (within this plan's own scope)**: fail-loud metric registry
  (`StatisticRegistry.compute_all()` now logs any stat computation failure instead of silently
  returning `"0.00"` indistinguishably from a legitimately-zero metric — fallback value unchanged)
  and QNT-14 leg-vs-round-trip separation (new opt-in `aggregate_legs_to_round_trips()`, wired via
  `round_trip_stats=True` on `run_backtest_simulation`, default `False` — persisted
  `backtestTrades`/`tradeCount` always stay per-leg; only statistics get the round-trip view when
  opted in). Both golden-master confirmed byte-identical at default settings. `"inf"`-string
  persistence stays open (re-audited, still genuinely dormant — zero client/server consumption);
  block-bootstrap MC is Plan 10's scope, not this plan's. **9.10's fill-model ladder shipped
  2026-07-17**: new opt-in `LadderedTransactionCostModel` (`core/models/cost.py`) — volatility-
  scaled slippage + √-impact on top of the base constant slippage; golden-master-safe by
  construction (no seeded strategy assigns it). Liquidation fee (QNT-4) deliberately NOT
  implemented — contradicts a documented `engine/CLAUDE.md` contract, needs a `DECISIONS.md` call
  from the user, not a mechanical fix. Warmup-insufficiency fail-loud (QNT-16) deferred to
  coordinate with Plan 8 per this step's own text. **9.8's intrabar detail resolution shipped
  2026-07-17**: `ExecutionKernel` gained opt-in `intrabar_detail`/`detail_candles_by_symbol`/
  `base_timeframe_ms` — when both SL and TP wicks hit one base candle (the genuinely ambiguous
  case), scans 1m sub-candles in time order to find which level actually triggered first, instead
  of the code-order SL-first default. `check_exits()` refactored to a candidate-then-decide
  structure, behavior-preserving by construction for the default (off) path — golden master
  confirmed byte-identical. `backtest_runner.py` fetches 1m candles only when opted in and the
  base timeframe isn't already 1m (zero fetch cost by default). No 1m-fetch size guardrail added
  — a long backtest opting in would fetch a very large candle set, left as a known limitation.
  **9.7's historical funding ledger shipped 2026-07-17 — Plan 9 is now fully complete within its
  own scope (9.1–9.11 all shipped).** New TimescaleDB `funding_rates` hypertable (added to
  `docker/timescale/init.sql` AND applied live), `services/funding_importer.py` +
  `funding_manager.py` (mirrors the candle-importer/manager idempotent-fetch pattern exactly),
  wired via a new opt-in `historical_funding` param — `BacktestAdapter.charge_funding()` charges
  each REAL Binance funding event's own signed rate + mark price instead of the flat-rate/
  fixed-8h-boundary fallback. Manually verified end-to-end against real mainnet data (22 real
  BTCUSDT funding events fetched, idempotent re-fetch confirmed). Default `None` reproduces the
  exact pre-9.7 code path — golden master byte-identical.
- **10** — MC core math is honest (Phase 1a shipped) but still behind the old synchronous
  endpoint; everything else (job queue, `labResults`, Strategy Lab UI, optimizer exposure)
  unstarted. Phase 3 absorbs plans 18/19 — build from their design notes, not their specs.
- **13/17** — **13 shipped 2026-07-17**: `informative_timeframes` + `self.htf()` on `BaseStrategy`,
  as-of aligned (freqtrade ffill+shift pattern) via `utils/timeframes.to_ms()`, wired into both
  `backtest_runner.py` and `live_bot_manager.py`. No seeded strategy adopts it yet — this shipped
  the primitive only. Golden master byte-identical, container suite 364/364. **Gate any future
  `htf()` adopter through the shipped 9.5 lookahead sentinel** before shipping that strategy — the
  primitive's own unit tests (`test_informative_alignment.py`) prove it's causal, not that a
  specific consumer uses it right. **17 shipped 2026-07-17**: `engine/scripts/recursive.py` sweeps
  every seeded strategy's `prepare()`-computed indicators across warmup sizes, diffing each
  column's anchor value vs. a full-history baseline. Real finding: no column drifts beyond 0.01%
  at `w=500` (live's rolling re-prepare window) for any of the 5 seeded strategies — including
  AdaptiveTrend's `EMA(200)` trend filter (the case this plan's own audit flagged as
  high-relevance), which drifts `-2.56%` at `w=200` but has converged to `-0.0007%` by `w=500`.
  Live's 500-candle warmup is sufficient today; no `live_bot_manager.py` change needed. Container
  suite 374/374 (new `test_recursive.py`, 10 cases, self-tests the tool via real TA-Lib EMA/SMA
  over synthetic data). No golden master needed (standalone diagnostic, never touches the sim
  pipeline). Recorded in `CURRENT_STATE.md`.
- **6/7** — Blocked on Plan 5 fully shipping. Plan 6 should treat Plan 22's `governor.py` /
  `portfolio_risk.py` as already-extracted modules and land after 21.3/21.4 so correctness
  fixes move with the code.
- **8** — 8.1 shipped (F6). Remaining: 8.2–8.6 + the SYS-3 named-volume documentation item
  carried from F6. 8.3/8.4 are golden-master-touching. 8.6 resolved 2026-07-18 — no code
  needed, see Step 8.6 in the plan doc.
- **Standing open questions** (carried from earlier sessions), **resolved 2026-07-18** unless
  noted: golden-master re-baseline sign-off ownership for 5.5 — user will review the diff
  personally (9.7/9.8 already shipped, moot). `IcebergAlgorithm` — keep, evaluate later, no code
  change. Local dev sharing production's MongoDB Atlas cluster — fixed: new `mongodb` service
  added to `docker-compose.yml`, user swaps `MONGO_URI` in their own local `.env` (root CLAUDE.md
  forbids Claude from editing `.env` directly). **Still open**: event-log store choice (Mongo
  shipped, Timescale revisit only on volume).
