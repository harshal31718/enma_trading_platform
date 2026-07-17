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
| 5  | Live-trading state integrity | 5.5 (Decimal money, golden-master sign-off), 5.6 (restart recovery / projection) | In progress | P0 | 21.1–21.2 inform 5.6 | 2026-07-16 |
| 22 | Industry-standard risk management (Session Risk Governor) | 22.7 (22.1–22.6 shipped, container-verified 2026-07-17 [323/323 pytest]: governor core, capital integrity gate, portfolio open-risk budget, liq-buffer guard, `risk_breach` webhook, MaxDrawdown/LowProfitPairs protections, risk_check events, shared `services/portfolio_risk.py` + live VaR/CVaR enforcement, correlation-aware concentration cap, inverse-vol allocation layer (golden-master-verified) — pending live re-verification only) | In progress (22.1–22.6 shipped + container-verified 2026-07-17) | P2 (rest) | 21 (21.1–21.4, shipped) | 2026-07-17 |
| 9  | Backtest & optimizer correctness (quant core) | 9.7 (funding ledger), 9.8 (intrabar sim), 9.9 (stats portion), 9.10 (fill-model ladder), **9.11 (cost-gate resurrection, M-1/M-2/M-3 — Step A inert, Step B re-baselined)** | Ready | P1 | — | 2026-07-16 |
| 10 | Monte Carlo Optimiser & Strategy Lab | Phases 1b–4 (job plumbing, `labResults`, UI, optimizer w/ walk-forward + Optuna) | Ready | P1 | 9 (9.1/9.3, shipped) | 2026-07-16 |
| 13 | Informative / multi-timeframe contract (`self.htf()`) | All | Ready | P2 | — | 2026-07-16 |
| 17 | Recursive-formula / warmup-insufficiency analysis | All | Ready | P2 | 13 (sequence after) | 2026-07-16 |
| 6  | Engine decomposition & exchange abstraction | All | Blocked | P2 | 5 fully shipped; 21.3/21.4 should land first | 2026-07-16 |
| 7  | Server & client structure | All | Blocked | P2 | 2 (done), 5 | 2026-07-16 |
| 8  | Governance, correctness & cleanup | 8.2–8.6 (8.3/8.4 golden-master; 8.6 product decision; SYS-3 doc item carried from F6) | In progress | P3 | 3 (done), 5, 6 | 2026-07-16 |
| 23 | New strategy: high-risk/high-leverage breakout scalper ("MarginSurge") | All — backtest gates can start now; live gated on 21.1–21.4 | Draft | P2 | 21 (live phase), 22.1–22.2 (liq-buffer + governor, soft) | 2026-07-16 |
| 24 | BestSupertrend fixes (never trades at defaults) | S-1 sizing/affordability, S-2 live HTF off-by-one, S-3 fail-loud unsatisfiable configs, S-4 `order_type` collision, S-5 docs | Ready | P1 | — (live verify after 21.1–21.2); S-1/S-2 need a cheap BestSupertrend re-baseline | 2026-07-16 |

**Plus the fixes queue:** F7 (algo-fill detection — 21.1+21.2 shipped, container-verified
2026-07-17, pending live re-verification) and F8 (Redis `requirepass`, wants a full-stack-restart
window) —
see `0_fixes-queue.md`.

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
  golden-master re-baseline with sign-off, never a same-day bundle. 5.6 (restart recovery)
  depends on the "LiveSession as pure projection" work 5.1 deliberately did not ship; factor
  Plan 21's A-8 (ACCOUNT_UPDATE-driven reconcile) into 5.6's design.
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
  strategies). 22.7 (Zone 2 UI/schema batch) is next in the plan's own sequencing, not yet started.
- **9** — Remaining steps 9.7–9.10 change backtest outputs **by design** → per-step golden-master
  re-baseline with sign-off (Rule C). Who signs off is still an open question.
- **10** — MC core math is honest (Phase 1a shipped) but still behind the old synchronous
  endpoint; everything else (job queue, `labResults`, Strategy Lab UI, optimizer exposure)
  unstarted. Phase 3 absorbs plans 18/19 — build from their design notes, not their specs.
- **13/17** — Independent feature work; 17 sequences after 13 so it also sweeps multi-TF
  indicators. Gate any `htf()` adopter through the shipped 9.5 lookahead sentinel.
- **6/7** — Blocked on Plan 5 fully shipping. Plan 6 should treat Plan 22's `governor.py` /
  `portfolio_risk.py` as already-extracted modules and land after 21.3/21.4 so correctness
  fixes move with the code.
- **8** — 8.1 shipped (F6). Remaining: 8.2–8.6 + the SYS-3 named-volume documentation item
  carried from F6. 8.3/8.4 are golden-master-touching; 8.6 needs a product decision
  (multi-session same-account modelling) before code.
- **Standing open questions** (carried from earlier sessions): golden-master re-baseline
  sign-off ownership (9.7/9.8, 5.5); keep-or-delete `IcebergAlgorithm`; local dev sharing
  production's MongoDB Atlas cluster (structural fix still pending); event-log store choice
  (Mongo shipped, Timescale revisit only on volume).
