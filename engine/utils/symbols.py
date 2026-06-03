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
    import ccxt
    import os

    if exchange == "Binance Futures":
        return ccxt.binanceusdm({
            "enableRateLimit": True,
            "options": {"defaultType": "future"},
        })
    elif exchange == "Binance Spot":
        return ccxt.binance({
            "enableRateLimit": True,
        })
    else:
        raise ValueError(f"Unsupported exchange: {exchange}")
