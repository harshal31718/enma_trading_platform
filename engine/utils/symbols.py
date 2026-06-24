import logging
from decimal import Decimal, ROUND_DOWN, ROUND_UP
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# Cached exchange filter rules: (exchange, symbol) -> {"tickSize": Decimal, "stepSize": Decimal, "minQty": Decimal, "minNotional": Decimal}
_rules_cache: dict[tuple[str, str], dict] = {}

# ── Per-symbol max leverage ─────────────────────────────────────────────────
# Source: GET /fapi/v1/leverageBracket (signed) → first bracket's initialLeverage.
# Live/manual paths do a signed fetch and cache the result; backtest uses the
# offline map below (no creds in the worker — keeps backtests deterministic).

_MAX_LEVERAGE_CACHE: dict[tuple[str, str], int] = {}  # (exchange, symbol) -> max_lev

# Hardcoded offline fallback: symbols relevant to the platform's chaos runner
# and golden-master backtest suite.  Unknown symbols default to 20.
_MAX_LEVERAGE_OFFLINE_MAP: dict[str, int] = {
    "BTCUSDT":   125,
    "ETHUSDT":   100,
    "SOLUSDT":    50,
    "BNBUSDT":    75,
    "XRPUSDT":    75,
    "DOGEUSDT":   75,
    "ADAUSDT":    75,
    "AVAXUSDT":   50,
    "LINKUSDT":   75,
    "DOTUSDT":    50,
    "LTCUSDT":    75,
    "MATICUSDT":  75,
    "POLUSDT":    75,
    "ARBUSDT":    50,
    "OPUSDT":     50,
    "NEARUSDT":   50,
    "INJUSDT":    50,
    "SUIUSDT":    50,
}

_LEVERAGE_BRACKET_URLS = {
    "testnet":  "https://testnet.binancefuture.com/fapi/v1/leverageBracket",
    "mainnet":  "https://fapi.binance.com/fapi/v1/leverageBracket",
}


async def get_max_leverage(
    exchange: str,
    symbol: str,
    *,
    api_key: str | None = None,
    api_secret: str | None = None,
    mode: str = "testnet",
) -> int:
    """
    Return the Binance maximum leverage for (exchange, symbol).

    Priority:
      1. In-memory cache hit.
      2. Signed GET /fapi/v1/leverageBracket → first bracket's initialLeverage
         (only when api_key + api_secret provided).
      3. Offline fallback map (used by backtest worker that has no creds).
      4. Hard default of 20.
    """
    cache_key = (exchange, symbol)
    cached = _MAX_LEVERAGE_CACHE.get(cache_key)
    if cached is not None:
        return cached

    if api_key and api_secret:
        try:
            # Signed request — requires timestamp + signature
            import hashlib
            import hmac
            import time
            ts = int(time.time() * 1000)
            query = f"symbol={symbol}&timestamp={ts}"
            sig = hmac.new(
                api_secret.encode(), query.encode(), hashlib.sha256
            ).hexdigest()
            url = _LEVERAGE_BRACKET_URLS.get(mode, _LEVERAGE_BRACKET_URLS["testnet"])
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    url,
                    params={"symbol": symbol, "timestamp": ts, "signature": sig},
                    headers={"X-MBX-APIKEY": api_key},
                )
                resp.raise_for_status()
                data = resp.json()
            # Response is a list of {symbol, brackets:[{initialLeverage,...}]}
            if isinstance(data, list) and data:
                brackets = data[0].get("brackets", [])
            else:
                brackets = data.get("brackets", [])
            if brackets:
                max_lev = int(brackets[0]["initialLeverage"])
                _MAX_LEVERAGE_CACHE[cache_key] = max_lev
                return max_lev
        except Exception as e:
            logger.warning(f"get_max_leverage({symbol}): signed fetch failed — {e}; using offline map")

    # Offline fallback
    max_lev = _MAX_LEVERAGE_OFFLINE_MAP.get(symbol, 20)
    _MAX_LEVERAGE_CACHE[cache_key] = max_lev
    return max_lev


async def clamp_leverage(
    requested: int,
    exchange: str,
    symbol: str,
    *,
    api_key: str | None = None,
    api_secret: str | None = None,
    mode: str = "testnet",
) -> int:
    """Return min(requested, symbol_max_leverage)."""
    max_lev = await get_max_leverage(exchange, symbol, api_key=api_key, api_secret=api_secret, mode=mode)
    return min(requested, max_lev)

_EXCHANGE_INFO_URLS = {
    "Binance Futures": "https://testnet.binancefuture.com/fapi/v1/exchangeInfo",
    "Binance Spot": "https://api.binance.com/api/v3/exchangeInfo",
}

DEFAULT_LIMITS = {
    # symbol: (tickSize, stepSize, minQty, minNotional)
    "BTCUSDT": (0.1, 0.0001, 0.0001, 50.0),
    "ETHUSDT": (0.01, 0.001, 0.001, 20.0),
    "BNBUSDT": (0.01, 0.01, 0.01, 5.0),
    "SOLUSDT": (0.01, 0.01, 0.01, 5.0),
    "XRPUSDT": (0.0001, 0.1, 0.1, 5.0),
    "DOGEUSDT": (0.00001, 1.0, 1.0, 5.0),
    "ADAUSDT": (0.0001, 1.0, 1.0, 5.0),
    "AVAXUSDT": (0.001, 1.0, 1.0, 5.0),
    "LINKUSDT": (0.001, 0.01, 0.01, 5.0),
    "DOTUSDT": (0.001, 0.1, 0.1, 5.0),
    "POLUSDT": (0.00001, 1.0, 1.0, 5.0),
    "MATICUSDT": (0.00001, 1.0, 1.0, 5.0),
    "LTCUSDT": (0.01, 0.001, 0.001, 5.0),
    "BCHUSDT": (0.01, 0.001, 0.001, 5.0),
    "UNIUSDT": (0.001, 1.0, 1.0, 5.0),
    "ATOMUSDT": (0.001, 0.01, 0.01, 5.0),
    "ETCUSDT": (0.001, 0.01, 0.01, 5.0),
    "XLMUSDT": (0.00001, 1.0, 1.0, 5.0),
    "FILUSDT": (0.001, 0.1, 0.1, 5.0),
    "APTUSDT": (0.0001, 0.1, 0.1, 5.0),
    "ARBUSDT": (0.0001, 0.1, 0.1, 5.0),
    "OPUSDT": (0.0001, 0.1, 0.1, 5.0),
    "NEARUSDT": (0.001, 1.0, 1.0, 5.0),
    "INJUSDT": (0.001, 0.1, 0.1, 5.0),
    "SUIUSDT": (0.0001, 0.1, 0.1, 5.0),
    "TIAUSDT": (0.0001, 1.0, 1.0, 5.0),
    "SEIUSDT": (0.0001, 1.0, 1.0, 5.0),
    "WLDUSDT": (0.0001, 1.0, 1.0, 5.0),
    "STXUSDT": (0.0001, 1.0, 1.0, 5.0),
    "RUNEUSDT": (0.0001, 1.0, 1.0, 5.0),
    "SANDUSDT": (0.00001, 1.0, 1.0, 5.0),
    "MANAUSDT": (0.0001, 1.0, 1.0, 5.0),
    "AXSUSDT": (0.001, 1.0, 1.0, 5.0),
    "GALAUSDT": (0.000001, 1.0, 1.0, 5.0),
    "ENJUSDT": (0.00001, 1.0, 1.0, 5.0),
    "CHZUSDT": (0.00001, 1.0, 1.0, 5.0),
    "1000SHIBUSDT": (0.000001, 1.0, 1.0, 5.0),
    "1000PEPEUSDT": (0.0000001, 1.0, 1.0, 5.0),
    "1000FLOKIUSDT": (0.00001, 1.0, 1.0, 5.0),
    "FLOKIUSDT": (0.00001, 1.0, 1.0, 5.0),
    "1000BONKUSDT": (0.000001, 1.0, 1.0, 5.0),
    "BONKUSDT": (0.000001, 1.0, 1.0, 5.0),
    "JTOUSDT": (0.0001, 1.0, 1.0, 5.0),
    "PYTHUSDT": (0.00001, 1.0, 1.0, 5.0),
    "JUPUSDT": (0.0001, 1.0, 1.0, 5.0),
    "WUSDT": (0.00001, 0.1, 0.1, 5.0),
    "STRKUSDT": (0.0001, 0.1, 0.1, 5.0),
    "ORDIUSDT": (0.001, 0.1, 0.1, 5.0),
    "1000SATSUSDT": (0.00000001, 1.0, 1.0, 5.0),
    "SATSUSDT": (0.00000001, 1.0, 1.0, 5.0),
    "LDOUSDT": (0.0001, 1.0, 1.0, 5.0),
    "CRVUSDT": (0.0001, 0.1, 0.1, 5.0),
    "AAVEUSDT": (0.01, 0.1, 0.1, 5.0),
}


def to_ccxt_symbol(symbol: str) -> str:
    """Identity — symbols are already in raw Binance format (e.g. BTCUSDT)."""
    return symbol


def to_app_symbol(symbol: str) -> str:
    """Identity — symbols are already in raw Binance format (e.g. BTCUSDT)."""
    return symbol


def to_binance_symbol(symbol: str) -> str:
    """Identity — symbols are already in raw Binance format (e.g. BTCUSDT)."""
    return symbol


async def load_exchange_rules(exchange: str) -> None:
    """
    Fetch tick/step filters from Binance exchangeInfo and cache them.
    Populates _rules_cache[(exchange, symbol)] with tickSize and stepSize Decimals.
    """
    url = _EXCHANGE_INFO_URLS.get(exchange)
    if not url:
        logger.warning(f"load_exchange_rules: unknown exchange '{exchange}'")
        return

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.error(f"load_exchange_rules({exchange}): fetch failed — {e}")
        return

    loaded = 0
    for sym_info in data.get("symbols", []):
        symbol = sym_info.get("symbol", "")
        tick_size: Optional[Decimal] = None
        step_size: Optional[Decimal] = None
        min_qty: Optional[Decimal] = None
        min_notional: Optional[Decimal] = None

        market_step_size: Optional[Decimal] = None
        market_min_qty: Optional[Decimal] = None

        for f in sym_info.get("filters", []):
            ft = f.get("filterType", "")
            if ft == "PRICE_FILTER":
                tick_size = Decimal(f["tickSize"])
            elif ft == "LOT_SIZE":
                step_size = Decimal(f["stepSize"])
                min_qty = Decimal(f["minQty"])
            elif ft == "MARKET_LOT_SIZE":
                # Market orders on some symbols (e.g. JUPUSDT) have stricter
                # constraints than the resting LOT_SIZE filter. Use the stricter
                # values for all market-order sizing to avoid Binance rejections.
                raw_step = f.get("stepSize", "0")
                raw_min = f.get("minQty", "0")
                if Decimal(raw_step) > 0:
                    market_step_size = Decimal(raw_step)
                if Decimal(raw_min) > 0:
                    market_min_qty = Decimal(raw_min)
            elif ft in ("MIN_NOTIONAL", "NOTIONAL"):
                min_notional = Decimal(f.get("minNotional") or f.get("notional") or "0")

        # If MARKET_LOT_SIZE is stricter than LOT_SIZE, prefer it for market orders.
        if market_step_size is not None and step_size is not None:
            if market_step_size > step_size:
                step_size = market_step_size
        elif market_step_size is not None:
            step_size = market_step_size

        if market_min_qty is not None and min_qty is not None:
            if market_min_qty > min_qty:
                min_qty = market_min_qty
        elif market_min_qty is not None:
            min_qty = market_min_qty

        if tick_size is not None and step_size is not None:
            _rules_cache[(exchange, symbol)] = {
                "tickSize": tick_size,
                "stepSize": step_size,
                "minQty": min_qty,
                "minNotional": min_notional,
            }
            loaded += 1

    logger.info(f"load_exchange_rules({exchange}): cached rules for {loaded} symbols")


def _get_precision(value: Decimal) -> Decimal:
    """Return the quantize step for a given tickSize/stepSize Decimal."""
    # Normalize to remove trailing zeros, then re-quantize
    sign, digits, exp = value.normalize().as_tuple()
    if exp >= 0:
        return Decimal("1")
    return Decimal("0." + "0" * (-exp - 1) + "1")


def round_price(symbol: str, exchange: str, price: float) -> float:
    """Round price to the exchange tick size for (exchange, symbol)."""
    rules = _rules_cache.get((exchange, symbol))
    if not rules:
        return price
    tick = rules["tickSize"]
    quantize_to = _get_precision(tick)
    return float(Decimal(str(price)).quantize(quantize_to, rounding=ROUND_DOWN))


def round_qty(symbol: str, exchange: str, qty: float) -> float:
    """Round quantity to the exchange step size for (exchange, symbol)."""
    rules = _rules_cache.get((exchange, symbol))
    if not rules:
        return qty
    step = rules["stepSize"]
    quantize_to = _get_precision(step)
    return float(Decimal(str(qty)).quantize(quantize_to, rounding=ROUND_DOWN))


def clamp_and_round_qty(symbol: str, exchange: str, qty: float, price: float) -> float:
    """
    Round quantity to step size, ensuring it meets minQty and minNotional filters.
    """
    rules = _rules_cache.get((exchange, symbol))
    
    # Fallback to DEFAULT_LIMITS if not cached
    if not rules and symbol in DEFAULT_LIMITS:
        tick, step, min_qty, min_notional = DEFAULT_LIMITS[symbol]
        step_dec = Decimal(str(step))
        min_qty_dec = Decimal(str(min_qty))
        min_not_dec = Decimal(str(min_notional))
    else:
        step_dec = rules["stepSize"] if rules else Decimal("0.01")
        min_qty_dec = rules.get("minQty") if rules and rules.get("minQty") is not None else Decimal("0.001")
        min_not_dec = rules.get("minNotional") if rules and rules.get("minNotional") is not None else Decimal("20.0")

    # 1. Round down to stepSize precision first
    quantize_to = _get_precision(step_dec)
    qty_dec = Decimal(str(qty)).quantize(quantize_to, rounding=ROUND_DOWN)

    # 2. Ensure it meets minimum quantity
    if qty_dec < min_qty_dec:
        qty_dec = min_qty_dec

    # 3. Ensure it meets minimum notional
    price_dec = Decimal(str(price))
    if qty_dec * price_dec < min_not_dec:
        # Calculate required quantity and round UP to stepSize
        req_qty = min_not_dec / price_dec
        qty_dec = req_qty.quantize(quantize_to, rounding=ROUND_UP)
        # Re-verify minQty
        if qty_dec < min_qty_dec:
            qty_dec = min_qty_dec

    return float(qty_dec)


def get_all_rules(exchange: str) -> dict:
    """
    Return all cached symbol rules for the exchange.
    Falls back to DEFAULT_LIMITS for any symbol in FUTURES_SYMBOLS not yet cached.
    """
    from core.constants import FUTURES_SYMBOLS
    
    rules = {}
    for symbol in FUTURES_SYMBOLS:
        cached = _rules_cache.get((exchange, symbol))
        if cached:
            rules[symbol] = {
                "tickSize": float(cached["tickSize"]),
                "stepSize": float(cached["stepSize"]),
                "minQty": float(cached["minQty"]),
                "minNotional": float(cached["minNotional"]),
            }
        else:
            limit = DEFAULT_LIMITS.get(symbol)
            if limit:
                rules[symbol] = {
                    "tickSize": float(limit[0]),
                    "stepSize": float(limit[1]),
                    "minQty": float(limit[2]),
                    "minNotional": float(limit[3]),
                }
            else:
                rules[symbol] = {
                    "tickSize": 0.001,
                    "stepSize": 0.01,
                    "minQty": 0.01,
                    "minNotional": 5.0,
                }
    return rules
