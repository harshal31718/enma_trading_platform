import os
import asyncpg

_pool: asyncpg.Pool | None = None


async def init_pool() -> None:
    global _pool
    if _pool is None:
        dsn = os.getenv(
            "TIMESCALE_URL",
            "postgresql://enma:enma_dev_password@timescaledb:5432/enma_candles",
        )
        _pool = await asyncpg.create_pool(dsn=dsn, min_size=2, max_size=10)


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("TimescaleDB pool not initialised — call init_pool() first")
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
