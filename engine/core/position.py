from core.margin import initial_margin, liquidation_price


class Position:
    """
    Represents a futures trading position in the simulation.

    Handles P&L for long and short, plus isolated-margin accounting:
    initial margin locked on open and the liquidation price.

    Backward compatibility: the live bot constructs ``Position(type, qty,
    entry_price)`` with no margin context. In that case ``leverage`` defaults to
    1 and the margin/liquidation fields are still computed but harmless — the
    live bot relies on Binance's native bracket orders, not this object's
    liquidation check.
    """

    def __init__(
        self,
        type: str,
        qty: float,
        entry_price: float,
        leverage: float = 1.0,
        isolated_wallet: float | None = None,
        mmr_table: list | None = None,
    ):
        if type not in ("long", "short"):
            raise ValueError("Position type must be 'long' or 'short'")
        self.type = type
        self.qty = qty
        self.entry_price = entry_price
        self.leverage = max(float(leverage), 1.0)
        self.close_price = None
        self.is_open = True
        self.pnl = 0.0
        self.pnl_pct = 0.0

        # ── Isolated-margin accounting ──────────────────────────────────────
        notional = abs(qty) * entry_price
        # Initial margin locked from the wallet for this isolated position.
        self.margin = initial_margin(notional, self.leverage)
        # Wallet allocated to the isolated position. If the caller passes the
        # post-fee wallet explicitly we use it; otherwise it equals the margin.
        self._isolated_wallet = self.margin if isolated_wallet is None else isolated_wallet
        self.liquidation_price = liquidation_price(
            type, qty, entry_price, self._isolated_wallet, mmr_table
        )

    def update_pnl(self, current_price: float) -> None:
        """Update unrealized P&L and P&L percentage based on current price.

        pnl_pct is expressed on margin (ROE) so it reflects leverage — a 1%
        adverse move at 10x is a -10% return on the margin committed.
        """
        if not self.is_open:
            return

        if self.type == "long":
            self.pnl = (current_price - self.entry_price) * self.qty
        else:
            self.pnl = (self.entry_price - current_price) * self.qty

        self.pnl_pct = (self.pnl / self.margin) * 100.0 if self.margin > 0 else 0.0

    def is_liquidated(self, high: float, low: float) -> bool:
        """True if this candle's range reached the liquidation price."""
        if not self.is_open or self.liquidation_price <= 0:
            return False
        if self.type == "long":
            return low <= self.liquidation_price
        return high >= self.liquidation_price

    def close(self, close_price: float) -> None:
        """Close the position and realize P&L."""
        self.close_price = close_price
        self.is_open = False
        self.update_pnl(close_price)
