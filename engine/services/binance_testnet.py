import hashlib
import hmac
import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

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

# Plan 21.5 (A-9): weight tracking + 429/418 backpressure. Binance shares a
# 2400-weight/min budget across ALL of this server's outbound requests (single
# IP, all users) — a busy multi-symbol Chaos run's reconcile polls (positionRisk
# w5 + openOrders w1 + openAlgoOrders per symbol per candle) can burn a large
# fraction of that budget with zero backpressure, and a 429/418 would surface as
# a generic per-symbol exception with no coordinated pause, risking a cascade
# into the 5-consecutive-errors loop-kill or an IP ban. Two independent guards:
#   (a) track the last-seen X-MBX-USED-WEIGHT-1M per base_url; once at/above
#       _WEIGHT_SOFT_LIMIT, defer (raise BinanceBackpressureError) any
#       non-order-critical call rather than risk tipping into a real 429.
#   (b) on an actual 429/418, honor Retry-After and pause ALL non-order-critical
#       calls on that base_url until the pause expires.
# Order-critical paths (placing/cancelling/querying an order or bracket) are
# NEVER deferred by either guard — a skipped SL placement or emergency close is
# far worse than a rate-limit warning; if Binance is truly banning the IP those
# calls will fail on their own and existing retry/emergency-exit logic handles it.
_used_weight_1m: dict[str, tuple[int, float]] = {}  # base_url -> (weight, observed_at)
_backpressure_until: dict[str, float] = {}  # base_url -> epoch seconds
_WEIGHT_SOFT_LIMIT = 1800  # 75% of the shared 2400/min budget
_WEIGHT_READING_TTL_SECONDS = 60  # Binance's own window — a stale reading can't gate
_DEFAULT_RETRY_AFTER_SECONDS = 60
_ORDER_CRITICAL_PATHS = {"/fapi/v1/order", "/fapi/v1/algoOrder"}


class BinanceBackpressureError(RuntimeError):
    """Raised instead of making a non-order-critical signed call when this
    base_url is either paused (recent 429/418, still inside Retry-After) or
    running hot on its shared weight budget. Callers already wrap signed calls
    in try/except (reconcile, weight-lookup helpers) — this is a deliberate
    skip-this-cycle signal, not a Binance-side failure."""


def _is_order_critical_path(path: str) -> bool:
    return path in _ORDER_CRITICAL_PATHS


def _record_used_weight(base_url: str, headers) -> None:
    raw = headers.get("X-MBX-USED-WEIGHT-1M")
    if raw is None:
        return
    try:
        _used_weight_1m[base_url] = (int(raw), time.time())
    except (TypeError, ValueError):
        pass


def _check_backpressure(base_url: str, path: str) -> None:
    if _is_order_critical_path(path):
        return
    pause_until = _backpressure_until.get(base_url, 0.0)
    if time.time() < pause_until:
        raise BinanceBackpressureError(
            f"{base_url}: paused until {pause_until:.0f} (epoch) after a 429/418 — "
            f"deferring non-order call {path}"
        )
    weight, observed_at = _used_weight_1m.get(base_url, (0, 0.0))
    if weight >= _WEIGHT_SOFT_LIMIT and (time.time() - observed_at) < _WEIGHT_READING_TTL_SECONDS:
        raise BinanceBackpressureError(
            f"{base_url}: used weight {weight} >= soft limit {_WEIGHT_SOFT_LIMIT} — "
            f"deferring non-order call {path}"
        )


def _handle_rate_limit_response(base_url: str, exc: httpx.HTTPStatusError) -> None:
    """On 429 (TOO_MANY_REQUESTS) or 418 (IP auto-ban), honor Retry-After and
    pause all non-order-critical calls on this base_url until it expires."""
    status = exc.response.status_code
    if status not in (429, 418):
        return
    retry_after_raw = exc.response.headers.get("Retry-After")
    try:
        retry_after = float(retry_after_raw) if retry_after_raw is not None else _DEFAULT_RETRY_AFTER_SECONDS
    except (TypeError, ValueError):
        retry_after = _DEFAULT_RETRY_AFTER_SECONDS
    resume_at = time.time() + retry_after
    _backpressure_until[base_url] = max(_backpressure_until.get(base_url, 0.0), resume_at)
    logger.error(
        f"Binance {status} on {base_url} — pausing non-order-critical calls for "
        f"{retry_after:.0f}s (Retry-After{'='+retry_after_raw if retry_after_raw else ' missing, using default'})"
    )


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

    Plan 21.5 (A-9): non-order-critical calls (anything other than
    `/fapi/v1/order` / `/fapi/v1/algoOrder`) are deferred with
    `BinanceBackpressureError` if this base_url is either paused from a recent
    429/418 or running at/above the shared weight soft limit — see the module
    docstring above `_check_backpressure`. Order-critical calls always proceed.
    """
    base_url = _BASE_URLS.get(mode, _BASE_URLS["testnet"])
    _check_backpressure(base_url, path)

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
    _record_used_weight(base_url, resp.headers)

    try:
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        _handle_rate_limit_response(base_url, exc)
        if not _is_invalid_timestamp_error(exc):
            raise
        # Clock drifted since the last sync — resync and retry exactly once.
        offset = await _get_time_offset(base_url, force=True)
        resp = await _dispatch(_build_signed_url(base_url, path, api_secret, p, offset))
        _record_used_weight(base_url, resp.headers)
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc2:
            _handle_rate_limit_response(base_url, exc2)
            raise

    return resp.json()
