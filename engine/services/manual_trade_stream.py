"""Per-user Binance User Data Stream registry for manual trading (Trade page).

Binance's own guidance is to source real-time account/order state from the
User Data Stream WebSocket rather than REST polling — REST calls like
GET /fapi/v1/openOrders cost weight 40 without a symbol filter, and that
budget is shared across every user proxied through this server's one
outbound IP (see workspace/docs/core/ARCHITECTURE.md rule 5). The live bot
manager already does this per session via UserDataStreamManager (F-020);
this module extends the same mechanism to manual trading, keyed by userId
instead of a LiveSession, since the Trade page has no session concept.

Lifecycle: the client starts a stream when the Trade page mounts and stops
it on unmount (see client/src/hooks/useTrade.js -> useTradeStream()). For
tabs closed without a clean unmount, an idle reaper stops any stream whose
owning user hasn't "touched" it (re-called start_for_user, used as a
heartbeat) within IDLE_TIMEOUT_SECONDS.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time

import redis.asyncio as aioredis

from services.user_data_stream import UserDataStreamManager

logger = logging.getLogger(__name__)

IDLE_TIMEOUT_SECONDS = 300  # stop a stream nobody has touched in 5 minutes
_REAP_INTERVAL_SECONDS = 60

_streams: dict[str, UserDataStreamManager] = {}
_last_touch: dict[str, float] = {}
_reaper_task: asyncio.Task | None = None

_redis_client: aioredis.Redis | None = None


def _get_redis() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            os.getenv("REDIS_URL", "redis://redis:6379"),
            decode_responses=True,
        )
    return _redis_client


def _channel(user_id: str) -> str:
    return f"trade-stream:{user_id}"


async def start_for_user(user_id: str, api_key: str, api_secret: str) -> None:
    """Start (or heartbeat-refresh) the manual-trading user data stream for *user_id*."""
    _last_touch[user_id] = time.time()
    _ensure_reaper_running()

    if user_id in _streams:
        return  # already running — the touch above is enough

    manager = UserDataStreamManager(api_key=api_key, api_secret=api_secret)

    async def _relay(event_type: str, payload: dict) -> None:
        r = _get_redis()
        await r.publish(_channel(user_id), json.dumps({"type": event_type, "data": payload}))

    manager.register_stream_callback(_relay)
    try:
        await manager.start()
        _streams[user_id] = manager
        logger.info(f"[ManualTradeStream] Started for user {user_id}")
    except Exception as e:
        logger.warning(f"[ManualTradeStream] Failed to start for user {user_id}: {e}")


async def stop_for_user(user_id: str) -> None:
    """Stop and discard the manual-trading stream for *user_id*, if any."""
    _last_touch.pop(user_id, None)
    manager = _streams.pop(user_id, None)
    if manager is None:
        return
    await manager.stop()
    logger.info(f"[ManualTradeStream] Stopped for user {user_id}")


def _ensure_reaper_running() -> None:
    global _reaper_task
    if _reaper_task is None or _reaper_task.done():
        _reaper_task = asyncio.create_task(_reap_idle_streams())


async def _reap_idle_streams() -> None:
    """Stop streams whose user hasn't called start_for_user (heartbeat) recently."""
    try:
        while True:
            await asyncio.sleep(_REAP_INTERVAL_SECONDS)
            now = time.time()
            idle_users = [
                uid for uid, ts in list(_last_touch.items())
                if now - ts > IDLE_TIMEOUT_SECONDS
            ]
            for uid in idle_users:
                logger.info(f"[ManualTradeStream] Reaping idle stream for user {uid}")
                await stop_for_user(uid)
            if not _streams:
                # Nothing left to watch — let the task end; next start_for_user
                # call will spin a fresh one up via _ensure_reaper_running().
                return
    except asyncio.CancelledError:
        pass
