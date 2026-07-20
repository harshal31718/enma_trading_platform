"""Registers the ``engine.*`` import alias (Plan 6 Step 6.6, ENG-12) for the
pytest process, so tests that dynamically load a strategy file (which import
``from engine.core.strategy import BaseStrategy`` etc — engine/CLAUDE.md's
documented strategy-author convention) resolve those imports to the exact
same module objects as the rest of the suite's ``core.xxx``/``services.xxx``
imports. See core/engine_alias.py's own docstring for the full rationale.
"""
from core.engine_alias import install_engine_alias

install_engine_alias()
