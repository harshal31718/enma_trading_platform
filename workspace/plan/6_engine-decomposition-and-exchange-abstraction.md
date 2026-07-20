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
- **OrderRouter** — order placement/close/reduce (already idempotent from Plan 5.3). **Not
  started — real scoping note (2026-07-20), materially different from the other four.** This maps
  to `LiveAdapter.execute_entry`/`execute_reduce`/`execute_exit`/`execute_flip` (~1,260 lines
  combined, `execute_entry` alone ~900). Unlike MarketDataFeed/NodeNotifier/SessionRegistry/
  Reconciler, these methods deeply interleave three concerns that don't cleanly separate: (1) raw
  Binance order placement (the actual "router" part), (2) risk/governor/portfolio decision logic
  (VaR/CVaR, correlation cap, liq-buffer, protections), and (3) `LiveAdapter`'s job as the
  `ExecutionKernel`'s polymorphic `ExecutionAdapter` — which Step 6.4 explicitly owns fixing (kill
  `is_live` branching, stop the adapter reaching into `manager` internals). Extracting a clean
  "OrderRouter" here without also doing 6.4's redesign risks either an incomplete split (leaving
  the leaky parts behind) or scope creep into 6.4's own work. Recommendation for whoever picks
  this up: treat OrderRouter and Step 6.4 as one combined design pass, not two independent
  mechanical moves like the four already shipped.
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
`LiveBotManager` becomes a thin orchestrator wiring these together. Line count so far:
3830 → 2783 (MarketDataFeed + NodeNotifier + SessionRegistry + Reconciler; only OrderRouter
remains — the biggest single drop was Reconciler's 943-line cluster moving out in one piece,
leaving only ~30-line delegating wrappers behind).
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
  WS reconnect every ~60 min instead of ever actually renewing the key. **Real scope still open,
  and the larger/riskier half of this step**: migrating the ~24 existing call sites in
  `live_bot_manager.py`/`reconciler.py`/`user_data_stream.py` to actually USE this abstraction
  instead of calling `send_signed_request(..., mode="testnet")` directly, and wiring a per-session
  `Exchange` selection from config. That's live-trading-critical code with zero golden-master
  coverage — a deliberate, separate, later pass, not squeezed into the same session that designed
  the interface. Verified: engine pytest 619/619 (600 + 19 new), golden-master byte-identical
  (`before_plan6.json` vs `after_plan6_2a.json` — expected, since nothing calls this module yet),
  running dev container's `/health` confirmed still 200 after the change.

### Step 6.3 — Typed strategy↔engine contract (issue ENG-6)
- Replace the mutable-attribute protocol (`strategy.buy = (qty, price)`, tuple `stop_loss`,
  `qty_to_adjust`, `_pending_flip`, etc.) with an explicit `OrderIntent` / `Signal` object the
  strategy returns and the kernel consumes. Kill the temporal coupling where who-clears-what
  ordering is spread across kernel/adapter/manager.
- Golden-master is the guard here — the five-model pipeline output must not change. Run
  before/after; this is exactly the >3-file pipeline refactor Rule C exists for.
- Acceptance check: golden-master byte-identical; a typo'd field is now a type error, not a
  silent no-op.

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
