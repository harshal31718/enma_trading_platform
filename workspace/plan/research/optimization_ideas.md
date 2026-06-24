# Optimization Ideas — For Future Consideration

**Source:** `workspace/archive/research/` (deep review 2026-06-17, archived into `plan/` 2026-06-24)

**Status:** Parking lot — no decisions made, nothing implemented. Review these when prioritizing future work.

---

These are ideas surfaced during a codebase-wide review. Each is listed with its original impact/effort rating exactly as researched. **None have been evaluated for fit, prioritized, or approved.** When the time comes to pick up optimization work, revisit this list, assess each against current priorities, and create a proper plan.

---

## Performance

| Idea | Impact | Effort | What it touches |
|------|--------|--------|-----------------|
| Parallel candle fetching — `asyncio.gather()` with semaphore for multi-symbol batch download | High | M | `candle_importer.py` |
| Pre-compute indicators on full series — `warmup_compute()` / `prepare()` method on BaseStrategy | High | M | `backtest_runner.py`, `BaseStrategy` |
| Backtest metrics vectorization — pure NumPy for streaks/holding periods | Medium | S | `backtest_runner.py` |
| TimescaleDB connection pool tuning — configurable min/max pool size | Medium | S | `config/timescale.py` |
| Combined WS stream for live bots — Binance `/stream?streams=...` single connection | Medium | M | `live_bot_manager.py` |
| React Query stale time tuning — per-query-type staleTime config | Low | S | `client/src/hooks/*.js` |
| Configurable indicator caching — LRU cache keyed on `(candle_array_id, period)` | Medium | M | Indicator provider |

---

## Architecture

| Idea | Impact | Effort | What it touches |
|------|--------|--------|-----------------|
| Shared `ExecutionEngine` base class — unify backtest/live entry/exit logic | High | L | `backtest_runner.py`, `live_bot_manager.py` |
| Strategy parameter validation middleware — centralized inject/validate in BaseStrategy | Medium | S | `BaseStrategy`, both runners |
| Event sourcing for backtest results — append-only event log with snapshot to Mongo | Medium | L | Engine + Server |
| Exchange interface abstraction — `ExchangeProvider` ABC for multi-exchange | Medium | L | Engine |

---

## Reliability

| Idea | Impact | Effort | What it touches |
|------|--------|--------|-----------------|
| Exponential backoff reconnection — WS reconnect with jitter | High | S | `live_bot_manager.py` |
| Heartbeat/watchdog monitoring — detect silent WS drops | Medium | M | `live_bot_manager.py` |
| BullMQ job retry with dead letter queue — exponential backoff on transient failures | Medium | S | `backtest.worker.js` |
| Graceful shutdown — SIGTERM handler, close sessions and DB pools | Medium | M | `main.py` |

---

## Security

| Idea | Impact | Effort | What it touches |
|------|--------|--------|-----------------|
| API key rotation support — `expiresAt`, multiple key pairs, rotate endpoint | Medium | M | Server Settings |
| Per-endpoint rate limiting — stricter limits on trade/algo endpoints | Low | S | `app.js` |

---

## Developer Experience

| Idea | Impact | Effort | What it touches |
|------|--------|--------|-----------------|
| Strategy SDK / template generator — `python -m engine.scripts.new_strategy` | High | M | Engine scripts |
| Backtest result comparison tool — side-by-side metrics, equity overlay | Medium | M | Client UI |
| Full TypeScript migration — compile-time type safety | Medium | L | Client |

---

## Feature Ideas

| Idea | Impact | Effort | What it touches |
|------|--------|--------|-----------------|
| Mainnet trading support — mode selector, confirmation dialog, red banner | High | M | Engine + Server + Client |
| Monte Carlo / walk-forward optimization — IS/OOS windows, parameter stability | High | L | Engine |
| Multi-exchange support — abstract exchange interface | Medium | L | Engine |

---

**How to use:** When you're ready to plan optimization work, pick items from above, assess against current needs, and create proper plan docs. Until then, this is just a reference.
