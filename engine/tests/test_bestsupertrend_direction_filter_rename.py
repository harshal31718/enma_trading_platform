"""Plan 24 Step S-4 regression: BestSupertrend's direction-filter param was
named "order_type", colliding with `OrderPlan.order_type`
(`core/models/base.py`) — `DefaultExecution.route()` builds
`OrderPlan(order_type=getattr(s, "order_type", "market"))`, so every
BestSupertrend order plan silently carried the filter string
("Longs+Shorts"/"LongsOnly"/"ShortsOnly") instead of "market". Renamed to
"direction_filter"; `BaseStrategy.__init__` already sets `self.order_type =
"market"`, so the rename lets that base default show through correctly.

Run inside the container::

    docker exec enma_trading_platform-engine-1 pytest /app/tests/test_bestsupertrend_direction_filter_rename.py
"""
import os
import sys

try:
    if not os.path.exists("/engine"):
        os.symlink("/app", "/engine")
except Exception:
    pass
if "/" not in sys.path:
    sys.path.insert(0, "/")

from strategies.BestSupertrend import BestSupertrend


def test_order_type_attribute_is_the_base_strategy_default_not_the_filter():
    s = BestSupertrend()
    assert s.order_type == "market"


def test_direction_filter_param_holds_the_old_filter_semantics():
    s = BestSupertrend()
    assert s.direction_filter == "Longs+Shorts"
    assert "direction_filter" in s.PARAMS
    assert "order_type" not in s.PARAMS


def test_old_order_type_param_key_no_longer_exists_in_params():
    """Confirms F-016 unknown-param validation will reject a saved config
    still using the old key — the desired loud failure, not a silent
    fall-through to the default filter."""
    s = BestSupertrend()
    assert "order_type" not in s.PARAMS
    assert set(s.PARAMS["direction_filter"]["options"]) == {"Longs+Shorts", "LongsOnly", "ShortsOnly"}
