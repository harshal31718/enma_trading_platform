import os

from fastapi import APIRouter, HTTPException

from config.mongo import get_database

router = APIRouter()

STRATEGIES_DIR = os.path.join(os.path.dirname(__file__), "..", "strategies")


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
    file_path = os.path.join(STRATEGIES_DIR, name, "__init__.py")

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"Strategy '{name}' not found on disk")

    with open(file_path, "r") as f:
        code = f.read()

    return {
        "success": True,
        "data": {
            "code": code,
            "name": name,
            "filePath": f"strategies/{name}/__init__.py",
        },
    }
