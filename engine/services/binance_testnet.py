import hashlib
import hmac
import time
from typing import Any

import httpx

BINANCE_TESTNET_BASE = "https://testnet.binancefuture.com"


async def send_signed_request(
    method: str,
    path: str,
    api_key: str,
    api_secret: str,
    params: dict | None = None,
) -> Any:
    """Make a signed request to the Binance Futures Testnet REST API."""
    p = dict(params) if params else {}
    p["timestamp"] = int(time.time() * 1000)
    p["recvWindow"] = 5000

    # Sort alphabetically and build query string
    query_string = "&".join(f"{k}={v}" for k, v in sorted(p.items()))

    signature = hmac.new(
        api_secret.encode("utf-8"),
        query_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    query_string += f"&signature={signature}"
    url = f"{BINANCE_TESTNET_BASE}{path}?{query_string}"
    headers = {"X-MBX-APIKEY": api_key}

    async with httpx.AsyncClient(timeout=10.0) as client:
        if method.upper() == "GET":
            resp = await client.get(url, headers=headers)
        elif method.upper() == "POST":
            resp = await client.post(url, headers=headers)
        elif method.upper() == "DELETE":
            resp = await client.delete(url, headers=headers)
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")

    resp.raise_for_status()
    return resp.json()
