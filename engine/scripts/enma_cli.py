"""Enma data conversion CLI (Plan 15 / fixes-queue F4).

Offline export/import of candle data (TimescaleDB) and read-only export of
backtest trades (MongoDB `backtestTrades`), for reproducible datasets,
sharing, and offline analysis outside the running stack.

REQUIRES the engine's databases — run INSIDE the engine container (root
CLAUDE.md Rule B):

    docker compose exec engine python -m scripts.enma_cli list-data

    docker compose exec engine python -m scripts.enma_cli export-candles \\
        --symbol BTCUSDT --tf 1h --start 2024-01-01 --end 2024-12-31 \\
        --format csv --out /data/btc_1h.csv

    docker compose exec engine python -m scripts.enma_cli import-candles \\
        --in /data/btc_1h.csv

    docker compose exec engine python -m scripts.enma_cli export-trades \\
        --job-id <id> --format json --out /data/trades.json

This is a **local-data tool only** — it never calls Binance. If a requested
candle range is missing, it reports that and exits non-zero; it does not
fetch (that's `services/candle_importer.py`'s job, invoked via the running
API, not this CLI). `import-candles` reuses the exact same
`INSERT ... ON CONFLICT DO NOTHING` as `candle_importer.py`, so re-importing
the same file is always a safe no-op.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# `python -m scripts.enma_cli` run from /app (the container's cwd) already
# resolves `config`/`services` as top-level packages — no import-path hack
# needed here (unlike golden_master.py, this CLI never loads strategy code).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # engine/

from config.mongo import close_mongo, get_database
from config.timescale import close_pool, get_pool, init_pool
from services.candle_manager import get_cached_candles_summary
from scripts._io_formats import (
    CANDLE_COLUMNS,
    TRADE_EXPORT_COLUMNS,
    candle_record_to_row,
    candle_row_to_insert_tuple,
    read_csv,
    read_json,
    trade_doc_to_row,
    write_csv,
    write_json,
)

_CANDLE_INSERT_SQL = """
    INSERT INTO candles
      (time, exchange, symbol, timeframe, instrument_type, expiry, open, high, low, close, volume, quote_volume)
    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
    ON CONFLICT DO NOTHING
"""

_CANDLE_SELECT_SQL = """
    SELECT time, exchange, symbol, timeframe, instrument_type, expiry,
           open, high, low, close, volume, quote_volume
    FROM candles
    WHERE exchange = $1 AND symbol = $2 AND timeframe = $3
      AND time >= $4 AND time < $5
    ORDER BY time
"""


def _infer_format(path: str, explicit: str | None) -> str:
    if explicit:
        return explicit
    ext = os.path.splitext(path)[1].lower()
    if ext == ".csv":
        return "csv"
    if ext == ".json":
        return "json"
    raise ValueError(f"Cannot infer format from '{path}' — pass --format csv|json explicitly")


def _parse_utc(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


async def cmd_list_data(args: argparse.Namespace) -> int:
    await init_pool()
    try:
        summary = await get_cached_candles_summary()
    finally:
        await close_pool()

    if not summary:
        print("No cached candles found.")
        return 0

    print(f"{'symbol':<12} {'tf':<6} {'exchange':<16} {'type':<8} {'start':<26} {'end':<26} {'count':>10}")
    for row in summary:
        print(
            f"{row['symbol']:<12} {row['timeframe']:<6} {row['exchange']:<16} "
            f"{row['instrument_type']:<8} {str(row['start_date']):<26} {str(row['end_date']):<26} "
            f"{row['total_candles']:>10}"
        )
    return 0


async def cmd_export_candles(args: argparse.Namespace) -> int:
    fmt = _infer_format(args.out, args.format)
    start_dt = _parse_utc(args.start)
    end_dt = _parse_utc(args.end)

    await init_pool()
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            records = await conn.fetch(
                _CANDLE_SELECT_SQL, args.exchange, args.symbol, args.tf, start_dt, end_dt
            )
    finally:
        await close_pool()

    if not records:
        print(f"No candles found for {args.symbol} {args.tf} on {args.exchange} in that range — nothing exported.")
        return 1

    rows = [candle_record_to_row(r) for r in records]
    if fmt == "csv":
        write_csv(args.out, rows, CANDLE_COLUMNS)
    else:
        write_json(args.out, rows)
    print(f"Exported {len(rows)} candles to {args.out} ({fmt}).")
    return 0


async def cmd_import_candles(args: argparse.Namespace) -> int:
    fmt = _infer_format(args.infile, args.format)
    rows = read_csv(args.infile) if fmt == "csv" else read_json(args.infile)
    if not rows:
        print(f"No rows found in {args.infile} — nothing to import.")
        return 1

    insert_rows = [candle_row_to_insert_tuple(r) for r in rows]

    await init_pool()
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.executemany(_CANDLE_INSERT_SQL, insert_rows)
    finally:
        await close_pool()

    print(f"Imported {len(insert_rows)} candle rows from {args.infile} (ON CONFLICT DO NOTHING — re-import is a no-op).")
    return 0


async def cmd_export_trades(args: argparse.Namespace) -> int:
    fmt = _infer_format(args.out, args.format)
    db = get_database()
    try:
        cursor = db.backtestTrades.find({"jobId": args.job_id}).sort("tradeIndex", 1)
        docs = [doc async for doc in cursor]
    finally:
        close_mongo()

    if not docs:
        print(f"No trades found for jobId={args.job_id} — nothing exported.")
        return 1

    rows = [trade_doc_to_row(d) for d in docs]
    if fmt == "csv":
        write_csv(args.out, rows, TRADE_EXPORT_COLUMNS)
    else:
        write_json(args.out, rows)
    print(f"Exported {len(rows)} trades to {args.out} ({fmt}).")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="enma_cli",
        description="Enma data conversion CLI — export/import candles, export backtest trades. "
                    "Run inside the engine container.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list-data", help="Inventory cached candles (matches GET /candles/cached).")

    p_export_c = sub.add_parser("export-candles", help="Export a candle range to CSV/JSON.")
    p_export_c.add_argument("--symbol", required=True)
    p_export_c.add_argument("--tf", required=True, help="Timeframe, e.g. 1h, 1m, 1d.")
    p_export_c.add_argument("--start", required=True, help="ISO date/datetime, e.g. 2024-01-01.")
    p_export_c.add_argument("--end", required=True, help="ISO date/datetime, e.g. 2024-12-31.")
    p_export_c.add_argument("--out", required=True, help="Output file path.")
    p_export_c.add_argument("--format", choices=["csv", "json"], default=None,
                             help="Defaults to the --out file extension.")
    p_export_c.add_argument("--exchange", default="Binance Futures")

    p_import_c = sub.add_parser("import-candles", help="Import candles from a CSV/JSON file (idempotent).")
    p_import_c.add_argument("--in", dest="infile", required=True, help="Input file path.")
    p_import_c.add_argument("--format", choices=["csv", "json"], default=None,
                             help="Defaults to the --in file extension.")

    p_export_t = sub.add_parser("export-trades", help="Export backtestTrades for a job to CSV/JSON.")
    p_export_t.add_argument("--job-id", required=True, dest="job_id")
    p_export_t.add_argument("--out", required=True)
    p_export_t.add_argument("--format", choices=["csv", "json"], default=None,
                             help="Defaults to the --out file extension.")

    return p


_HANDLERS = {
    "list-data": cmd_list_data,
    "export-candles": cmd_export_candles,
    "import-candles": cmd_import_candles,
    "export-trades": cmd_export_trades,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return asyncio.run(_HANDLERS[args.cmd](args))


if __name__ == "__main__":
    sys.exit(main())
