import sys
import os
try:
    if not os.path.exists('/engine'):
        os.symlink('/app', '/engine')
except Exception:
    pass
sys.path.insert(0, '/')

import asyncio
import contextvars
import hmac
import logging
import uuid
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config.mongo import close_mongo, get_database
from config.timescale import close_pool, init_pool, get_pool
from routers.algo import router as algo_router
from routers.backtest import router as backtest_router
from routers.candles import router as candles_router
from routers.dashboard import router as dashboard_router
from routers.strategies import router as strategies_router
from routers.trade import router as trade_router
from routers.risk import router as risk_router
from routers.leverage_sensitivity import router as leverage_sensitivity_router
from routers.optimize import router as optimize_router
from routers.simulate import router as simulate_router
from services.strategy_seeder import seed_strategies
from services.binance_testnet import close_client
from utils.symbols import load_exchange_rules, load_symbol_volume_tiers, load_book_tickers

load_dotenv()

# Plan 2 Step 2.4 (SYS-6): every log line carries the correlation id of the
# request that produced it, threaded from Node's X-Request-Id header (see
# request_id_middleware below) so one Trade request's id is greppable across
# both server and engine logs.
correlation_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("correlation_id", default="-")


class _CorrelationIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = correlation_id_var.get()
        return True


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(correlation_id)s] %(name)s: %(message)s",
)
for _handler in logging.getLogger().handlers:
    _handler.addFilter(_CorrelationIdFilter())

logger = logging.getLogger(__name__)

ENGINE_API_KEY = os.getenv("ENGINE_API_KEY", "")
# Plan 3 Step 3.1 (SEC-1): shared secret for engine -> Node /internal/* calls.
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "")
CLIENT_ORIGIN = os.getenv("CLIENT_URL", "http://localhost:5173")
SERVER_ORIGIN = os.getenv("SERVER_URL", "http://localhost:5000")
EXCHANGE_RULES_REFRESH_INTERVAL_S = 30 * 60  # utils/symbols.py _rules_cache — see round_price()


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

    try:
        await load_exchange_rules("Binance Futures")
        await load_exchange_rules("Binance Spot")
        logger.info("Exchange rules cached")

        await load_symbol_volume_tiers("Binance Futures")
        await load_symbol_volume_tiers("Binance Spot")
        logger.info("Symbol volume tiers computed")

        await load_book_tickers("Binance Futures")
        await load_book_tickers("Binance Spot")
        logger.info("Book tickers (bid/ask) cached")
    except Exception as e:
        logger.error(f"Exchange rules caching FAILED: {e}")

    # _rules_cache (utils/symbols.py) was previously populated only once, here,
    # at process start. Any symbol relisted afterward, or whose PRICE_FILTER/
    # LOT_SIZE filters were momentarily incomplete on that one fetch, stayed
    # unrounded forever — round_price() silently passed the raw price through,
    # and Binance rejected TP/SL algoOrder placement with a 400. Refresh on an
    # interval so a stale/missing cache entry is self-healing.
    async def _refresh_exchange_rules_periodically():
        while True:
            await asyncio.sleep(EXCHANGE_RULES_REFRESH_INTERVAL_S)
            try:
                await load_exchange_rules("Binance Futures")
                await load_exchange_rules("Binance Spot")
                logger.info("Exchange rules cache refreshed")
            except Exception as e:
                logger.error(f"Exchange rules cache refresh FAILED: {e}")

    rules_refresh_task = asyncio.create_task(_refresh_exchange_rules_periodically())

    try:
        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{SERVER_ORIGIN}/internal/algo/engine-startup",
                timeout=10.0,
                headers={"X-Internal-Key": INTERNAL_API_KEY},
            )
            if resp.status_code == 200:
                logger.info("Notified Node server of engine startup for session/lock reconciliation")
            else:
                logger.warning(f"Node server responded with status {resp.status_code} on engine startup notification")
    except Exception as e:
        logger.warning(f"Failed to notify Node server of engine startup: {e}")

    yield

    # Shutdown
    rules_refresh_task.cancel()
    close_mongo()
    await close_pool()
    await close_client()
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
    # Plan 3 Step 3.5 (SEC-8): constant-time compare — a naive `!=` leaks
    # timing information proportional to the shared-prefix length.
    if not api_key or not hmac.compare_digest(api_key, ENGINE_API_KEY):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")

    return await call_next(request)


# Registered last so Starlette makes it the OUTERMOST middleware (runs first on
# the way in, last on the way out) — every request, including ones require_api_key
# rejects, gets a correlation id in its logs and an echoed X-Request-Id response header.
@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
    token = correlation_id_var.set(request_id)
    try:
        response = await call_next(request)
    finally:
        correlation_id_var.reset(token)
    response.headers["X-Request-Id"] = request_id
    return response


app.include_router(candles_router, prefix="/candles", tags=["candles"])
app.include_router(strategies_router, prefix="/strategies", tags=["strategies"])
app.include_router(backtest_router, prefix="/backtest", tags=["backtest"])
app.include_router(dashboard_router, prefix="/dashboard", tags=["dashboard"])
app.include_router(trade_router, prefix="/trade", tags=["trade"])
app.include_router(algo_router, prefix="/algo", tags=["algo"])
app.include_router(risk_router, prefix="/risk", tags=["risk"])
app.include_router(leverage_sensitivity_router, prefix="/backtest", tags=["backtest"])
app.include_router(optimize_router, prefix="/optimize", tags=["optimize"])
app.include_router(simulate_router, prefix="/simulate", tags=["simulate"])


@app.get("/health")
async def health():
    # ENG-13 (Plan 2 Step 2.5): health must reflect LIVE dependency state, not
    # a hardcoded "ok" — a Docker healthcheck reading this is meaningless
    # otherwise. Live-pings both DBs on every call (cheap: single round trip
    # each) rather than trusting a startup-time snapshot that can go stale.
    health_state = {"status": "ok", "service": "engine", "mongo": "error", "timescale": "error"}

    try:
        db = get_database()
        await db.command("ping")
        health_state["mongo"] = "connected"
    except Exception as e:
        logger.warning(f"/health: MongoDB ping failed: {e}")

    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        health_state["timescale"] = "connected"
    except Exception as e:
        logger.warning(f"/health: TimescaleDB ping failed: {e}")

    if health_state["mongo"] != "connected" or health_state["timescale"] != "connected":
        health_state["status"] = "degraded"
        return JSONResponse(status_code=503, content=health_state)

    return health_state
