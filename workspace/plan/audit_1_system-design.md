# Project Issues Audit — 2026-07-14

**Shelf:** audit (evidence) · **Formerly:** `issues.md` (renamed 2026-07-14; issue IDs unchanged)

Scope: system design, SOLID principles, CS fundamentals. Issues only — no solutions.
Confidence: [Certain] verified in code · [Likely] strong inference. Severity: H / M / L.

---

## 1. Security / Config / Infrastructure

**SEC-1 (H) [Certain] — `/internal/*` routes are completely unauthenticated.**
`server/src/app.js` mounts `internalRoutes` before the `verifyJWT` gate with no API key, no IP allowlist, no shared secret. These endpoints update session stats (`PATCH /internal/algo/sessions/:id/stats`), place orders, close positions, and set leverage — the order endpoints decrypt the owning user's Binance credentials server-side (`algo.controller.js:967-989`). In dev compose, port 5000 is published to the host, so anything on the host/LAN can drive them. In prod it binds 127.0.0.1, but any process or container on the box can still call them. Meanwhile the engine's own API *is* key-protected (`X-API-Key`) — the trust is asymmetric in the wrong direction.

**SEC-2 (H) [Certain] — Strategy code editing = arbitrary remote code execution for any authenticated user.**
`PUT /api/v1/strategies/:id/code` (Node) is behind `verifyJWT` only — login is open to anyone with a Google account, and strategies are global/shared (no `userId`). It proxies to engine `PUT /strategies/{name}/code`, which writes arbitrary Python to disk and `importlib.reload()`s it into the live engine process — the same process that holds every user's decrypted Binance API keys in memory and executes trades. `ast.parse` + top-level-class-name checks validate syntax, not safety. Additionally, `importlib.reload` does not swap classes on already-instantiated strategy objects, so running sessions keep executing stale code while new sessions get the new code (version skew).

**SEC-3 (H) [Certain] — Encryption silently falls back to a hardcoded dev key.**
`server/src/utils/encryption.js`: if `ENCRYPTION_KEY` is missing or not exactly 32 utf8 bytes, the key silently becomes `scryptSync('dev-secret-key-salt-placeholder', 'dev-salt', 32)` — a publicly known value in the repo. User Binance secrets would be encrypted with it with no error, no log. Fail-open on a secrets primitive. Also: `decrypt()` returns the *input unmodified* on any failure, which (a) silently tolerates plaintext-stored keys, (b) masks corruption, (c) can forward ciphertext downstream as if it were a credential.

**SEC-4 (M) [Certain] — One shared `.env` injected into every container, including the client.**
`docker-compose.yml` gives client, server, and engine the same `env_file: ./.env` — so the Vite dev container's environment holds `JWT_SECRET`, `ENCRYPTION_KEY`, `GOOGLE_CLIENT_SECRET`, DB URIs. Violates least privilege; one compromised container leaks everything. (Directly relevant to the planned migration of personal tokens out of `.env` and into per-user settings — see SEC-9.)

**SEC-5 (M) [Certain] — Effectively no rate limiting; open registration amplifies it.**
`apiLimiter` is 10,000 requests / 15 min per IP (~11 rps sustained). Combined with SEC-2 (any Google account can log in), abuse cost is near zero. Auth endpoints have no separate, stricter limiter.

**SEC-6 (M) [Certain] — User Binance API secret transmitted in a custom HTTP header.**
`algo.controller.js` sends `X-Binance-API-Secret: <plaintext>` over plain HTTP on the Docker network. Headers are routinely captured by proxies/logging middleware; secrets-in-headers is a leak-prone transport.

**SEC-7 (L) [Certain] — Unpinned/loose infra versions and dev DB credentials.**
`timescale/timescaledb:latest-pg16` ("latest" tag) in both dev and prod compose; Redis runs with no auth in both; dev Postgres password `enma_dev_password` with 5432/6379 published to host in dev.

**SEC-8 (L) [Certain] — API-key comparison is not constant-time; `/health` spawns a new Redis connection per request.**
Engine `require_api_key` uses `!=` (timing side-channel, low practical risk). Node health check creates and connects a fresh ioredis client on every call — an unauthenticated resource-churn endpoint.

**SEC-9 (M) [Certain] — Residual env-level personal credentials (migration hit-list for the ".env → user settings" plan).**
Per-user encrypted keys in `Settings` already exist and session flows pass them explicitly — good. Still env/file-based: `BINANCE_API_KEY` / `BINANCE_SECRET` in `.env.example` (dead or fallback config — ambiguous contract), `keys/binance_testnet.env` on disk, `ADMIN_EMAIL` bootstrap in env, and `ENGINE_API_KEY` shared static secret with no rotation story. `ENCRYPTION_KEY` itself is a single static key — no key-versioning field on encrypted records, so rotation would break all stored secrets silently (SEC-3 makes this worse).

**SEC-10 (M) [Likely] — No request-body validation layer on the Node API.**
No zod/joi/celebrate anywhere in `server/src`; controllers destructure `req.body` directly. `handleEngineStats` persists unvalidated body content into Mongo, including `positionDetails` keys interpolated into `$set` dotted paths (`positionDetails.${eventData.symbol}`) — attacker-influenced field paths (contained under `positionDetails`, but the pattern is unsafe).

---

## 2. Engine (Python / FastAPI)

**ENG-1 (H) [Certain] — `LiveBotManager` is a god class (2,002 lines).**
It owns session lifecycle, per-symbol WebSocket loops, warmup candle fetching from three different sources (TimescaleDB, mainnet REST, HTF REST), exchange reconciliation, order placement, emergency exits, PnL accounting, trade recording, Node notification transport, and stats pushing. SRP is gone; every live-trading change funnels through this file. `_run_symbol_loop` alone is ~400 lines with nested closures.

**ENG-2 (H) [Certain] — Exit/emergency paths record fabricated fills and diverge local state from the exchange.**
Three distinct accounting integrity problems: (a) `execute_exit` sends the close order in a try/except, logs failure, then *unconditionally* proceeds to close the local position, credit PnL, and record the trade — exchange may still hold the position while the engine reports it closed; (b) trade records use the SL/TP *trigger* price or `strategy.price` (last candle close, in `_close_position_on_stop`) as exit price instead of the actual `avgPrice` fill; (c) the emergency-exit record in `execute_entry` books entry price == exit price even though the real market close filled elsewhere. Recorded PnL is systematically not exchange PnL.

**ENG-3 (H) [Certain] — Race between fill-callback reconciliation and the candle-loop, with no per-symbol lock.**
`_on_fill` (user-data-stream) and the candle loop both call `_reconcile_exchange_state` and mutate the same session dict / strategy object. Every path is full of `await`s (REST calls) between check and act — e.g. both can observe "local position, exchange flat" and both run the close-local-and-record-trade branch, double-counting PnL and duplicating trade records. Session state (`session["pnl"]`, `open_positions`) has no synchronization discipline.

**ENG-4 (M) [Certain] — "Live" manager is hardwired to testnet.**
`mode="testnet"` is a literal at ~15 call sites, the WS URL is the testnet host, and `binance_testnet.py` is imported inline inside functions throughout. `exchange_name = "Binance Futures"` is a repeated string literal. Going to mainnet means editing dozens of scattered sites — OCP violation on the single axis this system will most certainly need to vary. Meanwhile warmup/HTF candles come from *mainnet* REST while execution and kline WS are testnet — two different market-data universes feeding one strategy.

**ENG-5 (M) [Certain] — Adapter abstraction is leaky and circular.**
`LiveAdapter` holds a back-reference to the manager and reaches into its privates (`manager.sessions`, `manager._order_semaphores`, `manager._notify_node`) — adapter and manager are one object split in two. `ExecutionKernel` still branches on `is_live` throughout `check_exits`/`evaluate_and_route`, so the polymorphism the adapter exists to provide is bypassed by flags anyway (LSP/OCP). The kernel also reads/writes strategy *private* fields (`_pending_flip`, `_close_at_open`).

**ENG-6 (M) [Certain] — Strategy ↔ engine contract is an implicit mutable-attribute protocol.**
Signals travel as attribute pokes on the strategy object: `strategy.buy = (qty, price)`, `stop_loss = (qty, price)` tuples, `qty_to_adjust`, `adjust_tag`, engine-injected flags (`is_livetrading`, `balance`, `leverage`, ~20 more in `BaseStrategy.__init__`). Primitive obsession + temporal coupling (the order of who clears `buy/sell/_pending_flip` matters and is spread across kernel, adapter, and manager). No typed Order/Signal object crosses the boundary; a typo'd attribute fails silently.

**ENG-7 (M) [Certain] — Session state is an untyped dict; runtime state is memory-only.**
`self.sessions[session_id]` is a raw dict with ~16 magic string keys, mutated from five+ places. No dataclass, no schema. Engine restart loses all live session state (a startup reconciliation hook exists on Node, but the engine-side design is still "hope the dict survives").

**ENG-8 (M) [Certain] — Warmup math is self-contradictory.**
`WARMUP_CANDLES = 200` fetched, but `_get_min_candles_required` = largest numeric param × 3 (docstring says 2x — comment/code drift). A param of 100 needs 300 candles → warmup fetch can never satisfy it and the bot silently waits for live candles (on 1h TF that's days). Worse, `_append_candle` caps history at 500, so any param > 166 makes readiness *permanently unreachable*. The heuristic itself ("largest numeric param") conflates unrelated params (e.g. an RSI threshold of 70 would demand 210 candles).

**ENG-9 (M) [Certain] — Reconciliation is O(symbols) signed REST spam outside any rate limiter.**
`_reconcile_exchange_state` fires 2–3 signed calls per symbol per candle close plus on every fill event; a 100-symbol Chaos session bursts 200–300 requests at each shared candle boundary. `OrderRateLimiter` only gates entries; exits explicitly log "rate limited, proceeding anyway". Binance API weight limits will be the real ceiling. Also one WS connection per symbol (100+ sockets) instead of combined streams.

**ENG-10 (M) [Certain] — No order idempotency.**
Entry/exit MARKET orders carry no `newClientOrderId`. On an httpx timeout where Binance actually filled, the engine's error path treats it as not-entered (`strategy.buy = None`, return False) with no dedupe key to detect the fill — duplicate or orphan positions on retry/reconcile. (Only SL/TP algo orders get `tpsl_` client IDs.)

**ENG-11 (M) [Certain] — Float arithmetic for money end-to-end.**
Prices, quantities, PnL, balances are Python floats; `decimal` is imported only for rounding *modes*. Accounting accumulates float error (`session["pnl"] += ...`), then values are shipped as `str(round(x, 2))`. Classic CS-fundamentals violation for financial code.

**ENG-12 (M) [Certain] — Packaging is broken and patched with path hacks.**
`main.py` creates an `/engine → /app` symlink and does `sys.path.insert(0, '/')`; nearly every core module has the dual `try: from engine.core... except ImportError: from core...` import dance; imports happen inline inside functions repeatedly (`send_signed_request` imported ~8 times inside methods). No installable package layout; import-root ambiguity is a standing source of duplicate-module bugs (same module can be loaded twice under two names, breaking `isinstance` and module-level singletons).

**ENG-13 (M) [Certain] — 124 broad `except Exception` sites; several swallow silently.**
Includes `except Exception: pass` around `should_cancel_entry()` and `adjust_trade_position()` in the kernel (strategy bugs vanish), and startup that logs-and-continues when Mongo/Timescale are down while `/health` still returns `{"status": "ok"}` — the Docker healthcheck passes with dead dependencies.

**ENG-14 (L) [Certain] — Unvalidated dynamic import from config in the live path.**
`start_session` does `importlib.import_module(f"strategies.{strategy_name}")` with no name validation (the strategies router validates; the live manager doesn't). An unknown-param `ValueError` raised inside `_run_symbol_loop` before the try block kills that symbol's task silently — no Node notification, session still shows running.

**ENG-15 (L) [Certain] — Nonstandard candle column order `[ts, open, close, high, low, volume]`.**
Every fetcher must remap Binance's `[open, high, low, close]`; the kernel indexes candles positionally (`candle[1]`, `candle[2]`...). One remap mistake is silent and catastrophic; there is no named accessor or constant for columns.

**ENG-16 (L) [Certain] — Node notification transport is chatty, unordered, and lossy.**
`_notify_node` opens a new `httpx.AsyncClient` per event (no pooling), fire-and-forgets one HTTP PATCH per log line/position event, and failures are dropped after a warning. Concurrent per-symbol tasks PATCH the same session with last-write-wins (`findByIdAndUpdate`) — status/PnL updates can arrive and apply out of order. No queue, no retry, no sequence numbers, despite Redis already being in the stack.

**ENG-17 (L) [Likely] — Live/backtest duplication.**
Param coercion + risk-param injection in `_run_symbol_loop` "mirrors backtest_runner step 6b" (its own comment) — two hand-synced copies; golden-master exists precisely because this drift keeps happening. `execute_entry`'s DCA branch duplicates most of the normal entry branch.

**ENG-18 (L) [Certain] — Backtest intrabar assumption undocumented at the decision point.**
`check_exits` checks SL before TP when both trigger in the same candle — a pessimism-bias policy choice embedded silently in branch order.

---

## 3. Server (Node / Express)

**SRV-1 (M) [Certain] — Fat controllers, no service layer.**
`algo.controller.js` is 1,072 lines mixing HTTP handling, credential decryption, Binance parameter assembly, session orchestration, Socket.IO emission, and Mongo persistence. Session-start and chaos-start duplicate the credential/config assembly (lines ~31/121 vs ~655/869). `trade.controller.js` (730 lines) same pattern. Routes → controller is the only layering; business logic has no home of its own, so it can't be tested without HTTP.

**SRV-2 (M) [Certain] — Zero tests.**
No test files under `server/` (0) or `client/src` (0); engine has 11 test modules. The service that gates auth, money movement, and credential decryption is the least-tested component in the repo.

**SRV-3 (M) [Certain] — `handleEngineStats` trusts and persists its input wholesale.**
Beyond SEC-1/SEC-10: `pnl` accepted as any stringable value, `openPositions` any shape, `positionDetails` copied field-by-field without validation into the doc the UI treats as "single source of truth". Node-side PnL is whatever the last PATCH said — no reconciliation against engine truth, no monotonic sequencing.

**SRV-4 (L) [Certain] — `verifyJWT` conflates infrastructure failure with auth failure and hits Mongo per request.**
A DB outage surfaces as 401 "Invalid or expired token" (catch-all). Every authenticated request does `User.findById` with no caching. Errors swallowed with bare `catch {}` in several places (`$push` log persistence `.catch(() => {})`).

**SRV-5 (L) [Certain] — 1-hour axios timeout on all engine calls.**
`engineClient` sets `timeout: 60*60*1000` globally because "candle imports can take a long time" — every proxied call inherits a 1h hang budget; long-running work is synchronous HTTP instead of job + poll (BullMQ is already a dependency).

---

## 4. Client (React)

**CLI-1 (M) [Certain] — God components.**
`Trade.jsx` is 1,760 lines with 29 `useState` hooks in one page component; `Backtest.jsx` 765, `Settings.jsx` 749, `ChaosWizard.jsx` 677. State, effects, data fetching, and rendering are interleaved with no container/presenter split; these are effectively untestable (and there are no tests — SRV-2).

**CLI-2 (L) [Certain] — Committed build output locally / duplicated realtime stacks.**
`client/dist/` exists in the working tree (ignored by git, but syncs/copies drag it around). The client maintains three realtime channels — Socket.IO to Node, direct Binance WS (`lib/binanceWS.js`, `useBinanceWS`), and TanStack Query polling — with no single ownership of "current market state"; the same symbol price can come from three sources that disagree.

**CLI-3 (L) [Likely] — Hook-per-domain files hide duplicated fetch/error patterns.**
15 `useX` hooks each re-implement loading/error/toast conventions around axios/query rather than a shared query factory; drift already visible between `useTrade` (347 lines — a hook that size is business logic, not a hook) and smaller hooks.

---

## 5. Cross-Cutting / System Design

**SYS-1 (H) [Certain] — Trust topology is inverted.**
The most dangerous surface (Node `/internal` order/session endpoints, engine strategy-code write) has the weakest protection, while low-risk surfaces (engine read routes) sit behind an API key. There is no service-to-service authentication story: engine→Node is anonymous HTTP, Node→engine is one static shared key that also lives in every container's env (SEC-4).

**SYS-2 (H) [Certain] — Two sources of truth for live trading state, reconciled by heuristics.**
Exchange truth vs engine memory vs Node's Mongo `LiveSession` — three copies. The engine reconciles itself to Binance with estimated exit prices (candle/SL/TP guesses); Node reconciles itself to whatever PATCHes arrive, in arrival order. There is no event log or sequence; recorded trades/PnL are best-effort reconstructions (see ENG-2, ENG-16, SRV-3). For a trading system this is the deepest design issue in the repo.

**SYS-3 (M) [Certain] — Strategies are global mutable shared state, hot-swappable at runtime.**
No `userId` on strategies (by documented design), any user can rewrite them (SEC-2), the prod compose persists `engine/strategies` in a named volume so deployed code diverges from the image, and reloads don't propagate to running sessions. Code-as-data without versioning, review, isolation, or audit trail.

**SYS-4 (M) [Certain] — Documentation/reality drift on core rules.**
CLAUDE.md rule 2 says "Node server only proxies to engine" and forbids direct Binance calls outside the engine — but the engine now bypasses Node deliberately (F-003) *and* Node's internal handlers were built to place orders "credentials held server-side" (comment in `internal.routes.js`), two contradictory generations of architecture coexisting. The dead `BINANCE_API_KEY`/`BINANCE_SECRET` env entries (SEC-9) are the same pattern. Governance docs are extensive, yet the load-bearing invariants they state are already false.

**SYS-5 (M) [Likely] — No CI quality gate.**
No CI config found in the repo root (no .github/, no pipeline files). Tests that exist (engine) run only when someone remembers; golden-master discipline is enforced by convention in CLAUDE.md, not by machinery.

**SYS-6 (L) [Certain] — Observability is print-grade.**
`logging.basicConfig(level=INFO)` + f-string logs in the engine, `morgan('dev')` on the server, no correlation IDs across the client→Node→engine→Binance chain, no metrics, no structured logs. Diagnosing ENG-2/ENG-3 class incidents post-hoc is currently impossible.

**SYS-7 (L) [Certain] — Multi-session/same-account interference is unmodeled.**
Per-user Binance credentials are account-global, but each session (and each per-symbol strategy instance) tracks its own `balance`/margin slice locally. Two sessions on one account share real margin and positions; reconciliation is per-symbol per-session and will fight over the same exchange position (e.g. both sessions trading BTCUSDT).

---

*End of audit. Written incrementally; sections 1–5 complete as of 2026-07-14.*

> **Extension (2026-07-14):** a dedicated quant-core deep-dive (backtest runner, kernel,
> fill/margin models, metrics, optimizer, Monte Carlo, live-loop parity) found 17 additional
> issues — **QNT-1..17**, including two H-severity shipped-behavior bugs (multi-symbol
> backtests never fire SL/TP/liquidation/funding; exec-algo mode silently drops close/flip
> intents). Evidence: [`audit_2_quant-core.md`](audit_2_quant-core.md).
> Remediation: [`9_backtest-and-optimizer-correctness.md`](9_backtest-and-optimizer-correctness.md).
