"""Execution event log (Plan 5 Step 5.1, SYS-2/SRV-3).

Append-only record of live-trading state transitions — fills (entry/add/exit),
close failures, and reconcile adjustments — keyed by (sessionId, symbol) with
a monotonic per-key `seq`. Node uses `seq` to reject a stale PATCH racing a
newer one for the same symbol (the same race Step 5.4's per-symbol lock
serializes engine-side; this is the Node-side half of that guarantee since
Node's `/internal/algo/sessions/:id/stats` calls aren't themselves ordered).

Scope note: this is additive. `LiveBotManager`'s in-memory session dict and
Node's `LiveSession` document remain the live read path — turning them into
pure projections *derived from* this log (so an engine restart replays state
instead of losing it) is Step 5.6, which depends on this step but is
deliberately not done here (it changes the live-session bootstrap sequence
and deserves its own dedicated verification pass, not a same-day bundle).

Persists to MongoDB collection `executionEvents`. Best-effort: write
failures are logged, never raised — an event-log outage must never block a
fill or a reconcile decision. Matches `services/trade_recorder.py`'s
established convention exactly.
"""
import logging
from datetime import datetime, timezone
from typing import Any

from config.mongo import get_database

logger = logging.getLogger(__name__)

EVENT_TYPES = frozenset({
    "fill",                  # entry, add (DCA), or exit — see payload["side"]
    "close_failed",          # close order failed/raised; position stays open
    "reconcile_adjustment",  # exchange-truth reconciliation forced a state change
})

# Monotonic seq counters, keyed by (session_id, symbol). Reset on engine
# restart — acceptable for now since the read-path state being guarded is
# itself in-memory and lost on restart too (Step 5.6 fixes both together).
_seq_counters: dict[tuple[str, str], int] = {}


def _next_seq(session_id: str, symbol: str) -> int:
    key = (session_id, symbol)
    _seq_counters[key] = _seq_counters.get(key, 0) + 1
    return _seq_counters[key]


def reset_session_seq(session_id: str) -> None:
    """Drop seq counters for a stopped session (mirrors symbol-lock cleanup)."""
    for key in [k for k in _seq_counters if k[0] == session_id]:
        _seq_counters.pop(key, None)


async def append_event(
    *,
    session_id: str,
    symbol: str,
    event_type: str,
    payload: dict[str, Any],
    client_order_id: str | None = None,
) -> int | None:
    """Append one event; returns its seq, or None on write failure.

    Never raises — callers should not (and do not need to) branch on the
    return value except to forward `seq` to Node's ordering guard when one
    was assigned.
    """
    if event_type not in EVENT_TYPES:
        logger.warning(f"[EventLog] Unrecognized event_type {event_type!r} — recording anyway")
    seq = _next_seq(session_id, symbol)
    doc = {
        "sessionId": session_id,
        "symbol": symbol,
        "seq": seq,
        "eventType": event_type,
        "clientOrderId": client_order_id,
        "payload": payload,
        "createdAt": datetime.now(timezone.utc),
    }
    try:
        db = get_database()
        await db.executionEvents.insert_one(doc)
    except Exception as e:
        logger.error(f"[EventLog] Failed to append event ({session_id}/{symbol}/{event_type}): {e}")
        return None
    return seq


def fold_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Pure fold: replay one session+symbol's ordered events into final
    {isOpen, entryPrice, qty, realizedPnl}. `events` must be pre-sorted by
    `seq` ascending (callers query MongoDB with `.sort("seq", 1)`).

    This is the acceptance check for Step 5.1 ("replaying the event log for
    a session reproduces its final PnL and open positions exactly") and is
    reusable by Step 5.6's restart-recovery path.
    """
    state: dict[str, Any] = {"isOpen": False, "entryPrice": None, "qty": 0.0, "realizedPnl": 0.0}
    for ev in events:
        payload = ev.get("payload", {})
        event_type = ev.get("eventType")

        if event_type == "fill":
            side = payload.get("side")
            if side in ("entry", "add"):
                qty = float(payload.get("qty", 0.0))
                price = float(payload.get("price", 0.0))
                if side == "add" and state["isOpen"]:
                    old_qty = state["qty"]
                    new_qty = old_qty + qty
                    old_price = state["entryPrice"] or 0.0
                    state["entryPrice"] = (old_qty * old_price + qty * price) / new_qty if new_qty else price
                    state["qty"] = new_qty
                else:
                    state["isOpen"] = True
                    state["entryPrice"] = price
                    state["qty"] = qty
            elif side == "exit":
                state["isOpen"] = False
                state["qty"] = 0.0
                state["realizedPnl"] += float(payload.get("realizedPnl", 0.0))
        elif event_type == "reconcile_adjustment":
            if payload.get("nowFlat"):
                state["isOpen"] = False
                state["qty"] = 0.0
                state["realizedPnl"] += float(payload.get("realizedPnl", 0.0))
            elif payload.get("nowOpen"):
                state["isOpen"] = True
                state["entryPrice"] = float(payload.get("price", 0.0))
                state["qty"] = float(payload.get("qty", 0.0))
        # close_failed intentionally changes nothing — the position stayed
        # open (that's the whole point of Step 5.2), so it's a log-only event.
    return state
