import sys
import os
try:
    if not os.path.exists('/engine'):
        os.symlink('/app', '/engine')
except Exception:
    pass
sys.path.insert(0, '/')

import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from config.mongo import close_mongo, get_database
from config.timescale import close_pool, init_pool, get_pool
from routers.backtest import router as backtest_router
from routers.candles import router as candles_router
from routers.dashboard import router as dashboard_router
from routers.strategies import router as strategies_router
from services.strategy_seeder import seed_strategies

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ENGINE_API_KEY = os.getenv("ENGINE_API_KEY", "")
CLIENT_ORIGIN = os.getenv("CLIENT_URL", "http://localhost:5173")
SERVER_ORIGIN = os.getenv("SERVER_URL", "http://localhost:5000")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup — test both DB connections
    logger.info("Starting engine — testing database connections...")

    try:
        db = get_database()
        await db.command("ping")
        logger.info("MongoDB connection OK")
    except Exception as e:
        logger.error(f"MongoDB connection FAILED: {e}")

    try:
        await init_pool()
        pool = get_pool()
        async with pool.acquire() as conn:
            result = await conn.fetchval(
                "SELECT COUNT(*) FROM timescaledb_information.hypertables "
                "WHERE hypertable_name = 'candles'"
            )
            if result:
                logger.info("TimescaleDB connection OK — candles hypertable exists")
            else:
                logger.warning("TimescaleDB connected but candles hypertable not found")
    except Exception as e:
        logger.error(f"TimescaleDB connection FAILED: {e}")

    try:
        await seed_strategies()
        logger.info("Strategy seeding complete")
    except Exception as e:
        logger.error(f"Strategy seeding FAILED: {e}")

    yield

    # Shutdown
    close_mongo()
    await close_pool()
    logger.info("Engine shutdown complete")


app = FastAPI(title="Enma Engine", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[CLIENT_ORIGIN, SERVER_ORIGIN],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def require_api_key(request: Request, call_next):
    # /health is public — all other routes require X-API-Key
    if request.url.path == "/health":
        return await call_next(request)

    api_key = request.headers.get("X-API-Key")
    if not api_key or api_key != ENGINE_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")

    return await call_next(request)


app.include_router(candles_router, prefix="/candles", tags=["candles"])
app.include_router(strategies_router, prefix="/strategies", tags=["strategies"])
app.include_router(backtest_router, prefix="/backtest", tags=["backtest"])
app.include_router(dashboard_router, prefix="/dashboard", tags=["dashboard"])


@app.get("/health")
async def health():
    return {"status": "ok", "service": "engine"}
