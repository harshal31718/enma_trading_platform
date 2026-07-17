"""Plan 15 / fixes-queue F4 regression: the data-conversion CLI's export/
import round-trip must be exact, and re-importing the same file must be a
safe no-op (ON CONFLICT DO NOTHING).

Follows the repo's established hermetic-test convention (see
test_live_fill_booking.py's stubbed Binance layer, test_execution_event_log.py's
stubbed Mongo) — no live TimescaleDB/Mongo connection. A fake asyncpg
pool/connection backs the `candles` table with an in-memory list and
replicates the real unique index (time, exchange, symbol, timeframe,
instrument_type) for ON CONFLICT DO NOTHING semantics; a fake Mongo
collection backs `backtestTrades`.

Run inside the container::

    docker exec enma_trading_platform-engine-1 pytest /app/tests/test_cli_roundtrip.py
"""
import asyncio
import json
from datetime import date, datetime, timezone

import pytest

import scripts.enma_cli as cli
from scripts._io_formats import (
    CANDLE_COLUMNS,
    candle_record_to_row,
    candle_row_to_insert_tuple,
    read_csv,
    read_json,
    trade_doc_to_row,
    write_csv,
    write_json,
)

SYMBOL = "BTCUSDT"
TF = "1h"
EXCHANGE = "Binance Futures"


def _make_candle_rec(hour: int, expiry=None) -> dict:
    """A plain dict stands in for an asyncpg.Record — both support `rec["col"]`."""
    return {
        "time": datetime(2024, 1, 1, hour, tzinfo=timezone.utc),
        "exchange": EXCHANGE,
        "symbol": SYMBOL,
        "timeframe": TF,
        "instrument_type": "futures",
        "expiry": expiry,
        "open": 100.0 + hour,
        "high": 101.5 + hour,
        "low": 99.25 + hour,
        "close": 100.75 + hour,
        "volume": 12.34 + hour,
        "quote_volume": 1234.5678 + hour,
    }


# ── Fake asyncpg pool/connection backing an in-memory "candles" table ───────

class _FakeConn:
    def __init__(self, store: list):
        self.store = store

    async def fetch(self, query, exchange, symbol, timeframe, start, end):
        rows = [
            r for r in self.store
            if r["exchange"] == exchange and r["symbol"] == symbol and r["timeframe"] == timeframe
            and start <= r["time"] < end
        ]
        rows.sort(key=lambda r: r["time"])
        return rows

    async def executemany(self, query, rows):
        # Replicates the real unique index — ON CONFLICT DO NOTHING.
        for row in rows:
            key = (row[0], row[1], row[2], row[3], row[4])
            existing_keys = {
                (r["time"], r["exchange"], r["symbol"], r["timeframe"], r["instrument_type"])
                for r in self.store
            }
            if key in existing_keys:
                continue
            self.store.append(dict(zip(CANDLE_COLUMNS, row)))


class _AcquireCtx:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *exc):
        return False


class _FakePool:
    def __init__(self, store: list):
        self._conn = _FakeConn(store)

    def acquire(self):
        return _AcquireCtx(self._conn)


@pytest.fixture
def candle_store(monkeypatch):
    store: list = []
    pool = _FakePool(store)

    async def _noop():
        return None

    monkeypatch.setattr(cli, "init_pool", _noop)
    monkeypatch.setattr(cli, "close_pool", _noop)
    monkeypatch.setattr(cli, "get_pool", lambda: pool)
    return store


# ── Fake Mongo collection backing "backtestTrades" ──────────────────────────

class _FakeCursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, *args, **kwargs):
        return self

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for d in self._docs:
            yield d


class _FakeCollection:
    def __init__(self, docs):
        self._docs = docs

    def find(self, query):
        matched = [d for d in self._docs if d.get("jobId") == query.get("jobId")]
        return _FakeCursor(matched)


class _FakeDb:
    def __init__(self, docs):
        self.backtestTrades = _FakeCollection(docs)


@pytest.fixture
def trade_docs(monkeypatch):
    docs = [
        {
            "_id": "mongo-oid-1", "jobId": "job123", "userId": "u1", "tradeIndex": 1,
            "type": "long", "symbol": "BTCUSDT", "qty": "0.5", "entryPrice": "60000",
            "exitPrice": "61000", "entryAt": "2024-01-01T00:00:00Z", "exitAt": "2024-01-01T01:00:00Z",
            "exitReason": "take_profit", "pnl": "500", "pnlPct": "1.67", "leverage": 5,
            "liqPrice": "50000", "runUpPct": "2.0", "drawdownPct": "0.1", "barsHeld": 4,
            "entryTag": "", "exitTag": "",
        },
        {
            "_id": "mongo-oid-2", "jobId": "job123", "userId": "u1", "tradeIndex": 2,
            "type": "short", "symbol": "BTCUSDT", "qty": "0.5", "entryPrice": "61500",
            "exitPrice": "61000", "entryAt": "2024-01-01T02:00:00Z", "exitAt": "2024-01-01T03:00:00Z",
            "exitReason": "stop_loss", "pnl": "-250", "pnlPct": "-0.4", "leverage": 5,
            "liqPrice": "70000", "runUpPct": "0.5", "drawdownPct": "0.8", "barsHeld": 2,
            "entryTag": "", "exitTag": "",
        },
    ]

    def _fake_get_database():
        return _FakeDb(docs)

    monkeypatch.setattr(cli, "get_database", _fake_get_database)
    monkeypatch.setattr(cli, "close_mongo", lambda: None)
    return docs


def _args(**kw):
    import argparse
    return argparse.Namespace(**kw)


# ── _io_formats.py: pure transform round-trip ───────────────────────────────

def test_candle_record_to_row_and_back_preserves_all_fields_with_expiry():
    rec = _make_candle_rec(0, expiry=date(2024, 6, 28))
    row = candle_record_to_row(rec)
    assert row["expiry"] == "2024-06-28"
    tup = candle_row_to_insert_tuple(row)
    assert tup[5] == date(2024, 6, 28)
    assert tup[6:] == (rec["open"], rec["high"], rec["low"], rec["close"], rec["volume"], rec["quote_volume"])
    assert tup[0] == rec["time"]


def test_candle_record_to_row_none_expiry_survives_csv_not_as_the_string_none(tmp_path):
    rec = _make_candle_rec(0, expiry=None)
    row = candle_record_to_row(rec)
    assert row["expiry"] is None

    path = tmp_path / "one.csv"
    write_csv(str(path), [row], CANDLE_COLUMNS)
    reread = read_csv(str(path))
    assert reread[0]["expiry"] == ""  # empty, never the literal "None"

    tup = candle_row_to_insert_tuple(reread[0])
    assert tup[5] is None


def test_candle_json_roundtrip_preserves_float_precision(tmp_path):
    rec = _make_candle_rec(3)
    row = candle_record_to_row(rec)
    path = tmp_path / "candles.json"
    write_json(str(path), [row])
    reread = read_json(str(path))
    tup = candle_row_to_insert_tuple(reread[0])
    assert tup[6:] == (rec["open"], rec["high"], rec["low"], rec["close"], rec["volume"], rec["quote_volume"])


# ── CLI commands: export -> import -> re-export round trip ─────────────────

def test_export_then_import_candles_csv_roundtrip_is_exact(candle_store, tmp_path):
    candle_store.extend(_make_candle_rec(h) for h in range(3))
    out_path = tmp_path / "btc_1h.csv"

    export_args = _args(
        symbol=SYMBOL, tf=TF, exchange=EXCHANGE, out=str(out_path), format=None,
        start="2024-01-01T00:00:00+00:00", end="2024-01-01T03:00:00+00:00",
    )
    rc = asyncio.get_event_loop().run_until_complete(cli.cmd_export_candles(export_args))
    assert rc == 0
    exported_rows = read_csv(str(out_path))
    assert len(exported_rows) == 3

    # Clear the "table" and re-import from the exported file.
    candle_store.clear()
    import_args = _args(infile=str(out_path), format=None)
    rc = asyncio.get_event_loop().run_until_complete(cli.cmd_import_candles(import_args))
    assert rc == 0
    assert len(candle_store) == 3

    # Re-export and compare row-for-row against the original export.
    out_path_2 = tmp_path / "btc_1h_2.csv"
    export_args_2 = _args(
        symbol=SYMBOL, tf=TF, exchange=EXCHANGE, out=str(out_path_2), format=None,
        start="2024-01-01T00:00:00+00:00", end="2024-01-01T03:00:00+00:00",
    )
    asyncio.get_event_loop().run_until_complete(cli.cmd_export_candles(export_args_2))
    re_exported_rows = read_csv(str(out_path_2))
    assert re_exported_rows == exported_rows


def test_export_then_import_candles_json_roundtrip_is_exact(candle_store, tmp_path):
    candle_store.extend(_make_candle_rec(h) for h in range(2))
    out_path = tmp_path / "btc_1h.json"

    export_args = _args(
        symbol=SYMBOL, tf=TF, exchange=EXCHANGE, out=str(out_path), format=None,
        start="2024-01-01T00:00:00+00:00", end="2024-01-01T02:00:00+00:00",
    )
    asyncio.get_event_loop().run_until_complete(cli.cmd_export_candles(export_args))
    exported_rows = read_json(str(out_path))
    assert len(exported_rows) == 2

    candle_store.clear()
    import_args = _args(infile=str(out_path), format=None)
    asyncio.get_event_loop().run_until_complete(cli.cmd_import_candles(import_args))
    assert len(candle_store) == 2
    # Re-query directly from the store, bypassing another export round.
    assert sorted(r["open"] for r in candle_store) == sorted(r["open"] for r in exported_rows)


def test_reimporting_the_same_file_is_a_noop(candle_store, tmp_path):
    candle_store.extend(_make_candle_rec(h) for h in range(2))
    out_path = tmp_path / "btc_1h.csv"
    export_args = _args(
        symbol=SYMBOL, tf=TF, exchange=EXCHANGE, out=str(out_path), format=None,
        start="2024-01-01T00:00:00+00:00", end="2024-01-01T02:00:00+00:00",
    )
    asyncio.get_event_loop().run_until_complete(cli.cmd_export_candles(export_args))

    import_args = _args(infile=str(out_path), format=None)
    # Import into the SAME (already-populated) store twice.
    asyncio.get_event_loop().run_until_complete(cli.cmd_import_candles(import_args))
    asyncio.get_event_loop().run_until_complete(cli.cmd_import_candles(import_args))
    assert len(candle_store) == 2  # no duplicates


def test_export_candles_reports_failure_when_range_is_empty(candle_store, tmp_path):
    out_path = tmp_path / "empty.csv"
    export_args = _args(
        symbol=SYMBOL, tf=TF, exchange=EXCHANGE, out=str(out_path), format=None,
        start="2030-01-01T00:00:00+00:00", end="2030-01-02T00:00:00+00:00",
    )
    rc = asyncio.get_event_loop().run_until_complete(cli.cmd_export_candles(export_args))
    assert rc == 1
    assert not out_path.exists()


# ── export-trades ────────────────────────────────────────────────────────────

def test_export_trades_json_writes_expected_rows(trade_docs, tmp_path):
    out_path = tmp_path / "trades.json"
    args = _args(job_id="job123", out=str(out_path), format=None)
    rc = asyncio.get_event_loop().run_until_complete(cli.cmd_export_trades(args))
    assert rc == 0

    rows = json.loads(out_path.read_text())
    assert len(rows) == 2
    assert rows[0]["tradeIndex"] == 1
    assert rows[0]["symbol"] == "BTCUSDT"
    assert "_id" not in rows[0]  # Mongo internals dropped


def test_export_trades_reports_failure_for_unknown_job_id(trade_docs, tmp_path):
    out_path = tmp_path / "trades.json"
    args = _args(job_id="does-not-exist", out=str(out_path), format=None)
    rc = asyncio.get_event_loop().run_until_complete(cli.cmd_export_trades(args))
    assert rc == 1
    assert not out_path.exists()


def test_trade_doc_to_row_drops_mongo_id_and_fills_missing_fields():
    row = trade_doc_to_row({"_id": "x", "jobId": "j1", "symbol": "ETHUSDT"})
    assert "_id" not in row
    assert row["jobId"] == "j1"
    assert row["symbol"] == "ETHUSDT"
    assert row["exitTag"] == ""  # defaulted, not KeyError


# ── format inference ─────────────────────────────────────────────────────────

def test_infer_format_from_extension():
    assert cli._infer_format("foo.csv", None) == "csv"
    assert cli._infer_format("foo.json", None) == "json"
    assert cli._infer_format("foo.csv", "json") == "json"  # explicit wins


def test_infer_format_raises_on_unknown_extension():
    with pytest.raises(ValueError):
        cli._infer_format("foo.txt", None)
