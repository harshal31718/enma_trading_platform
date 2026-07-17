# Plan 19 — Bayesian Hyperopt (Optuna)

**Status:** Merged→10 · **Superseded by:** `10_monte-carlo-strategy-lab.md` Phase 3 (§2.2, §3.3)

> **2026-07-15:** same conflict as `18_walk-forward-analysis.md` — Plan 10 Phase 3 already
> specifies Optuna TPE as the Strategy Lab's search engine, extending the existing `/optimize`
> surface rather than this file's proposed `method` param on the old sync endpoint in isolation.
> **Do not build this file standalone.** Its real value — the `trial.suggest_*` search-space
> adapter mapping (reusing the existing `param_grid` JSON spec unchanged for both grid and
> Bayesian) and the async ask/tell-vs-executor design note — is good input for Plan 10 Phase 3's
> implementation. The design below is kept unmodified as that reference.

**Goal:** Replace brute-force grid search with sample-efficient Bayesian optimization so we find good
parameters in far fewer backtests. Same objective registry, same backtest path — smarter search.

---

## Current state (audited)

- `engine/services/optimizer.py` is **grid-only**: `_build_param_grid()` → `itertools.product()` over
  per-param value lists, optional random subsample to `max_combinations`. Scored by an
  `OBJECTIVE_REGISTRY` keyed `"sharpe"`, etc. Public entry: `run_optimization(config, param_grid,
  max_combinations)`. Router: `engine/routers/optimize.py → POST /optimize`.
- **No optuna / no Bayesian search.** This is a confirmed gap.
- Reusable assets: the objective functions, `OptimizerConfig`, and the `run_backtest_simulation` call
  per trial are all already factored — S8 swaps only the **search loop**.

## Upstream reference

- **freqtrade Hyperopt** uses **optuna** (TPE sampler) under the loss-function interface
  `IHyperOptLoss.hyperopt_loss_function(results, min_date, max_date, starting_balance, ...) -> float`
  where **lower is better** (e.g. `SharpeHyperOptLoss` returns `-sharpe`). Multiple built-in loss
  functions; users select one.
- TPE (Tree-structured Parzen Estimator) models P(params | good) vs P(params | bad) and proposes the
  next trial — far fewer evaluations than grid for the same quality.

Port: keep Enma's existing objective registry, but **negate for minimization** and drive trials with
an optuna `study` instead of `itertools.product`.

## Design (Enma-native)

Additive: grid stays the default; Bayesian is an opt-in `method`. No behavior change unless requested.

### New dependency
- `optuna` → add to `engine/requirements.txt` **and** update root + engine `CLAUDE.md` (per the
  "no new packages without updating CLAUDE.md" rule). Optuna is pure-Python, no native build (safe in
  the container).

### Search-space mapping
- Reuse the existing `param_grid` spec but interpret it for optuna:
  - `{min, max, step|num, type: int}` → `trial.suggest_int(name, min, max, step=step)`
  - `{min, max, type: float}` → `trial.suggest_float(name, min, max)` (or `log=True` for scale params)
  - categorical lists → `trial.suggest_categorical`.
- One adapter so the **same `param_grid` JSON** works for both grid and Bayesian — no new client contract.

### Objective wrapper
```python
def _objective(trial, config, param_grid, objective_name):
    params = _suggest_params(trial, param_grid)        # uses suggest_* per spec
    metrics = await run_backtest_simulation(config_with(params))   # existing path
    score = OBJECTIVE_REGISTRY[objective_name](metrics)            # existing scorer
    return -score                                                   # optuna minimizes; we maximize
```

### Driver
- `run_bayesian_optimization(config, param_grid, n_trials, objective, seed)`:
  `study = optuna.create_study(direction="minimize", sampler=TPESampler(seed=seed))`, then
  `study.optimize(..., n_trials=n_trials)`. **Seed the sampler** for reproducibility (matches the
  determinism stance everywhere else in the engine).
- Publish progress to Redis each trial (reuse the optimizer's progress mechanism); support cancel via
  the same Redis cancel channel pattern.
- Return the same ranked-results shape as grid `run_optimization()` so the UI is unchanged.

### Router
- Extend `POST /optimize` with `method: "grid" | "bayesian"` (default `"grid"`) and `nTrials`
  (bayesian only). Backward compatible — omitting `method` = today's grid behavior.

## Files to create / modify

| Action | File | Change |
|--------|------|--------|
| Modify | `engine/services/optimizer.py` | `run_bayesian_optimization()` + `_suggest_params()` adapter; share `OBJECTIVE_REGISTRY` |
| Modify | `engine/routers/optimize.py` | `method` + `nTrials` params; dispatch grid vs bayesian |
| Modify | `engine/requirements.txt` | add `optuna` |
| Modify | `CLAUDE.md` (root) + `engine/CLAUDE.md` | record the new dependency + the optuna usage |
| Create | `engine/tests/test_bayesian_optimizer.py` | param-suggestion mapping correctness; seeded study is reproducible; finds a known optimum of a toy objective in ≤ N trials |
| Modify | `client/src/...optimize UI` | (optional) method selector + trial budget input (no rounded corners; emerald tokens) |

## Verification gate

- **Reproducibility:** same seed + same space → identical trial sequence and best params (byte-stable).
- **Efficiency claim:** on a strategy/space where grid needs ~M evaluations to find the optimum,
  Bayesian reaches within X% of that optimum in ≤ M/4 trials. Demonstrate in the test/report.
- **Back-compat:** `POST /optimize` with no `method` behaves exactly as before (grid) — existing
  optimize flows untouched.

## Sequencing & risks

- **Last.** It plugs into the **S7 walk-forward** train step (Bayesian per-fold optimization), so build
  S7 first, then make S8 selectable as the fold optimizer.
- Risk: new dependency — optuna must install cleanly in the engine image; pin a version and note it.
- Risk: async + optuna — `study.optimize` is sync; run trials in an executor or use optuna's ask/tell
  API to await `run_backtest_simulation` per trial. Decide and document (ask/tell is cleaner for async).
- No golden-master gate (optimizer doesn't alter the single-run sim), but the **per-trial backtest must
  remain the unchanged `run_backtest_simulation`** — do not fork the sim for speed.
