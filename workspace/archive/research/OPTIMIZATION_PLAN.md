# Enma Platform — Optimization Plan

**Date:** 2026-06-17
**Status:** Draft
**Research Method:** Codebase analysis + web research on trading platform best practices

---

## Executive Summary

After thorough analysis of the entire Enma codebase — engine (Python/FastAPI), server (Node.js/Express), client (React/Vite), and all infrastructure — this document identifies 28 optimization opportunities across performance, architecture, reliability, security, and developer experience. Each item is categorized by impact (High/Medium/Low), effort (S/M/L), and layer (Engine/Server/Client/Infra).

---

## Table of Contents

1. [Performance Optimizations](#1-performance-optimizations)
2. [Architecture Improvements](#2-architecture-improvements)
3. [Reliability & Resilience](#3-reliability--resilience)
4. [Security Hardening](#4-security-hardening)
5. [Developer Experience](#5-developer-experience)
6. [Feature Enhancements](#6-feature-enhancements)
7. [Recommended Implementation Order](#7-recommended-implementation-order)

---

## 1. Performance Optimizations

### 1.1 Candle Fetching — Parallel Batch Download
**Layer:** Engine | **Impact:** High | **Effort:** M

**Current:** `candle_importer.py` fetches 1000 candles per request with `asyncio.sleep(fetch_delay)` between batches. Sequential — one symbol at a time.

**Proposed:** Use `httpx.AsyncClient` with `asyncio.gather()` for parallel batch fetches across multiple symbols, and use a semaphore to respect rate limits.

```python
# Pseudocode
sem = asyncio.Semaphore(5)  # max 5 concurrent Binance requests
async def fetch_batch(client, symbol, timeframe, start_ms, end_ms, sem):
    async with sem:
        # fetch + insert
        pass
await asyncio.gather(*[fetch_batch(...) for batch in batches])
```

**Benefit:** 3-5x faster candle import for multi-symbol backtests. Binance allows ~1200 weight/minute; 5 parallel requests use ~50 weight/min (well within limits).

**Risk:** Must respect `BINANCE_FETCH_DELAY_MS` per-symbol. Cross-symbol parallelism is safe.

---

### 1.2 Backtest Loop — Pre-compute Indicators on Full Series
**Layer:** Engine | **Impact:** High | **Effort:** M

**Current:** `backtest_runner.py` calls `strategy.before()` on every candle (line 749), which recomputes indicators from scratch each iteration. For 100k candles, this means 100k redundant EMA/RSI/ATR computations.

**Proposed:** Add an optional `warmup_compute()` method to BaseStrategy that pre-computes sequential indicators on the full candle array. The backtest runner calls this once before the loop, and `before()` only processes the delta.

```python
# In BaseStrategy
def warmup_compute(self) -> None:
    """Pre-compute sequential indicators on self.candles (full array).
    Override to cache EMA, RSI, ATR, etc. as instance arrays."""
    pass

# In backtest_runner.py (before loop)
strategy.candles = candles_np
strategy.warmup_compute()  # pre-compute once
```

**Benefit:** 10-50x faster backtests for indicator-heavy strategies (MultiDivergence, AdaptiveTrend). Currently MicroScalper takes ~5s for 10k candles; this could drop to <1s.

**Risk:** Strategies that use `self.vars` dynamically in `before()` won't benefit. Only sequential indicators (EMA, RSI, ATR, MACD, etc.) can be pre-computed.

---

### 1.3 Backtest Metrics — Pure NumPy Elimination of Python Loops
**Layer:** Engine | **Impact:** Medium | **Effort:** S

**Current:** `_compute_side_metrics()` (backtest_runner.py:85-163) uses Python loops for consecutive win/loss streaks and holding period calculations.

**Proposed:** Vectorize streaks using `np.diff` and `np.where`:

```python
# Vectorized consecutive wins/losses
signs = np.sign(pnls)
changes = np.diff(signs, prepend=0)
groups = np.cumsum(changes != 0)
# ... count per group
```

**Benefit:** Minor — streaks are O(n) with small n (trade count << candle count). But it's a good principle.

---

### 1.4 TimescaleDB — Connection Pool Tuning
**Layer:** Engine | **Impact:** Medium | **Effort:** S

**Current:** `config/timescale.py` creates an asyncpg pool. Pool size is likely default (10).

**Proposed:** Make pool size configurable via env var, and add `min_size` for warm connections:

```python
import os
pool = await asyncpg.create_pool(
   dsn=os.getenv("TIMESCALE_URL"),
    min_size=int(os.getenv("TS_POOL_MIN", "2")),
    max_size=int(os.getenv("TS_POOL_MAX", "10")),
    command_timeout=30,
)
```

**Benefit:** Faster candle fetches during concurrent backtests. The default pool works but could bottleneck with 5+ simultaneous backtests.

---

### 1.5 Live Bot — WebSocket Connection Pool
**Layer:** Engine | **Impact:** Medium | **Effort:** M

**Current:** `live_bot_manager.py` creates a new `websockets.connect()` per symbol. Each connection is independent with its own TCP handshake and TLS negotiation.

**Proposed:** Use Binance's combined stream endpoint (`/stream?streams=btcusdt@kline_1h/ethusdt@kline_1h`) for multi-symbol sessions, reducing connection count from N to 1.

```python
# Single combined stream for all symbols in a session
streams = "/".join([f"{s.lower()}@kline_{timeframe}" for s in symbols])
ws_url = f"wss://fstream.binancefuture.com/stream?streams={streams}"
```

**Benefit:** Reduces TCP/TLS overhead. Binance recommends combined streams for multi-symbol. Reduces testnet connection pressure.

**Risk:** Message routing becomes more complex. Each message has a `stream` field to identify the symbol.

---

### 1.6 Client — React Query Stale Time Tuning
**Layer:** Client | **Impact:** Low | **Effort:** S

**Current:** TanStack Query hooks use default stale time (0 — always stale). For example, `useStrategies()` refetches on every mount.

**Proposed:** Set appropriate `staleTime` per query type:

```js
// Static data (strategies, candle symbols)
staleTime: 5 * 60 * 1000  // 5 minutes

// Semi-static (dashboard stats, cached candles)
staleTime: 30 * 1000  // 30 seconds

// Dynamic (account, positions, orders)
staleTime: 0  // always refetch
```

**Benefit:** Fewer unnecessary API calls. Smoother UI. The strategies list rarely changes — no need to refetch on every page navigation.

---

## 2. Architecture Improvements

### 2.1 Shared Base Class for Backtest/Live Execution
**Layer:** Engine | **Impact:** High | **Effort:** L

**Current:** `backtest_runner.py` (1025 lines) and `live_bot_manager.py` (876 lines) share significant logic (entry execution, SL/TP checks, flip handling, position management) but it's duplicated with slight variations.

**Proposed:** Extract a shared `ExecutionEngine` base class:

```python
class ExecutionEngine(ABC):
    """Shared execution logic for backtest and live."""
    
    def process_candle(self, strategy, candle) -> OrderPlan | None:
        """Unified candle processing: check exits, evaluate pipeline, plan entries."""
        ...
    
    def execute_entry(self, strategy, plan) -> bool:
        """Place entry order. Returns True if filled."""
        ...
    
    def execute_exit(self, strategy, reason) -> bool:
        """Close position. Returns True if filled."""
        ...
    
    def execute_flip(self, strategy) -> bool:
        """Atomic close-and-reverse."""
        ...

class BacktestEngine(ExecutionEngine):
    """Next-open market fills, simulated fees/slippage."""

class LiveEngine(ExecutionEngine):
    """Real Binance Testnet fills via Node proxy."""
```

**Benefit:** Eliminates ~200 lines of duplicated logic. Makes bug fixes apply to both backtest and live. Easier to add new execution modes (paper trading, mainnet).

**Risk:** Large refactor. Must maintain exact behavioral parity. Golden master tests (existing `golden_master.py`) are critical safety net.

---

### 2.2 Strategy Parameter Validation Middleware
**Layer:** Engine | **Impact:** Medium | **Effort:** S

**Current:** `validate_params()` is called in `backtest_runner.py` line 284-287 but not in `live_bot_manager.py`. Parameter injection logic is duplicated between both.

**Proposed:** Centralize parameter injection and validation in BaseStrategy:

```python
class BaseStrategy:
    @classmethod
    def inject_params(cls, instance, alpha_params: dict, risk_params: dict):
        """Inject and validate all params (alpha + risk). Shared by backtest and live."""
        for key, val in alpha_params.items():
            if key in cls.PARAMS:
                # bounds check
                setattr(instance, key, val)
        # risk params
        instance.risk_pct = risk_params.get("risk_pct", instance.risk_pct)
        instance.validate_params()
```

**Benefit:** Single source of truth for param injection. Live bot gets the same validation as backtest.

---

### 2.3 Event Sourcing for Backtest Results
**Layer:** Engine + Server | **Impact:** Medium | **Effort:** L

**Current:** Backtest results are computed in one shot and written to MongoDB. If the write fails, all computation is lost.

**Proposed:** Use an append-only event log in Redis/TimescaleDB during simulation, with a final snapshot write to MongoDB. This also enables:
- Streaming partial results to the UI during long backtests
- Resume-from-checkpoint for interrupted backtests
- Audit trail of every decision the engine made

**Benefit:** Fault tolerance. Better progress reporting. Enables future optimization (Monte Carlo re-simulations from cached events).

**Risk:** Significant architectural change. Not recommended until the platform needs production-grade reliability.

---

### 2.4 Configurable Indicator Caching
**Layer:** Engine | **Impact:** Medium | **Effort:** M

**Current:** Every `ta.ema()` call recomputes from scratch. No memoization.

**Proposed:** Add an optional LRU cache keyed on `(candle_array_id, period)` that strategies can opt into:

```python
from functools import lru_cache

# In indicator provider
_ema_cache = {}

def ema(self, candles, period=9, sequential=False):
    key = (id(candles), period)  # numpy array identity
    if key in self._ema_cache:
        return self._ema_cache[key]
    result = self._compute_ema(candles, period, sequential)
    self._ema_cache[key] = result
    return result
```

**Benefit:** Dramatic speedup for strategies that call the same indicator with the same parameters multiple times per candle. MultiDivergence calls 9+ indicators.

**Risk:** Cache invalidation is tricky when candles array is mutated. Must clear cache when `strategy.candles` changes.

---

## 3. Reliability & Resilience

### 3.1 Live Bot — Exponential Backoff Reconnection
**Layer:** Engine | **Impact:** High | **Effort:** S

**Current:** `live_bot_manager.py` line 393-400 uses fixed 5-second delay on WS disconnect:

```python
await asyncio.sleep(5)
```

**Proposed:** Exponential backoff with jitter:

```python
reconnect_delay = min(30, 2 ** consecutive_reconnects + random.uniform(0, 1))
await asyncio.sleep(reconnect_delay)
```

**Benefit:** Prevents thundering herd if Binance temporarily bans the IP. Standard pattern for WebSocket resilience.

---

### 3.2 Live Bot — Heartbeat/Keepalive Monitoring
**Layer:** Engine | **Impact:** Medium | **Effort:** M

**Current:** No heartbeat check. If Binance WS silently stops sending messages (network partition), the bot hangs indefinitely.

**Proposed:** Add a watchdog task per symbol loop:

```python
async def _watchdog(self, session_id, symbol, timeout=120):
    """Kill symbol loop if no candle received within timeout."""
    while not stop_event.is_set():
        last_candle_time = self.sessions[session_id]["last_candle_at"].get(symbol)
        if last_candle_time and (now - last_candle_time) > timeout:
            logger.error(f"{symbol}: no candle for {timeout}s, reconnecting")
            # trigger reconnect
            break
        await asyncio.sleep(30)
```

**Benefit:** Detects silent failures. Prevents stale bot state.

---

### 3.3 Server — BullMQ Job Retry with Dead Letter Queue
**Layer:** Server | **Impact:** Medium | **Effort:** S

**Current:** `backtest.worker.js` fails jobs but doesn't retry. A transient engine error (OOM, timeout) permanently fails the job.

**Proposed:** Configure BullMQ retry with backoff:

```js
const backtestQueue = new Queue('bull:backtest', {
  defaultJobOptions: {
    attempts: 3,
    backoff: { type: 'exponential', delay: 5000 },
    removeOnComplete: { age: 3600 },
    removeOnFail: { age: 86400 },
  }
});
```

**Benefit:** Transient failures (engine restart, network blip) are automatically retried. Dead jobs are preserved for 24h for debugging.

---

### 3.4 Engine — Graceful Shutdown
**Layer:** Engine | **Impact:** Medium | **Effort:** M

**Current:** `main.py` doesn't handle SIGTERM/SIGINT gracefully. Active backtests and live bots may lose state.

**Proposed:** Add shutdown handler in FastAPI lifespan:

```python
@app.on_event("shutdown")
async def shutdown():
    # 1. Stop all live bot sessions
    await live_bot_manager.stop_all()
    # 2. Cancel running backtests (publish cancel to all active jobs)
    # 3. Close DB pools
    await timescale_pool.close()
    await mongo_client.close()
```

**Benefit:** Prevents data corruption on Docker restart. Ensures Binance positions are closed cleanly.

---

## 4. Security Hardening

### 4.1 API Key Rotation Support
**Layer:** Server | **Impact:** Medium | **Effort:** M

**Current:** API keys are stored once in `Settings` collection. No rotation mechanism.

**Proposed:** Add `createdAt`, `expiresAt` fields to the keys document. Support multiple key pairs (primary + backup). Add a `/api/v1/settings/keys/rotate` endpoint that:
1. Validates new key
2. Saves as new primary
3. Moves old key to backup (kept for 24h for pending orders)

**Benefit:** Binance recommends periodic key rotation. Currently, rotating requires manual DB edit.

---

### 4.2 Rate Limiting Per Endpoint
**Layer:** Server | **Impact:** Low | **Effort:** S

**Current:** Global rate limit in `app.js` via `express-rate-limit`. No per-endpoint granularity.

**Proposed:** Add stricter limits on sensitive endpoints:

```js
// Trade endpoints: 10 requests/second (Binance testnet limit)
app.use('/api/v1/trade', rateLimit({ windowMs: 1000, max: 10 }));

// Algo sessions: 1/second (start/stop are rare)
app.use('/api/v1/algo/sessions', rateLimit({ windowMs: 1000, max: 2 }));
```

**Benefit:** Prevents accidental API abuse. Matches Binance's actual rate limits.

---

## 5. Developer Experience

### 5.1 Strategy Development Kit (SDK)
**Layer:** Engine | **Impact:** High | **Effort:** M

**Current:** Strategy authors must read BaseStrategy source, CLAUDE.md, and docs/strategies/*.md to understand the API. No template or scaffolding.

**Proposed:** Create a strategy template generator:

```bash
python -m engine.scripts.new_strategy --name MyStrategy --type trend
# Generates: engine/strategies/MyStrategy/__init__.py
# With: class MyStrategy(BaseStrategy), PARAMS, should_long/short, go_long/short
# And: docstring explaining each method
```

**Benefit:** Reduces barrier for writing new strategies. Ensures consistent structure.

---

### 5.2 Backtest Result Comparison Tool
**Layer:** Client | **Impact:** Medium | **Effort:** M

**Current:** No way to compare two backtest runs side-by-side. Must manually switch between results.

**Proposed:** Add a comparison view:
- Select 2-3 backtest results from history
- Side-by-side metrics table with delta highlighting
- Overlay equity curves on single chart
- Diff view for parameter configurations

**Benefit:** Essential for strategy optimization. Currently the most requested feature in trading platforms (per web research: TradingView, QuantConnect, Backtrader all have this).

---

### 5.3 Type Safety — Full TypeScript Client
**Layer:** Client | **Impact:** Medium | **Effort:** L

**Current:** Client uses `.jsx` files with PropTypes (implicit). API response types are documented in `API_CONTRACTS.md` but not enforced at compile time.

**Proposed:** Migrate to `.tsx` with TypeScript interfaces derived from API_CONTRACTS.md:

```typescript
interface BacktestMetric {
  totalTrades: number;
  winRate: string;
  netProfit: string;
  // ... from API_CONTRACTS.md
}
```

**Benefit:** Compile-time type errors catch API contract violations before runtime. Better IDE support.

**Risk:** Large migration. Could be done incrementally (one page at a time).

---

## 6. Feature Enhancements

### 6.1 Mainnet Trading Support
**Layer:** Engine + Server + Client | **Impact:** High | **Effort:** M

**Current:** `DECISIONS.md #9` documents the plan but it's not implemented. `binance_testnet.py` has `_BASE_URLS` dict ready.

**Proposed:**
1. Add `mode` selector to Exchange Settings (Testnet / Mainnet)
2. Server stores mode in Settings and passes it to engine
3. Engine reads mode and selects base URL from `_BASE_URLS`
4. Add confirmation dialog in UI for mainnet orders ("This will place a REAL order with REAL money")
5. Add visual indicator (red banner) when in mainnet mode

**Benefit:** Users can graduate from testnet to live trading without switching platforms.

---

### 6.2 Monte Carlo Optimization
**Layer:** Engine | **Impact:** High | **Effort:** L

**Current:** `CURRENT_STATE.md` lists this as planned. `/optimize` endpoint not implemented.

**Proposed:** Implement walk-forward optimization:
1. Split backtest period into in-sample (IS) and out-of-sample (OOS) windows
2. Grid search or random search over PARAMS space on IS windows
3. Validate best parameters on OOS windows
4. Report: parameter stability, IS vs OOS performance, Monte Carlo distribution of returns

**Benefit:** Prevents overfitting. Essential for serious strategy development.

---

### 6.3 Multi-Exchange Support
**Layer:** Engine | **Impact:** Medium | **Effort:** L

**Current:** Binance only. `ccxt` is explicitly rejected (`AGENTS.md` constraint).

**Proposed:** Abstract exchange interface:

```python
class ExchangeProvider(ABC):
    @abstractmethod
    async def fetch_klines(self, symbol, timeframe, start, end) -> list[dict]: ...
    @abstractmethod
    async def place_order(self, symbol, side, type, qty, price=None) -> dict: ...
    @abstractmethod
    async def get_position(self, symbol) -> dict: ...

class BinanceProvider(ExchangeProvider):
    """Current implementation via httpx + HMAC signing."""

class OKXProvider(ExchangeProvider):
    """Future: OKX integration."""
```

**Benefit:** Platform independence. Access to more markets and liquidity.

---

## 7. Recommended Implementation Order

### Phase 1 — Quick Wins (1-2 weeks)
| # | Item | Impact | Effort |
|---|------|--------|--------|
| 1.1 | Parallel candle fetching | High | M |
| 3.1 | Exponential backoff reconnection | High | S |
| 1.6 | React Query stale time tuning | Low | S |
| 3.3 | BullMQ retry with DLQ | Medium | S |
| 4.2 | Per-endpoint rate limiting | Low | S |

### Phase 2 — Core Performance (2-4 weeks)
| # | Item | Impact | Effort |
|---|------|--------|--------|
| 1.2 | Pre-compute indicators on full series | High | M |
| 2.2 | Centralized parameter injection | Medium | S |
| 3.2 | Heartbeat/watchdog monitoring | Medium | M |
| 5.1 | Strategy SDK/template generator | High | M |

### Phase 3 — Architecture (4-8 weeks)
| # | Item | Impact | Effort |
|---|------|--------|--------|
| 2.1 | Shared ExecutionEngine base class | High | L |
| 1.5 | Combined WS stream for live bots | Medium | M |
| 4.1 | API key rotation support | Medium | M |
| 3.4 | Graceful shutdown | Medium | M |

### Phase 4 — Major Features (8-12 weeks)
| # | Item | Impact | Effort |
|---|------|--------|--------|
| 6.1 | Mainnet trading support | High | M |
| 5.2 | Backtest comparison tool | Medium | M |
| 1.4 | TimescaleDB pool tuning | Medium | S |
| 6.2 | Monte Carlo optimization | High | L |

### Phase 5 — Long-term (12+ weeks)
| # | Item | Impact | Effort |
|---|------|--------|--------|
| 6.3 | Multi-exchange support | Medium | L |
| 2.3 | Event sourcing for backtests | Medium | L |
| 5.3 | Full TypeScript migration | Medium | L |
| 2.4 | Indicator caching layer | Medium | M |

---

## Appendix: Web Research Findings

### Industry Best Practices (2026)
- **Backtesting speed:** Vectorized backtests (vectorbt, backtrader) process 1M candles in <1s. Enma's per-candle loop is 100-1000x slower due to Python overhead and indicator recomputation.
- **WebSocket resilience:** Production trading bots use exponential backoff + jitter + heartbeat monitoring. Fixed delays cause thundering herd on exchange restarts.
- **Risk management:** Industry standard is 1-2% risk per trade (Enma's default 1% is correct). Position sizing by risk is best practice.
- **Indicator caching:** Most platforms cache sequential indicators (EMA, RSI) because recomputing on every candle is wasteful.
- **Combined streams:** Binance documentation recommends combined streams for multi-symbol subscriptions to reduce connection overhead.

### Alternatives Considered
| Alternative | Why Not |
|-------------|---------|
| `ccxt` library | Rejected per AGENTS.md #NoCcxT rule. Insufficient control over order types. |
| `pandas` for backtest loop | Too slow for sequential candle replay. NumPy is correct. |
| `redis-py` pipeline for batching | BullMQ already handles queuing. Redis pub/sub is correct for progress. |
| `websockets` library | Already used. No better alternative for Binance WS. |
| `SQLAlchemy` for TimescaleDB | asyncpg is more performant and already in use. ORM overhead not justified. |
