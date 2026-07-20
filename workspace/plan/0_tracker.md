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
| 21 | Live algo industry-standard audit — **fixes** | **ALL SHIPPED IN CODE 2026-07-20** — 21.5c (batched reconcile) shipped, container-verified [653/653 pytest, golden-master byte-identical] (21.1–21.4 + 21.5a/b + all of 21.7 [A-11/A-12/A-13/A-14] shipped, container-verified 2026-07-17 [301/301 pytest]; 21.6 → Merged→22.1) — pending live re-verification only, same as every other sub-item | **Done** (pending live re-verification) | — | — | 2026-07-20 |
| 5  | Live-trading state integrity | ALL SHIPPED (5.1–5.6, container-verified 2026-07-18 [engine 441/441, server 112/112]) — 5.5 scoped to running-total accumulation sites (documented scope decision, not full float→Decimal); 5.6's resume capability shipped but not wired into the default restart path (explicit open decision) | **Done** | — | 21.1–21.2 informed 5.6 | 2026-07-18 |
| 22 | Industry-standard risk management (Session Risk Governor) | ALL SHIPPED (22.1–22.7, container/Jest-verified 2026-07-17 [330/330 pytest, 88/88 jest], 22.6 golden-master-verified, 22.7 live-verified in-browser) — pending live Testnet re-verification only | **Done** (pending live re-verification) | — | 21 (21.1–21.4, shipped) | 2026-07-17 |
| 9  | Backtest & optimizer correctness (quant core) | ALL STEPS SHIPPED (9.1–9.11, container-verified 2026-07-18 [427/427 pytest]) — liquidation fee (QNT-4) shipped opt-in 2026-07-18 per user decision; 2 deliberately deferred sub-items remain: warmup fail-loud (needs Plan 8 coordination), `"inf"`-string persistence (dormant, no active consumer) | **Done** | — | — | 2026-07-18 |
| 10 | Monte Carlo Optimiser & Strategy Lab | **SHIPPED IN FULL 2026-07-19/20 — no remaining scope.** Phase 1 (job plumbing) + Phase 2 (MC tab) + Phase 3a (walk-forward job plumbing) + Phase 3c (Optimizer tab UI, fold-level) + Phase 3d (per-trial persistence + trials table UI) + Phase 3b (Optuna/TPE Bayesian search, 1 pre-existing bug fixed — inf-loss JSON crash) + Phase 3e (Deflated Sharpe Ratio, 1 real unrelated bug found/fixed — `_build_param_grid` OOM/hang) + Phase 4a (MC-scored trial selection) + Phase 4b (copy-to-backtest, backtest-page MC summary strip, risk_pct/leverage search) — all real-Docker-verified 2026-07-19 (engine 551/551, server jest 169/169, client build clean + vitest 11/11). **PBO (Probability of Backtest Overfitting, CSCV) — the plan's last item — shipped and real-Docker-verified 2026-07-19/20**: new `engine/services/pbo.py` (full-range optimizer run + in-memory CSCV block combinatorics, zero extra backtests beyond the initial candidates), `POST/GET /api/v1/lab/pbo`, new "Overfitting (PBO)" `/lab` tab. Engine 567/567 (+16), server jest 181/181 (+12), client build clean + vitest 11/11, live-verified via a real `/lab` PBO tab browser session. One real bug caught during design (CSCV rank-direction convention, would have silently inverted the statistic) — caught and fixed before being trusted, via two hand-derived exact-value test scenarios. | Shipped | P1 | 9 (9.1/9.3, shipped) | 2026-07-20 |
| 13 | Informative / multi-timeframe contract (`self.htf()`) | Shipped — primitive only, no seeded strategy adopts it yet | **Done** | — | — | 2026-07-17 |
| 17 | Recursive-formula / warmup-insufficiency analysis | Shipped — no live-vs-backtest drift risk found at w=500 for any seeded strategy | **Done** | — | — | 2026-07-17 |
| 6  | Engine decomposition & exchange abstraction | **6.1 SHIPPED IN FULL 2026-07-20** — all 5 planned `LiveBotManager`/`LiveAdapter` extractions done (MarketDataFeed, NodeNotifier, SessionRegistry, Reconciler, OrderRouter; `live_bot_manager.py` 3830→2631 lines); **6.2 SHIPPED IN FULL 2026-07-20** — the ~23 direct `send_signed_request(mode="testnet")` call sites in `reconciler.py`/`order_router.py`/`user_data_stream.py`/`live_bot_manager.py` now route through a per-session `Exchange` instance (`start_session` resolves `BinanceFuturesTestnet()` once); the 3 sites reached via `portfolio_risk.py`/`utils/symbols.py` wrapper functions (`compute_var_cvar`×2, `clamp_leverage`×1) now pass `mode=session["exchange"].mode` through those wrappers' existing `mode` param instead of a literal, closing the gap without changing the wrappers' signatures; 6.4 (LiveAdapter half shipped + kernel `is_live` PARAMETER-threading killed 2026-07-20 — `ExecutionAdapter.is_live` is now an adapter-owned property, `check_exits`/`evaluate_and_route` no longer take `is_live` as an argument; the internal `if is_live:` checks themselves are unchanged in behavior, and the deeper "kernel calls one polymorphic method, timing model lives in the adapter" redesign was deliberately not attempted — see plan file); 6.5 (pooled-client half shipped; Redis-stream ordered/at-least-once channel — needs Node-side consumer too — still open); **6.6 SHIPPED IN FULL 2026-07-20** — user authorized a real container rebuild; new `core/engine_alias.py` installs a `sys.meta_path` hook so `engine.xxx` resolves to the exact same module objects as `core.xxx` (genuine single identity, no packaging change needed after all — the originally-proposed `pyproject.toml` shape turned out unnecessary); replaces the symlink hack in `main.py` AND 4 other scripts that had independent copies of it, deletes the dual `try/except` import dance across 16 internal files + 4 test files; verified via a REAL `docker compose build` + `up -d --no-deps engine` restart (not just `docker exec`) — clean boot, all 5 strategies seeded, `/health` 200, pytest 647/647, golden-master output byte-identical across the restart; **6.3 target design AUTHORIZED 2026-07-20 (DECISIONS.md #28), implementation deliberately still phased** — user explicitly signed off on the interface-touching direction; re-investigation with that authorization found the honest scope is bigger than first sized, not smaller: `LiveAdapter.execute_entry` reads `strategy.stop_loss`/`take_profit` directly as its ONLY live-path SL/TP channel (no `OrderPlan` involved), so closing the gap needs `LiveAdapter`/`OrderRouter` parameterization too, not just a kernel change; the previously-recommended "small, independently-fixable" exec_algo `kernel.py` violation turns out NOT independently fixable for the same reason (filed as **F10** in `0_fixes-queue.md`, explicitly "not a quick fix"). See plan file's Step 6.3 section for the full phased sequencing (4 independently-verified phases). **Phase (a) SHIPPED 2026-07-20 (later same day)** — real `docker compose build` + `up -d --no-deps engine` rebuild, pytest 647/647, golden-master `MultiDivergence` byte-identical to the 6.6-rebuild baseline. `route()` (`core/models/execution.py`) now returns a typed `OrderPlan` for all 5 paths (new `"exit"`/`"flip"`/`"maintain"` intents alongside `"enter"`), `kernel.py`'s 2 `plan is not None` gates now check `plan.intent == "enter"` explicitly. **Phase (b) SHIPPED 2026-07-20** — verified: pytest 647/647, golden-master `MultiDivergence` byte-identical to phase (a)'s baseline.
`LiveAdapter.execute_entry`/`ExecutionAdapter.execute_entry` gained optional `stop_loss`/
`take_profit` params (mirrors `execute_flip`'s existing pattern), `kernel.py`'s live-entry call
site passes `plan.stop_loss`/`plan.take_profit` explicitly — provably a no-op by construction
(same value, different read path), `OrderRouter` needed no change (never reads strategy attrs
itself). **Phase (c) investigated 2026-07-20, NOT implemented — F10 is not independently
closeable**: `check_exits()` also reads `strategy.stop_loss`/`take_profit` directly, as the
trigger state checked every candle after entry (backtest + live) — `OrderPlan` isn't persisted
across candles, so deleting the kernel-write (phase (c)'s original goal) would silently break
exit triggering for exec_algo-sliced positions. Entangled with phase (d)'s wider cleanup instead
of standalone — see `0_fixes-queue.md` F10 / DECISIONS.md #28 addendum. Stopped here per user
choice. **Phase (d) scoped 2026-07-20 (docs only), then AUTHORIZED — d1+d2+d3+d4 SHIPPED same day, all 4 clusters now migrated.** Read-site surface breaks into 4 clusters: `kernel.py check_exits()` (cross-candle trigger), `reconciler.py` (exchange-bracket amendment, live-only, different call frame), `execute_exit`/`BacktestAdapter.execute_entry` (logging/sizing), `kernel.py`'s rounding block. d1: new persisted `strategy.active_bracket` field, written additively by `route()`/exec_algo. d2: `check_exits()` + rounding migrated to read/write it instead of the mutable tuples. d3: all 5 `reconciler.py` read sites (SL-tighten amend, trade-record booking ×2, naked-position re-arm, `compute_open_risk_breakdown()`) migrated too — live-only, zero golden-master coverage for this cluster. d4: `LiveAdapter.execute_exit` (trade-record logging) and `BacktestAdapter.execute_entry`'s sizing-percent read migrated — the first phase to touch actual backtest code, so golden-master coverage was real (not incidental); safety argument mirrors phase (b)'s (`execute_pending()` runs before `evaluate_and_route()` each candle, so `active_bracket` still holds the prior candle's value at read time). All four verified via real rebuild (pytest 647/647, golden-master `MultiDivergence` byte-identical every time: `trades=55 netProfit=-1784.02 winRate=0.36 cagr=-71.32 sqn=-2.08`) — d2 needed 4 test fixtures fixed, d3 needed 8 more, d4 needed 3 more, same root cause every time (`_FakeStrategy`/manually-constructed doubles that bypass `route()` and never got `active_bracket` populated: `test_armed_legs_wick_check_skip.py`/`test_entry_candle_exits.py`/`test_intrabar_detail_resolution.py`/`test_multi_symbol_portfolio_exits.py` for d2; `test_execute_entry_correlation_cap.py`/`test_execute_entry_portfolio_risk_and_liq_buffer.py`/`test_execute_entry_risk_check_event.py`/`test_execute_entry_var_breach.py`/`test_maybe_amend_exchange_sl.py`/`test_reconcile_fixes.py`/`test_reconcile_naked_position_rearm.py` for d3; `test_execute_flip_idempotency.py`/`test_live_fill_booking.py`/`test_live_money_accumulation.py` for d4). Only d5 (retiring `stop_loss`/`take_profit` as strategy-facing API) remains, needs its own `DECISIONS.md` entry — see plan file's Step 6.3 section. | In progress | P2 | 5 (shipped 2026-07-18), 21.3/21.4 (shipped 2026-07-17) — unblocked | 2026-07-20 |
| 7  | Server & client structure | 7.1 IN PROGRESS (first slice shipped 2026-07-20 — see below); 7.2–7.5 not started | In progress | P2 | 2 (done), 5 (shipped), 6 (done in every way that mattered — 6.5's Node consumer is unrelated) | 2026-07-20 |
| 8  | Governance, correctness & cleanup | 8.2–8.5, 8.7 (8.3/8.4 golden-master; SYS-3 doc item carried from F6) — 8.6 verified-already-shipped 2026-07-18, no code needed | In progress | P3 | 3 (done), 5, 6 | 2026-07-18 |
| 23 | New strategy: high-risk/high-leverage breakout scalper ("MarginSurge") | All — backtest gates can start now; live gated on 21.1–21.4 | Draft | P2 | 21 (live phase), 22.1–22.2 (liq-buffer + governor, soft) | 2026-07-16 |
| 24 | BestSupertrend fixes (never trades at defaults) | ALL SHIPPED (S-1 through S-5, container-verified 2026-07-17 [353/353 pytest], golden-master re-baselined for S-1 — only BestSupertrend diverges, other 4 strategies byte-identical) — pending live Testnet re-verification only | **Done** (pending live re-verification) | — | — | 2026-07-17 |

**Plus the fixes queue:** F7 (algo-fill detection) — **LIVE-VERIFIED & effectively resolved
2026-07-19**: container pytest 444/444 (F7's 3 tests pass); live testnet chaos confirmed the
fill-staleness symptom is FIXED (~0.5s via the A-8 ACCOUNT_UPDATE reconcile, not ~60s); the
TP/SL-placement 400 root cause is `-2021 Order would immediately trigger` (tight stops at extreme
leverage — expected & self-healed by A-7 re-arm; the prior `PERCENT_PRICE` hypothesis is
DISPROVEN). **Two NEW bugs surfaced by the live run:** (a) FIXED — server governor-config coercion
(`risk.js` `Number(null)===0` armed correlation/VaR/CVaR/margin caps at 0 when the user left the
field blank; blocked ALL live entries; +5 jest tests, 116/116); (b) FIXED — `-4015` emergency-close
`clientOrderId` > 36 chars (systemic across ~6 placement sites; new central `_make_client_id()`
budgets ≤35 chars, engine pytest 450/450, `engine/tests/test_make_client_id.py`). Both fixes are in
the working tree, uncommitted, pending commit. See `0_fixes-queue.md`'s F7 entry + `handoff.md`
2026-07-19. — and F8 (Redis
`requirepass`, wants a full-stack-restart window) — see `0_fixes-queue.md`.

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
  instead. **21.5's part (c) shipped 2026-07-20**: batching `positionRisk`/`openOrders`/
  `openAlgoOrders` into one un-parametered call per session per candle wave. Confirmed against
  Binance's actual documented weights first — `positionRisk` is flat weight-5 regardless of the
  symbol param, `openOrders`/`openAlgoOrders` are weight 1 per-symbol but weight 40 when symbol
  is omitted, so batching only wins above ~13 symbols (exactly the Chaos-run case this item was
  scoped for). New `Reconciler._get_batched_reconcile_snapshot()` caches one fetch per session
  per `wave_key` (the closed candle's own open-time ms, shared across every symbol in a session),
  guarded by a per-session `asyncio.Lock` so concurrent symbol tasks reconciling the same wave
  share one fetch instead of each triggering their own. `reconcile_exchange_state` gained an
  optional `wave_key` param — only the routine per-candle-close call site passes it; the
  event-driven `_on_fill`/`_on_account_update` sites are unchanged (still per-symbol, fresh every
  time). A-15's `position_query_ok` invariant preserved: a failed batched `positionRisk` call
  blocks Case 2 for every symbol sharing that wave, not just the one that triggered the fetch.
  New `engine/tests/test_batched_reconcile_snapshot.py` (6 cases, incl. a real concurrency test —
  multiple symbols reconciling the same wave concurrently issue exactly one underlying fetch).
  Verified via real Docker rebuild: pytest 653/653, golden-master `MultiDivergence`
  byte-identical (live-only change, zero backtest import overlap). Tests: `engine/tests/test_binance_backpressure.py` (18 cases)
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
- **10** — MC core math is honest (Phase 1a shipped 2026-07-15). **Phase 1b (job plumbing) shipped
  2026-07-19**: new `labResults` collection, `simulationQueue`/`simulation.worker.js`, engine
  `routers/simulate.py` (`POST /simulate/monte-carlo`), Node `lab.controller.js`/`lab.routes.js` at
  `/api/v1/lab` — same BullMQ/Socket.IO job pattern as backtest, `configHash` cache short-circuit,
  ownership-checked. Real end-to-end smoke test against a live 38-trade backtest completed in
  ~1.0s. Engine 458/458, server jest 129/129. **Phase 2 (Strategy Lab page, MC tab) shipped
  2026-07-19**: new `/lab` route + nav, `hooks/useLab.js`, `components/lab/` (RunWizard,
  HistoryRail, FanChart, PercentileSpread, ExceedanceCurve, RuinCard, VerdictStrip, ConfigDrawer),
  socket wiring against `simulation:{labId}` mirroring `Backtest.jsx`'s pattern. `SimulationResults.jsx`
  deleted, its Risk Dashboard slot replaced with a `/lab` CTA; `GET /api/v1/risk/backtest/:id/simulation`
  now returns 410 Gone; `useBacktestSimulation` hook removed. Deep-link "Robustness Check" button
  added on the Backtest report page. **Real gap found and handled honestly, not silently:** §4.2's
  final-equity/max-drawdown "histograms" need raw per-run samples the engine discards after computing
  percentiles — `PercentileSpread.jsx` renders a percentile box/whisker spread instead, documented
  in-code as a follow-up scope item (persist bins/raw samples in `run_lab_simulation` if needed).
  Mode-breakdown table also deferred (engine runs one mode per submission, not several at once —
  unchanged from Phase 1's own scoping). **Not done:** backtest-page auto-enqueued MC summary strip
  (only the manual deep-link shipped), results-canvas component tests (no per-component test harness
  convention exists in this repo yet to follow), and **build/test verification** — this session's
  sandbox has no Docker access and its `client/node_modules` is a platform-mismatched (Windows→Linux)
  bind mount, so `vite build`/`vitest` could not run; reinstalling would violate the "don't alter
  node_modules on host" constraint. All new files were hand-reviewed against sibling component
  patterns but not compiled — verification debt carried to next session, same pattern as 2026-07-18's
  Docker gap. Deliberately still deferred from Phase 1: cancel endpoint, the 3 remaining MC modes,
  progress publishing. **Phase 3a (walk-forward job plumbing, grid search only) shipped
  2026-07-19**: new `engine/services/walk_forward.py` (fold split by candle count, rolling/anchored
  train, per-fold grid-optimize train + backtest test, per-fold degradation ratio, trade-level
  stitched-OOS aggregate), new `POST /simulate/optimize`, opt-in `min_trades` filter added to
  `services/optimizer.py` (default off, backward compatible). Node: `buildWalkForwardConfig()`,
  `/api/v1/lab/optimizations` (`lab.controller.js`/`lab.routes.js`), new `optimizationQueue`/
  `optimization.worker.js` mirroring the simulation job pattern, `socketEmitter.js`/`socket.js`
  gained an `optimization` job type (also fixed `socket.js`'s room handling, which turned out to be
  3 hardcoded string-prefix checks, not the generic `<prefix>:<id>` handler a prior session's
  tracker note claimed). **Deliberately deferred, documented in-plan:** Optuna/TPE search (Phase
  3b — swappable search loop, doesn't touch this session's fold/stitch logic), DSR/PBO overfitting
  statistics (Phase 3b/3c — needs a normal-CDF/inverse-CDF primitive this session couldn't verify
  without pytest access; shipping an unverified formula traders would use to judge overfitting was
  judged worse than shipping none), the Optimizer tab UI (Phase 3c — job plumbing before UI, same
  sequencing as Phase 1b→2), and per-fold progress publishing (wired but unused — a walk-forward
  run is genuinely multi-minute, unlike MC's sub-second job, so this is a real gap not a documented
  non-issue). **Verification gap, same as Phase 2:** this sandbox has no Docker, so
  `engine/tests/test_walk_forward.py` (14 cases) and `labConfig.test.js`'s 12 new
  `buildWalkForwardConfig` cases were written but not executed. **Phase 3c (Optimizer tab UI)
  shipped 2026-07-19, same session:** new "Optimizer" tab on `StrategyLab.jsx` (Tabs alongside the
  existing MC tab) — `WalkForwardWizard.jsx` (strategy/symbol/TF/range + `ParamGridForm.jsx`
  auto-rendering min/max/step from the strategy's existing PARAMS schema + objective/mode/nFolds/
  trainRatio/minTrades/maxCombinations + a combo-count cost estimate), `OptimizationHistoryRail.jsx`,
  results canvas (`DegradationVerdict.jsx`, `StitchedOOSCard.jsx`, `FoldResultsTable.jsx`). New thin
  Node proxy `GET /api/v1/lab/objectives`. Fixed a real gap found while wiring: Phase 3a's
  `runOptimization` controller trusted a raw `strategyFile` from the client instead of resolving
  `strategyId` → `filePath` via `Strategy.findById` like `POST /api/v1/backtest` does — fixed.
  **Honestly scoped, not faked:** `walk_forward.py` only persists each fold's WINNING combo, not
  every trial — so this is a fold-level table, not the plan's full per-trial "trials table" with
  IS-vs-OOS scatter/param heatmap. That needs an engine change to persist every trial (new **Phase
  3d**), explicitly noted in-UI and in the plan doc rather than silently relabeling fold rows as
  trials. Same verification gap as everything else this session — not compiled/rendered.
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
- **6/7** — Plan 6 is now done in every way that mattered to Plan 7's dependency (6.5's Node-side
  Redis-stream consumer is unrelated to server/client structure). **Plan 7 Step 7.1 started
  2026-07-20**: extracted the ~150-line credential/capital-check/risk-cascade duplication between
  `startSession` and `startChaos` (`server/src/controllers/algo.controller.js`) into new
  `server/src/services/algoSessionService.js` — `resolveBinanceCredentials`,
  `checkCapitalOverCommit`, `checkConcurrentBotCap`, `buildRiskParamsCascade`. Pure extraction,
  no behavior change (same status codes/error codes; message text only reworded where it
  referenced a now-shared computed value). Deliberately scoped to just this duplication, not
  every credential-lookup site — `_getBinanceHeaders` (internal engine-callback routes) and
  `reconciliation.js`'s `_testnetHeadersFor` resolve by sessionId/cache rather than by
  `req.user.id`, a different enough shape to leave as a documented follow-up rather than force
  into this module. New `server/src/services/__tests__/algoSessionService.test.js` (12 cases,
  100% line coverage on the new module). Verified: full server jest suite 193/193 (181 existing +
  12 new), server container restarted clean via nodemon on every edit (`/health` 200 throughout).
  **7.1 second slice, same day**: extracted `handleEngineStats` (algo.controller.js, ~260 lines,
  the single biggest extraction target) into `algoSessionService.js` as `processEngineStatsUpdate`
  (+ `computeSymbolStats`, moved alongside it since `processEngineStatsUpdate` is its only
  internal caller). `io` is passed in by the controller (`getIO()`) rather than required by the
  service, keeping the service testable without a live Socket.IO server. Pure extraction — same
  seq-guard/status-code/event-emit/webhook-dispatch/lock-release behavior, just relocated; the
  controller's `handleEngineStats` is now a 6-line wrapper. New tests: 12 cases for
  `processEngineStatsUpdate` (stale-seq rejection, session-not-found short-circuit, each event
  branch — position:open/close, error, log, risk_breach, stopped — plus positionDetails
  persistence, both symbolStats-aggregation-failure catches, and a thrown-socket-emit-is-caught
  case) in `algoSessionService.test.js`; `computeSymbolStats.test.js` relocated from
  `controllers/__tests__` to `services/__tests__` (same 6 cases, import path updated) since the
  function moved. Full server jest suite 207/207 (193 + 14 new/moved), server container restarted
  clean via nodemon on every edit (`/health` 200 throughout).
  **7.1 third slice, same day**: extracted the symbol-lock guard duplicated 3x/4x across both
  controllers into `symbolLock.js` (the natural home — both controllers already import lock
  primitives from it directly) rather than `algoSessionService.js`: `assertSymbolNotBotLocked
  (symbol, { closing })` (manual-trading side — "reject if a bot already owns this symbol",
  `trade.controller.js`'s `placeOrder`/`placeOCOOrder`/`placeOrderWithTpSl`/`closePosition`, the
  last with a different message via `{ closing: true }`) and `assertSymbolLockedByBotSession
  (symbol, sessionId)` (engine-callback side — the inverse "reject unless THIS session owns the
  lock", `algo.controller.js`'s `handleAlgoPlaceOrder`/`ClosePosition`/`SetLeverage`, identical
  message across all 3). Both throw an `ApiError`, so call sites just `await` them inside their
  existing try/catch — the manual side's `return next(new ApiError(...))` became `throw` (behavior
  identical: every catch already forwards an `ApiError` instance as-is via `handleEngineError`);
  the engine-callback side's `throw` was already there. **Deliberately did NOT touch** a latent bug
  found while reading `handleAlgoPlaceOrder`'s catch block: it does
  `res.status(err.response?.status || 500)`, which for an `ApiError` (no `.response`) always
  resolves to 500 even though the thrown error is a 409 — pre-existing, out of scope for a
  behavior-preserving extraction, not silently "fixed" in passing.
  New tests: 8 cases in `symbolLock.test.js` (unlocked/manually-locked resolve, bot-locked throws
  with the right message per `closing`, and the 4 ownership branches for
  `assertSymbolLockedByBotSession`: matching session / no lock / wrong session / manual-not-bot).
  Full server jest suite 215/215 (207 + 8 new), server container restarted clean via nodemon on
  every edit (`/health` 200 throughout).
  **7.1 fourth slice, same day**: extracted the 3x-duplicated engine-sync-then-bulkWrite pattern
  shared by `trade.controller.js`'s `getTradeOrders`/`getTradeExecutions`/`getTradeTransactions`
  into new `server/src/services/tradeHistoryService.js`'s `syncAndListTradeHistory({ Model,
  engineEndpoint, headers, query, idField, transform, syncErrorLabel, readFilter })` — best-effort
  engine fetch → per-item bulkWrite upsert → degrade to `synced:false` on any failure (fetch or
  write) rather than throwing → always read back from the local Mongoose collection regardless of
  sync outcome. Each caller supplies its own `Model` (`TradeOrder`/`TradeExecution`/
  `TradeTransaction`), dedupe key (`orderId`/`id`/`tranId`), per-item transform (orders also set
  `updateTime`; executions/transactions don't), and read filter (`getTradeTransactions`'s symbol
  is optional, the other two require it — validation stays in the controller, not the shared
  function). Log text preserved exactly via an explicit `syncErrorLabel` param rather than
  derived from the model name, so `console.error` output is byte-identical to before. Pure
  extraction — same try/catch boundary, same bulkWrite op shape, same never-throw-on-sync-failure
  behavior. New `server/src/services/__tests__/tradeHistoryService.test.js` (6 cases: bulkWrite op
  shape + transform, empty-array skips bulkWrite, malformed non-array response treated as no
  items, failed engine fetch degrades to `synced:false` without throwing, failed bulkWrite also
  degrades rather than throwing, local read uses the exact given filter sorted by `time:-1`). Full
  server jest suite 221/221 (215 + 6 new), server container restarted clean via nodemon on every
  edit (`/health` 200 throughout).
  **Not done**: `startSession`/`startChaos` themselves are still 1,000+-line functions (the shared
  cross-cutting logic moved out, but each function's own remaining body — session
  create/lock/rollback/engine-call sequencing — has not been moved into the service layer);
  `trade.controller.js`'s order-placement/cancel bodies (`placeOrder`, `placeOCOOrder`,
  `placeOrderWithTpSl`, `cancelOrder`, `cancelAllOrders`) still inline their own engine-call +
  `upsertTradeOrder`/status-update logic — not duplicated 3x the way the sync-then-list functions
  were, so lower priority for further extraction.
  **7.2 (SRV-5, jobs not hour-long HTTP) shipped same day**: `services/engineClient.js`'s shared
  axios instance used to default every call (including request-path calls a browser is waiting
  on — place order, start session, fetch account) to `timeout: 60*60*1000`, so an engine hang on
  a *quick* call held the Express connection open for up to an hour. Root cause was never that
  quick calls needed an hour — only backtest/simulation/optimization/PBO runs did, and those
  already run through BullMQ workers (`backtest.worker.js` + 3 siblings), not a request/response
  cycle. Fix: lowered the instance default to `DEFAULT_TIMEOUT_MS = 30_000` (comfortably above the
  engine's own internal Binance client timeout of 30s in `services/binance_testnet.py`, plus
  processing headroom) and exposed `engineClient.LONG_JOB_TIMEOUT_MS = 60*60*1000` as a property
  on the shared instance; each of the 4 worker files now passes `{ timeout:
  engineClient.LONG_JOB_TIMEOUT_MS }` explicitly on its one long-running engine POST, so their
  behavior is unchanged while every other call site (controllers, `reconciliation.js`'s startup
  calls) now fails fast instead of hanging for an hour. Confirmed no other call site needed the
  long budget: `backtest.controller.js`'s own two `engineClient` calls (`benchmark`, `cancel`) are
  quick proxies, not the run itself — the run only happens inside the worker. New
  `server/src/services/__tests__/engineClient.test.js` (3 cases: default timeout is 30s not the
  old 1-hour value, `LONG_JOB_TIMEOUT_MS` is exposed, default is strictly less than the long-job
  constant). Full server jest suite 224/224 (221 + 3 new). Verified via `docker logs`: nodemon
  restarted clean, all 4 workers (required as side-effect modules in `server.js`) loaded without
  error, `/health` 200 throughout. Acceptance check met: no engine call inherits the 1-hour budget
  by default; the long-running calls remain jobs with queryable status (unchanged from before —
  they were already jobs, just previously piggy-backing on a global default instead of an
  explicit opt-in).
  **7.3 (SRV-4, auth robustness) shipped same day, per the user's explicit "proceed through 7.3,
  don't stop" instruction**: `verifyJWT` (`middleware/auth.middleware.js`) used to catch-all
  everything — a bad/expired JWT and a Mongo outage during `User.findById` both produced the same
  401 UNAUTHORIZED, which sends a client into a useless re-login loop when the real problem is the
  DB being unreachable. Split into two try/catches: `jwt.verify` failures stay 401 UNAUTHORIZED
  (unchanged); a `User.findById` failure now throws `ApiError(503, 'SERVICE_UNAVAILABLE', ...)`
  instead. Confirmed the client only special-cases 401 for its logged-out redirect
  (`client/src/hooks/useAuth.js`) — a 503 surfaces as a generic error, not a forced logout, which
  is exactly the intended distinction. Added a short-TTL (5s) in-memory `Map` cache for the
  per-request `User.findById` lookup (every protected route runs it on every request — e.g.
  Trade's 4s position poll), following `symbolService.js`'s existing cache-with-TTL pattern.
  Cache hits return a shallow copy, never the shared cached object, since `verifyJWT` mutates
  `.id` onto whatever it assigns `req.user` and two concurrent requests must never alias the same
  object. **Preserved the documented "grants/revokes apply immediately" invariant exactly, not
  approximately**: `admin.controller.js`'s `setUserAlgoAccess` now calls the newly-exported
  `invalidateUserCache(userId)` right after its `User.updateOne`, so an algoAccess change is
  visible on the very next request regardless of the 5s TTL — checked this was the only User
  mutation site outside login/creation (`isActive`/`role` are never toggled elsewhere; no
  deactivate-user route exists).
  **Also fixed (explicitly called out in the plan's own Step 7.3 bullet, not scope creep)**: the
  bare `.catch(() => {})` silent-swallow pattern, sitewide — 18 call sites across
  `algo.controller.js` (4), `trade.controller.js` (3), `algoSessionService.js` (7),
  `reconciliation.js` (4), all fire-and-forget lock-release/DB-write/log-push operations that
  previously discarded their failure with zero observability. Each now logs via `console.error`
  with enough context (symbol/session id/user id) to actually debug a real failure, while staying
  non-blocking/non-throwing exactly as before — pure "replace silence with a log line," no control-
  flow change. **Deliberately left alone**: `app.js`'s 2 health-check catches (already surface
  `'error'` in the response body — not silent), `config/socket.js`'s auth catch (rejects the
  socket connection with an explicit error, not silent), `constants/top_symbols.js`'s 2 catches
  and `symbolService.js`'s 1 catch (each falls through to a documented static/cached fallback,
  already commented) — none of these are the discard-and-forget anti-pattern the plan's example
  called out; they're deliberate fallback behavior that already has an observable effect.
  New tests: 7 more cases in `auth.middleware.test.js` (503-not-401 on DB failure, bad-token-stays-
  401-distinct-from-503, cache-hit-skips-second-`User.findById`, cache-never-shares-object-
  references-across-requests, `invalidateUserCache`-forces-a-fresh-read) plus a new
  `admin.controller.test.js` (4 cases: invalidates on grant, invalidates on revoke, does NOT
  invalidate when rejected before the update on bad status or an admin target). Full server jest
  suite 233/233 (224 + 9 new). Verified via `docker logs`: nodemon restarted clean, `/health` 200
  throughout.
  **Files changed:** `server/src/middleware/auth.middleware.js`,
  `server/src/controllers/admin.controller.js`, `server/src/controllers/algo.controller.js`,
  `server/src/controllers/trade.controller.js`, `server/src/services/algoSessionService.js`,
  `server/src/services/reconciliation.js`, `server/src/middleware/__tests__/auth.middleware.test.js`,
  new `server/src/controllers/__tests__/admin.controller.test.js`.
  **7.5 (CLI-2/CLI-3, single realtime-state owner) — design question resolved, core shipped same
  day**: asked the user the plan's own open question (Zustand+TanStack-Query-thin-store vs
  TanStack-Query-only) via AskUserQuestion before writing any code, per the plan file's explicit
  "do not just pick one" instruction — **Zustand + TanStack Query (thin store)** was chosen.
  Surveyed the actual current-state architecture first (an Explore agent, not assumption):
  confirmed `client/src/store/` had been fully deleted (no Zustand store existed at all — a
  greenfield slot, not a migration), and found the concrete "3 disagreeing sources" problem was
  narrower than the plan's framing suggested — `binanceWS.js` already ref-counts WebSocket
  connections by stream name, so Trade.jsx's 2 independent `<sym>@ticker` subscriptions (header
  `TickerBar`, the order-entry sizing calc) shared one real connection but each parsed the tick
  into its own local state/ref, meaning "this symbol's price" had no single documented value even
  though the underlying data was already identical. New `client/src/store/marketStore.js` —
  `useMarketTicker(streamPrefix)` (reactive, for display) and a non-reactive
  `useMarketStore.getState().tickers[...]` read pattern (for sizing math that shouldn't re-render
  on every tick, preserving the old ref's non-reactive-read intent exactly). Migrated both
  Trade.jsx consumers. **Deliberately scoped to ticker/price only** — OrderBook/RecentTrades/the
  candle chart keep their own dedicated `useBinanceWS` subscriptions (depth/aggTrade/kline are
  structurally different data, and client/CLAUDE.md's realtime rules already document
  per-sub-component isolation for those as a deliberate render-perf choice, not an oversight).
  `client/dist/` requirement already satisfied — confirmed gitignored, 0 tracked files, no action
  needed. Verified in a real browser (not just the smoke test): header ticker live-updates, the
  50% sizing button correctly computes qty from the shared store's price, zero console errors.
  New `client/src/store/__tests__/marketStore.test.js` (4 cases). `client/CLAUDE.md` updated (the
  store directory's "no longer exists" note was stale; realtime rules section now documents the
  ticker exception). **Deliberately NOT attempted**: the plan's "hooks share a factory" sub-item
  (collapsing duplicated loading/error/toast logic across ~15 per-domain hooks) — surveyed the
  actual duplication (mostly `const { data } = await api.get(url); return data.data` unwrap
  boilerplate repeated per query, not loading/error/toast which client/CLAUDE.md already
  documents as page-level, not hook-level) and judged a full mechanical migration across every
  hook file too large/risky to append to an already-large session without its own dedicated
  regression pass — flagged as a follow-up, not silently declared done.
  **7.4 (CLI-1, decompose god components) — Trade.jsx done, 3 files remain**: surveyed all four
  target files' actual shape before touching anything — Trade.jsx (1,760 lines) was structurally
  different from the other three: ~20 already-separate named function components crammed into one
  file (a mechanical file-split, low risk), whereas Backtest.jsx (831 lines, one ~640-line
  `export default function` plus 2 small table helpers), Settings.jsx (928 lines, **entirely** one
  single function, zero pre-existing internal decomposition), and ChaosWizard.jsx (677 lines, one
  ~600-line function plus one helper) are single monolithic component bodies needing real
  JSX-tree/container-presenter splitting — a different, slower, higher-risk kind of refactor.
  Prioritized the mechanical, high-value, low-risk win: extracted 8 new files under
  `client/src/features/trade/` (`formatters.js`, `TableHelpers.jsx`, `TpSlModal.jsx`,
  `PositionsTable.jsx`, `OpenOrdersTable.jsx`, `AssetsTable.jsx`, `HistoryTables.jsx`,
  `BottomPanel.jsx`) — pure moves, no logic changes. Trade.jsx: **1,760 → 892 lines (49%
  reduction)**. Verified: `vite build` succeeds with an identical bundle size (confirms nothing
  silently duplicated), `vitest` 15/15, and a real-browser check (chart/order book/trades/order
  form/bottom-panel tabs all render and function, % sizing still computes correctly, zero console
  errors after a hard reload).
  **7.4 continued, same day — Settings.jsx and Backtest.jsx also decomposed**, per the user's
  explicit "proceed on them" follow-up after the Trade.jsx-only report. Settings.jsx (928 lines,
  entirely one function) split into 7 self-contained cards under `client/src/features/settings/`
  (`ProfileCard`, `AlgoAccessCard`, `EnvironmentConfigCard`, `ChaosSettingsCard`,
  `NotificationsCard`, `ExchangeSettingsCard`, `styles.js`) — each card owns its own
  `useExchangeSettings()`/mutation calls rather than receiving 20+ props from a parent (TanStack
  Query dedupes the identical `['settings','exchange']` query automatically, so this is the
  standard usage pattern, not N redundant requests). **Settings.jsx: 928 → 30 lines.**
  Backtest.jsx (831 lines, one ~640-line function + 2 small table helpers) split into
  `client/src/features/backtest/{PerformanceTable,ComparisonTable,OverviewTab,TradesTab,
  ComparisonTab}.jsx` — each tab-content component takes already-fetched data as props;
  `Backtest.jsx` still owns every TanStack Query hook call and all page-level state (a
  presentational split, not a data-ownership change, since the hooks are tightly coupled to
  page-level `selectedResultId`/`tradePage` state that several tabs and the history sidebar all
  share). **Backtest.jsx: 831 → 503 lines.**
  Verified both: `vite build` succeeds with stable bundle size, `vitest` 15/15, and a real-browser
  walkthrough of every affected surface (Settings: all 6 cards render with real loaded data,
  correct `space-y-0` flush-card spacing preserved exactly, zero console errors; Backtest: all 4
  result tabs — Overview/Performance Summary/List of Trades/Compare — render correct data via the
  accessibility tree after a screenshot-tool CDP timeout made pixel screenshots unreliable
  mid-session, confirmed via DOM inspection instead of narrating around the tooling failure).
  **Found, not caused, not fixed**: a pre-existing React "duplicate/missing key" console warning
  on `TradesTab`'s `key={tr.id}` — checked via `git show HEAD:client/src/pages/Backtest.jsx`, the
  identical `key={tr.id}` was already in the pre-refactor committed code, so this is a pre-existing
  trade-data quality issue (likely duplicate/undefined `id` on some rows), not a regression from
  the extraction. Flagged, not silently fixed (would be scope creep for a decomposition task).
  **Deliberately still not attempted**: ChaosWizard.jsx's internal decomposition (677 lines, one
  ~600-line function + one helper — same monolithic-body shape as Settings.jsx/Backtest.jsx was,
  its own dedicated pass); the "hooks share a factory" sub-item from 7.5 (collapsing duplicated
  `api.get/post`-and-unwrap boilerplate across ~15 per-domain hooks); the remaining WS-entangled
  Trade.jsx components (TickerBar, ChartContainer, OrderBook, RecentTrades, OrderForm,
  LeverageModal, `TradeInner`) — already touched for 7.5's price-store work, further splitting
  trades more regression risk for less file-size benefit than the tables did. See `handoff.md` for
  the resume point.
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
