# Plan 15 — Data Conversion CLI

**Status:** Shipped 2026-07-16 (fixes-queue F4) · **Priority:** P3 · **Phase:** 9 · **Depends on:** 11 (independent) · **Related:** —

**Goal:** A small command-line tool to export/import candle and backtest-trade data between
TimescaleDB and flat files (CSV/JSON), for offline analysis, sharing, and reproducible datasets.

## Shipped summary (2026-07-16)

Implemented exactly as designed below — four subcommands in `engine/scripts/enma_cli.py`
(`list-data`, `export-candles`, `import-candles`, `export-trades`), pure CSV/JSON<->DB-record
transforms in `engine/scripts/_io_formats.py` (stdlib `csv`/`json` only, no new deps, `engine/
CLAUDE.md` updated). `list-data` reuses `services/candle_manager.py`'s
`get_cached_candles_summary()` verbatim rather than reimplementing the query, which structurally
guarantees it matches `GET /candles/cached`. `import-candles` reuses `services/
candle_importer.py`'s exact `INSERT ... ON CONFLICT DO NOTHING` (same column order, same
conflict target), so re-importing a file is always a safe no-op. `export-trades` is read-only —
no `import-trades` command exists, matching the original design (no round-trip requirement for
trades).

Verification, three ways: (1) 12 new hermetic tests in `engine/tests/test_cli_roundtrip.py`,
following the repo's established mocking convention (a fake asyncpg pool/connection replicating
the real `(time, exchange, symbol, timeframe, instrument_type)` unique index for ON CONFLICT
semantics; a fake Mongo collection for `backtestTrades`) — no live DB dependency in the test
itself. Full engine suite 142/142 (130 + 12) after this change. (2) A real round trip against the
live stack's actual TimescaleDB data: exported BTCUSDT/1d (565 rows, the smallest cached set) to
CSV, re-imported the same file into the same live table, confirmed via `list-data` that the count
stayed at exactly 565 — no duplication, genuinely idempotent against production data, not just a
mock. (3) `list-data`'s real output was inspected directly against the live cache inventory.

CSV precision note (flagged as a risk in the original design): candle columns are Postgres
NUMERIC, which asyncpg returns as `decimal.Decimal`; converted to Python `float` on export to
match every other consumer in this not-yet-Decimal codebase (Plan 5.5 hasn't landed). Python's
`str(float)` is a shortest-round-tripping representation since Python 3.1, so the CSV path
round-trips exactly for any float actually produced by this pipeline — verified directly in the
hermetic tests, not just assumed.

Files: new `engine/scripts/enma_cli.py`, new `engine/scripts/_io_formats.py`, new `engine/tests/
test_cli_roundtrip.py`, `engine/CLAUDE.md` (folder-structure doc).

---

## Current state (audited)

- **No CLI exists** — grep for `*cli*` outside `node_modules` finds nothing in `engine/` or `server/`.
- Candle data lives **only** in TimescaleDB (`candles` hypertable), reached via asyncpg through
  `engine/config/timescale.py`. There is no export path today — backtests always re-query Timescale.
- Backtest trades live in MongoDB `backtestTrades` (engine is sole writer).

## Upstream reference

- **freqtrade `convert-data` / `convert-trade-data`** — CLI subcommands that convert OHLCV between
  formats (json, jsongz, hdf5, feather, parquet) and between exchanges' on-disk layouts. Pure I/O, no
  network. Also `list-data` to inventory what's stored.
- **nautilus `ParquetDataCatalog`** — a versioned on-disk catalog; CSV→Parquet ingest with a defined
  schema. Heavier than we need now (full catalog is deferred in `ref_gap-matrix-freqtrade-nautilus.md`).

Port freqtrade's *lightweight* idea: a focused converter + an inventory command. Skip the catalog.

## Design (Enma-native)

A thin Python CLI in the engine container (engine owns Timescale + Mongo access; **must run inside
Docker** per root `CLAUDE.md` Rule B). No new web surface.

### Commands (`engine/scripts/enma_cli.py`, argparse)
```
python -m scripts.enma_cli list-data
    → prints the same inventory as GET /candles/cached (symbol/tf/range/count)

python -m scripts.enma_cli export-candles --symbol BTCUSDT --tf 1h \
    --start 2024-01-01 --end 2024-12-31 --format csv --out /data/btc_1h.csv
    → reads candles via the asyncpg pool, writes CSV/JSON (12-column schema)

python -m scripts.enma_cli import-candles --in /data/btc_1h.csv
    → INSERT ... ON CONFLICT DO NOTHING (idempotent, same guarantee as candle_importer)

python -m scripts.enma_cli export-trades --job-id <id> --format json --out /data/trades.json
    → dumps backtestTrades for a run
```

### Rules it must respect (from engine `CLAUDE.md`)
- Reuse `ensure_candles_available()` semantics for any fetch; **never** call Binance directly here
  (this is a local-data tool — if a range is missing, report it, don't fetch).
- Candle schema is the full 12 columns `(time, exchange, symbol, timeframe, instrument_type, expiry,
  open, high, low, close, volume, quote_volume)`. Export and import must round-trip all 12.
- `instrument_type` uses `"futures"`/`"spot"` (never `"perpetual"`).
- Import uses `ON CONFLICT DO NOTHING` — re-import is always safe.

### Why a CLI (not an endpoint)
Bulk file I/O on the API event loop is wrong (root `CLAUDE.md`: never block the loop). A CLI invoked
via `docker compose exec engine` keeps it off the request path and matches freqtrade's UX.

## Files to create / modify

| Action | File | Change |
|--------|------|--------|
| Create | `engine/scripts/enma_cli.py` | argparse CLI: `list-data`, `export-candles`, `import-candles`, `export-trades` |
| Create | `engine/scripts/_io_formats.py` | CSV/JSON read+write helpers for the 12-col candle schema |
| Create | `engine/tests/test_cli_roundtrip.py` | export→import→re-query equals original rows exactly |
| Modify | `engine/CLAUDE.md` | document the CLI under "scripts" (no new pip deps — stdlib `csv`/`json`) |

## Verification gate

- **Round-trip equality:** export a known candle range to CSV, truncate a scratch table (or use a test
  schema), re-import, re-query → byte-equal rows (same ordering, same float values).
- `list-data` output matches `GET /candles/cached` for the same DB state.
- Re-importing the same file twice changes nothing (ON CONFLICT DO NOTHING verified).

## Sequencing & risks

- Independent — ship any time after V0. No pipeline touch, no golden master, no new deps.
- Risk: float precision on CSV round-trip. Use full `repr`/`%.10g` for doubles, or prefer JSON for
  exact round-trips; document the CSV precision caveat.
- Keep it stdlib-only (`csv`, `json`, `argparse`) — adding pandas-to-parquet would need a `CLAUDE.md`
  dependency update and is out of scope (parquet catalog is deferred).
