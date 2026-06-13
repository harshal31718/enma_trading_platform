"""
Binance USDⓈ-M futures isolated-margin math.

Used by the backtest engine to model real leverage, margin allocation, and
liquidation. All formulas follow Binance's official "How to Calculate
Liquidation Price of USDⓈ-M Futures Contracts" methodology:

    https://www.binance.com/en/support/faq/how-to-calculate-liquidation-price-of-usd%E2%93%A2-m-futures-contracts-b3c689c1f50a44cabb3a84e663b81d93

Notes
-----
* The maintenance-margin-rate (MMR) tier table below is a *documented static
  approximation* of Binance's published BTCUSDT leverage brackets. Smaller
  alt-coins have higher MMRs and lower max leverage; using the BTC table for
  every symbol slightly understates liquidation risk for alts. This is an
  acceptable, explicit simplification for backtesting and can later be replaced
  by a cached `/fapi/v1/leverageBracket` fetch per symbol.
* "cum" is Binance's *maintenance amount* — the constant that makes the tiered
  maintenance margin continuous across brackets. Each tier's cum satisfies:
      cum_n = cum_(n-1) + cap_(n-1) * (MMR_n - MMR_(n-1))
"""

from __future__ import annotations

# (notional_upper_bound_usdt, maintenance_margin_rate, maintenance_amount_cum)
# Sorted ascending by notional bound. Representative Binance BTCUSDT brackets.
DEFAULT_MMR_TABLE: list[tuple[float, float, float]] = [
    (50_000,        0.004, 0.0),
    (500_000,       0.005, 50.0),
    (1_000_000,     0.010, 2_550.0),
    (5_000_000,     0.025, 17_550.0),
    (20_000_000,    0.050, 142_550.0),
    (50_000_000,    0.100, 1_142_550.0),
    (100_000_000,   0.125, 2_392_550.0),
    (200_000_000,   0.150, 4_892_550.0),
    (300_000_000,   0.250, 24_892_550.0),
    (500_000_000,   0.500, 99_892_550.0),
]


def get_mmr(notional: float, table: list[tuple[float, float, float]] | None = None) -> tuple[float, float]:
    """Return (maintenance_margin_rate, cum) for a given absolute notional value.

    Picks the first tier whose upper bound is >= notional. Notionals above the
    top tier reuse the top tier's rate (Binance would reject the position, but
    for backtesting we degrade gracefully).
    """
    tbl = table or DEFAULT_MMR_TABLE
    notional = abs(notional)
    for upper, mmr, cum in tbl:
        if notional <= upper:
            return mmr, cum
    return tbl[-1][1], tbl[-1][2]


def initial_margin(notional: float, leverage: float) -> float:
    """Initial margin locked for an isolated position. leverage must be >= 1."""
    lev = max(float(leverage), 1.0)
    return abs(notional) / lev


def liquidation_price(
    side: str,
    qty: float,
    entry_price: float,
    isolated_wallet: float,
    table: list[tuple[float, float, float]] | None = None,
) -> float:
    """Isolated-margin liquidation price for a single one-way position.

    Derived from the liquidation condition `margin_balance == maintenance_margin`:

        isolated_wallet + uPnL(LP) == |qty|*LP*MMR - cum

    Solving for LP:
        long  : LP = (entry*qty - isolated_wallet - cum) / (qty * (1 - MMR))
        short : LP = (isolated_wallet + entry*qty + cum) / (qty * (1 + MMR))

    where MMR/cum are taken from the tier matching the *entry* notional.

    Parameters
    ----------
    side            : "long" | "short"
    qty             : absolute position size (always positive)
    entry_price     : average entry price
    isolated_wallet : wallet balance allocated to this isolated position
                      (initial margin, net of any opening fee already deducted)

    Returns
    -------
    The mark price at which the position is liquidated. For a long this is
    below entry; for a short, above. Returns 0.0 for degenerate inputs.
    """
    qty = abs(qty)
    if qty <= 0 or entry_price <= 0:
        return 0.0

    notional = qty * entry_price
    mmr, cum = get_mmr(notional, table)

    if side == "long":
        denom = qty * (1.0 - mmr)
        if denom <= 0:
            return 0.0
        lp = (entry_price * qty - isolated_wallet - cum) / denom
        return max(lp, 0.0)
    else:  # short
        denom = qty * (1.0 + mmr)
        lp = (isolated_wallet + entry_price * qty + cum) / denom
        return max(lp, 0.0)
