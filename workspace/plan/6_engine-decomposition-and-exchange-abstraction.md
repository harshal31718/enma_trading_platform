# Plan 6 — Engine decomposition & exchange abstraction

**Status:** Ready · **Priority:** P2 · **Depends on:** 5 · **Related:** 7

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
  finishing ENG-7 started in Plan 5.6).
- **MarketDataFeed** — warmup/HTF/live candle sourcing (the three fetchers) behind one
  interface, with a single documented rule for which source (fixes the testnet-exec /
  mainnet-warmup split in ENG-4).
- **OrderRouter** — order placement/close/reduce (already idempotent from Plan 5.3).
- **Reconciler** — the exchange-truth reconciliation (already race-safe from Plan 5.4).
- **NodeNotifier** — the transport (see Step 6.5).
`LiveBotManager` becomes a thin orchestrator wiring these together.
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

### Step 6.5 — Reliable Node notification transport (issue ENG-16)
- Replace per-event `httpx.AsyncClient()` construction + fire-and-forget PATCH with a pooled
  client and a durable, ordered channel. Since the event log (Plan 5.1) is now the source of
  truth with sequence numbers, the notifier ships **sequenced** events (Redis stream/queue —
  Redis is already in the stack) so Node applies them in order with at-least-once delivery and
  dedupe, instead of last-write-wins `findByIdAndUpdate`.
- Acceptance check: out-of-order/duplicate deliveries do not corrupt the Node projection.

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
