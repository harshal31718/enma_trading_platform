"""CSV/JSON read+write helpers for the data-conversion CLI (Plan 15 /
fixes-queue F4). Pure I/O + transform functions, no DB access — kept
separate from `enma_cli.py` so the transforms are independently testable
without a live TimescaleDB/Mongo connection.

Candle schema (12 columns, matches `docker/timescale/init.sql`'s `candles`
table and `services/candle_importer.py`'s INSERT exactly):
    time, exchange, symbol, timeframe, instrument_type, expiry,
    open, high, low, close, volume, quote_volume

`open`/`high`/`low`/`close`/`volume`/`quote_volume` are Postgres NUMERIC,
which asyncpg returns as `decimal.Decimal` — converted to `float` here to
match every other consumer in this codebase (candle_importer.py inserts
`float(...)`, the rest of the pipeline is float-based pending Plan 5.5's
Decimal migration). `expiry` is a nullable Postgres DATE.
"""
from __future__ import annotations

import csv
import json
from datetime import date, datetime
from typing import Any

CANDLE_COLUMNS = [
    "time", "exchange", "symbol", "timeframe", "instrument_type", "expiry",
    "open", "high", "low", "close", "volume", "quote_volume",
]

TRADE_EXPORT_COLUMNS = [
    "jobId", "userId", "tradeIndex", "type", "symbol", "qty", "entryPrice",
    "exitPrice", "entryAt", "exitAt", "exitReason", "pnl", "pnlPct", "leverage",
    "liqPrice", "runUpPct", "drawdownPct", "barsHeld", "entryTag", "exitTag",
]


# ── Candles ──────────────────────────────────────────────────────────────────

def candle_record_to_row(rec: Any) -> dict:
    """asyncpg Record (or any mapping with the same keys) -> a plain,
    JSON/CSV-safe dict. `time` becomes an ISO 8601 string; `expiry` becomes
    an ISO date string or `None` (never the literal string "None" — callers
    writing CSV must pass this through `_csv_safe` first)."""
    expiry = rec["expiry"]
    return {
        "time": rec["time"].isoformat(),
        "exchange": rec["exchange"],
        "symbol": rec["symbol"],
        "timeframe": rec["timeframe"],
        "instrument_type": rec["instrument_type"],
        "expiry": expiry.isoformat() if expiry else None,
        "open": float(rec["open"]),
        "high": float(rec["high"]),
        "low": float(rec["low"]),
        "close": float(rec["close"]),
        "volume": float(rec["volume"]),
        "quote_volume": float(rec["quote_volume"]),
    }


def candle_row_to_insert_tuple(row: dict) -> tuple:
    """A dict read back from CSV (all-string values) or JSON (native types)
    -> a 12-tuple in the exact column order `services/candle_importer.py`'s
    INSERT expects. Idempotent with itself: calling this on the output of
    `candle_record_to_row` (round-tripped through CSV or JSON) reproduces
    the original insert-ready values exactly."""
    time_val = row["time"]
    if isinstance(time_val, str):
        time_val = datetime.fromisoformat(time_val)

    expiry_raw = row.get("expiry")
    expiry_val: date | None
    if not expiry_raw:
        expiry_val = None
    elif isinstance(expiry_raw, str):
        expiry_val = date.fromisoformat(expiry_raw)
    else:
        expiry_val = expiry_raw

    return (
        time_val,
        row["exchange"],
        row["symbol"],
        row["timeframe"],
        row["instrument_type"],
        expiry_val,
        float(row["open"]),
        float(row["high"]),
        float(row["low"]),
        float(row["close"]),
        float(row["volume"]),
        float(row["quote_volume"]),
    )


# ── Trades (export-only — no import-trades command in Plan 15) ─────────────

def trade_doc_to_row(doc: dict) -> dict:
    """Mongo `backtestTrades` document -> a flat CSV/JSON-safe dict, in the
    fixed column order below. Drops Mongo's `_id`; missing fields default to
    an empty string (older documents may predate a field)."""
    return {col: doc.get(col, "") for col in TRADE_EXPORT_COLUMNS}


# ── CSV / JSON I/O ───────────────────────────────────────────────────────────

def _csv_safe(row: dict) -> dict:
    """None has no CSV representation — write it as empty string, never the
    literal text "None" (which would fail to parse back on import)."""
    return {k: ("" if v is None else v) for k, v in row.items()}


def write_csv(path: str, rows: list[dict], columns: list[str]) -> None:
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow(_csv_safe(row))


def read_csv(path: str) -> list[dict]:
    with open(path, "r", newline="") as f:
        return [dict(r) for r in csv.DictReader(f)]


def write_json(path: str, rows: list[dict]) -> None:
    with open(path, "w") as f:
        json.dump(rows, f, indent=2)


def read_json(path: str) -> list[dict]:
    with open(path, "r") as f:
        return json.load(f)
