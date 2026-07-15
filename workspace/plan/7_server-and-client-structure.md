# Plan 7 — Server & client structure

**Status:** Ready · **Priority:** P2 · **Depends on:** 2, 5 · **Related:** 6

> Source issues: SRV-1, SRV-4, SRV-5, CLI-1, CLI-2, CLI-3. Structural cleanup of Node and
> React. Depends on Plan 2 (tests must exist before you refactor) and Plan 5 (the client and
> Node projections should render the new event/state model, not the old three-way-divergent
> one). Behaviour-preserving where the state model is concerned.

## Goal

Controllers stop being 1,000-line god functions; business logic lives in a testable service
layer. Long engine work is a job, not a 1-hour HTTP hang. Page components stop being
1,700-line, 29-`useState` monsters; realtime market state has a single owner.

## Scope / what changes

### Step 7.1 — Server service layer (issue SRV-1)
- Extract business logic out of `algo.controller.js` (1,072 lines) and `trade.controller.js`
  (730) into service modules (`services/algoSessionService`, `services/tradeService`, …).
  Controllers become thin: parse/validate request → call service → format response.
- De-duplicate the session-start vs chaos-start credential/config assembly (they duplicate
  ~150 lines) into one shared builder.
- With logic in services, unit tests (Plan 2 harness) can cover money paths without HTTP.
- Acceptance check: controllers contain no Binance/Mongo/Socket logic; services are unit-tested.

### Step 7.2 — Jobs, not hour-long HTTP (issue SRV-5)
- Replace the global `timeout: 60*60*1000` on `engineClient` with a sane default. Long
  operations (candle imports, big backtests) run through BullMQ (already a dependency) as jobs
  with progress polling / socket updates, not a synchronous request held open for an hour.
- Acceptance check: no engine call inherits a 1-hour budget; long tasks are jobs with a
  queryable status.

### Step 7.3 — Auth robustness (issue SRV-4)
- `verifyJWT` must distinguish infra failure (DB down → 503) from auth failure (bad token →
  401) instead of catch-all 401. Add a short-TTL cache for the per-request `User.findById`
  lookup. Remove bare `catch {}` swallowing (e.g. the `$push` log `.catch(()=>{})`), replacing
  with logged handling.
- Acceptance check: a simulated Mongo outage yields 503, not 401; user lookups are cached.

### Step 7.4 — Decompose god components (issue CLI-1)
- Break `Trade.jsx` (1,760 lines / 29 `useState`), `Backtest.jsx`, `Settings.jsx`,
  `ChaosWizard.jsx` into container/presenter splits: data hooks + focused presentational
  components. Target no component owning more than a handful of concerns.
- Lean on the Plan 2.2 render smoke tests as the net; add interaction tests for the highest-
  risk widget (order entry).
- Acceptance check: no page component exceeds an agreed line/`useState` budget; tests pass.

### Step 7.5 — Single owner for realtime market state (issue CLI-2, CLI-3)
- Today three channels (Socket.IO to Node, direct Binance WS, TanStack Query polling) can
  disagree about the same symbol's price. Establish one source of truth per data kind:
  exchange-truth position/PnL from Node's event-sourced socket (Plan 5), market price from a
  single chosen feed. Collapse the 15 per-domain hooks onto a shared query/socket factory to
  kill duplicated loading/error/toast logic (`useTrade` at 347 lines is business logic in a
  hook — move it to a service/store).
- Remove committed build output (`client/dist/`) from the working tree / sync set.
- Acceptance check: a symbol's displayed price/PnL has one documented source; no `dist/` in the
  tree; hooks share a factory.

## Out of scope
- Engine internals (Plans 5, 6).
- The state/event model itself (Plan 5) — this plan *renders* it, doesn't define it.

## Acceptance criteria (phase)
- Controllers are thin; a tested service layer owns business logic.
- No hour-long synchronous engine calls; long work is jobbed.
- `verifyJWT` separates 503 from 401 and caches lookups; no silent `catch {}`.
- Page components are within budget and have tests.
- One documented source per realtime data kind; `dist/` not tracked/synced.
- CI green.

## Open questions
- State container for the client: keep Zustand + TanStack Query (per CLAUDE.md Rule 7, no
  Redux) and add a thin market-state store, or push everything through TanStack Query? Confirm
  the split.

## Handoff note template
`Next session: [steps done 7.x], [next step], [files changed], [open questions]`
