"""Golden-master harness for the Five-Model refactor (see plan.md §7).

Runs the seeded strategies through the REAL backtest runner with fixed,
deterministic parameters and records each run's metrics to JSON. Used to gate
every phase: capture a baseline, apply the phase, re-run, and assert the metrics
are unchanged within float tolerance.

REQUIRES TA-Lib + the engine databases → run INSIDE the engine container:

    # Capture a snapshot (writes scripts/golden/<label>.json):
    docker compose exec engine python -m scripts.golden_master run --label baseline

    # ...apply the phase, then:
    docker compose exec engine python -m scripts.golden_master run --label phase1

    # Assert equality (exit 0 = identical within tolerance, 1 = drift):
    docker compose exec engine python -m scripts.golden_master compare --a baseline --b phase1

Determinism: identical candles (fixed symbol/timeframe/date range) + identical
params + no randomness ⇒ identical metrics. Results are written to MongoDB under
``jobId = gm_<label>_<strategy>`` so they never collide with real backtests.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

# Replicate the engine's production import environment (see main.py): seeded
# strategies import ``from engine.core...`` / ``import engine.indicators``, which
# resolve via the ``/engine -> /app`` symlink with ``/`` on sys.path. ``python -m``
# already puts /app (cwd) on the path so ``core``/``services`` resolve; we add the
# symlink + ``/`` so ``engine`` resolves too — otherwise the harness loads the
# strategies in a different import root than the real runner and every load fails.
try:
    if not os.path.exists("/engine"):
        os.symlink("/app", "/engine")
except Exception:
    pass
sys.path.insert(0, "/")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # engine/

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# The five seeded strategies (Alpha Models). Keep in sync with strategy_seeder.
STRATEGIES = [
    "MicroScalper",
    "AdaptiveTrend",
    "BestSupertrend",
    "MicroMacroRSIDivergence",
    "MultiDivergence",
]

# Fixed, settled-history config — deterministic across runs.
DEFAULT_CONFIG = {
    "exchange": "Binance Futures",
    "symbol": "BTCUSDT",
    "timeframe": "1h",
    "start_date": "2024-01-01",
    "end_date": "2025-01-01",
    "capital": 10_000.0,
    "leverage": 3,
    "fee_rate": 0.0005,
    "slippage_pct": 0.0005,
    "funding_enabled": False,
    "funding_rate": 0.0,
    "risk_params": {
        "risk_pct": 0.01,
        "rrr": 2.0,
        "liq_buffer_pct": 0.005,
        "max_session_dd": 0.20,
    },
}

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "golden")


def _out_path(label: str) -> str:
    return os.path.join(OUT_DIR, f"{label}.json")


async def _run(label: str, cfg: dict, strategies: list[str]) -> dict:
    from config.timescale import init_pool, close_pool
    from config.mongo import close_mongo, get_database
    from services.backtest_runner import run_backtest_simulation

    await init_pool()
    results: dict[str, dict] = {}
    try:
        for name in strategies:
            job_id = f"gm_{label}_{name}"
            print(f"[golden] running {name} ...", flush=True)
            try:
                out = await run_backtest_simulation(
                    job_id=job_id,
                    strategy_file=f"strategies/{name}/__init__.py",
                    exchange=cfg["exchange"],
                    symbol=cfg["symbol"],
                    timeframe=cfg["timeframe"],
                    start_date=cfg["start_date"],
                    end_date=cfg["end_date"],
                    capital=cfg["capital"],
                    leverage=cfg["leverage"],
                    fee_rate=cfg["fee_rate"],
                    slippage_pct=cfg["slippage_pct"],
                    funding_enabled=cfg["funding_enabled"],
                    funding_rate=cfg["funding_rate"],
                    alpha_params=None,
                    risk_params=cfg["risk_params"],
                )
                # Capture metrics (legacy + Phase 2 fields) plus the new
                # curves persisted in the result document. We pull directly
                # from MongoDB so every persisted field is captured —
                # including underwaterCurve, rollingMetricsCurve,
                # returnsHistogram, mfeMaeScatter (Phase 2 additions).
                metrics_payload = out.get("metrics", {})
                try:
                    db = get_database()
                    doc = await db.backtestResults.find_one({"jobId": job_id})
                    if doc is not None:
                        # Carry over the Phase 2 top-level fields
                        for k in ("underwaterCurve",
                                  "rollingMetricsCurve",
                                  "returnsHistogram",
                                  "mfeMaeScatter"):
                            if k in doc:
                                metrics_payload[k] = doc[k]
                except Exception as e:
                    print(f"[golden]   {name}: curve capture failed: {e}", flush=True)
                results[name] = metrics_payload
                m = results[name]
                print(f"[golden]   {name}: trades={m.get('totalTrades')} "
                      f"netProfit={m.get('netProfit')} winRate={m.get('winRate')} "
                      f"cagr={m.get('cagrPct')} sqn={m.get('sqn')}", flush=True)
            except Exception as e:
                results[name] = {"__error__": str(e)}
                print(f"[golden]   {name}: ERROR {e}", flush=True)
    finally:
        await close_pool()
        close_mongo()

    os.makedirs(OUT_DIR, exist_ok=True)
    payload = {"label": label, "config": cfg, "results": results}
    with open(_out_path(label), "w") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
    print(f"[golden] wrote {_out_path(label)}")
    return payload


def _as_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _compare(a_label: str, b_label: str, tol: float) -> int:
    with open(_out_path(a_label)) as f:
        a = json.load(f)
    with open(_out_path(b_label)) as f:
        b = json.load(f)

    a_res, b_res = a["results"], b["results"]
    drift: list[str] = []
    names = sorted(set(a_res) | set(b_res))
    for name in names:
        am, bm = a_res.get(name), b_res.get(name)
        if am is None or bm is None:
            drift.append(f"{name}: missing in {'A' if am is None else 'B'}")
            continue
        if "__error__" in am or "__error__" in bm:
            drift.append(f"{name}: errored (A={am.get('__error__')} B={bm.get('__error__')})")
            continue
        keys = sorted(set(am) | set(bm))
        for k in keys:
            av, bv = am.get(k), bm.get(k)
            af, bf = _as_float(av), _as_float(bv)
            if af is not None and bf is not None:
                if abs(af - bf) > tol * max(1.0, abs(af), abs(bf)):
                    drift.append(f"{name}.{k}: {av} != {bv}")
            elif av != bv:
                drift.append(f"{name}.{k}: {av!r} != {bv!r}")

    if drift:
        print(f"GOLDEN-MASTER DRIFT ({a_label} vs {b_label}):")
        for d in drift:
            print("  -", d)
        return 1
    print(f"GOLDEN-MASTER OK — {a_label} == {b_label} within tol={tol} "
          f"({len(names)} strategies)")
    return 0


def main() -> None:
    p = argparse.ArgumentParser(description="Five-Model golden-master harness")
    sub = p.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("run", help="run strategies and snapshot metrics")
    pr.add_argument("--label", required=True)
    pr.add_argument("--symbol")
    pr.add_argument("--timeframe")
    pr.add_argument("--start")
    pr.add_argument("--end")
    pr.add_argument("--only", help="comma-separated subset of strategies")

    pc = sub.add_parser("compare", help="assert two snapshots match")
    pc.add_argument("--a", required=True)
    pc.add_argument("--b", required=True)
    pc.add_argument("--tol", type=float, default=1e-6)

    args = p.parse_args()

    if args.cmd == "run":
        cfg = dict(DEFAULT_CONFIG)
        if args.symbol:
            cfg["symbol"] = args.symbol
        if args.timeframe:
            cfg["timeframe"] = args.timeframe
        if args.start:
            cfg["start_date"] = args.start
        if args.end:
            cfg["end_date"] = args.end
        strategies = (
            [s.strip() for s in args.only.split(",") if s.strip()]
            if args.only else STRATEGIES
        )
        asyncio.run(_run(args.label, cfg, strategies))
    elif args.cmd == "compare":
        sys.exit(_compare(args.a, args.b, args.tol))


if __name__ == "__main__":
    main()
