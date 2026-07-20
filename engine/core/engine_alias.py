"""Plan 6 Step 6.6 (ENG-12): makes ``engine.*`` imports resolve to the exact
SAME module objects as the canonical ``core.*``/``services.*``/``utils.*``/
``config.*``/``routers.*``/``indicators.*`` imports every internal module
already uses — without the old ``/engine -> /app`` symlink + ``sys.path.
insert(0, '/')`` hack that used to be duplicated three times (``main.py``,
``scripts/golden_master.py``, ``scripts/recursive.py``).

**Why ``engine.*`` needs to resolve at all**: it is not dead/accidental —
it's ``engine/CLAUDE.md``'s own documented public strategy-author convention
(``from engine.core.strategy import BaseStrategy``, ``import engine.core.
models``, ``import engine.indicators as ta``), used unconditionally by all 5
seeded strategies, and strategies are user-uploadable at runtime (``PUT
/strategies/:name/code``) — real stored strategy code outside this repo may
already depend on it. So the fix cannot be "delete engine.* usage."

**Why the symlink was wrong, not just inelegant**: a symlink makes ``/engine``
a SEPARATE filesystem path from ``/app``, so Python's import system treats
``engine.core.margin`` and ``core.margin`` as two independently-loaded module
objects for the same source file (verified: ``engine.core.margin is core.
margin`` was ``False``) — exactly the "duplicate-module identity/singleton"
bug class ENG-12 exists to kill, not preserve, for any module with
module-level state (caches, singletons, connection pools).

This module installs a ``sys.meta_path`` finder/loader so that importing
``engine`` or any ``engine.X`` reassigns ``sys.modules['engine.X']`` to the
ALREADY-LOADED (or freshly imported) ``X`` module object — genuine single
identity, zero duplicate state, no filesystem symlink, no ``sys.path``
mutation. Call ``install_engine_alias()`` once, as early as possible, in any
process that might dynamically load a strategy file (the live app via
``main.py``, the golden-master harness, ``scripts/recursive.py``, and the
pytest process via ``tests/conftest.py``) — idempotent, safe to call more
than once or from more than one of those entry points.
"""
from __future__ import annotations

import importlib
import importlib.abc
import importlib.machinery
import sys


class _EngineAliasLoader(importlib.abc.Loader):
    def create_module(self, spec):
        return None  # let the import machinery create a default module

    def exec_module(self, module) -> None:
        fullname = module.__name__
        if fullname == "engine":
            # Lightweight namespace root — never has its own source file;
            # submodule imports (engine.core, engine.services, ...) attach
            # themselves to it as the import machinery resolves each one.
            module.__path__ = []
            return
        real_name = fullname[len("engine."):]
        real_module = importlib.import_module(real_name)
        # Reassigning sys.modules[fullname] here is the standard import-alias
        # pattern: CPython's import machinery re-fetches sys.modules[spec.name]
        # AFTER exec_module() returns, so this becomes the module every caller
        # of `import engine.X` / `from engine.X import Y` actually receives —
        # the real, already-canonical module object, not a copy.
        sys.modules[fullname] = real_module


class _EngineAliasFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname != "engine" and not fullname.startswith("engine."):
            return None
        return importlib.machinery.ModuleSpec(fullname, _EngineAliasLoader(), is_package=True)


def install_engine_alias() -> None:
    """Idempotent — safe to call from every process entry point that might
    dynamically load a strategy file."""
    if any(isinstance(f, _EngineAliasFinder) for f in sys.meta_path):
        return
    sys.meta_path.insert(0, _EngineAliasFinder())
