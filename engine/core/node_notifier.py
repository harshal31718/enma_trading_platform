"""Transport for engine -> Node notifications (stats/event PATCH, internal
POST calls).

Extracted from `LiveBotManager` (Plan 6 Step 6.1, ENG-1) as a behavior-
preserving move. Plan 6 Step 6.5 (ENG-16) pooled-client half shipped
2026-07-20: a lazy module-level `httpx.AsyncClient` singleton (`get_client`/
`close_client`, wired into `main.py`'s lifespan shutdown), mirroring the same
pattern `services/binance_testnet.py` already uses for its own outbound
client — was constructing (and TLS-handshaking/tearing down) a brand new
connection on every single `notify()`/`call_internal()` call, which fires on
essentially every candle-loop tick across every open symbol.

Still NOT done, and a real separate piece of work (not attempted here — see
`workspace/plan/6_engine-decomposition-and-exchange-abstraction.md` Step
6.5's own notes): the durable, ORDERED, at-least-once delivery channel
(Redis stream, sequenced against the Plan 5.1 event log) that replaces
Node's current last-write-wins `findByIdAndUpdate` projection. That needs
new consumer code on the Node side too, not just an engine-side change.
"""
from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger(__name__)

# Server URL for callbacks
SERVER_URL = os.getenv("SERVER_URL", "http://server:5000")

# Plan 3 Step 3.1 (SEC-1): shared secret authenticating engine -> Node
# /internal/* calls (distinct from ENGINE_API_KEY, which authenticates the
# other direction, Node -> engine).
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "")

_client: httpx.AsyncClient | None = None


def get_client() -> httpx.AsyncClient:
    """Lazy singleton — one pooled connection reused across every notify()/
    call_internal() call instead of a new TCP+TLS handshake per call."""
    global _client
    if _client is None:
        _client = httpx.AsyncClient()
    return _client


async def close_client() -> None:
    """Call from the app's shutdown lifespan (mirrors `services.binance_
    testnet.close_client`) — not required for correctness (the process
    exiting tears the socket down anyway) but avoids an unclosed-client
    warning and matches the existing convention."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def _internal_headers() -> dict:
    return {"X-Internal-Key": INTERNAL_API_KEY}


class NodeNotifier:
    """Sends live-session stats/event updates and internal calls to Node."""

    async def notify(self, session_id: str, data: dict) -> None:
        """Send stats/event update to Node server via HTTP PATCH."""
        try:
            client = get_client()
            await client.patch(
                f"{SERVER_URL}/internal/algo/sessions/{session_id}/stats",
                json=data,
                headers=_internal_headers(),
                timeout=5.0,
            )
        except Exception as e:
            logger.warning(f"[AlgoBot] Failed to notify Node for session {session_id}: {e}")

    async def call_internal(self, session_id: str, path: str, body: dict) -> dict:
        """Call a Node internal endpoint and return parsed JSON response."""
        try:
            client = get_client()
            resp = await client.post(
                f"{SERVER_URL}{path}", json=body, headers=_internal_headers(), timeout=45.0,
            )
            return resp.json()
        except Exception as e:
            logger.error(f"[AlgoBot] Node internal call failed ({path}): {e}")
            return {"success": False, "error": str(e)}
