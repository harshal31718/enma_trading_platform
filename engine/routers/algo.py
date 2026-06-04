import logging
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Optional

from core.live_bot_manager import live_bot_manager

router = APIRouter()
logger = logging.getLogger(__name__)


class StartSessionRequest(BaseModel):
    session_id: str
    strategy_name: str
    symbols: list[str]
    timeframe: str
    params: dict = {}
    capital: str
    leverage: int = 1


class StopSessionRequest(BaseModel):
    pass


@router.post("/sessions")
async def start_session(req: StartSessionRequest, background_tasks: BackgroundTasks):
    """Start a new live bot session. Called by Node server."""
    try:
        session_config = req.model_dump()
        # Start in background so the route returns immediately
        background_tasks.add_task(live_bot_manager.start_session, session_config)
        return {"success": True, "data": {"session_id": req.session_id, "status": "starting"}}
    except Exception as e:
        logger.error(f"Failed to start session {req.session_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sessions/{session_id}/stop")
async def stop_session(session_id: str, background_tasks: BackgroundTasks):
    """Stop a running bot session. Returns immediately, stop runs in background."""
    session = live_bot_manager.sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session["status"] not in ("running", "starting"):
        raise HTTPException(status_code=409, detail=f"Session is {session['status']}, not running")

    session["status"] = "stopping"
    background_tasks.add_task(live_bot_manager.stop_session, session_id)

    return {"success": True, "data": {"session_id": session_id, "status": "stopping"}}


@router.get("/sessions/{session_id}/status")
async def get_session_status(session_id: str):
    """Get current session status. Called by Node for health polls."""
    status = await live_bot_manager.get_session_status(session_id)
    return {"success": True, "data": status}
