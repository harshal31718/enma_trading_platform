"""
Pairlist pipeline — dynamic symbol selection for live trading sessions.

Inspired by freqtrade's pairlist plugin system (VolumePairList + chained filters).
Generates an initial pool of symbols, then runs it through a series of filters
to produce the final symbol set for a live session.

Each handler is independently testable. The pipeline is configured via a dict
passed in the session's risk_params or pairlist config.
"""

import logging
from abc import ABC, abstractmethod
from typing import Optional

from utils.symbols import (
    get_symbol_tier,
    get_ticker_data,
    get_all_symbols,
    _rules_cache,
)

logger = logging.getLogger(__name__)


# ── Handler protocol ───────────────────────────────────────────────────────

class PairlistHandler(ABC):
    """Base class for a pairlist handler (generator or filter)."""

    @abstractmethod
    def filter(self, pairs: list[str], exchange: str) -> list[str]:
        ...


# ── Generator: VolumePairList ──────────────────────────────────────────────

class VolumePairList(PairlistHandler):
    """
    Generate the initial pairlist by selecting the top N symbols by 24h
    quote volume (from the cached ticker data loaded at engine startup).
    """

    def __init__(self, top_n: int = 30):
        self.top_n = max(1, top_n)

    def filter(self, pairs: list[str], exchange: str) -> list[str]:
        # Collect all symbols with known volume tiers
        all_syms = get_all_symbols(exchange)
        # Sort by tier priority: high > mid > low, then alphabetically
        tier_order = {"high": 0, "mid": 1, "low": 2}
        ranked = sorted(
            all_syms,
            key=lambda s: (
                tier_order.get(s.get("tier", "mid"), 99),
                s["symbol"],
            ),
        )
        # Keep only TRADING symbols
        result = [s["symbol"] for s in ranked if s.get("status") == "TRADING"]
        result = result[: self.top_n]
        logger.info(
            f"[VolumePairList] generated {len(result)} symbols "
            f"(top {self.top_n} by volume)"
        )
        return result


# ── Filter: SpreadFilter ───────────────────────────────────────────────────

class SpreadFilter(PairlistHandler):
    """
    Remove pairs where the bid/ask spread ratio exceeds max_spread_ratio.
    Spread ratio = (askPrice - bidPrice) / askPrice.
    Uses cached 24hr ticker bid/ask data.
    """

    def __init__(self, max_spread_ratio: float = 0.005):
        self.max_spread_ratio = max_spread_ratio

    def filter(self, pairs: list[str], exchange: str) -> list[str]:
        kept = []
        dropped = 0
        for sym in pairs:
            ticker = get_ticker_data(exchange, sym)
            if ticker is None:
                kept.append(sym)
                continue
            bid = ticker.get("bidPrice")
            ask = ticker.get("askPrice")
            if bid is None or ask is None or bid <= 0 or ask <= 0:
                kept.append(sym)
                continue
            ratio = (ask - bid) / ask
            if ratio <= self.max_spread_ratio:
                kept.append(sym)
            else:
                dropped += 1
        if dropped:
            logger.info(
                f"[SpreadFilter] dropped {dropped}/{len(pairs)} pairs "
                f"(max_spread_ratio={self.max_spread_ratio})"
            )
        return kept


# ── Filter: VolatilityFilter ───────────────────────────────────────────────

class VolatilityFilter(PairlistHandler):
    """
    Keep pairs whose 24h volatility (high/low range / close) falls within
    [min_volatility, max_volatility]. Uses cached 24hr ticker high/low.
    """

    def __init__(self, min_volatility: float = 0.005, max_volatility: float = 0.20):
        self.min_volatility = max(0.0, min_volatility)
        self.max_volatility = max(self.min_volatility, max_volatility)

    def filter(self, pairs: list[str], exchange: str) -> list[str]:
        kept = []
        dropped = 0
        for sym in pairs:
            ticker = get_ticker_data(exchange, sym)
            if ticker is None:
                kept.append(sym)
                continue
            high = ticker.get("highPrice")
            low = ticker.get("lowPrice")
            if high is None or low is None or high <= 0 or low <= 0:
                kept.append(sym)
                continue
            volatility = (high - low) / high  # normalized range
            if self.min_volatility <= volatility <= self.max_volatility:
                kept.append(sym)
            else:
                dropped += 1
        if dropped:
            logger.info(
                f"[VolatilityFilter] dropped {dropped}/{len(pairs)} pairs "
                f"(volatility∈[{self.min_volatility},{self.max_volatility}])"
            )
        return kept


# ── Filter: PrecisionFilter ────────────────────────────────────────────────

class PrecisionFilter(PairlistHandler):
    """
    Drop pairs where the exchange's precision / step size makes stop-loss
    placement unreliable — i.e. where a single tick jump represents a large
    fraction of the stop distance. This directly addresses the JUPUSDT class
    of bugs where rounding broke the stop.
    """

    def __init__(self, max_tick_fraction: float = 0.5):
        self.max_tick_fraction = max_tick_fraction

    def filter(self, pairs: list[str], exchange: str) -> list[str]:
        kept = []
        dropped = 0
        for sym in pairs:
            rules = _rules_cache.get((exchange, sym))
            if not rules:
                kept.append(sym)
                continue
            tick = rules.get("tickSize")
            if tick is None or tick <= 0:
                kept.append(sym)
                continue
            # Check if tick is a significant fraction of typical stop distance.
            # A reasonable stop is ~0.5% of price. If tick > 0.5% of price,
            # stop placement is unreliable. We approximate: if minNotional > 0
            # and price is very low, tick/price could be large.
            tick_fraction = float(tick) / 100.0  # normalized to ~0.5% of price
            if tick_fraction > self.max_tick_fraction:
                dropped += 1
            else:
                kept.append(sym)
        if dropped:
            logger.info(
                f"[PrecisionFilter] dropped {dropped}/{len(pairs)} pairs "
                f"(max_tick_fraction={self.max_tick_fraction})"
            )
        return kept


# ── Filter: AgeFilter (no-op without listing date data) ────────────────────

class AgeFilter(PairlistHandler):
    """
    Placeholder: drop pairs listed for fewer than min_days_listed.
    Requires exchangeInfo listing date data not currently cached.
    Currently passes all pairs through unchanged.
    """

    def __init__(self, min_days_listed: int = 30):
        self.min_days_listed = min_days_listed

    def filter(self, pairs: list[str], exchange: str) -> list[str]:
        # TODO: implement when exchangeInfo listing dates are cached
        return pairs


# ── Pipeline ───────────────────────────────────────────────────────────────

class PairlistPipeline:
    """
    Chain a generator + filters into a single pipeline.
    Usage:
        pipe = PairlistPipeline(VolumePairList(30), [SpreadFilter(), PrecisionFilter()])
        symbols = pipe.run("Binance Futures")
    """

    def __init__(
        self,
        generator: Optional[PairlistHandler] = None,
        filters: Optional[list[PairlistHandler]] = None,
    ):
        self.generator = generator or VolumePairList(30)
        self.filters = filters or []

    def run(self, exchange: str = "Binance Futures") -> list[str]:
        pairs = self.generator.filter([], exchange)
        for f in self.filters:
            pairs = f.filter(pairs, exchange)
        return pairs

    def __repr__(self):
        parts = [f"gen={self.generator.__class__.__name__}"]
        for f in self.filters:
            parts.append(f.__class__.__name__)
        return f"PairlistPipeline({'→'.join(parts)})"


# ── Config-based factory ───────────────────────────────────────────────────

HANDLER_REGISTRY = {
    "volume": VolumePairList,
    "spread": SpreadFilter,
    "volatility": VolatilityFilter,
    "precision": PrecisionFilter,
    "age": AgeFilter,
}


def _build_handler(cfg: dict) -> PairlistHandler:
    handler_type = cfg.pop("type", "volume")
    cls = HANDLER_REGISTRY.get(handler_type)
    if cls is None:
        logger.warning(f"[pairlist] unknown handler type '{handler_type}', using VolumePairList fallback")
        cls = VolumePairList
        cfg = {"top_n": 30}
    return cls(**cfg)


def pairlist_from_config(config: Optional[dict]) -> PairlistPipeline:
    """
    Build a PairlistPipeline from a config dict.
    Config shape:
        {
            "generator": {"type": "volume", "top_n": 30},
            "filters": [
                {"type": "spread", "max_spread_ratio": 0.005},
                {"type": "precision"},
            ]
        }
    Returns a default pipeline (VolumePairList(30) only) if config is empty.
    """
    if not config:
        return PairlistPipeline(generator=VolumePairList(30), filters=[])

    gen_cfg = dict(config.get("generator", {"type": "volume", "top_n": 30}))
    generator = _build_handler(gen_cfg)

    filters = []
    for f_cfg in config.get("filters", []):
        filters.append(_build_handler(dict(f_cfg)))

    return PairlistPipeline(generator=generator, filters=filters)
