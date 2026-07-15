# 03 — Gap Analysis & Better-Options Evaluation

**Shelf:** research · **Date:** 2026-07-14 · **Formerly:** `refinements/03_better_options.md` (series mapping in `0_plans.md`)
**Inputs:** `research_1_project-outline.md` (current state) × `research_2_market-survey.md` (industry state).
**Cross-refs:** issue IDs from `workspace/plan/audit_1_system-design.md`; plan numbers from `0_tracker.md`.
**Scoring:** Effort S/M/L/XL · Payoff 1–5 · Maintainability Δ (+ better / − worse long-term).

---

## 0. The framing decision that dominates everything else

**Gap:** Enma applies single-operator patterns (web-editable global strategies, one engine
process holding all users' decrypted keys, shared rate-limit budget) in a **multi-tenant**
deployment. No reference platform does this (02 §10).

**Options:**

| Option | Effort | Payoff | Maint. | Verdict |
|---|---|---|---|---|
| A. Stay multi-tenant, harden everything (sandboxing, per-user budgets, event isolation) | XL | 3 | − | Reject unless multi-tenancy is the product |
| B. **Reframe as "operator + invited guests"**: strategies become operator-owned artifacts (no web editing for non-admins), algo gate stays, per-user keys stay | S–M | 5 | + | **Recommended** — matches actual usage (admin-granted algo access already exists) |
| C. Full single-tenant retreat (per-user deployments) | L | 2 | + | Overkill; loses the shared-platform value |

Option B collapses SEC-2 and most of SYS-3 from "build a sandbox" (research: CPython can't be
language-sandboxed; real isolation = gVisor/Firecracker, XL effort) into a **permissions
decision** — exactly the product decision Plan 3 already flags (§3.2 sign-off). The research
strengthens the case for its "retire/gate UI strategy editing" branch: the sandbox alternative
is an order of magnitude more expensive than the gate.

---

## 1. Evaluation matrix (per component)

### 1.1 Live-trading state integrity (SYS-2, ENG-2/3/10) — the deepest gap

| Option | Effort | Payoff | Maint. | Notes |
|---|---|---|---|---|
| Keep heuristic reconciliation, patch worst cases | S | 1 | − | Whack-a-mole; recorded PnL stays fiction |
| **Hummingbot-style `InFlightOrder` + client-order-ID on every order + user-stream-driven typed state machine** | M | 5 | + | Proven pattern; fits existing `user_data_stream.py`; Binance `newClientOrderId` is the native dedupe key |
| **+ Append-only trade-event log (Mongo collection or Redis stream) as source of truth; `LiveSession`/PnL as projections** | M | 5 | + | Selective event sourcing (order pipeline only); makes ENG-3 races recoverable and PnL auditable |
| Full event-sourced engine (NautilusTrader-style deterministic core) | XL | 4 | + | Right end-state, wrong step size; revisit only if rewriting |
| Adopt NautilusTrader outright, port strategies | XL | 3 | ± | Discards five-model pipeline, UI integration, multi-user layer; not worth it |

**Recommended:** rows 2+3 together. This is Plan 5's scope — research confirms its direction
and sharpens it: key every order with a deterministic `newClientOrderId`
(`enma_<sessionId>_<seq>`), let the user-data stream drive a typed order state machine, write
every transition to an append-only log, derive session PnL from the log using real `avgPrice`
fills. Per-symbol `asyncio.Lock` closes ENG-3's check-then-act races.

### 1.2 Exchange abstraction (ENG-4/5)

| Option | Effort | Payoff | Maint. | Notes |
|---|---|---|---|---|
| Adopt ccxt | M | 2 | ± | Rejected in DECISIONS.md for control/latency — research shows Hummingbot made the same call; no reason to reverse |
| **Single `Exchange` interface (native httpx impl), mode injected once at construction; testnet/mainnet = config** | M | 4 | + | Keeps the no-ccxt decision; kills ~15 literal call sites; prerequisite for ever enabling mainnet |
| Status quo | — | — | − | Every future venue/mode change touches dozens of sites |

**Recommended:** row 2 (this is Plan 6's exchange-abstraction half). Include: combined WS
streams (one socket per session, not per symbol — ENG-9) and all signed calls routed through
one budget-aware rate limiter (weight is per-IP and shared platform-wide).

### 1.3 Money representation (ENG-11)

| Option | Effort | Payoff | Maint. | Notes |
|---|---|---|---|---|
| **`Decimal` on the ledger path** (orders, fills, fees, PnL accumulation, balance) w/ explicit quantization at exchange filters | M | 4 | + | Consensus practice; Hummingbot precedent; floats stay in numpy indicator math |
| Integer smallest-units | M | 4 | ± | Equivalent correctness; more invasive against Binance's decimal-string API |
| Status quo float | — | — | − | Error compounds with volume; disqualifying for mainnet |

**Recommended:** Decimal on ledger path only (Plan 5 already includes this). Golden-master will
show diffs — expected and desirable; re-baseline once verified.

### 1.4 Strategy code execution (SEC-2, SYS-3)

Resolved by §0 Option B: strategies = operator-owned, git-versioned artifacts; UI editing
admin-only (or read-only view + clone-to-file workflow). Sandbox tier (gVisor/Firecracker)
documented as the *only* acceptable path should public strategy editing ever return —
RestrictedPython-style approaches are a research dead end. Add strategy versioning (hash stamped
into sessions/backtests) so running sessions pin the code they started with (fixes the
`importlib.reload` version-skew).

### 1.5 Service-to-service trust (SEC-1, SYS-1)

| Option | Effort | Payoff | Maint. | Notes |
|---|---|---|---|---|
| **Shared-secret header on `/internal/*` + bind to docker network only + zod validation** | S | 4 | + | 90% of the risk closed for hours of work; symmetric with existing `X-API-Key` |
| mTLS between server↔engine | M | 4 | − | Gold standard, but cert lifecycle overhead is real for a 2-service compose stack; defer |
| Signed short-lived JWTs (service tokens) | M | 4 | ± | Middle path; adopt if/when services multiply |

**Recommended:** row 1 now (Plan 3), mTLS documented as the scale-up path.

### 1.6 Validation layer (SEC-10, SRV-3)

**Zod at every Node route boundary** (parse-don't-validate), including `/internal/*` payloads —
whitelist known `positionDetails` fields to kill the `$set` dotted-path injection pattern.
Effort S–M, payoff 4, maintainability +. Engine already has pydantic; extend to every router
body. (Plans 3/8.)

### 1.7 Secrets & config topology (SEC-3/4/9)

Ladder, in order: (1) **fail-closed encryption** — missing/invalid `ENCRYPTION_KEY` crashes at
boot, `decrypt()` never returns input on failure (S, payoff 5 — hours of work); (2) **per-service
env scoping** in compose — client container gets nothing secret (S, payoff 4); (3) key-version
field on encrypted records to enable rotation (S); (4) **SOPS** for the repo's secret files —
right-sized for this team, no new infra (M); Vault documented as the beyond-compose path.
(Plan 4 — research confirms its direction and supplies the tooling choice.)

### 1.8 Observability (SYS-6)

**OpenTelemetry auto-instrumentation on both services + Pino (Node) / structured JSON (engine)
with `traceId` on every line**; W3C Trace Context propagated client→Node→engine→Binance-call
spans. Effort M, payoff 4 (it is the *enabler* for verifying 1.1), maintainability +.
Minimal viable: correlation-ID middleware + structured logs first (Plan 2's scope), full OTel
traces second. Metrics worth exporting: reconcile-divergence count, order round-trip latency,
rate-limit budget consumption, WS reconnects.

### 1.9 Candle storage (no issue ID — optimization)

**TimescaleDB continuous aggregates** for HTF derivation (1m base → 5m/1h/4h/1d hierarchical
rollups) + native compression on old chunks. Effort S–M, payoff 3, maintainability +. Removes
the engine's mainnet-REST HTF fetch path (one of ENG-8's warmup data sources) and cuts disk.
Not urgent; pairs naturally with Plan 6 engine work.

### 1.10 Node/client structure (SRV-1/2/5, CLI-1/3)

Research adds little novel here — the fixes are standard: service layer extraction on Node
(testable without HTTP), BullMQ jobs instead of 1-hour axios timeouts (queue already in stack),
container/presenter split + shared query factory on the client, and **tests before refactor**
(vitest/msw already in devDependencies, unused). Effort M–L, payoff 3, maintainability ++.
(Plans 2/7.)

---

## 2. What NOT to change (deliberate anti-recommendations)

- **Don't adopt ccxt** — the native-httpx decision is validated by Hummingbot's identical choice.
- **Don't rewrite on NautilusTrader** — parity instinct already exists in the five-model
  pipeline; incremental event-log adoption captures most value at ~10% of the cost.
- **Don't build a Python sandbox** — research is unanimous that language-level sandboxing is
  unwinnable; the permission gate (§0-B) is the correct move.
- **Don't add microservices/mTLS/Vault yet** — 2-service compose stack; shared-secret +
  SOPS + per-service env is the right-sized rung.
- **Keep** TimescaleDB (right tool), BullMQ (right tool, underused), Zustand/TanStack split,
  the indicator provider architecture, and the golden-master discipline (extend it, don't
  replace it).

## 3. Priority-ordered summary (feeds [`0_roadmap.md`](0_roadmap.md))

| # | Change | Closes | Effort | Payoff | Aligned plan |
|---|--------|--------|--------|--------|--------------|
| 1 | Fail-closed encryption + per-service env + internal-route auth + zod boundary | SEC-1/3/4/10, SYS-1 | S | 5 | 2, 3, 4 |
| 2 | Strategy editing → operator-owned artifacts + versioning (product decision §0-B) | SEC-2, SYS-3 | S–M | 5 | 3 |
| 3 | Client-order-ID idempotency + typed order state machine + append-only trade-event log + per-symbol locks + real fill prices | SYS-2, ENG-2/3/10, ENG-16 | M | 5 | 5 |
| 4 | Decimal ledger path | ENG-11 | M | 4 | 5 |
| 5 | Correlation IDs + structured logs, then OTel traces + metrics | SYS-6 | S→M | 4 | 2 |
| 6 | `Exchange` interface + combined WS streams + global signed-call rate budget | ENG-4/5/9 | M | 4 | 6 |
| 7 | Server service layer + jobs-not-timeouts; client decomposition; test harnesses + CI | SRV-1/2/5, CLI-1/3, SYS-5 | M–L | 3 | 2, 7 |
| 8 | Timescale continuous aggregates + compression; warmup-math fix; candle-column named accessors; packaging fix | ENG-8/12/15 | M | 3 | 6, 8 |

**Verdict on existing plans 2–8:** research validates the sequencing already in `0_tracker.md`.
The refinements this analysis adds: (a) §0's reframing makes Plan 3's product decision easier to
sign off, (b) concrete pattern names + tooling choices (InFlightOrder state machine, SOPS, Zod,
OTel, continuous aggregates) for plans that were direction-correct but tool-agnostic, (c) the
anti-recommendations in §2 as guardrails against scope creep.

---

*Next: [`0_roadmap.md`](0_roadmap.md) — the phased engineering blueprint (supersedes the former `04_improvement_roadmap.md`).*
