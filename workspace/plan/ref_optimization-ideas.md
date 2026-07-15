# Optimization Ideas — Solutions & Architecture Designs

**Source:** a deep review from 2026-06-17 (original research docs deleted — git history). Updated on 2026-06-24 with concrete technical solutions and architecture designs for the highest-impact ideas.

---

## 1. Summary Registry of Optimization Ideas

These ideas were surfaced during a codebase-wide review. None are currently scheduled for near-term sprints, but they serve as a reference for future design improvements.

### Performance

| Idea | Impact | Effort | What it touches |
|------|--------|--------|-----------------|
| Parallel candle fetching — `asyncio.gather()` with semaphore for multi-symbol batch download | High | M | `candle_importer.py` |
| ~~Pre-compute indicators on full series — `warmup_compute()` / `prepare()` method on BaseStrategy~~ | High | M | **Shipped** — `BaseStrategy.prepare()` (`engine/core/strategy.py`), used by all 5 seeded strategies. See `13_informative-multi-timeframe.md` ("workstream #1 (done)"). Row kept for history only. |
| Backtest metrics vectorization — pure NumPy for streaks/holding periods | Medium | S | `backtest_runner.py` |
| TimescaleDB connection pool tuning — configurable min/max pool size | Medium | S | `config/timescale.py` |
| Combined WS stream for live bots — Binance `/stream?streams=...` single connection | Medium | M | `live_bot_manager.py` |
| React Query stale time tuning — per-query-type staleTime config | Low | S | `client/src/hooks/*.js` |
| Configurable indicator caching — LRU cache keyed on `(candle_array_id, period)` | Medium | M | Indicator provider |

### Architecture

| Idea | Impact | Effort | What it touches |
|------|--------|--------|-----------------|
| ~~Shared `ExecutionEngine` base class — unify backtest/live entry/exit logic~~ | High | L | **Shipped** — `engine/core/kernel.py` (`ExecutionKernel`/`ExecutionAdapter`, tagged F-024). Also listed as done in `ref_gap-matrix-freqtrade-nautilus.md` ("Event-driven engine ... Enma (ExecutionKernel)"). Row kept for history only. |
| Strategy parameter validation middleware — centralized inject/validate in BaseStrategy | Medium | S | `BaseStrategy`, both runners |
| Event sourcing for backtest results — append-only event log with snapshot to Mongo | Medium | L | Engine + Server |
| Exchange interface abstraction — `ExchangeProvider` ABC for multi-exchange | Medium | L | Engine |

### Reliability

| Idea | Impact | Effort | What it touches |
|------|--------|--------|-----------------|
| Exponential backoff reconnection — WS reconnect with jitter | High | S | `live_bot_manager.py` |
| Heartbeat/watchdog monitoring — detect silent WS drops | Medium | M | `live_bot_manager.py` |
| BullMQ job retry with dead letter queue — exponential backoff on transient failures | Medium | S | `backtest.worker.js` |
| Graceful shutdown — SIGTERM handler, close sessions and DB pools | Medium | M | `main.py` |

---

## 2. Technical Solutions & Brainstormed Designs for Key Ideas

### 2.1 Parallel Candle Fetching (High Impact / Medium Effort)
*   **Problem:** Historical candle ingestion imports symbols sequentially. Fetching 10 symbols across a 2-year range takes minutes due to connection overhead and flat sequencing.
*   **Solution Design:**
    *   Rewrite `CandleImporter.import_history()` to compose symbol tasks into an `asyncio.gather()` list.
    *   Introduce an `asyncio.Semaphore(value=5)` to restrict concurrent connections and prevent triggering Binance IP-rate bans.
    *   Wrap requests in an exponential backoff decorator that inspects response status codes: if `429 Too Many Requests` is encountered, inspect the `Retry-After` header or wait $2^n \times \text{random\_jitter}$ seconds before retry.
    *   Example implementation pattern:
        ```python
        sem = asyncio.Semaphore(5)
        async def fetch_with_semaphore(symbol, timeframe):
            async with sem:
                return await self._fetch_single_symbol(symbol, timeframe)
        results = await asyncio.gather(*(fetch_with_semaphore(s, tf) for s in symbols))
        ```

### 2.2 Shared `ExecutionEngine` Base Class (High Impact / Large Effort)
*   **Problem:** The simulator (`backtest_runner.py`) and live coordinator (`live_bot_manager.py`) implement duplicate order routing and margin validation rules (leverage clamping, margin allocation, fee calculations).
*   **Solution Design:**
    *   Create a base class `BaseExecutionEngine(ABC)` that defines standard position state management and compliance checks.
    *   Move leverage checks, margin affordability calculations, and bracket order size allocations into helper methods on this class.
    *   Define abstract hooks: `async def submit_order(...)` and `async def cancel_order(...)`.
    *   Inherit with:
        *   `SimulatedExecutionEngine` which runs offline candle-matching (updates PnL, handles liquidations and slippage simulated locally).
        *   `BinanceTestnetExecutionEngine` which sends HMAC-signed HTTPS calls via `httpx` to the testnet REST endpoint.
    *   This enforces single-source-of-truth logic for position tracking.

### 2.3 Combined WebSocket Stream for Live Bots (Medium Impact / Medium Effort)
*   **Problem:** Running multiple live strategies on separate symbols creates independent WS connections per symbol-loop. Ten active symbol-loops = ten persistent network connections, increasing system vulnerability to connection drops and socket fatigue.
*   **Solution Design:**
    *   Implement a centralized `MarketDataBroker` class in the engine.
    *   This broker establishes a single connection using the Binance Combined Stream endpoint: `wss://fstream.binance.com/stream?streams=btcusdt@kline_1m/ethusdt@kline_1m/...`
    *   Each symbol loop registers a callback queue with the broker: `broker.subscribe(symbol, queue)`.
    *   When the WebSocket receives a packet, the broker parses the symbol and drops the candle update into the appropriate queue.
    *   If a symbol loop is added or stopped, the broker dynamically updates the streams list using `SUBSCRIBE`/`UNSUBSCRIBE` message frames over the existing WebSocket connection without dropping active streams.

### 2.4 Centralized Strategy Parameter Validation Middleware (Medium Impact / Small Effort)
*   **Problem:** Strategies define custom parameters in `PARAMS` dictionary metadata, but input overrides sent from the frontend/server are not rigorously validated, exposing the engine to runtime type crashes or division-by-zero math errors.
*   **Solution Design:**
    *   Define parameter constraint schemas using Pydantic directly within `BaseStrategy`.
    *   Implement a static validation hook:
        ```python
        def validate_overrides(cls, overrides: dict) -> dict:
            validated = {}
            for name, param in cls.PARAMS.items():
                val = overrides.get(name, param["default"])
                # Type cast check
                if param["type"] == "int": val = int(val)
                elif param["type"] == "float": val = float(val)
                # Bounds check
                if "min" in param and val < param["min"]: raise ValueError(...)
                if "max" in param and val > param["max"]: raise ValueError(...)
                validated[name] = val
            return validated
        ```
    *   Run this validation middleware in `backtest_runner.py` and `live_bot_manager.py` immediately when a session payload is parsed, rejecting run creation at the API gate if validation fails.

### 2.5 Graceful Container Shutdown (Medium Impact / Medium Effort)
*   **Problem:** Standard container restarts (SIGTERM) kill the engine process abruptly, leaving DB connection pools hanging, Redis locks orphaned, and active bot sessions marked as "running" when they are actually dead.
*   **Solution Design:**
    *   In `main.py`, catch terminate signals:
        ```python
        import signal
        def setup_signals(self):
            for sig in (signal.SIGTERM, signal.SIGINT):
                asyncio.get_event_loop().add_signal_handler(
                    sig, lambda: asyncio.create_task(self.shutdown())
                )
        ```
    *   The `shutdown()` handler will:
        1. Set a global `shutting_down = True` flag to pause new WS message processing.
        2. Cleanly stop and close all active live loops, sending order cancellations to Binance Testnet for open brackets.
        3. Release all Redis symbol locks.
        4. Flush any pending trade records to MongoDB.
        5. Mark all running session states in MongoDB as `aborted`.
        6. Close TimescaleDB and MongoDB client connection pools.
