"""
Chaos Runner — thin client of POST /api/v1/algo/chaos.

Launches every strategy in max-volatility configuration on 1m timeframe for
pipeline stress testing.  Run from INSIDE the engine container (CLAUDE.md Rule B):

    docker exec enma_trading_platform-engine-1 python scripts/chaos_runner.py
    docker exec enma_trading_platform-engine-1 python scripts/chaos_runner.py --stop
    docker exec enma_trading_platform-engine-1 python scripts/chaos_runner.py --leverage 20

⚠️  TESTNET ONLY — sessions run on Binance Testnet (mode: paper).
    This script calls Node, which calls the engine, which calls Binance Testnet.
    It never touches mainnet credentials.

    When chaos sessions are running, the following symbols are locked and cannot
    be manually traded: BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT, XRPUSDT, DOGEUSDT, ADAUSDT.
    Run --stop (or Ctrl-C) to release all locks.
"""

import argparse
import os
import signal
import sys
import time

import httpx

SERVER_URL = os.getenv("SERVER_URL", "http://server:5000")
POLL_INTERVAL = 10  # seconds between status polls

_launched_session_ids: list[str] = []


def _banner():
    print("=" * 70)
    print("  ⚡ CHAOS MODE — Enma all-strategy stress runner")
    print("  TESTNET ONLY — Binance Testnet (paper trading mode)")
    print("=" * 70)


def launch_chaos() -> list[dict]:
    """Call POST /api/v1/algo/chaos and return the launched session list."""
    print("\n[chaos] Calling POST /api/v1/algo/chaos …")
    try:
        resp = httpx.post(f"{SERVER_URL}/api/v1/algo/chaos", timeout=60.0)
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        print(f"[chaos] ERROR: HTTP {e.response.status_code} — {e.response.text[:200]}")
        sys.exit(1)
    except httpx.RequestError as e:
        print(f"[chaos] ERROR: Could not reach Node server at {SERVER_URL}: {e}")
        sys.exit(1)

    body = resp.json()
    data = body.get("data", {})
    launched = data.get("launched", [])
    errors = data.get("errors", [])

    if launched:
        print(f"\n[chaos] Launched {len(launched)} session(s):")
        for s in launched:
            print(f"  ✓ {s['strategy']:<30} {s['sessionId']}  symbols={s['symbols']}")
    if errors:
        print(f"\n[chaos] {len(errors)} strategy(ies) failed to start:")
        for e in errors:
            print(f"  ✗ {e['strategy']:<30} {e['error']}")

    if not launched:
        print("\n[chaos] Nothing launched — check errors above and ensure Node + Engine are up.")
        sys.exit(1)

    return launched


def stop_sessions(session_ids: list[str]) -> None:
    """POST /api/v1/algo/sessions/:id/stop for each session."""
    print(f"\n[chaos] Stopping {len(session_ids)} session(s) …")
    for sid in session_ids:
        try:
            resp = httpx.post(f"{SERVER_URL}/api/v1/algo/sessions/{sid}/stop", timeout=30.0)
            ok = resp.status_code < 300
            print(f"  {'✓' if ok else '✗'} stop {sid}  → {resp.status_code}")
        except Exception as e:
            print(f"  ✗ stop {sid}  → {e}")


def poll_sessions(session_ids: list[str]) -> None:
    """Fetch session summaries and print a compact status table."""
    try:
        resp = httpx.get(f"{SERVER_URL}/api/v1/algo/sessions", timeout=10.0)
        resp.raise_for_status()
    except Exception:
        print("[chaos] Could not fetch session list")
        return

    sessions_by_id = {
        str(s["_id"]): s
        for s in resp.json().get("data", {}).get("sessions", [])
    }

    print(f"\n[chaos] Status @ t+{int(time.time() % 100000)}s")
    print(f"  {'Strategy':<30} {'Status':<12} {'PnL':>8}  {'Symbols'}")
    print("  " + "-" * 70)
    for sid in session_ids:
        s = sessions_by_id.get(sid)
        if not s:
            print(f"  {'<not found>':<30} {'?':<12} {'?':>8}  {sid}")
            continue
        pnl = s.get("pnl", "0")
        status = s.get("status", "?")
        syms = ",".join(s.get("symbols", []))
        name = s.get("strategyName", "?")
        print(f"  {name:<30} {status:<12} {float(pnl or 0):>8.2f}  {syms}")


def _setup_sigint(session_ids: list[str]) -> None:
    def _handler(sig, frame):
        print("\n[chaos] Ctrl-C received — stopping all sessions …")
        stop_sessions(session_ids)
        sys.exit(0)
    signal.signal(signal.SIGINT, _handler)


def main() -> None:
    parser = argparse.ArgumentParser(description="Chaos mode stress runner")
    parser.add_argument(
        "--stop",
        action="store_true",
        help="Stop all currently running sessions (uses GET /sessions to find them)",
    )
    parser.add_argument(
        "--leverage",
        type=int,
        default=None,
        help="Override requested leverage (default: 50, clamped per-symbol by engine)",
    )
    args = parser.parse_args()

    _banner()

    if args.stop:
        # Find running sessions and stop them
        try:
            resp = httpx.get(f"{SERVER_URL}/api/v1/algo/sessions", timeout=10.0)
            resp.raise_for_status()
            sessions = resp.json().get("data", {}).get("sessions", [])
        except Exception as e:
            print(f"[chaos] Could not fetch sessions: {e}")
            sys.exit(1)
        running = [s for s in sessions if s.get("status") in ("running", "starting")]
        if not running:
            print("[chaos] No running sessions found.")
            return
        ids = [str(s["_id"]) for s in running]
        stop_sessions(ids)
        return

    launched = launch_chaos()
    session_ids = [s["sessionId"] for s in launched]
    _setup_sigint(session_ids)

    print(f"\n[chaos] Polling every {POLL_INTERVAL}s — Ctrl-C to stop all sessions\n")
    try:
        while True:
            poll_sessions(session_ids)
            time.sleep(POLL_INTERVAL)
    except KeyboardInterrupt:
        pass  # handled by signal handler


if __name__ == "__main__":
    main()
