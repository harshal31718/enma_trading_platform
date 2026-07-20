# Plan 6 — Engine decomposition & exchange abstraction

**Status:** In progress (starting 6.1) · **Priority:** P2 · **Depends on:** 5 (shipped) · **Related:** 7

> Source issues: ENG-1, ENG-4, ENG-5, ENG-6, ENG-7, ENG-12, ENG-16. Structural cleanup of the
> live engine. Comes **after** Plan 5 because you want the correctness/state model settled
> before you move the code that implements it — restructuring on top of the broken state
> machine would just relocate the bugs.

## Goal

`LiveBotManager` stops being a 2,000-line god class. Live vs backtest vs mainnet vary behind a
real abstraction instead of `is_live` flags and hardcoded `mode="testnet"`. The strategy↔engine
contract is a typed object, not mutable-attribute pokes. Packaging is a proper installable
layout, not symlink/`sys.path` hacks.

## Scope / what changes

### Step 6.1 — Extract collaborators from `LiveBotManager` (issue ENG-1)
Split by responsibility into separate, individually testable modules:
- **SessionRegistry** — session lifecycle + typed session state (replaces the untyped dict,
  finishing ENG-7 started in Plan 5.6). **Lifecycle half shipped 2026-07-20, typing half still
  open.** New `engine/core/session_registry.py` (`SessionRegistry` — owns `sessions`/
  `stop_signals`/`tasks`/`order_semaphores`/`symbol_state_locks` + `get_symbol_lock()`, moved
  verbatim). `LiveBotManager.__init__` now holds `self._registry = SessionRegistry()`; kept
  `sessions`/`_stop_signals`/`_tasks`/`_order_semaphores`/`_symbol_state_locks` as thin delegating
  `@property`s and `_get_symbol_lock()` as a delegating method — a deliberate choice over rewriting
  every call site: `self.sessions`/`self.manager.sessions` is referenced ~90 times across
  `start_session`/`stop_session`/`_run_symbol_loop`/`_reconcile_exchange_state`/etc, and ~62 more
  times across the test suite (including direct `mgr.sessions[sid] = ...` mutation, which needs
  the SAME dict object, not a copy — verified by `test_manager_properties_delegate_to_same_
  registry_objects`). The facade means every one of those ~150 sites kept working with **zero
  changes**, first pytest run after wiring was already 582/582 green — a deliberate contrast with
  the NodeNotifier extraction's 49-failure first pass. **Real scope still open**: the "typed
  session state" half of this bullet — `sessions[id]`'s value is still a raw untyped `dict`, not a
  typed object. That's a materially larger, separate change (hundreds of `session["key"]`
  read/write sites across the whole file) left for its own pass, most naturally paired with
  Step 6.3's typed-contract work since both replace mutable-dict/attribute protocols with real
  types.
- **MarketDataFeed** — warmup/HTF/live candle sourcing (the three fetchers) behind one
  interface, with a single documented rule for which source (fixes the testnet-exec /
  mainnet-warmup split in ENG-4). **Shipped 2026-07-20**: new `engine/core/market_data_feed.py`
  (`MarketDataFeed` class — `fetch_warmup_candles`/`fetch_candles_from_rest`/`fetch_htf_candles`/
  `append_candle`, pure move, zero logic changes). `LiveBotManager.__init__` now holds
  `self._market_data = MarketDataFeed()`; all 8 call sites across `start_session`/
  `_run_symbol_loop` updated to `self._market_data.<method>(...)`. Dead `get_pool` import removed
  (no longer used directly in `live_bot_manager.py`). Golden-master byte-identical
  (`before_plan6.json` vs `after_plan6_1.json`, 5/5 strategies incl. exact `MultiDivergence`
  trades/netProfit/winRate/cagr/sqn match), container pytest 567/567.
- **OrderRouter** — order placement/close/reduce (already idempotent from Plan 5.3). **Shipped
  2026-07-20 — the fifth and final Step 6.1 extraction.** Read `execute_entry`/`execute_reduce`/
  `execute_exit`/`execute_flip` in full before drawing the boundary (not assumed from `execute_
  entry` alone): the real seam is NOT "everything in these four methods" — it's the narrower,
  genuinely reusable "place a MARKET/algo order on Binance and confirm its real fill price, never
  trusting a candle/trigger-price estimate" plumbing (Plan 5 Step 5.2/5.3, ENG-2/ENG-10) that
  repeats near-verbatim across the entry order, DCA-add order, SL/TP algo orders, the emergency-
  close retry loop, the reduce order, and the exit order. The risk/governor decision chain
  (TradingState, protections, rate limiter, risk-governor pre-trade/portfolio-risk/VaR-CVaR/
  correlation, liq-buffer, M-5 SL-validity) and all local session/position state mutation
  deliberately stay in `LiveAdapter` — moving them would blur the exact seam this extraction
  exists to draw, and `LiveAdapter`'s job as the `ExecutionKernel`'s polymorphic `ExecutionAdapter`
  (killing `is_live` branching in `core/kernel.py`) remains Step 6.4's own unattempted, separate
  half. New `engine/core/order_router.py`: six free functions moved verbatim (`fmt_num`/
  `make_client_id`/`binance_error_detail`/`extract_fill_price`/`query_real_fill_price`/
  `uuid4_hex8` — previously module-level in `live_bot_manager.py`, still imported unchanged by
  `Reconciler` via `from core.live_bot_manager import ...`, which now re-exports them from here so
  that import needed zero changes) plus a new `OrderRouter` class (`place_market_order`/
  `place_algo_order`/`confirm_fill`, stateless — takes the session's own api_key/api_secret per
  call rather than holding them, matching every other call site's existing pattern). `LiveAdapter.
  __init__` gained `self._order_router = OrderRouter()`; the 8 actual "build a signed-request
  params dict + call `send_signed_request` inline" blocks across the four methods (DCA add,
  entry, SL algo order, emergency close's 3-attempt retry loop, TP algo order, DCA reduce, exit
  close) were rewritten to call the new methods 1:1 — same params, same `mode="testnet"`, same
  fill-confirmation ladder (`extract_fill_price` then `query_real_fill_price` re-query), zero
  behavior change. `live_bot_manager.py` 2783→2631 lines (152-line drop — smaller than the other
  four extractions since only the plumbing, not the risk/decision logic, actually moved). New
  `engine/tests/test_order_router.py` (21 cases) — the six free functions (incl. the F7-regression
  zero-avgPrice-string case), `OrderRouter.place_market_order`/`place_algo_order`'s exact param
  shape (incl. `reduceOnly` present/absent), `confirm_fill`'s trust-real-avgPrice/re-query-on-zero/
  still-unconfirmed-returns-None paths, and `LiveAdapter` wiring. Deliberately not a re-test of
  execute_entry/reduce/exit/flip BEHAVIOR — the 20+ pre-existing tests
  (`test_entry_unconfirmed_fill.py`, `test_execute_entry_bracket_safety.py`,
  `test_execute_flip_idempotency.py`, etc.) already cover that, now reached via `self._order_
  router` instead of inline code. Verified: engine pytest 619→640 (619 + 21 new, zero regressions),
  golden-master byte-identical (`before_orderrouter.json` vs `after_orderrouter.json` — expected,
  live-only file with zero backtest-path overlap).
- **Reconciler** — the exchange-truth reconciliation (already race-safe from Plan 5.4). **Shipped
  2026-07-20.** New `engine/core/reconciler.py` (`Reconciler` class) — bundled all 7 methods that
  form one cohesive "keep local state true to exchange + apply governor consequences" cluster:
  `cancel_symbol_algo_orders`, `maybe_amend_exchange_sl`, `close_position_on_stop`,
  `reconcile_exchange_state`, `compute_session_equity_and_margin` (static),
  `compute_open_risk_breakdown` (static), `apply_governor_breach` — 943 lines moved as one unit
  (confirmed via dependency grep before moving: the whole cluster only touched `self._notifier`/
  `self.sessions`/its own sibling methods, i.e. nothing outside the cluster except one real
  remaining coupling, see below). Constructor takes `(registry: SessionRegistry, notifier:
  NodeNotifier, manager)` — the `manager` param is a **known, documented, not-yet-removed**
  coupling: `reconcile_exchange_state`'s naked-position force-close path (A-7) constructs a
  `LiveAdapter(manager, session_id)` to call `execute_exit`, and `LiveAdapter`'s constructor still
  wants a full manager reference. Fully severing this (an adapter factory instead of a raw manager)
  is explicitly Step 6.4's job, not this mechanical extraction's — documented in the new module's
  own docstring rather than silently left as an unexplained parameter. Same facade pattern as
  SessionRegistry: `LiveBotManager` kept all 7 old method names (`_cancel_symbol_algo_orders`,
  `_maybe_amend_exchange_sl`, `_close_position_on_stop`, `_reconcile_exchange_state`,
  `_compute_session_equity_and_margin`, `_compute_open_risk_breakdown`, `_apply_governor_breach`)
  as thin delegating wrappers — avoided touching ~30 call sites in `LiveAdapter`/`_run_symbol_loop`
  and ~35 direct test call sites (`mgr._reconcile_exchange_state(...)`, `mgr._maybe_amend_exchange_
  sl(...)`, one class-level `monkeypatch.setattr(LiveBotManager, "_cancel_symbol_algo_orders",
  ...)`) across 8 existing test files — first pytest run after wiring was 593/593 green with zero
  test-file edits needed. New `engine/tests/test_reconciler.py` (6 cases) verifies the extraction
  seam itself (standalone constructibility, correct wiring, delegation) — deliberately NOT a
  re-test of reconcile/cancel/amend/governor-breach BEHAVIOR, which the existing 20+ test files
  already cover end-to-end through the same code, now reached via the wrapper. One real dead-code
  find during cleanup: `get_ticker_data` import in `live_bot_manager.py` became fully unused once
  its only caller moved — removed.
- **NodeNotifier** — the transport (see Step 6.5). **Shipped 2026-07-20**: new
  `engine/core/node_notifier.py` (`NodeNotifier` class — `notify`/`call_internal`, same
  per-event `httpx.AsyncClient()` fire-and-forget as before, deliberately NOT redesigned here —
  that's Step 6.5's job, this just gives it one clean seam to land in). Moved `SERVER_URL`/
  `INTERNAL_API_KEY`/`_internal_headers()` into the new module (were only used by these two
  methods). `LiveBotManager.__init__` gained `self._notifier = NodeNotifier()`; ~42 call sites
  (`self.manager._notify_node(...)` from `LiveAdapter`, `self._notify_node(...)`/
  `self._call_node_internal(...)` from `LiveBotManager` itself) rewritten to
  `self.manager._notifier.notify(...)` / `self._notifier.notify(...)` /
  `self._notifier.call_internal(...)`. **11 test files monkeypatched the old method names
  directly** (`monkeypatch.setattr(mgr, "_notify_node", ...)`, one class-level
  `monkeypatch.setattr(LiveBotManager, "_notify_node", ...)`, one direct `mgr._notify_node = ...`
  assignment) — all updated to patch `mgr._notifier.notify`/`NodeNotifier.notify` instead; this is
  exactly why "pytest 578/578" isn't sufficient on its own for these extractions, the tests
  themselves are load-bearing on the internal method names and need updating in lockstep.
`LiveBotManager` becomes a thin orchestrator wiring these together. Line count:
3830 → 2783 → 2631 (MarketDataFeed + NodeNotifier + SessionRegistry + Reconciler + OrderRouter —
all five planned Step 6.1 extractions now shipped; the biggest single drop was Reconciler's
943-line cluster moving out in one piece, leaving only ~30-line delegating wrappers behind;
OrderRouter's 152-line drop is the smallest of the five since only the order-placement plumbing,
not the risk/decision logic living alongside it in the same methods, actually moved).
- Acceptance check: each extracted module has unit tests; `LiveBotManager` shrinks
  substantially; golden-master identical.

### Step 6.2 — Real exchange abstraction (issue ENG-4)
- Introduce an `Exchange` interface (place/close/query/leverage/rules/streams) with a
  `BinanceFuturesTestnet` and a `BinanceFuturesMainnet` implementation. `mode="testnet"`
  literals, the hardcoded WS host, and repeated `"Binance Futures"` strings collapse into the
  implementation choice, selected once per session from config.
- This is the axis the system will most need to vary (testnet→mainnet); make it the seam.
- Note: mainnet must stay gated behind Plan 5 being `Shipped` (state integrity) — wiring the
  class is fine; enabling mainnet trading is a separate product gate.
- Acceptance check: switching a session's exchange is a config value, not a code edit; both
  implementations satisfy the same contract tests.
- **Interface half shipped 2026-07-20 — deliberately not wired to any existing call site yet.**
  New `engine/core/exchange.py`: `Exchange` ABC (`place_order`/`cancel_order`/`query_order`,
  `place_algo_order`/`cancel_algo_order`/`query_open_algo_orders`, `query_open_orders`/
  `query_position_risk`/`query_account`/`query_user_trades`, `set_leverage`/`set_margin_type`,
  `create_listen_key`/`keepalive_listen_key`/`close_listen_key`, `user_data_ws_url`) with
  `BinanceFuturesTestnet`/`BinanceFuturesMainnet` concrete implementations — every method routes
  through `send_signed_request` using the INSTANCE's own `mode`, so a call site can no longer
  accidentally cross-wire a testnet session onto `mode="mainnet"` (or vice versa) via a stray
  literal, which is exactly the class of risk ENG-4 flags. Endpoint surface sized by grepping
  every real `send_signed_request(...)` call site across `live_bot_manager.py`/`reconciler.py`/
  `user_data_stream.py` first (24 call sites, 9 distinct endpoints) rather than guessing at a
  surface — `set_leverage`/`set_margin_type` included for completeness even though their only
  current callers live in `routers/trade.py` (the separate manual-trade path), matching the
  plan's own "leverage" in the interface's stated scope. **Deliberately excludes the kline/candle
  WebSocket** — per Plan 21 A-12 (DECISIONS.md #24) that stream is ALWAYS mainnet-sourced
  regardless of session mode (documented design decision, not a gap this abstraction should
  paper over); `user_data_ws_url()` covers the stream that genuinely IS mode-dependent (the
  authenticated listen-key WS, `wss://fstream.binancefuture.com` testnet vs
  `wss://fstream.binance.com` mainnet — confirmed by reading `user_data_stream.py` directly, not
  guessed). New `engine/tests/test_exchange.py` (19 cases, parametrized across both
  implementations) — every method's endpoint/HTTP-method/mode routing, listen-key lifecycle
  extracting `listenKey` from the response, and an explicit "mode can never be overridden by a
  call site" contract test. **Found and fixed one real, unrelated bug while scoping this** (not
  bundled into this step's own commit — see fixes-queue F9): `send_signed_request`'s `_dispatch`
  had no PUT branch, so `user_data_stream.py`'s listen-key keepalive (which calls it with
  `method="PUT"` every 30 min) had been silently failing every time, self-healing only via a full
  WS reconnect every ~60 min instead of ever actually renewing the key. Verified: engine pytest
  619/619 (600 + 19 new), golden-master byte-identical (`before_plan6.json` vs
  `after_plan6_2a.json` — expected, since nothing calls this module yet), running dev container's
  `/health` confirmed still 200 after the change.
- **Call-site migration mostly shipped 2026-07-20 — the larger/riskier half this step's own scoping
  note flagged.** `start_session` (`live_bot_manager.py`) now resolves ONE `session["exchange"] =
  BinanceFuturesTestnet()` per session (mainnet selection stays a separate, deliberate product
  decision — nothing in `session_config` chooses it yet); every collaborator that used to hardcode
  `mode="testnet"` now resolves and routes through that instance instead:
  - `reconciler.py` — new module-level `_resolve_exchange(session)` helper (`session.get("exchange")
    or BinanceFuturesTestnet()`, the same fallback-default pattern as `SessionRegistry`/`Reconciler`
    themselves), all 11 real call sites across `cancel_symbol_algo_orders`/`maybe_amend_exchange_sl`/
    `close_position_on_stop`/`reconcile_exchange_state` migrated.
  - `order_router.py` — `OrderRouter.place_market_order`/`place_algo_order`/`confirm_fill` and the
    free `query_real_fill_price` function all gained an `exchange: Exchange | None = None` param
    (defaults to `BinanceFuturesTestnet()` for direct/test callers), routing through `Exchange.
    place_order`/`place_algo_order`/`query_order` instead of a raw `send_signed_request(...,
    mode="testnet")`. All 10 `LiveAdapter` call sites (`execute_entry`/`execute_reduce`/
    `execute_exit`) now pass `exchange=session["exchange"]`.
  - `user_data_stream.py` — `UserDataStreamManager.__init__` gained an `exchange: Exchange | None =
    None` param (default `BinanceFuturesTestnet()`); `_create_listen_key`/`_delete_listen_key`/
    `_keepalive_listen_key` route through `self._exchange.create_listen_key`/`close_listen_key`/
    `keepalive_listen_key` instead of three separate `send_signed_request(mode="testnet")` calls,
    AND the module-level `_BINANCE_FUTURES_WS` constant (hardcoded regardless of caller — exactly
    the "hardcoded WS host" this step's own goal names) is gone; all 3 WS-URL construction sites now
    call `self._exchange.user_data_ws_url(listen_key)`. `start_session` passes `exchange=
    session_exchange` when constructing the per-session `UserDataStreamManager`.
  - `live_bot_manager.py`'s own direct sites: the OUO peer-cancel inside `_run_symbol_loop`'s fill
    callback now resolves `session.get("exchange") or BinanceFuturesTestnet()` and calls `exchange.
    cancel_algo_order(...)`; `_query_real_exit_from_user_trades` gained the same optional `exchange`
    param, threaded from `reconcile_exchange_state`'s call site; `_fetch_available_balance` (called
    BEFORE a session — and therefore an Exchange — exists) now calls `BinanceFuturesTestnet().
    query_account(...)` directly, documented as always-testnet-by-construction rather than an
    oversight.
  - **A real bug caught and fixed while wiring this, before it could silently break every test that
    monkeypatches `send_signed_request`**: `exchange.py`'s `_signed()` had imported `send_signed_
    request` BY NAME at module load time (`from services.binance_testnet import send_signed_
    request`) — tests across this codebase monkeypatch `services.binance_testnet.send_signed_
    request` (the module attribute), which only reaches code that looks the function up via the
    module reference at call time, not a name bound once at import time. `Exchange._signed` now
    does `import services.binance_testnet as _binance_testnet` + calls `_binance_testnet.send_
    signed_request(...)`, matching the convention every other call site (all local, function-scoped
    imports) already used by construction. `test_exchange.py`'s own monkeypatch target was updated
    to match (`services.binance_testnet`, not `core.exchange`) — proven correct by every one of the
    ~20 pre-existing `Reconciler`/`OrderRouter`/reconcile-behavior tests passing UNCHANGED (they
    still patch `services.binance_testnet.send_signed_request` exactly as before) once those modules
    started routing through `Exchange` instances.
  - **The 3 previously-deferred wrapper-routed sites are now closed out (2026-07-20, same
    session).** `compute_var_cvar`/`clamp_leverage` already accepted a `mode: str = "testnet"`
    param (shared with `routers/risk.py`'s non-session-scoped dashboard endpoint, which has no
    `Exchange` to inject) — rather than changing those wrapper functions' own signatures, all 3
    `live_bot_manager.py` call sites (`execute_entry`'s pre-trade VaR/CVaR gate, the periodic
    VaR/CVaR check, and `_run_symbol_loop`'s leverage-bracket probe) now pass
    `mode=session["exchange"].mode if session.get("exchange") else "testnet"` instead of the
    literal `mode="testnet"` — config-selected without touching the shared wrapper's contract.
    `services/portfolio_risk.py:126`'s own `send_signed_request` call is reached exclusively
    through `compute_var_cvar`'s `mode` param, so it's covered transitively, not a separate site.
    pytest 647/647 unchanged, golden-master byte-identical (`before_var_cvar_fix.json` vs
    `after_var_cvar_fix.json`).
  - New `engine/tests/test_exchange_migration.py` (7 cases) — `_resolve_exchange`'s default/override
    behavior, `OrderRouter.place_market_order` actually threading a mainnet `Exchange`'s mode through
    (not just defaulting), `UserDataStreamManager` defaulting to testnet and honoring an injected
    `Exchange` for both the listen-key calls AND the WS URL, and `start_session` putting a
    `BinanceFuturesTestnet` instance on every session. Deliberately not a re-test of reconcile/
    order-placement/user-data-stream BEHAVIOR — the ~20 pre-existing test files already cover that
    end-to-end, unchanged, through the same code now reached via `Exchange`.
  - Verified: engine pytest 647/647 (640 + 7 new, zero regressions — one pre-existing test,
    `test_uds_listen_key_expired_reconnect.py`, imported the now-removed `_BINANCE_FUTURES_WS`
    constant directly and was updated to build the same URL via `BinanceFuturesTestnet().
    user_data_ws_base`). Golden-master byte-identical (`before_exchange_migration.json` vs
    `after_exchange_migration.json` — expected, since this is still always testnet in practice, just
    config-selected in principle now). Running dev container's `/health` confirmed 200 and every
    touched module (`live_bot_manager`/`reconciler`/`order_router`/`exchange`/`user_data_stream`)
    imports cleanly.

### Step 6.3 — Typed strategy↔engine contract (issue ENG-6)
- Replace the mutable-attribute protocol (`strategy.buy = (qty, price)`, tuple `stop_loss`,
  `qty_to_adjust`, `_pending_flip`, etc.) with an explicit `OrderIntent` / `Signal` object the
  strategy returns and the kernel consumes. Kill the temporal coupling where who-clears-what
  ordering is spread across kernel/adapter/manager.
- Golden-master is the guard here — the five-model pipeline output must not change. Run
  before/after; this is exactly the >3-file pipeline refactor Rule C exists for.
- Acceptance check: golden-master byte-identical; a typo'd field is now a type error, not a
  silent no-op.
- **Investigated 2026-07-20, deliberately NOT implemented — real scope is larger than the plan
  text implies, and touches the governed `BaseStrategy` contract.** The typed value-object side
  ALREADY EXISTS and is not this step's real gap: `engine/core/models/base.py` defines the full
  `Signal → RiskConstraints → CostEstimate → TargetPortfolio → OrderPlan` pipeline (all
  `@dataclass`, typed, a typo'd field is already a type error there), and `pipeline.py`'s
  `evaluate()` already threads a strategy's `forecast() -> Signal` through Risk → Cost → Portfolio
  → `ExecutionModel.route()`, which returns a typed `OrderPlan`. So "an explicit OrderIntent/Signal
  object the strategy returns" is already true and has been for a while (Narang Five-Model
  Architecture, `engine/CLAUDE.md`'s own documented contract) — that part of the acceptance text
  is already satisfied.
  - **The real remaining gap is `DefaultExecution.route()`'s side-channel**: per its own docstring
    ("sole place that assigns `s.buy`, `s.sell`, `s.stop_loss`, `s.take_profit`,
    `s._pending_flip`, or `s._close_at_open`"), `route()` writes the SAME order intent it also
    returns as a typed `OrderPlan` — but ONLY for the flat→enter path (Path 3); for maintain/flip/
    close (Paths 2/4/5) it writes the mutable attributes and returns `None`, no `OrderPlan` at
    all. `kernel.py`'s `evaluate_and_route()` and `execute_pending()` then read a MIX of `plan.*`
    (entry direction/qty) and `strategy.*` mutable attributes (`has_pending_flip`,
    `_pending_flip`, `_close_at_open`, `qty_to_adjust`) for the exact same event — this mixed
    read pattern, not a missing type, is the actual "temporal coupling ... spread across
    kernel/adapter/manager" the acceptance text names. Confirmed by grep: `_pending_flip` (73
    occurrences/48 files), `_close_at_open` (51/32), `s.stop_loss`/`s.take_profit` (31+30
    occurrences across 18/16 files respectively) — an order of magnitude larger surface than any
    extraction shipped this session (OrderRouter/Exchange-migration/kernel-`is_live` each touched
    single-digit-to-low-double-digit call sites).
  - **Also found: kernel.py itself already violates `route()`'s own "sole writer" docstring** —
    inside `evaluate_and_route()`'s exec_algo branch (`core/kernel.py` lines ~496-499), the kernel
    writes `strategy.stop_loss`/`strategy.take_profit` directly from the (possibly-sliced)
    `OrderPlan`, when `self.exec_algo is not None`. So the mutable-attribute protocol isn't
    cleanly confined to one owner today even before touching anything — a genuine pre-existing
    violation of the model's own contract, worth its own fixes-queue item independent of this step.
  - **Why this needs a `DECISIONS.md` sign-off before implementation, not just careful execution**:
    `self.buy`/`self.sell`/`self.stop_loss`/`self.take_profit` are declared in
    `BaseStrategy.__init__` (`core/strategy.py` lines 63-66) and documented in `engine/CLAUDE.md`'s
    "Available properties inside any strategy" section as strategy-facing — root `CLAUDE.md`
    explicitly gates changing this interface behind a DECISIONS.md entry. A real fix here means
    deciding whether `kernel.py`/`LiveAdapter` stop READING these mutable attributes (keeping them
    as `ExecutionModel.route()`'s internal write-only scratch state, with the kernel/adapter
    consuming `OrderPlan` exclusively instead) — a decision that reaches into `BaseStrategy`'s
    documented public surface and every one of the 5 seeded strategies, on the live-trading path,
    with the same "zero golden-master coverage on the live side" gap every live-file change this
    session has had to navigate carefully. This is a call for the user to make explicitly, not one
    a background pass should commit to unilaterally.
- **Target design authorized 2026-07-20 (DECISIONS.md #28) — implementation deliberately still
  phased, not shipped this session.** User explicitly approved the interface-touching direction via
  sign-off. Re-investigated with that authorization in hand and found the honest scope is BIGGER
  than the first pass identified, not smaller — see DECISIONS.md #28 for the full writeup. Two new
  findings that changed the plan:
  1. **`LiveAdapter.execute_entry` (`core/live_bot_manager.py`) reads `strategy.stop_loss`/
     `strategy.take_profit` directly as its ONLY channel for SL/TP on the live path** — it never
     receives an `OrderPlan`. Closing the typed-contract gap for entries means `LiveAdapter`/
     `OrderRouter` (Step 6.1) also need an explicit SL/TP parameter path, not just a kernel-side
     change — live order placement, zero golden-master coverage.
  2. **The "small, independently-fixable" exec_algo `kernel.py` contract violation flagged by the
     first pass turns out not to be independently fixable** — `kernel.py` writes
     `strategy.stop_loss`/`strategy.take_profit` directly from a sliced `OrderPlan` specifically
     BECAUSE that's the same channel `LiveAdapter` reads from (finding 1). Removing the kernel's
     write without also giving `LiveAdapter` an explicit parameter would silently break live SL/TP
     placement for exec_algo-sliced entries. Filed as **F10** in `0_fixes-queue.md`, explicitly
     marked "not a quick fix" rather than attempted in isolation.
  3. Making `route()` return a typed, non-`None` `OrderPlan` for every path (the natural way to
     close the gap) requires updating `kernel.py`'s two `if plan is not None:` gates to check
     `plan.intent == "enter"` explicitly, AND auditing that `exec_algo.process_order_plan()`/
     `.step()` — built and tested only for slicing entries — never receives a close/flip/maintain
     plan by accident. Small in file-count (2 files) but sits directly upstream of every order the
     pipeline places, live and backtest.
  - **No code changed this pass either** — writing the DECISIONS.md entry (the design
    authorization) IS this session's real deliverable for 6.3, not a stand-in for implementation.
    The phased plan for whoever implements next: (a) `route()` returns a complete `OrderPlan` for
    all 5 paths + `kernel.py`'s 2 gate sites updated + exec_algo audit, verified in isolation with
    full golden-master/pytest before touching anything live-side; (b) `LiveAdapter`/`OrderRouter`
    gain explicit SL/TP parameters sourced from `OrderPlan`, verified against all 19+ existing
    `LiveAdapter` tests; (c) only then does F10's kernel-write become removable; (d) the wider
    mutable-attribute-read cleanup across the ~48-file surface the first pass sized. Each phase
    independently golden-master-verified — do not attempt (a)+(b)+(c) as one change.

### Step 6.4 — Fix the adapter leak (issue ENG-5)
- `LiveAdapter` no longer reaches into `manager.sessions` / `_order_semaphores` / `_notify_node`
  — dependencies are injected. `ExecutionKernel` stops branching on `is_live`: live vs backtest
  differences live entirely behind the adapter/exchange interfaces (restores the polymorphism
  the adapter was supposed to provide). Kernel stops touching strategy privates directly.
- Acceptance check: no `is_live` branch remains in the kernel's core paths; golden-master identical.
- **Partially shipped 2026-07-20 — the `LiveAdapter` half only, deliberately scoped narrow.**
  `LiveAdapter.__init__` now resolves `self._registry`/`self._notifier`/`self._reconciler` from
  `manager` ONCE, and every method body was rewritten to reference those directly — the
  33-occurrence `self.manager.sessions`/`self.manager._order_semaphores`/`self.manager._notifier`/
  `self.manager._cancel_symbol_algo_orders`/`self.manager._compute_session_equity_and_margin`/
  `self.manager._compute_open_risk_breakdown` chain pattern is gone. **Deliberately did NOT change
  the constructor signature** (still `LiveAdapter(manager, session_id)`, not
  `LiveAdapter(registry, notifier, reconciler, session_id)`) — this file has zero golden-master
  coverage (live-only, no backtest import overlap, confirmed by Plan 5.3's own note), and 19
  existing tests construct `LiveAdapter(mgr, sid)` directly; a signature change is a real, separate,
  larger-blast-radius move left for later rather than bundled in here. **Real gap this fix
  surfaced**: `test_execute_entry_bracket_safety.py` had a class-level `monkeypatch.setattr(
  LiveBotManager, "_cancel_symbol_algo_orders", ...)` that silently stopped intercepting anything
  once `LiveAdapter` started calling `self._reconciler.cancel_symbol_algo_orders(...)` directly
  instead of going through the manager wrapper — caught by running the full suite (not just
  assuming green), fixed by patching `Reconciler` instead. New `engine/tests/
  test_live_adapter_dependency_wiring.py` (2 cases) proves the resolved collaborators are the
  SAME instances as the manager's own, and that patching the manager-level wrapper no longer
  intercepts adapter calls (the exact class of bug the bracket-safety test hit). **NOT done, and
  a real separate piece of work**: the kernel's `is_live` branching (7 sites in `core/kernel.py`,
  shared by BOTH backtest — golden-master-protected — and live — not protected) is completely
  untouched. That's a materially different, higher-risk, cross-cutting change (touches the shared
  pipeline both paths run through) that deserves its own dedicated design pass with golden-master
  verification at every intermediate step, not something to bundle into a same-session adapter
  cleanup. Verified: engine pytest 595/595 (593 + 2 new), golden-master byte-identical
  (`before_plan6.json` vs `after_plan6_4a.json`, 5/5 strategies) — confirms this is genuinely
  behavior-preserving even though it touches a live-only file with no automatic backtest-path
  safety net.
- **Kernel `is_live` parameter-threading killed, 2026-07-20 — a deliberately narrower slice than
  a full timing-model unification.** `ExecutionAdapter` (`core/kernel.py`) gained an abstract
  `is_live: bool` property; `check_exits()`/`evaluate_and_route()` no longer take `is_live` as a
  parameter at all — the kernel reads `self.adapter.is_live` once at the top of each method
  instead. `LiveAdapter.is_live` returns `True`, `BacktestAdapter.is_live` returns `False`. This
  kills the actual risk the acceptance check's spirit is aimed at: a caller could previously pass
  the WRONG `is_live` value for the adapter it was driving (nothing enforced that
  `is_live=True` was only ever paired with a `LiveAdapter`) — now that class of bug is
  structurally impossible, since the kernel derives the answer from the adapter instance itself
  rather than trusting a re-stated boolean at every call site (backtest_runner.py had 4 call
  sites doing this, live_bot_manager.py had 2, ~9 across 5 test files).
  **What did NOT change, deliberately**: the actual "is_live" CHECKS inside `check_exits`/
  `evaluate_and_route` bodies (lines ~301/328/368/405/520 — entry-candle-exit skip, simulated
  liquidation, gap-through-stop pricing, and the big immediate-execute-vs-defer-to-
  `execute_pending()` branch) still exist as `if is_live:`/`if not is_live:` checks — just now
  fed from `self.adapter.is_live` (captured once into a local `is_live` var per method) instead
  of a parameter. A genuinely deeper redesign — the kernel calling ONE polymorphic method and
  each adapter owning its own timing model — was considered and explicitly NOT attempted: it
  would require `BacktestAdapter` to somehow own "defer this fill to the next candle," but
  backtest's deferral today is not adapter machinery at all — it's `strategy.buy`/`sell`/
  `_pending_flip`/`_close_at_open`/`qty_to_adjust` attributes that `evaluate()`'s pipeline sets
  and that `execute_pending()` (a THIRD kernel method, called by the runner loop on the NEXT
  candle, only for backtest — live never calls it) reads and clears. Verified via
  `backtest_runner.py`'s runner loop (both the single-symbol and portfolio call sites) that
  `execute_pending → check_exits → evaluate_and_route` runs in that exact order every candle,
  and that live's own call site never calls `execute_pending` at all — moving that orchestration
  into the adapters would mean giving `BacktestAdapter` authority over candle-loop advancement it
  doesn't have today, a materially bigger structural change than a single session should
  responsibly attempt on the golden-master-protected path without its own dedicated design pass.
  This session's change is a pure, mechanical substitution (parameter → adapter-property lookup,
  same value, same order of operations, zero timing change) — the safe subset of Step 6.4's
  acceptance check, not the full "no is_live branch remains anywhere" reading of it.
  **Verified:** engine pytest 647/647 unchanged (zero new tests needed — this is a refactor of
  HOW the kernel learns `is_live`, not a behavior change; existing tests' adapter subclasses were
  updated to implement the new `is_live` property and their call sites stopped passing
  `is_live=`). Golden-master byte-identical (`before_kernel_is_live.json` vs
  `after_kernel_is_live.json`, 5/5 strategies) — the one Plan 6 change this session that actually
  touches the golden-master-protected path. Container `/health` 200, `core.kernel`/
  `core.live_bot_manager`/`services.backtest_runner` all import cleanly.
  **Files changed:** `engine/core/kernel.py` (`is_live` abstract property, signature changes on
  both methods), `engine/core/live_bot_manager.py` (`LiveAdapter.is_live` property, 2 call sites
  no longer pass `is_live=`), `engine/services/backtest_runner.py` (`BacktestAdapter.is_live`
  property, 4 call sites no longer pass `is_live=`); `engine/tests/test_entry_candle_exits.py`,
  `test_armed_legs_wick_check_skip.py`, `test_intrabar_detail_resolution.py`,
  `test_exec_algo_slicing.py` (adapter subclasses gained `is_live`, call sites updated).
  **Real remaining scope**: the full timing-model unification described above, if ever pursued,
  needs its own dedicated design pass — not scoped here.

### Step 6.5 — Reliable Node notification transport (issue ENG-16)
- Replace per-event `httpx.AsyncClient()` construction + fire-and-forget PATCH with a pooled
  client and a durable, ordered channel. Since the event log (Plan 5.1) is now the source of
  truth with sequence numbers, the notifier ships **sequenced** events (Redis stream/queue —
  Redis is already in the stack) so Node applies them in order with at-least-once delivery and
  dedupe, instead of last-write-wins `findByIdAndUpdate`.
- Acceptance check: out-of-order/duplicate deliveries do not corrupt the Node projection.
- **Pooled-client half shipped 2026-07-20.** `NodeNotifier` (`engine/core/node_notifier.py`)
  no longer builds a fresh `httpx.AsyncClient()` — with its own TCP+TLS handshake — on every
  single `notify()`/`call_internal()` call, which fires on essentially every candle-loop tick
  across every open symbol. New lazy module-level singleton (`get_client()`/`close_client()`),
  mirroring the identical pattern `services/binance_testnet.py` already uses for its own
  outbound client (found by checking `main.py`'s existing shutdown lifespan for a convention
  to follow rather than inventing a new one). `close_client()` wired into `main.py`'s lifespan
  shutdown alongside `close_mongo()`/`close_pool()`/`binance_testnet.close_client()`. Per-call
  `timeout=` now passed explicitly per request (5.0 for `notify`, 45.0 for `call_internal`) since
  the pooled client itself has no fixed default. 3 new tests in `test_node_notifier.py` (singleton
  identity, close-then-rebuild, close-when-never-created no-ops) plus the 4 existing tests updated
  for the new mock target (`get_client()` instead of `httpx.AsyncClient`). Verified: engine pytest
  598/598, golden-master byte-identical (`before_plan6.json` vs `after_plan6_5a.json`), and the
  running dev container's `/health` endpoint + an active live session's real position-check traffic
  both confirmed healthy after the change (checked container logs directly, not just pytest — this
  touches `main.py`'s startup/shutdown path, which no test suite exercises end-to-end). **Still
  NOT done, and a materially different, larger piece of work**: the durable, ORDERED, at-least-once
  Redis-stream delivery channel replacing Node's last-write-wins `findByIdAndUpdate` projection.
  That needs new consumer code on the Node/server side too (not just this engine-side change) —
  left for its own dedicated session per this plan's own Rule D (planning tasks produce docs, not
  half-built cross-service features).

### Step 6.6 — Proper packaging (issue ENG-12)
- Remove the `/engine→/app` symlink and `sys.path.insert(0,'/')` from `main.py`. Establish one
  canonical import root and delete the dual `try: from engine... except: from core...` dance
  and the inline in-function imports of `send_signed_request`. Make the engine an installable
  package with a single, unambiguous module identity (kills duplicate-module `isinstance`/
  singleton bugs).
- Acceptance check: `pytest` and the app run with no path hacks; a module is importable under
  exactly one name.
- **SHIPPED IN FULL 2026-07-20, verified via a real image rebuild + container restart** (user
  explicitly authorized the rebuild via AskUserQuestion, after a prior same-session investigation
  correctly stopped short of implementing without that sign-off — see that investigation's
  reasoning preserved below, since it's what determined the fix couldn't just rewrite `engine.xxx`
  sites to `core.xxx`). **Design ended up different from the originally-proposed `pyproject.toml`/
  `pip install -e .` shape** — no packaging change was actually needed. New `engine/core/
  engine_alias.py` (`install_engine_alias()`) registers a `sys.meta_path` finder/loader that
  intercepts any `engine`/`engine.X` import and reassigns `sys.modules['engine.X']` to the
  ALREADY-CANONICAL `X` module (`core.X`/`services.X`/etc) — genuine single module identity
  (`engine.core.margin is core.margin` is now `True`; confirmed `False` before the fix, the exact
  duplicate-module bug ENG-12 exists to kill) with zero duplicate state, no symlink, no `sys.path`
  mutation. `engine.xxx` still resolves for strategy authors (the documented, must-preserve
  convention identified below) — it simply is no longer a second, independently-loaded module
  object for the same source file. Installed at every real process entry point that might
  dynamically load a strategy file: `main.py` (replacing its symlink+`sys.path.insert(0,'/')`
  hack), and — found via a fresh grep, not assumed — 4 MORE standalone scripts each had their own
  independent copy of the identical hack (`scripts/golden_master.py`, `scripts/recursive.py`,
  `scripts/lookahead_sentinel.py`, `scripts/_portfolio_check.py`), plus a new `engine/tests/
  conftest.py` so the pytest process gets it too (pytest never runs `main.py`). Also deleted the
  now-genuinely-redundant dual `try: from engine.X import ... except ImportError: from core.X
  import ...` dance across all 16 internal files that had it (`core/kernel.py`, `core/live_bot_
  manager.py`, `core/models/{cost,execution,exec_algo,risk}.py`, `core/pipeline.py`, `core/
  strategy.py`, `services/backtest_runner.py`, all 5 `strategies/*/__init__.py` — internal code
  now uses the canonical bare `core.X`/`services.X`/`utils.X` form uniformly; the 5 strategy files
  keep `engine.X` as their primary import, matching the documented author convention, just without
  the now-unnecessary fallback) plus 4 test files' own inline hack copies (made redundant by the
  new `conftest.py`) — closing out this step's full stated scope (path hacks AND the dual-import
  dance), not just the packaging-identity half. The two remaining `except ImportError` sites in
  the whole codebase (`indicators/adapters/talib_adapter.py`, `indicators/config.py`) are genuine
  optional-dependency fallbacks (TA-Lib / indicator-backend availability), unrelated to this step
  and correctly left untouched. **Verified via a REAL rebuild, not just `docker exec`** (the one
  change this session requiring it): `docker compose build engine` (clean build, only the final
  `COPY . .` layer changed), `docker compose up -d --no-deps engine` (container recreated) —
  confirmed via `docker logs`: full clean boot, exchange rules cached for 729 futures + 3649 spot
  symbols, all 5 strategies seeded successfully (proves the alias resolves in the real live app
  process, not just an ad-hoc check), `/health` → 200 with Mongo/Timescale both connected.
  Post-restart: pytest 647/647, golden-master's `MultiDivergence` summary line byte-identical to
  every prior run this session (`before_packaging_v2.json` itself didn't survive the container
  recreate — ephemeral filesystem, not a bind mount — the deterministic output match across the
  restart is the real proof of correctness). Zero symlink/`sys.path` hack copies remain anywhere
  in the codebase (verified by grep). **Original investigation's reasoning, preserved because it's
  what shaped the fix**: the container's real WORKDIR is `/app`, so bare `core.xxx`/`services.xxx`
  imports were already correct and needed no hack — the symlink/sys.path hack existed ONLY to make
  `engine.xxx` resolve, and `engine.xxx` is not an accident, it's `engine/CLAUDE.md`'s own
  documented public strategy-author convention (`from engine.core.strategy import BaseStrategy`),
  used unconditionally by all 5 seeded strategies, and strategies are user-uploadable at runtime
  (`PUT /strategies/:name/code`) — meaning real stored strategy code outside this repo may already
  depend on `engine.xxx` resolving. That's why the fix could not simply rewrite `engine.xxx` sites
  to `core.xxx`; it had to make `engine.xxx` resolve WITHOUT creating a second module identity —
  exactly what `engine_alias.py`'s `sys.meta_path` hook does.

## Out of scope
- Server/client structure (Plan 7).
- Any behaviour change to the trading logic — this plan is behaviour-preserving (golden-master
  is the contract).

## Acceptance criteria (phase)
- `LiveBotManager` is an orchestrator; its former responsibilities live in tested modules.
- Testnet/mainnet is a config-selected `Exchange` implementation; no `mode="testnet"` literals
  scattered through business logic.
- Strategy↔engine communication is a typed object; golden-master byte-identical across 6.1–6.6.
- Node notification is ordered, pooled, and at-least-once.
- No symlink/`sys.path` import hacks remain.
- CI green.

## Open questions
- Does the typed-contract refactor (6.3) risk golden-master drift the team is unwilling to
  accept? If so, split 6.3 into its own plan and land 6.1/6.2/6.4/6.5/6.6 first.

## Handoff note template
`Next session: [steps done 6.x], [next step], [golden-master result], [files changed]`
