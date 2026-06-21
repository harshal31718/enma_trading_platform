import asyncio
import ast
import importlib
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, validator

from config.mongo import get_database

router = APIRouter()

STRATEGIES_DIR = Path(__file__).parent.parent / "strategies"

VALID_STRATEGY_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]+$")


def _validate_strategy_name(name: str) -> str:
    name = name.strip()
    if not VALID_STRATEGY_NAME.match(name):
        raise HTTPException(
            status_code=400,
            detail="Strategy name must start with a letter and contain only letters, numbers, and underscores.",
        )
    return name


def _get_strategy_path(name: str) -> Path:
    return STRATEGIES_DIR / name / "__init__.py"


def _read_strategy_code(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _detect_top_level_class_name(code: str) -> str | None:
    match = re.search(
        r"^class\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", code, flags=re.MULTILINE
    )
    return match.group(1) if match else None


def _rename_strategy_class(code: str, name: str) -> str:
    class_name = _detect_top_level_class_name(code)
    if class_name is None:
        raise ValueError("Could not detect a top-level strategy class definition.")
    if class_name == name:
        return code
    return re.sub(
        rf"^class\s+{re.escape(class_name)}\s*\(",
        f"class {name}(",
        code,
        count=1,
        flags=re.MULTILINE,
    )


def _strategy_template(name: str) -> str:
    return f'''"""Enma strategy template.

This strategy is intentionally minimal and uses the black-box forecast()
pattern. Do not write self.buy/self.sell/self.stop_loss/self.take_profit
from inside forecast(); the engine owns execution and order planning.
"""

import engine.indicators as ta
from engine.core.strategy import BaseStrategy, Signal


class {name}(BaseStrategy):
    PARAMS = {{
        "fast_period": {{"type": "int", "default": 12, "min": 2, "max": 50, "label": "Fast EMA Period"}},
        "slow_period": {{"type": "int", "default": 26, "min": 5, "max": 100, "label": "Slow EMA Period"}},
        "atr_multiplier": {{"type": "float", "default": 2.0, "min": 1.0, "max": 5.0, "label": "ATR Stop Multiplier"}},
    }}

    def forecast(self):
        fast = ta.ema(self.candles, period=self.fast_period)
        slow = ta.ema(self.candles, period=self.slow_period)

        if fast > slow:
            return Signal(direction=1, conviction=1.0, ref_price=self.price)
        if fast < slow:
            return Signal(direction=-1, conviction=1.0, ref_price=self.price)
        return Signal(direction=0, conviction=0.0, ref_price=self.price)
'''


class StrategyCreateRequest(BaseModel):
    name: str
    description: str = Field(default="")
    sourceName: str | None = None
    template: str | None = None

    @validator("name")
    def check_name(cls, name: str):
        return _validate_strategy_name(name)

    @validator("sourceName")
    def check_source_name(cls, source_name: str | None):
        if source_name is None:
            return source_name
        return _validate_strategy_name(source_name)

    @validator("template")
    def check_template(cls, template: str | None):
        if template is not None and template not in {"blank"}:
            raise ValueError("Unsupported template")
        return template


class StrategyCodeUpdateRequest(BaseModel):
    code: str


@router.get("")
async def list_strategies():
    """Returns strategy metadata from MongoDB"""
    db = get_database()
    strategies = await db.strategies.find(
        {},
        {
            "_id": 1,
            "name": 1,
            "description": 1,
            "filePath": 1,
            "createdAt": 1,
            "updatedAt": 1,
        },
    ).to_list(length=100)

    for s in strategies:
        s["id"] = str(s.pop("_id"))
        if hasattr(s.get("createdAt"), "isoformat"):
            s["createdAt"] = s["createdAt"].isoformat()
        if hasattr(s.get("updatedAt"), "isoformat"):
            s["updatedAt"] = s["updatedAt"].isoformat()

    return {"success": True, "data": {"strategies": strategies}}


@router.post("")
async def create_strategy(req: StrategyCreateRequest):
    """Creates a new strategy file on disk and inserts metadata into MongoDB."""
    strategy_name = req.name
    strategy_dir = STRATEGIES_DIR / strategy_name
    strategy_path = _get_strategy_path(strategy_name)

    if await asyncio.to_thread(strategy_path.exists):
        raise HTTPException(
            status_code=409, detail=f"Strategy '{strategy_name}' already exists"
        )

    if req.sourceName:
        source_path = _get_strategy_path(req.sourceName)
        if not await asyncio.to_thread(source_path.exists):
            raise HTTPException(
                status_code=404, detail=f"Source strategy '{req.sourceName}' not found"
            )
        source_code = await asyncio.to_thread(_read_strategy_code, source_path)
        try:
            code = _rename_strategy_class(source_code, strategy_name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
    else:
        code = _strategy_template(strategy_name)

    await asyncio.to_thread(strategy_dir.mkdir, parents=True, exist_ok=True)
    await asyncio.to_thread(strategy_path.write_text, code, encoding="utf-8")

    db = get_database()
    now = datetime.now(timezone.utc)
    result = await db.strategies.update_one(
        {"name": strategy_name},
        {
            "$set": {
                "name": strategy_name,
                "description": req.description,
                "filePath": f"strategies/{strategy_name}/__init__.py",
                "updatedAt": now,
            },
            "$setOnInsert": {"createdAt": now},
        },
        upsert=True,
    )

    strategy_doc = await db.strategies.find_one({"name": strategy_name})
    strategy_id = str(strategy_doc["_id"]) if strategy_doc else None

    return {
        "success": True,
        "data": {
            "strategy": {
                "id": strategy_id,
                "name": strategy_name,
                "description": req.description,
                "filePath": f"strategies/{strategy_name}/__init__.py",
                "createdAt": (
                    strategy_doc["createdAt"].isoformat()
                    if strategy_doc and hasattr(strategy_doc["createdAt"], "isoformat")
                    else now.isoformat()
                ),
                "updatedAt": (
                    strategy_doc["updatedAt"].isoformat()
                    if strategy_doc and hasattr(strategy_doc["updatedAt"], "isoformat")
                    else now.isoformat()
                ),
            }
        },
    }


@router.put("/{name}/code")
async def update_strategy_code(name: str, req: StrategyCodeUpdateRequest):
    """Writes updated strategy source code to disk."""
    strategy_name = _validate_strategy_name(name)
    strategy_path = _get_strategy_path(strategy_name)

    if not await asyncio.to_thread(strategy_path.exists):
        raise HTTPException(
            status_code=404, detail=f"Strategy '{strategy_name}' not found"
        )

    try:
        ast.parse(req.code)
    except SyntaxError as exc:
        raise HTTPException(
            status_code=400, detail=f"Syntax error in strategy code: {exc}"
        )

    top_class = _detect_top_level_class_name(req.code)
    if top_class != strategy_name:
        raise HTTPException(
            status_code=400,
            detail=f"Strategy code must define a top-level class named '{strategy_name}'. Found '{top_class or 'none'}'.",
        )

    await asyncio.to_thread(strategy_path.write_text, req.code, encoding="utf-8")

    db = get_database()
    await db.strategies.update_one(
        {"name": strategy_name},
        {"$set": {"updatedAt": datetime.now(timezone.utc)}},
    )

    module_name = f"strategies.{strategy_name}"
    if module_name in sys.modules:
        importlib.reload(sys.modules[module_name])

    now = datetime.now(timezone.utc).isoformat()
    return {"success": True, "data": {"savedAt": now}}


@router.get("/{name}/code")
async def get_strategy_code(name: str):
    """Reads strategy source code from disk"""
    path = _get_strategy_path(name)

    if not await asyncio.to_thread(path.exists):
        raise HTTPException(
            status_code=404, detail=f"Strategy '{name}' not found on disk"
        )

    code = await asyncio.to_thread(path.read_text, encoding="utf-8")

    return {
        "success": True,
        "data": {
            "code": code,
            "name": name,
            "filePath": f"strategies/{name}/__init__.py",
        },
    }


@router.get("/{name}/params")
async def get_strategy_params(name: str):
    """Returns the PARAMS schema for a strategy class."""
    try:
        module = importlib.import_module(f"strategies.{name}")
        strategy_class = getattr(module, name)
        params = getattr(strategy_class, "PARAMS", {})
        return {"success": True, "data": {"params": params}}
    except Exception:
        raise HTTPException(status_code=404, detail=f"Strategy '{name}' not found")
