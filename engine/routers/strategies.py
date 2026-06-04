import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException

from config.mongo import get_database

router = APIRouter()

STRATEGIES_DIR = Path(__file__).parent.parent / "strategies"


@router.get("")
async def list_strategies():
    """Returns strategy metadata from MongoDB"""
    db = get_database()
    strategies = await db.strategies.find(
        {}, {"_id": 1, "name": 1, "description": 1, "filePath": 1, "createdAt": 1, "updatedAt": 1}
    ).to_list(length=100)

    for s in strategies:
        s["id"] = str(s.pop("_id"))
        if hasattr(s.get("createdAt"), "isoformat"):
            s["createdAt"] = s["createdAt"].isoformat()
        if hasattr(s.get("updatedAt"), "isoformat"):
            s["updatedAt"] = s["updatedAt"].isoformat()

    return {"success": True, "data": {"strategies": strategies}}


@router.get("/{name}/code")
async def get_strategy_code(name: str):
    """Reads strategy source code from disk"""
    path = Path(STRATEGIES_DIR) / name / "__init__.py"

    if not await asyncio.to_thread(path.exists):
        raise HTTPException(status_code=404, detail=f"Strategy '{name}' not found on disk")

    code = await asyncio.to_thread(path.read_text, encoding="utf-8")

    return {
        "success": True,
        "data": {
            "code": code,
            "name": name,
            "filePath": f"strategies/{name}/__init__.py",
        },
    }
