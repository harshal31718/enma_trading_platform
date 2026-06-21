"""Trade recorder — best-effort writer for completed round-trip trades.

Persists to MongoDB collection `tradeRecords`. Engine is the sole writer;
server reads only. Write failures are logged but never propagated to avoid
delaying or blocking the position close path.
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from config.mongo import get_database

logger = logging.getLogger(__name__)


async def record_trade(record: dict[str, Any]) -> None:
    """Insert a trade record into MongoDB.

    Best-effort: logs on failure, never raises.
    """
    try:
        db = get_database()
        await db.tradeRecords.insert_one(record)
        logger.info(f"[TradeRecorder] Recorded trade {record.get('tradeId')}")
    except Exception as e:
        logger.error(f"[TradeRecorder] Failed to record trade: {e}")


def build_trade_record(
    *,
    source: str,
    executed_by: str,
    symbol: str,
    side: str,
    qty: str,
    entry_price: str,
    exit_price: str,
    sl_order_price: str | None,
    tp_order_price: str | None,
    margin: str | None,
    liquidation_price: str | None,
    leverage: float | None,
    net_pnl: str,
    pnl_pct: str | None,
    fee: str | None,
    exit_reason: str,
    session_id: str | None,
    strategy_name: str | None,
    entry_time: datetime,
    exit_time: datetime,
) -> dict[str, Any]:
    """Assemble a trade record dict from captured fields.

    Reusable by both bot close paths and future manual recorder.
    """
    trade_id = f"trade_{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc)

    return {
        "tradeId": trade_id,
        "source": source,
        "executedBy": executed_by,
        "symbol": symbol,
        "side": side,
        "qty": qty,
        "entryPrice": entry_price,
        "exitPrice": exit_price,
        "slOrderPrice": sl_order_price,
        "tpOrderPrice": tp_order_price,
        "margin": margin,
        "liquidationPrice": liquidation_price,
        "leverage": leverage,
        "netPnl": net_pnl,
        "pnlPct": pnl_pct,
        "fee": fee,
        "exitReason": exit_reason,
        "sessionId": session_id,
        "strategyName": strategy_name,
        "entryTime": entry_time,
        "exitTime": exit_time,
        "createdAt": now,
    }