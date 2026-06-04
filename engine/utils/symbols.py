_exchange_cache = {}


def to_ccxt_symbol(symbol: str) -> str:
    """Convert app symbol format to ccxt format. BTC-USDT → BTC/USDT"""
    return symbol.replace("-", "/")


def to_app_symbol(symbol: str) -> str:
    """Convert ccxt symbol format to app format. BTC/USDT → BTC-USDT"""
    return symbol.replace("/", "-")


def get_ccxt_exchange(exchange: str):
    """
    Return configured ccxt exchange instance for the given exchange name.
    exchange: 'Binance Futures' | 'Binance Spot'
    """
    if exchange in _exchange_cache:
        return _exchange_cache[exchange]

    import ccxt
    import os

    if exchange == "Binance Futures":
        inst = ccxt.binanceusdm({
            "enableRateLimit": True,
            "options": {"defaultType": "future"},
        })
    elif exchange == "Binance Spot":
        inst = ccxt.binance({
            "enableRateLimit": True,
        })
    else:
        raise ValueError(f"Unsupported exchange: {exchange}")

    _exchange_cache[exchange] = inst
    return inst
