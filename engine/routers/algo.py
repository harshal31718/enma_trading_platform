import json
import logging
from fastapi import APIRouter, HTTPException, BackgroundTasks, Query
from pydantic import BaseModel, Field
from typing import Optional

from core.live_bot_manager import live_bot_manager
from services.pairlist import pairlist_from_config

router = APIRouter()
logger = logging.getLogger(__name__)


class PairlistPreviewRequest(BaseModel):
    config: str = '{"generator": {"type": "volume", "top_n": 30}, "filters": []}'  # JSON string


@router.post("/pairlist/preview")
async def preview_pairlist(req: PairlistPreviewRequest):
    """Preview what symbols a pairlist configuration would produce."""
    try:
        config = json.loads(req.config) if isinstance(req.config, str) else req.config
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON config: {e}")

    try:
        pipeline = pairlist_from_config(config)
        symbols = pipeline.run(exchange="Binance Futures")
        return {
            "success": True,
            "data": {
                "symbols": symbols,
                "count": len(symbols),
                "pipeline": repr(pipeline),
            },
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


class StartSessionRequest(BaseModel):
    session_id: str
    strategy_name: str
    # Defensive ceiling only — real enforcement is Node-side (Settings.limits.*.maxSymbolsPerBot,
    # Mongoose max 30, and chaosMaxTotalSymbols, Mongoose max 250). Sized against the larger of
    # those two Mongoose maxes so it never fires under normal Node-enforced operation; it exists
    # purely to protect the engine if the Node layer is ever misconfigured or bypassed.
    symbols: list[str] = Field(..., max_length=250)
    timeframe: str
    params: dict = {}
    capital: str
    leverage: int = 1
    # Taker fee injected by the server from saved Exchange Settings. Must be
    # declared here — Pydantic drops undeclared fields, which would silently
    # discard the configured rate and leave the bot on its hardcoded fallback.
    fee_rate: float = 0.0005
    # Risk model parameters (Tier 2) — server merges global Risk settings with
    # any per-session override. Keyed by snake_case name (risk_pct, rrr,
    # liq_buffer_pct, max_session_dd); injected onto each strategy instance.
    risk_params: dict = {}
    # Per-user credentials forwarded from Node server (multi-user support).
    user_id: str = ""
    api_key: str = ""
    api_secret: str = ""


class StopSessionRequest(BaseModel):
    pass


class TradingStateRequest(BaseModel):
    state: str


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


@router.post("/sessions/{session_id}/trading-state")
async def set_trading_state(session_id: str, req: TradingStateRequest):
    """Set the trading state for a session (A-002)."""
    if session_id not in live_bot_manager.sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    result = await live_bot_manager.set_trading_state(session_id, req.state)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return {"success": True, "data": result["data"]}
