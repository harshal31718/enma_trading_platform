"""Shared strategy-name validation (Plan 8 Step 8.5, ENG-14).

Was defined only in `routers/strategies.py` (used by the strategy-creation
API) and never applied on the live-session start path
(`core/live_bot_manager.py`'s `start_session`), which dynamically imports
`strategies.{strategy_name}` with zero validation. Extracted here so both
call sites check the same shape — a helper that returns a bool rather than
raising, since the two callers need different error types (an HTTP 400 in
the router, a session-visible Node notification in the live path).
"""

import re

STRATEGY_NAME_REGEX = re.compile(r"^[A-Za-z][A-Za-z0-9_]+$")


def is_valid_strategy_name(name: str) -> bool:
    return isinstance(name, str) and bool(STRATEGY_NAME_REGEX.match(name.strip()))
