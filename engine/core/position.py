class Position:
    """
    Represents a trading position in the simulation.
    Handles P&L calculation for long and short types.
    """

    def __init__(self, type: str, qty: float, entry_price: float):
        if type not in ("long", "short"):
            raise ValueError("Position type must be 'long' or 'short'")
        self.type = type
        self.qty = qty
        self.entry_price = entry_price
        self.close_price = None
        self.is_open = True
        self.pnl = 0.0
        self.pnl_pct = 0.0

    def update_pnl(self, current_price: float) -> None:
        """Update unrealized P&L and P&L percentage based on current price."""
        if not self.is_open:
            return

        if self.type == "long":
            self.pnl = (current_price - self.entry_price) * self.qty
            self.pnl_pct = ((current_price / self.entry_price) - 1.0) * 100.0
        else:
            self.pnl = (self.entry_price - current_price) * self.qty
            self.pnl_pct = (1.0 - (current_price / self.entry_price)) * 100.0

    def close(self, close_price: float) -> None:
        """Close the position and realize P&L."""
        self.close_price = close_price
        self.is_open = False
        self.update_pnl(close_price)
