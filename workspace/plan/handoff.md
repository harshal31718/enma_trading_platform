# Session Handoff Log

Resume prompts for cross-session continuity (root `CLAUDE.md` Rule G / `AGENTS.md` → Session Handoff).

**Format rules:**
- Newest entry on top: `## <date> — <title> — <status>` with **Goal / Done / Files changed / Open questions**.
- Keep at most the **3 most recent entries**. When adding a new one, delete the oldest — git history is the archive. This file must stay a short resume prompt, not a project log.

---
## 2026-07-20 — Plan 6 Step 6.6 SHIPPED FOR REAL — engine_alias import hook replaces the symlink hack, verified via a real image rebuild + container restart

**Goal:** user authorized (via AskUserQuestion) a real container rebuild to close out Step 6.6,
which a prior pass this session had investigated but deliberately left unimplemented pending that
authorization. Full details/root-cause investigation are in that prior entry (now superseded) and
the plan file's Step 6.6 section — condensed here.

**Design, different from the originally-suggested `pyproject.toml`/`pip install -e .` shape**:
investigation found no packaging change was actually needed. A `sys.meta_path` finder/loader
(new `core/engine_alias.py`, `install_engine_alias()`) intercepts any `engine`/`engine.X` import
and reassigns `sys.modules['engine.X']` to the ALREADY-CANONICAL `X` module (`core.X`/
`services.X`/etc) — genuine single module identity (`engine.core.margin is core.margin` now
`True`, verified `False` before the fix), zero duplicate state, no symlink, no `sys.path`
mutation. `engine.*` still resolves for strategy authors (the documented, must-preserve
convention) — it's just no longer a SEPARATE module object. Installed at every real entry point
that might dynamically load a strategy file: `main.py` (replacing its symlink+sys.path hack),
`scripts/golden_master.py`/`scripts/recursive.py`/`scripts/lookahead_sentinel.py`/
`scripts/_portfolio_check.py` (each had their own independent copy of the same hack — 5 total,
not just main.py's one), and a new `engine/tests/conftest.py` for the pytest process. Also
cleaned up the now-redundant dual `try: from engine.X import ... except ImportError: from core.X
import ...` dance across 16 internal files (all internal code now imports bare `core.X`/
`services.X`/`utils.X`, the canonical form) and 4 test files with their own inline symlink-hack
copies (made redundant by `conftest.py`) — closing out ENG-12's stated scope in full, not just
the packaging-identity half.

**Verified via a REAL image rebuild + restart** (not just `docker exec` into the already-running
container, unlike every other change this session): `docker compose build engine` (clean build,
all layers cached except the final `COPY . .`), `docker compose up -d --no-deps engine`
(container recreated), confirmed via `docker logs` — full clean boot, exchange rules cached for
729 futures + 3649 spot symbols, all 5 strategies seeded successfully (proves the alias resolves
correctly in the actual live app process, not just an ad-hoc check), `/health` returns 200 with
Mongo/Timescale both connected. Post-restart: pytest 647/647, golden-master's `MultiDivergence`
summary line (`trades=55 netProfit=-1784.02 winRate=0.36 cagr=-71.32 sqn=-2.08`) byte-identical
to every prior golden-master run this session (the `before_packaging_v2.json` file itself didn't
survive the container recreate — ephemeral filesystem, not a bind mount — but the deterministic
computed output matching exactly across the restart is the real proof). Zero symlink/`sys.path`
hack copies remain anywhere in the codebase (verified by grep).

**Files changed:** `engine/core/engine_alias.py` (new), `engine/main.py`, `engine/scripts/
golden_master.py`/`recursive.py`/`lookahead_sentinel.py`/`_portfolio_check.py`, `engine/tests/
conftest.py` (new), 16 internal files' dual-import cleanup (`core/kernel.py`, `core/live_bot_
manager.py`, `core/models/{cost,execution,exec_algo,risk}.py`, `core/pipeline.py`, `core/
strategy.py`, `services/backtest_runner.py`, all 5 `strategies/*/__init__.py`), 4 test files'
inline hack cleanup (`test_bestsupertrend_direction_filter_rename.py`, `test_bestsupertrend_
htf_parity.py`, `test_boundaries.py`, `test_exchange_migration.py`, `test_start_session_risk_
params_shape.py`). Docs: `6_engine-decomposition-and-exchange-abstraction.md` (Step 6.6 section
replaced with the real outcome), `0_tracker.md` (Plan 6 row), this file.

**Open questions:** none blocking — Step 6.6 is fully shipped. Plan 6 status: 6.1, 6.2, 6.4
(narrower scope), 6.6 all shipped this session. Remaining: 6.3 (needs the user's `BaseStrategy`
DECISIONS.md call, see the entry two above this one), 6.5's Redis-stream channel (needs Node-side
consumer code, cross-service).

---
## 2026-07-20 — Plan 6 Step 6.3: investigated, deliberately NOT implemented — the typed value objects already exist, the real gap needs a BaseStrategy DECISIONS.md call

**Goal:** the last Plan 6 item not blocked on Node work (6.5) or a container rebuild sign-off
(6.6, prior entry) — "replace the mutable-attribute protocol with an explicit
OrderIntent/Signal object the strategy returns and the kernel consumes."

**Finding: the plan text's premise is partly stale.** `core/models/base.py` already defines a
full typed pipeline — `Signal → RiskConstraints → CostEstimate → TargetPortfolio → OrderPlan`,
all `@dataclass`, threaded through `pipeline.py`'s `evaluate()` and consumed by `kernel.py`. A
typo'd field there is already a type error. That part of Step 6.3's acceptance text is already
satisfied and has been for a while (Narang Five-Model Architecture).

**The real gap**: `DefaultExecution.route()` (`core/models/execution.py`) is documented as the
"sole writer" of `s.buy`/`s.sell`/`s.stop_loss`/`s.take_profit`/`s._pending_flip`/
`s._close_at_open`, and writes those SAME fields alongside returning a typed `OrderPlan` — but
only for its flat→enter path. For maintain/flip/close (3 of its 5 paths) it writes the mutable
attributes and returns `None`. `kernel.py` then reads a mix of `plan.*` and `strategy.*` for the
same event — that mixed read pattern is the real "temporal coupling ... spread across
kernel/adapter/manager" the acceptance text names, not a missing type. Grepped the surface before
estimating: `_pending_flip` 73 occurrences/48 files, `_close_at_open` 51/32,
`s.stop_loss`/`s.take_profit` 31+30 across 18/16 files — an order of magnitude bigger than
anything shipped this session.

**Also found, pre-existing and independent of this step**: `kernel.py`'s own exec_algo branch
(lines ~496-499) already writes `strategy.stop_loss`/`take_profit` directly, violating
`route()`'s own "sole writer" docstring. Worth its own small fixes-queue item — narrow, doesn't
need the interface decision below.

**Why NOT implemented**: `self.buy`/`self.stop_loss`/etc are declared in `BaseStrategy.__init__`
and documented in `engine/CLAUDE.md`'s "Available properties" as strategy-facing. A real fix means
`kernel.py`/`LiveAdapter` stop READING these (treating them as `route()`'s write-only internal
scratch state, consuming `OrderPlan` exclusively instead) — root `CLAUDE.md` requires a
`DECISIONS.md` entry before changing `BaseStrategy`'s interface, and this reaches all 5 seeded
strategies on the live-trading path with zero golden-master coverage on the live side. That's the
user's call, not a background pass's. No code changed; `before_typed_contract.json` golden-master
baseline was captured but is unused (safe to discard, or reuse whenever implementation starts).

**Files changed:** none (code). Docs: `6_engine-decomposition-and-exchange-abstraction.md` (Step
6.3 section — full design + recommendation), `0_tracker.md` (Plan 6 row), this file.

**Open questions — for the user, not blocking other work:** should `kernel.py`/`LiveAdapter` stop
reading `BaseStrategy`'s mutable order-state attributes and consume `OrderPlan` exclusively? If
yes, this needs a `DECISIONS.md` entry and is likely its own multi-session effort, not a single
pass. **Plan 6 overall status**: 6.1/6.2/6.4 shipped; 6.3 scoped-but-gated on a user decision; 6.5
needs Node-side consumer code; 6.6 scoped-but-gated on a container-rebuild sign-off. Nothing left
in Plan 6 is actionable without either the user's input or cross-service work.

---
## 2026-07-20 — Plan 6 Step 6.4: kernel `is_live` parameter-threading killed (deliberately narrower than full timing unification)

**Goal:** user picked kernel `is_live` removal (over 6.3's typed contract) as the next Plan 6 item.
This is the ONE piece of Plan 6 touching code shared by both the golden-master-protected backtest
path and the live path — treated with more caution than every other change this session.

**Design:** `ExecutionAdapter` (`core/kernel.py`) gained an abstract `is_live: bool` property.
`check_exits()`/`evaluate_and_route()` no longer take `is_live` as a parameter — each method reads
`self.adapter.is_live` once into a local var instead, and every existing internal `if is_live:`
check downstream is unchanged. `LiveAdapter.is_live` → `True`, `BacktestAdapter.is_live` → `False`.
This kills the real risk (a caller passing the WRONG `is_live` for the adapter it's driving —
structurally impossible now) without touching WHAT each branch does or WHEN it runs.

**Deliberately NOT attempted**: a full redesign where the kernel calls one polymorphic method and
each adapter owns its own execution-timing model (backtest defers to `execute_pending()` on the
next candle via strategy attributes; live executes inline). Investigated first: confirmed via
`backtest_runner.py`'s runner loop that `execute_pending → check_exits → evaluate_and_route` runs
in that exact order every candle, and live never calls `execute_pending` at all. Backtest's
deferral isn't adapter machinery today — it's `strategy.buy`/`sell`/`_pending_flip`/
`_close_at_open`/`qty_to_adjust` attributes the runner loop's NEXT iteration reads. Moving that
into the adapters means giving `BacktestAdapter` authority over candle-loop advancement it doesn't
have — a materially bigger structural change needing its own dedicated design pass, not something
to gamble on the no-lookahead invariant for in one session. This is a legitimate, deliberately
scoped partial result, not an incomplete one — see the plan file's Step 6.4 section for the full
reasoning.

**Verified:** engine pytest 647/647 unchanged (pure refactor — 4 test files' `ExecutionAdapter`
subclasses gained the `is_live` property, call sites stopped passing `is_live=`, zero new tests
needed since no behavior changed). Golden-master byte-identical (`before_kernel_is_live.json` vs
`after_kernel_is_live.json`, 5/5 strategies) — the one change this session that actually touches
the golden-master-protected path. Container `/health` 200; `core.kernel`/`core.live_bot_manager`/
`services.backtest_runner` import cleanly.

**Files changed:** `engine/core/kernel.py`, `engine/core/live_bot_manager.py`,
`engine/services/backtest_runner.py`; `engine/tests/test_entry_candle_exits.py`,
`test_armed_legs_wick_check_skip.py`, `test_intrabar_detail_resolution.py`,
`test_exec_algo_slicing.py`. Docs: `6_engine-decomposition-and-exchange-abstraction.md` (Step 6.4
section), `engine/CLAUDE.md` (`kernel.py` folder-structure entry), `0_tracker.md` (Plan 6 row),
this file.

**Open questions:** none blocking. The full timing-model unification described above remains
scoped-but-not-started if ever pursued — needs its own dedicated design pass. Remaining Plan 6
scope unchanged otherwise: Step 6.5's Redis-stream channel (cross-service, needs Node work), Steps
6.3/6.6 not started.

