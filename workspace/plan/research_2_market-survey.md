# 02 — Market Research: How Industry-Standard Systems Build Enma's Components

**Shelf:** research · **Date:** 2026-07-14 · **Formerly:** `refinements/02_market_research.md` (series mapping in `0_plans.md`)
**Method:** Web research (July 2026) mapped against the component inventory in
[`research_1_project-outline.md`](research_1_project-outline.md). Each section: what top-tier systems do → why → relevance to Enma.

---

## 1. Live-trading state & order tracking (vs Enma's `live_bot_manager` + heuristic reconciliation)

### 1.1 NautilusTrader — deterministic event-driven core
The current open-source gold standard for backtest/live parity. Rust-native engine, Python
control plane; **a single event-driven architecture spans research, simulation, and live** —
identical execution semantics in both modes, so strategies deploy with zero code changes. Time
advances only through an explicit event loop (no scheduler nondeterminism). This is the mature
version of Enma's "five-model pipeline shared by backtest and live" instinct — but built on an
ordered event stream rather than shared mutable dicts.
Sources: [GitHub](https://github.com/nautechsystems/nautilus_trader) ·
[Architecture docs](https://nautilustrader.io/docs/latest/concepts/architecture/) ·
[nautilustrader.io](https://nautilustrader.io/)

### 1.2 Hummingbot — `InFlightOrder` + `ClientOrderTracker` pattern
Every order gets a **client-side ID at creation, before exchange submission**; an
`InFlightOrder` object holds the full authoritative state of each order; a `ClientOrderTracker`
owns all of them. `buy()`/`sell()` return immediately with the client ID; a `UserStreamTracker`
consumes the exchange's user-data stream and emits **typed status events** until the order is
completed/cancelled/expired/failed. Periodic snapshot requests are the *fallback*, not the
mechanism. This is the industry answer to Enma's ENG-2/ENG-3/ENG-10 class of problems: state
transitions are event-driven and keyed by client order ID, never inferred from candle context.
Sources: [Connector architecture](https://hummingbot.org/connectors/connectors/architecture/) ·
[Order lifecycle](https://hummingbot.org/connectors/connectors/architecture/order_lifecycle/) ·
[Architecture blog pt.1](https://hummingbot.org/blog/hummingbot-architecture---part-1/)

### 1.3 Event sourcing for trade/PnL truth
Standard pattern for order pipelines: persist every state change as an **immutable, append-only
event**; current state is a projection; the log is the single source of truth, giving free audit
trail, temporal queries, and deterministic replay. Applied *selectively* (order pipeline + PnL
ledger — not the whole app). Directly addresses SYS-2 (three copies of live state reconciled by
heuristics, last-write-wins PATCHes).
Sources: [microservices.io — Event sourcing](https://microservices.io/patterns/data/event-sourcing.html) ·
[Azure Architecture Center](https://learn.microsoft.com/en-us/azure/architecture/patterns/event-sourcing) ·
[Event ordering in microservices](https://oneuptime.com/blog/post/2026-01-30-event-ordering-in-microservices/view)

**Pitfall of Enma's current approach (per research):** snapshot-and-guess reconciliation without
an ordered event log cannot distinguish "we closed it" from "exchange closed it" under
concurrency; every serious platform converged on client-order-ID-keyed event streams.

## 2. Exchange abstraction (vs Enma's hardwired testnet + native httpx)

**Freqtrade** (the most-deployed OSS crypto bot) delegates all exchange I/O to **CCXT**: one
`Exchange` base class, 100+ venue subclasses, unified `create_order`/`fetch_ticker`/
`load_markets`. Enma explicitly rejected ccxt (DECISIONS.md) — a defensible latency/control
choice that **Hummingbot also made** (native connectors) — but Hummingbot still routes
everything through a single `ConnectorBase` interface. The lesson is not "adopt ccxt"; it is
**"one Exchange interface, venue/mode (testnet|mainnet) as injected configuration, never as
literals at call sites"** (Enma has `mode="testnet"` at ~15 sites — ENG-4).
Sources: [Freqtrade exchange notes](https://www.freqtrade.io/en/stable/exchanges/) ·
[CCXT unified API](https://docs.ccxt.com/) ·
[Hummingbot connectors](https://hummingbot.org/connectors/)

## 3. Binance-specific mechanics (vs Enma's per-symbol sockets, entry-only rate limiter)

- **Idempotency:** Binance treats `newClientOrderId` as the dedupe key — a new order with the
  same ID is accepted only after the previous one fills/expires. Industry bots stamp *every*
  order with a deterministic client ID so a timeout can be resolved by querying the ID instead
  of guessing (Enma only stamps SL/TP — ENG-10).
- **Combined streams:** `/stream/` endpoints multiplex many symbols per connection; one WS per
  symbol (Enma's pattern, 100+ sockets in Chaos) is explicitly the anti-pattern the combined
  endpoint exists to prevent.
- **Rate limits:** weight is per-IP and shared across all connections; 429 → back off, repeat
  violations → escalating IP bans (2min–3days). Serious clients centralize *all* signed calls
  behind one budget-aware limiter (Enma's limiter covers entries only; reconciliation bypasses
  it — ENG-9).
Sources: [Binance USD-M WS API general info](https://developers.binance.com/docs/derivatives/usds-margined-futures/websocket-api-general-info) ·
[WS market streams](https://developers.binance.com/docs/derivatives/usds-margined-futures/websocket-market-streams) ·
[Spot WS streams (combined-stream semantics)](https://developers.binance.com/docs/binance-spot-api-docs/web-socket-streams) ·
[Binance futures rate limits FAQ](https://www.binance.com/en/support/faq/detail/281596e222414cdd9051664ea621cdc3)

## 4. Money representation (vs Enma's float-everywhere — ENG-11)

Consensus is unambiguous: **`decimal.Decimal` (or integer smallest-units) for anything that
accumulates or compares money**; floats accumulate representation error
(`0.1+0.2 != 0.3`) that compounds across thousands of trades. Standard practice: Decimal with
explicit context (precision + rounding mode) at boundaries (exchange filters: tickSize/stepSize
quantization), floats acceptable only inside vectorized indicator math (numpy) where values are
analytical, not ledger-grade. Hummingbot uses `Decimal` throughout its order/balance paths.
Sources: [Why float money is dangerous (Medium/Pythonworld)](https://medium.com/the-pythonworld/still-using-python-float-for-money-heres-why-that-s-dangerous-c761b994c526) ·
[LearnPython — counting money exactly](https://learnpython.com/blog/count-money-python/) ·
[Python Decimal guide](https://zetcode.com/python/decimal/)

## 5. Untrusted strategy code (vs Enma's `importlib.reload` of user-editable Python — SEC-2)

Research consensus (2025–2026): **CPython cannot be sandboxed at the language level** — its
introspection (frames, `__subclasses__`, tracebacks) defeats RestrictedPython-style approaches;
maintainers consider in-interpreter sandboxing a dead end. Viable tiers:
1. **Don't run untrusted code** — review/version strategies as git-controlled artifacts
   (Freqtrade's model: strategies are *files the operator owns*, not web-editable by any user).
2. **OS-level isolation** — gVisor (syscall-intercepting application kernel, GKE-proven) or
   **Firecracker micro-VMs** (~125ms boot, ~5MB overhead; powers AWS Lambda, E2B) for genuinely
   untrusted execution.
3. Shared-kernel Docker alone is considered insufficient isolation for untrusted code in 2026.
Also relevant: a mutable, hot-reloaded strategy in-process with decrypted credentials violates
the separation every platform above maintains (strategy code never lives in the credential
process).
Sources: [Notes on sandboxing untrusted code (gist)](https://gist.github.com/mavdol/2c68acb408686f1e038bf89e5705b28c) ·
[Running untrusted Python code — healeycodes](https://healeycodes.com/running-untrusted-python-code) ·
[4 ways to sandbox untrusted code in 2026](https://dev.to/mohameddiallo/4-ways-to-sandbox-untrusted-code-in-2026-1ffb) ·
[AI-agent sandboxing guide 2026](https://manveerc.substack.com/p/ai-agent-sandboxing-guide)

## 6. API-boundary validation & service-to-service trust (vs SEC-1, SEC-10, SYS-1)

2026 Node baseline: **schema validation at every boundary** (Zod dominant; parse-don't-validate
at the route edge, types + rules in one artifact) — eliminates mass assignment and the
`$set`-dotted-path class of injection Enma has in `handleEngineStats`. For internal service
calls, the standard ladder is: shared static key (weakest) → per-service keys with rotation →
**mTLS** (both sides authenticate; `requestCert: true` + `rejectUnauthorized: true` in Node) or
signed short-lived tokens. Public endpoints: strict per-route rate limits (auth endpoints
separately), JWT in httpOnly cookies (Enma already does this part right).
Sources: [Securing Node.js APIs 2026 (dev.to)](https://dev.to/_d7eb1c1703182e3ce1782/how-to-secure-your-nodejs-api-in-2026-complete-security-guide-4pll) ·
[Zod request validation in Express](https://dev.to/osalumense/validating-request-data-in-expressjs-using-zod-a-comprehensive-guide-3a0j) ·
[Node.js official security best practices](https://nodejs.org/learn/getting-started/security-best-practices) ·
[mTLS in Node from scratch](https://dev.to/woovi/node-mtls-from-scratch-3p4e)

## 7. Secrets & config topology (vs one shared `.env` in every container — SEC-3/4/9)

Best practice ladder for compose-based stacks: (1) **per-service env scoping** — each container
gets only its own variables (zero-cost, pure hygiene); (2) **file-mounted secrets**
(`/run/secrets/<name>`) instead of env vars — env vars have no access control and leak via
inspection/logs; (3) **SOPS** (age/KMS-encrypted files, git-committable — the sweet spot for
1–20-person teams, no extra infra); (4) **Vault** for dynamic secrets + rotation + audit at
scale. Key-versioning fields on encrypted records so keys can rotate without breaking stored
ciphertexts. Fail-**closed** on missing keys — never a hardcoded fallback.
Sources: [GitGuardian — secrets in Docker](https://blog.gitguardian.com/how-to-handle-secrets-in-docker/) ·
[Compose secrets threat-model writeup](https://byern.dev/secrets-management-in-docker-compose-env-sops-bitwarden-and-the-good-enough-threat-model/) ·
[Secrets management 2026: Vault/SOPS/ESO](https://zeonedge.com/blog/secrets-management-2026-vault-sops-external-secrets-operator)

## 8. Observability (vs print-grade logging, no correlation — SYS-6)

2026 baseline: **OpenTelemetry everywhere** — auto-instrumentation exists for both Express and
FastAPI; W3C Trace Context propagates one trace ID across client→Node→engine→(Binance call
spans); structured JSON logs (Pino on Node, structlog/std-logging-JSON on Python) carry
`traceId`/`spanId` on every line, so an ENG-2-class incident is reconstructable post-hoc.
Metrics (order latency, reconcile divergence count, WS reconnects, rate-limit budget) via OTel →
Prometheus. This is the enabling layer for debugging the state-integrity work in §1.
Sources: [FastAPI + OTel guide 2026](https://dev.to/kaushikcoderpy/fastapi-distributed-tracing-the-complete-opentelemetry-guide-2026-k) ·
[Node observability stack 2026](https://dev.to/axiom_agent/the-nodejs-observability-stack-in-2026-opentelemetry-prometheus-and-distributed-tracing-229b) ·
[Pino 9 + OTel structured logging](https://1xapi.com/blog/structured-logging-nodejs-pino-opentelemetry-2026) ·
[SigNoz — OTel FastAPI](https://signoz.io/blog/opentelemetry-fastapi/)

## 9. Time-series candle storage (vs plain hypertable — currently fine, upgradeable)

Enma's TimescaleDB usage (single `candles` hypertable, idempotent inserts) matches the base
pattern. What top deployments add: **continuous aggregates** to derive higher timeframes
(1m→5m/1h/1d) *in the database* via hierarchical rollups (merge 60 minute-candles per hour
instead of re-scanning), **native compression** on older chunks (order-of-magnitude disk
savings), and optional retention policies. This would replace engine-side HTF resampling and
shrink the multi-timeframe warmup problem (ENG-8's HTF fetch path).
Sources: [TigerData/Timescale — financial tick data](https://docs.tigerdata.com/tutorials/latest/financial-tick-data/) ·
[Hierarchical continuous aggregates](https://ideia.me/hierarchical-continuous-aggregates-with-ruby) ·
[OHLC pipeline tutorial](https://tradermade.com/tutorials/6-steps-fx-stock-ticks-ohlc-timescaledb)

## 10. Comparative snapshot — where Enma sits

| Concern | Enma today | Freqtrade | Hummingbot | NautilusTrader |
|---|---|---|---|---|
| Backtest/live parity | Shared five-model pipeline (good instinct), hand-synced live copies | Same strategy class both modes | Connector-level parity | Deterministic event-core parity (best) |
| Order state | Mutable dicts + attribute pokes, snapshot reconciliation | Persisted orders w/ ccxt IDs | `InFlightOrder` + typed events (best fit for Enma) | Full event sourcing |
| Money type | float | float (known criticism) | `Decimal` | Fixed-precision (Rust) |
| Exchange abstraction | None (testnet literals) | ccxt | `ConnectorBase` native | Adapter crates |
| Strategy code | Web-editable, hot-reload in credential process | Operator-owned files | Operator-owned files | Operator-owned code |
| User model | Multi-user open login (unusual!) | Single-operator | Single-operator | Single-operator |
| Observability | print-grade | Logs + FreqUI metrics | Logs + MQTT telemetry | Structured + Redis msgbus |

**The structural insight:** Enma is architecturally unusual in being **multi-tenant** — none of
the reference platforms let arbitrary Google-account holders share one engine process. That
choice raises the bar (sandboxing, per-user rate budgets, per-user event streams) far above what
any of the reference systems needed, and most of the audit's H-severity findings (SEC-1/2,
SYS-1/2/3) are consequences of applying single-operator patterns in a multi-tenant deployment.

---

*Next: [`research_3_gap-analysis.md`](research_3_gap-analysis.md) — gap analysis and evaluated alternatives.*
