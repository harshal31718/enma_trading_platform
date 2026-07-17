"""Regression tests for pairlist fixes (I-02 volume rank, I-03 spread source,
I-04 precision/price, I-12 age filter).

Seeds the module-level symbol caches under a test-only exchange name so it never
collides with data loaded at engine startup.

Run inside the container::

    docker exec enma_trading_platform-engine-1 pytest /app/tests/test_pairlist_fixes.py
"""
import time
from decimal import Decimal

import utils.symbols as sym_mod
from services.pairlist import VolumePairList, SpreadFilter, PrecisionFilter, AgeFilter

EX = "Test Futures"


def _clear():
    for cache in (
        sym_mod._symbol_meta_cache,
        sym_mod._rules_cache,
        sym_mod._ticker_cache,
        sym_mod._book_ticker_cache,
    ):
        for k in [k for k in cache if k[0] == EX]:
            del cache[k]


def _seed(symbol, *, status="TRADING", qv=0.0, last=100.0,
          bid=None, ask=None, tick=0.1, onboard_ms=None):
    sym_mod._symbol_meta_cache[(EX, symbol)] = {
        "status": status, "baseAsset": symbol[:-4], "quoteAsset": "USDT",
        "onboardDate": onboard_ms,
    }
    sym_mod._rules_cache[(EX, symbol)] = {
        "tickSize": Decimal(str(tick)), "stepSize": Decimal("0.001"),
        "minQty": Decimal("0.001"), "minNotional": Decimal("5"),
    }
    sym_mod._ticker_cache[(EX, symbol)] = {
        "quoteVolume": qv, "lastPrice": last, "weightedAvgPrice": last,
        "highPrice": last * 1.01, "lowPrice": last * 0.99,
        "bidPrice": None, "askPrice": None,
    }
    if bid is not None or ask is not None:
        sym_mod._book_ticker_cache[(EX, symbol)] = {"bidPrice": bid, "askPrice": ask}


def test_volume_pairlist_ranks_by_quote_volume():
    _clear()
    _seed("AAAUSDT", qv=10.0)    # alphabetically first, lowest volume
    _seed("ZZZUSDT", qv=100.0)   # alphabetically last, highest volume
    _seed("MIDUSDT", qv=50.0)
    out = VolumePairList(top_n=2).filter([], EX)
    assert out == ["ZZZUSDT", "MIDUSDT"], out  # by volume, NOT alphabetical


def test_spread_filter_uses_book_ticker():
    _clear()
    _seed("TIGHTUSDT", bid=99.9, ask=100.0)   # 0.1% spread → kept
    _seed("WIDEUSDT", bid=90.0, ask=100.0)    # 10% spread → dropped
    _seed("NOBOOKUSDT")                        # no book data → kept (cannot judge)
    out = SpreadFilter(max_spread_ratio=0.005).filter(
        ["TIGHTUSDT", "WIDEUSDT", "NOBOOKUSDT"], EX)
    assert "TIGHTUSDT" in out
    assert "WIDEUSDT" not in out
    assert "NOBOOKUSDT" in out


def test_precision_filter_uses_tick_over_price():
    _clear()
    _seed("FINEUSDT", last=100.0, tick=0.01)    # 0.01/100 = 0.0001 → kept
    _seed("COARSEUSDT", last=1.0, tick=0.1)     # 0.1/1   = 0.1    → dropped
    out = PrecisionFilter(max_tick_fraction=0.005).filter(
        ["FINEUSDT", "COARSEUSDT"], EX)
    assert out == ["FINEUSDT"], out


def test_age_filter_drops_young_listings():
    _clear()
    now_ms = time.time() * 1000.0
    day = 86400000.0
    _seed("OLDUSDT", onboard_ms=now_ms - 200 * day)      # kept
    _seed("NEWUSDT", onboard_ms=now_ms - 5 * day)        # dropped
    _seed("UNKNOWNUSDT", onboard_ms=None)                # kept (no date)
    out = AgeFilter(min_days_listed=30).filter(
        ["OLDUSDT", "NEWUSDT", "UNKNOWNUSDT"], EX)
    assert "OLDUSDT" in out
    assert "NEWUSDT" not in out
    assert "UNKNOWNUSDT" in out
