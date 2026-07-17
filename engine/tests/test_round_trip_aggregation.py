"""Plan 9 Step 9.9 (QNT-14) regression: `services.metrics.aggregate_legs_to_round_trips`
— groups a scale-out position's partial-exit legs + final close into one
synthetic round-trip record, so trade-level statistics (totalTrades/winRate/
SQN/streaks) don't triple-count a 3-leg DCA exit as 3 independent trades.

This function is opt-in at the `run_backtest_simulation(round_trip_stats=...)`
call site (default False, byte-identical) — these tests exercise the pure
function directly.

Run inside the container::

    docker exec enma_trading_platform-engine-1 pytest /app/tests/test_round_trip_aggregation.py
"""
from services.metrics import aggregate_legs_to_round_trips


def _leg(symbol, entry_at, exit_at, pnl, qty, entry_price=100.0, leverage=1, **extra):
    return {
        "symbol": symbol, "entryAt": entry_at, "exitAt": exit_at, "_exit_dt": exit_at,
        "pnl": str(pnl), "qty": str(qty), "entryPrice": str(entry_price), "leverage": leverage,
        "type": "long", **extra,
    }


def test_single_leg_position_passes_through_unchanged():
    leg = _leg("BTCUSDT", "t0", "t1", 50.0, 1.0)
    out = aggregate_legs_to_round_trips([leg])
    assert out == [leg]
    assert "legCount" not in out[0]


def test_scale_out_legs_aggregate_into_one_round_trip():
    legs = [
        _leg("BTCUSDT", "t0", "t1", 30.0, 0.3, exitReason="scale_out"),
        _leg("BTCUSDT", "t0", "t2", 20.0, 0.3, exitReason="scale_out"),
        _leg("BTCUSDT", "t0", "t3", 10.0, 0.4, exitReason="take_profit"),  # final leg
    ]
    out = aggregate_legs_to_round_trips(legs)
    assert len(out) == 1
    rt = out[0]
    assert rt["legCount"] == 3
    assert float(rt["pnl"]) == 60.0  # 30 + 20 + 10
    assert float(rt["qty"]) == 1.0   # 0.3 + 0.3 + 0.4 (original total position size)
    assert rt["exitReason"] == "take_profit"  # from the FINAL leg, not a scale_out
    assert rt["exitAt"] == "t3"


def test_pnl_pct_recomputed_from_aggregate_pnl_and_original_margin():
    legs = [
        _leg("BTCUSDT", "t0", "t1", 30.0, 0.5, entry_price=100.0, leverage=1),
        _leg("BTCUSDT", "t0", "t2", 20.0, 0.5, entry_price=100.0, leverage=1),
    ]
    out = aggregate_legs_to_round_trips(legs)
    # total_pnl=50, margin = 100 * 1.0(total qty) / 1(leverage) = 100 -> 50%
    assert out[0]["pnlPct"] == "50.00"


def test_distinct_positions_on_same_symbol_never_merge():
    """Two fully separate, sequential positions on the same symbol (different
    entryAt) must stay as two independent round trips, not merge."""
    legs = [
        _leg("BTCUSDT", "t0", "t1", 10.0, 1.0),
        _leg("BTCUSDT", "t5", "t6", -5.0, 1.0),
    ]
    out = aggregate_legs_to_round_trips(legs)
    assert len(out) == 2
    assert out[0]["entryAt"] == "t0"
    assert out[1]["entryAt"] == "t5"


def test_different_symbols_never_merge_even_with_same_entry_at():
    legs = [
        _leg("BTCUSDT", "t0", "t1", 10.0, 1.0),
        _leg("ETHUSDT", "t0", "t1", -5.0, 1.0),
    ]
    out = aggregate_legs_to_round_trips(legs)
    assert len(out) == 2


def test_output_preserves_insertion_order_of_first_occurrence():
    legs = [
        _leg("ETHUSDT", "tA", "tB", 1.0, 1.0),
        _leg("BTCUSDT", "t0", "t1", 30.0, 0.5),
        _leg("BTCUSDT", "t0", "t2", 20.0, 0.5),
    ]
    out = aggregate_legs_to_round_trips(legs)
    assert len(out) == 2
    assert out[0]["symbol"] == "ETHUSDT"
    assert out[1]["symbol"] == "BTCUSDT"
    assert out[1]["legCount"] == 2


def test_empty_input_returns_empty_list():
    assert aggregate_legs_to_round_trips([]) == []


def test_does_not_mutate_input_single_leg():
    leg = _leg("BTCUSDT", "t0", "t1", 50.0, 1.0)
    original = dict(leg)
    aggregate_legs_to_round_trips([leg])
    assert leg == original


def test_does_not_mutate_input_multi_leg():
    legs = [
        _leg("BTCUSDT", "t0", "t1", 30.0, 0.5),
        _leg("BTCUSDT", "t0", "t2", 20.0, 0.5),
    ]
    originals = [dict(l) for l in legs]
    aggregate_legs_to_round_trips(legs)
    assert legs == originals
