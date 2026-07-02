import hashlib
import hmac
import time
from typing import Any

import httpx

_BASE_URLS = {
    "mainnet": "https://fapi.binance.com",
    "testnet": "https://demo-fapi.binance.com",
}

_client: httpx.AsyncClient | None = None

# Clock-drift correction. Docker Desktop / WSL2 clocks routinely drift from
# Binance server time (especially after the host sleeps), which triggers Binance
# error -1021 "Timestamp for this request is outside of the recvWindow". We keep a
# per-host offset (serverTime - localTime, ms) refreshed from the public
# /fapi/v1/time endpoint and add it to every signed timestamp. On a -1021 we
# force-refresh the offset and retry once (covers a sudden jump, e.g. host resume).
_time_offset: dict[str, int] = {}
_offset_fetched_at: dict[str, float] = {}
_OFFSET_TTL_SECONDS = 300
# recvWindow padded above Binance's 5000 default to absorb residual jitter/latency
# on top of the offset correction (Binance max is 60000).
_RECV_WINDOW = 10000
_BINANCE_INVALID_TIMESTAMP = -1021


def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=30.0)
    return _client


async def close_client():
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def _refresh_time_offset(base_url: str) -> int:
    """Fetch Binance server time and cache the local-clock offset (ms)."""
    client = get_client()
    resp = await client.get(f"{base_url}/fapi/v1/time")
    resp.raise_for_status()
    server_time = int(resp.json()["serverTime"])
    offset = server_time - int(time.time() * 1000)
    _time_offset[base_url] = offset
    _offset_fetched_at[base_url] = time.time()
    return offset


async def _get_time_offset(base_url: str, force: bool = False) -> int:
    """Return the cached offset, refreshing it if stale, forced, or missing.

    Never lets a time-sync failure block the actual request — falls back to the
    last known offset (or 0), so a transient /fapi/v1/time hiccup doesn't break
    an otherwise-valid signed call.
    """
    fresh = (time.time() - _offset_fetched_at.get(base_url, 0)) < _OFFSET_TTL_SECONDS
    if not force and base_url in _time_offset and fresh:
        return _time_offset[base_url]
    try:
        return await _refresh_time_offset(base_url)
    except Exception:
        return _time_offset.get(base_url, 0)


def _build_signed_url(base_url: str, path: str, api_secret: str, params: dict, offset: int) -> str:
    p = dict(params)
    p["timestamp"] = int(time.time() * 1000) + offset
    p["recvWindow"] = _RECV_WINDOW

    query_string = "&".join(f"{k}={v}" for k, v in sorted(p.items()))
    signature = hmac.new(
        api_secret.encode("utf-8"),
        query_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{base_url}{path}?{query_string}&signature={signature}"


def _is_invalid_timestamp_error(exc: httpx.HTTPStatusError) -> bool:
    try:
        return int(exc.response.json().get("code")) == _BINANCE_INVALID_TIMESTAMP
    except Exception:
        return False


async def send_signed_request(
    method: str,
    path: str,
    api_key: str,
    api_secret: str,
    params: dict | None = None,
    mode: str = "testnet",
) -> Any:
    """Make a signed request to a Binance Futures REST API.

    mode selects the base URL:
      "mainnet" → https://fapi.binance.com
      "testnet" → https://demo-fapi.binance.com

    Timestamps are corrected by a cached server-time offset; a -1021 (timestamp
    outside recvWindow) triggers one offset refresh + retry.
    """
    base_url = _BASE_URLS.get(mode, _BASE_URLS["testnet"])
    p = dict(params) if params else {}
    method_upper = method.upper()
    headers = {"X-MBX-APIKEY": api_key}
    client = get_client()

    async def _dispatch(url: str) -> httpx.Response:
        if method_upper == "GET":
            return await client.get(url, headers=headers)
        if method_upper == "POST":
            return await client.post(url, headers=headers)
        if method_upper == "DELETE":
            return await client.delete(url, headers=headers)
        raise ValueError(f"Unsupported HTTP method: {method}")

    offset = await _get_time_offset(base_url)
    resp = await _dispatch(_build_signed_url(base_url, path, api_secret, p, offset))

    try:
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        if not _is_invalid_timestamp_error(exc):
            raise
        # Clock drifted since the last sync — resync and retry exactly once.
        offset = await _get_time_offset(base_url, force=True)
        resp = await _dispatch(_build_signed_url(base_url, path, api_secret, p, offset))
        resp.raise_for_status()

    return resp.json()
