"""Transport for engine -> Node notifications (stats/event stream, internal
POST calls).

Extracted from `LiveBotManager` (Plan 6 Step 6.1, ENG-1) as a behavior-
preserving move. Plan 6 Step 6.5 (ENG-16) pooled-client half shipped
2026-07-20: a lazy module-level `httpx.AsyncClient` singleton (`get_client`/
`close_client`, wired into `main.py`'s lifespan shutdown), mirroring the same
pattern `services/binance_testnet.py` already uses for its own outbound
client — was constructing (and TLS-handshaking/tearing down) a brand new
connection on every single `notify()`/`call_internal()` call, which fires on
essentially every candle-loop tick across every open symbol.

**Redis-stream half shipped 2026-07-24, closing Step 6.5 in full.** `notify()`
now publishes to a durable Redis Stream (`algo:events`, `XADD ... MAXLEN ~`)
instead of firing an HTTP PATCH — Node's consumer
(`server/src/services/eventStreamConsumer.js`) reads it via a consumer group
(`XREADGROUP`, `>` for new entries, `0` on startup to drain any unACKed
backlog from a prior crash) and applies each entry through the exact same
`processEngineStatsUpdate()` the old PATCH route used, then `XACK`s. This
gives ordered, at-least-once delivery that survives a Node restart, instead
of the old fire-and-forget PATCH silently dropping the event on any Node
downtime. Correctness against duplicate/out-of-order delivery relies on
`processEngineStatsUpdate`'s existing `lastSeqBySymbol` staleness guard
(already idempotent for `position:open/close/adjust`) — this change doesn't
add new dedup logic, it makes the transport reliable enough for that
existing guard to actually matter. `call_internal()` is unchanged (HTTP,
synchronous request/response — not a fit for a stream).
"""
from __future__ import annotations

import json
import logging
import os

import httpx
import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

# Server URL for callbacks
SERVER_URL = os.getenv("SERVER_URL", "http://server:5000")

# Plan 3 Step 3.1 (SEC-1): shared secret authenticating engine -> Node
# /internal/* calls (distinct from ENGINE_API_KEY, which authenticates the
# other direction, Node -> engine).
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "")

# Plan 6 Step 6.5 (ENG-16): single global stream, not per-session — avoids
# the "how does the consumer discover new per-session stream keys" problem
# entirely. Per-session ordering is still preserved (a single ordered log is
# a superset guarantee of per-subsequence ordering); the consumer applies
# every entry via the session id carried in its own fields.
STREAM_KEY = "algo:events"
STREAM_MAXLEN = 10_000  # approximate cap (MAXLEN ~) — bounds unbounded growth if Node is ever down for a long stretch

_client: httpx.AsyncClient | None = None
_redis_client: aioredis.Redis | None = None


def get_client() -> httpx.AsyncClient:
    """Lazy singleton — one pooled connection reused across every
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


def _get_redis_client() -> aioredis.Redis:
    """Lazy singleton, mirrors `services/progress.py`'s pattern — one pooled
    connection reused across every notify() call instead of reconnecting
    per candle-loop tick."""
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            os.getenv("REDIS_URL", "redis://redis:6379"),
            decode_responses=True,
        )
    return _redis_client


async def close_redis_client() -> None:
    """Call from the app's shutdown lifespan alongside close_client()."""
    global _redis_client
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None


def _internal_headers() -> dict:
    return {"X-Internal-Key": INTERNAL_API_KEY}


class NodeNotifier:
    """Sends live-session stats/event updates and internal calls to Node."""

    async def notify(self, session_id: str, data: dict) -> None:
        """Publish a stats/event update to Node via the durable Redis
        stream (Plan 6 Step 6.5) — see module docstring."""
        try:
            r = _get_redis_client()
            await r.xadd(
                STREAM_KEY,
                {"sessionId": session_id, "payload": json.dumps(data)},
                maxlen=STREAM_MAXLEN,
                approximate=True,
            )
        except Exception as e:
            logger.warning(f"[AlgoBot] Failed to publish event for session {session_id}: {e}")

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
