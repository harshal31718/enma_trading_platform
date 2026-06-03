import os
from motor.motor_asyncio import AsyncIOMotorClient

_client: AsyncIOMotorClient | None = None


def get_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        mongo_uri = os.getenv("MONGO_URI", "mongodb://mongodb:27017/enma_trading")
        _client = AsyncIOMotorClient(mongo_uri)
    return _client


def get_database():
    client = get_client()
    db_name = os.getenv("MONGO_DB", "enma_trading")
    return client[db_name]


def close_mongo():
    global _client
    if _client is not None:
        _client.close()
        _client = None
