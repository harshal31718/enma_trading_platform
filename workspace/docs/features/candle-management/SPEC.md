# Feature: Candle Management

**Status:** Implemented
**Last updated:** 2026-07-02 — documented the Phase 7 unified symbol list + per-symbol rules response fields; previous version dated 2026-06-05.

---

## What It Does

Fetches OHLCV candle data from Binance REST API and stores it permanently in TimescaleDB. Candles are fetched automatically before every backtest — no manual import step. Once stored, candles are reused indefinitely across all future backtests for the same symbol and timeframe.

---

## Data Flow

### Auto-fetch (triggered by backtest)

```
Backtest starts in engine
        ↓
ensure_candles_available(exchange, symbol, timeframe, start_date, end_date)
        ↓
Query TimescaleDB: count existing candles in date range
        ↓
If sufficient: proceed immediately (no fetch needed)
        ↓
If insufficient:
  import_candles(exchange, symbol, timeframe, start - 200 candles, end)
          ↓
  For each 1,000-candle batch:
    GET https://fapi.binance.com/fapi/v1/klines  (Binance production)
    INSERT INTO candles ON CONFLICT DO NOTHING    (TimescaleDB)
    Publish progress to Redis progress:{jobId}
    Sleep 200ms (BINANCE_FETCH_DELAY_MS)
          ↓
  Returns True if now available, False on error
        ↓
Backtest proceeds with simulation
```

### Cached candle inventory (Dashboard)

```
Client fetches GET /api/v1/candles/cached
        ↓
Server proxies → engine GET /candles/cached
        ↓
Engine queries TimescaleDB:
  SELECT exchange, symbol, timeframe, instrument_type,
         MIN(time), MAX(time), COUNT(*)
  FROM candles
  GROUP BY exchange, symbol, timeframe, instrument_type
        ↓
Returns: [{ symbol, timeframe, exchange, type, startDate, endDate, totalCandles }]
```

---

## Service Responsibilities

| Layer | Owns | Does NOT own |
|-------|------|-------------|
| Client | Symbol list for forms, cached candle inventory display | Any candle fetching |
| Node server | Route proxy | Candle storage or fetching |
| Python engine | All candle fetching, all TimescaleDB writes | None |
| TimescaleDB | Permanent OHLCV storage | — |

---

## Key Invariants

- **`ensure_candles_available()` is the only entry point.** Never call `import_candles()` directly from routers or the simulation loop.
- **Server never connects to TimescaleDB.** All candle data flows through engine HTTP endpoints.
- **Candles are never deleted.** Once stored, candles persist indefinitely and are reused across backtests.
- **Idempotent inserts.** `INSERT ... ON CONFLICT DO NOTHING` — safe to re-fetch any overlapping range.
- **Fetch is from Binance production.** Candle data uses `https://fapi.binance.com` (not Testnet), regardless of trading mode. This is OHLCV data only, not order-related.
- **Extended fetch range.** The importer fetches `start - 200 candles` to ensure indicators have warmup data from the very first backtest candle.

---

## TimescaleDB Schema

**Table:** `candles` (hypertable, partitioned on `time`)

| Column | Type | Notes |
|--------|------|-------|
| `time` | TIMESTAMPTZ NOT NULL | Candle open timestamp |
| `exchange` | TEXT | e.g. `binance` |
| `symbol` | TEXT | e.g. `BTCUSDT` |
| `timeframe` | TEXT | e.g. `1h`, `4h`, `1d` |
| `instrument_type` | TEXT | `futures` or `spot` |
| `expiry` | TEXT | Always NULL (reserved for dated futures) |
| `open` | DOUBLE PRECISION | |
| `high` | DOUBLE PRECISION | |
| `low` | DOUBLE PRECISION | |
| `close` | DOUBLE PRECISION | |
| `volume` | DOUBLE PRECISION | |
| `quote_volume` | DOUBLE PRECISION | |

**Primary key / unique constraint:** `(exchange, symbol, timeframe, instrument_type, time)`  
**Index:** `(exchange, symbol, timeframe, time DESC)`

---

## REST Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/candles/symbols` | `{ futures, spot, all, rules }` — `all` is the Phase 7 unified/tiered symbol list; `rules` gives per-symbol precision/tick/leverage data consumed by the Trade page order form |
| GET | `/api/v1/candles/cached` | Inventory of cached candles in TimescaleDB |

---

## Fetch Parameters

| Parameter | Value | Notes |
|-----------|-------|-------|
| Batch size | 1,000 candles | Binance API max per request |
| Inter-batch delay | 200ms | Configurable via `BINANCE_FETCH_DELAY_MS` env var |
| Fetch source | `fapi.binance.com` | Production REST, not Testnet |
| Extended range | start - 200 candles | Ensures indicator warmup coverage |

---

## Related Files

| File | Role |
|------|------|
| `client/src/hooks/useCandles.js` | `useSymbols()` for populating form dropdowns |
| `server/src/routes/candle.routes.js` | GET /symbols, GET /cached proxy routes |
| `server/src/controllers/candle.controller.js` | Proxy to engine endpoints |
| `engine/routers/candles.py` | GET /symbols, GET /cached |
| `engine/services/candle_manager.py` | `ensure_candles_available()` — single entry point |
| `engine/services/candle_importer.py` | Binance fetch + TimescaleDB insert logic; asyncpg writes inline, no separate store module |
| `engine/services/pairlist.py` | Phase 7 dynamic pairlist pipeline (VolumePairList + filters) backing the unified symbol list |
| `engine/utils/timeframes.py` | Consolidated timeframe conversion utility |
| `engine/utils/symbols.py` | `load_symbol_volume_tiers()`, `get_all_rules()` — backs the `all`/`rules` fields on `/candles/symbols` |
