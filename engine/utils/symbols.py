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

_TICKER_URLS = {
    "Binance Futures": "https://testnet.binancefuture.com/fapi/v1/ticker/24hr",
    "Binance Spot": "https://api.binance.com/api/v3/ticker/24hr",
}

# Book ticker (best bid/ask). The 24hr ticker endpoint does NOT return bid/ask
# for USDⓈ-M futures, so the SpreadFilter needs this separate source.
_BOOK_TICKER_URLS = {
    "Binance Futures": "https://testnet.binancefuture.com/fapi/v1/ticker/bookTicker",
    "Binance Spot": "https://api.binance.com/api/v3/ticker/bookTicker",
}

# Best bid/ask cache: (exchange, symbol) -> {"bidPrice": float|None, "askPrice": float|None}
_book_ticker_cache: dict[tuple[str, str], dict] = {}

# Symbol-level metadata beyond filters: (exchange, symbol) -> {"status": str, "baseAsset": str, "quoteAsset": str}
_symbol_meta_cache: dict[tuple[str, str], dict] = {}

# Volume-based tier cache: (exchange, symbol) -> "high" | "mid" | "low"
_volume_tier_cache: dict[tuple[str, str], str] = {}

# Ticker data cache (24hr statistics): (exchange, symbol) -> {bidPrice, askPrice, highPrice, lowPrice, volume, priceChangePercent, quoteVolume}
_ticker_cache: dict[tuple[str, str], dict] = {}

# Volume tier thresholds — top 20 by quoteVolume → high, top 55 → mid, rest → low
_VOLUME_TIER_HIGH_COUNT = 20
_VOLUME_TIER_MID_COUNT = 55

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
        status = sym_info.get("status", "UNKNOWN")
        base_asset = sym_info.get("baseAsset", "")
        quote_asset = sym_info.get("quoteAsset", "")

        _symbol_meta_cache[(exchange, symbol)] = {
            "status": status,
            "baseAsset": base_asset,
            "quoteAsset": quote_asset,
            # ms epoch listing date (USDⓈ-M futures provides it; spot does not) — AgeFilter
            "onboardDate": sym_info.get("onboardDate"),
        }

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


def round_price(symbol: str, exchange: str, price: float, rounding: str = ROUND_DOWN) -> float:
    """Round price to the exchange tick size for (exchange, symbol)."""
    rules = _rules_cache.get((exchange, symbol))
    if not rules:
        return price
    tick = rules["tickSize"]
    quantize_to = _get_precision(tick)
    return float(Decimal(str(price)).quantize(quantize_to, rounding=rounding))


def clamp_and_round_qty(
    symbol: str,
    exchange: str,
    qty: float,
    price: float,
    stop_loss_pct: float | None = None,
) -> float:
    """
    Round quantity to step size, ensuring it meets minQty and minNotional filters with a reserve buffer.
    """
    if qty <= 0.0:
        return 0.0

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

    # 3. Ensure it meets minimum notional with reserve buffer (F-008)
    price_dec = Decimal(str(price))
    if stop_loss_pct is not None and stop_loss_pct > 0:
        sl_pct = min(float(stop_loss_pct), 0.95)
        reserve_factor = Decimal(str(1.05 / (1.0 - sl_pct)))
    else:
        reserve_factor = Decimal("1.05")

    buffered_min_not = min_not_dec * reserve_factor

    if qty_dec * price_dec < buffered_min_not:
        # Calculate required quantity and round UP to stepSize
        req_qty = buffered_min_not / price_dec
        qty_dec = req_qty.quantize(quantize_to, rounding=ROUND_UP)
        # Re-verify minQty
        if qty_dec < min_qty_dec:
            qty_dec = min_qty_dec

    # 4. Tolerance check (F-013)
    # If the bumped quantity exceeds the original target quantity by more than +30%, skip the trade.
    if qty_dec > Decimal(str(qty)) * Decimal("1.30"):
        return 0.0

    return float(qty_dec)


def _safe_float_str(val) -> float | None:
    """Convert a ticker value to float, returning None if missing/invalid."""
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def get_symbol_status(exchange: str, symbol: str) -> str | None:
    """Return the exchange status for a symbol (e.g. TRADING, BREAK, HALT)."""
    meta = _symbol_meta_cache.get((exchange, symbol))
    return meta.get("status") if meta else None


async def load_symbol_volume_tiers(exchange: str) -> None:
    """
    Fetch 24hr ticker data and compute volume tiers (high/mid/low).
    Populates _volume_tier_cache.
    """
    url = _TICKER_URLS.get(exchange)
    if not url:
        logger.warning(f"load_symbol_volume_tiers: unknown exchange '{exchange}'")
        return

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.error(f"load_symbol_volume_tiers({exchange}): fetch failed — {e}")
        return

    # Sort by quoteVolume descending, keep only USDS-M perpetuals (symbol ends with USDT)
    usdt_pairs = []
    for s in data:
        if not isinstance(s, dict):
            continue
        sym = s.get("symbol", "")
        if not sym.endswith("USDT") or sym == "USDTUSDT":
            continue
        qv = float(s.get("quoteVolume", "0") or "0")
        usdt_pairs.append((sym, qv))

        # Cache full ticker data for pairlist filters
        _ticker_cache[(exchange, sym)] = {
            "bidPrice": _safe_float_str(s.get("bidPrice")),
            "askPrice": _safe_float_str(s.get("askPrice")),
            "highPrice": _safe_float_str(s.get("highPrice")),
            "lowPrice": _safe_float_str(s.get("lowPrice")),
            "lastPrice": _safe_float_str(s.get("lastPrice")),
            "weightedAvgPrice": _safe_float_str(s.get("weightedAvgPrice")),
            "volume": _safe_float_str(s.get("volume")),
            "quoteVolume": qv,
            "priceChangePercent": _safe_float_str(s.get("priceChangePercent")),
            "count": int(s.get("count", 0)),
        }

    usdt_pairs.sort(key=lambda x: x[1], reverse=True)

    for i, (symbol, _) in enumerate(usdt_pairs):
        if i < _VOLUME_TIER_HIGH_COUNT:
            tier = "high"
        elif i < _VOLUME_TIER_MID_COUNT:
            tier = "mid"
        else:
            tier = "low"
        _volume_tier_cache[(exchange, symbol)] = tier

    logger.info(
        f"load_symbol_volume_tiers({exchange}): {len(usdt_pairs)} symbols tiered "
        f"({_VOLUME_TIER_HIGH_COUNT} high, {_VOLUME_TIER_MID_COUNT - _VOLUME_TIER_HIGH_COUNT} mid, "
        f"{len(usdt_pairs) - _VOLUME_TIER_MID_COUNT} low)"
    )


def get_ticker_data(exchange: str, symbol: str) -> dict | None:
    """Return cached 24hr ticker data for a symbol, or None."""
    return _ticker_cache.get((exchange, symbol))


async def load_book_tickers(exchange: str) -> None:
    """Fetch best bid/ask (book ticker) for every symbol and cache it.

    Separate from the 24hr ticker because USDⓈ-M futures' /ticker/24hr does not
    include bid/ask — the SpreadFilter relies on this source.
    """
    url = _BOOK_TICKER_URLS.get(exchange)
    if not url:
        logger.warning(f"load_book_tickers: unknown exchange '{exchange}'")
        return

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.error(f"load_book_tickers({exchange}): fetch failed — {e}")
        return

    if isinstance(data, dict):
        data = [data]
    loaded = 0
    for s in data:
        if not isinstance(s, dict):
            continue
        sym = s.get("symbol", "")
        if not sym:
            continue
        _book_ticker_cache[(exchange, sym)] = {
            "bidPrice": _safe_float_str(s.get("bidPrice")),
            "askPrice": _safe_float_str(s.get("askPrice")),
        }
        loaded += 1

    logger.info(f"load_book_tickers({exchange}): cached bid/ask for {loaded} symbols")


def get_book_ticker(exchange: str, symbol: str) -> dict | None:
    """Return cached best bid/ask for a symbol, or None."""
    return _book_ticker_cache.get((exchange, symbol))


def get_symbol_onboard_date(exchange: str, symbol: str) -> float | None:
    """Return the symbol's onboard (listing) timestamp in ms epoch, or None."""
    meta = _symbol_meta_cache.get((exchange, symbol))
    if not meta:
        return None
    od = meta.get("onboardDate")
    try:
        return float(od) if od is not None else None
    except (ValueError, TypeError):
        return None


def get_symbol_tier(exchange: str, symbol: str) -> str:
    """Return the volume tier for a symbol, or 'mid' as default."""
    return _volume_tier_cache.get((exchange, symbol), "mid")


def get_all_symbols(exchange: str) -> list[dict]:
    """
    Return ALL symbols from the metadata cache for the exchange.
    Each entry: {symbol, status, baseAsset, quoteAsset, tier, rules}.
    """
    symbols = []
    seen = set()
    for (exch, sym), meta in _symbol_meta_cache.items():
        if exch != exchange or sym in seen:
            continue
        seen.add(sym)
        tier = get_symbol_tier(exchange, sym)
        rules = _rules_cache.get((exchange, sym))
        entry = {
            "symbol": sym,
            "status": meta.get("status", "UNKNOWN"),
            "baseAsset": meta.get("baseAsset", ""),
            "quoteAsset": meta.get("quoteAsset", ""),
            "tier": tier,
        }
        if rules:
            entry["tickSize"] = float(rules["tickSize"])
            entry["stepSize"] = float(rules["stepSize"])
            entry["minQty"] = float(rules["minQty"])
            entry["minNotional"] = float(rules["minNotional"])
        symbols.append(entry)
    return symbols


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
