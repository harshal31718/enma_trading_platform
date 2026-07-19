"""`_build_param_grid`/`_decode_combo_index` tests.

Regression coverage for a real bug found via live UI testing (Plan 10 Phase
3e session): `_build_param_grid` used to materialize the FULL cartesian
product via `list(itertools.product(*value_lists))` before applying the
`max_combinations` cap. A strategy with several wide-range params (e.g.
AdaptiveTrend's default Optimizer-wizard grid) has a total combo count in
the hundreds of trillions — building that list hung/OOM'd the entire engine
container (reproduced live: checking ~8 AdaptiveTrend params with default
ranges and clicking "Run" in the real `/lab` Optimizer wizard froze the
container, confirmed via `docker stats` showing near-zero CPU — stuck
allocating, not computing). No prior test existed for this function at all.
"""
import itertools

import pytest

from services.optimizer import _build_param_grid, _decode_combo_index


# ── _decode_combo_index — must match itertools.product's own ordering ──────

def test_decode_combo_index_matches_itertools_product_ordering():
    value_lists = [[1, 2, 3], ["a", "b"], [10, 20, 30, 40]]
    materialized = list(itertools.product(*value_lists))
    for i, expected in enumerate(materialized):
        assert _decode_combo_index(i, value_lists) == expected


def test_decode_combo_index_single_list():
    value_lists = [[7, 8, 9]]
    materialized = list(itertools.product(*value_lists))
    for i, expected in enumerate(materialized):
        assert _decode_combo_index(i, value_lists) == expected


def test_decode_combo_index_many_lists():
    value_lists = [[0, 1], [0, 1], [0, 1], [0, 1], [0, 1]]  # 32 combos
    materialized = list(itertools.product(*value_lists))
    for i, expected in enumerate(materialized):
        assert _decode_combo_index(i, value_lists) == expected


# ── _build_param_grid — small grids (no sampling needed) ───────────────────

def test_build_param_grid_full_grid_when_under_cap():
    param_grid = {"fast": {"min": 1, "max": 3, "step": 1, "type": "int"}}
    combos = _build_param_grid(param_grid, max_combinations=0)
    assert len(combos) == 3
    assert {c["fast"] for c in combos} == {1, 2, 3}


def test_build_param_grid_matches_old_materialize_then_slice_semantics_for_small_grid():
    """For a grid small enough to safely materialize both ways, the new
    sample-and-decode path must select the SAME combos (by value, not just
    count) as the old "materialize everything, then index into it" approach
    did — this is the actual regression risk of a mixed-radix decode bug."""
    param_grid = {
        "a": {"min": 1, "max": 5, "step": 1, "type": "int"},
        "b": {"min": 10, "max": 12, "step": 1, "type": "int"},
    }
    # Reconstruct what the OLD implementation would have produced.
    expanded_a = [1, 2, 3, 4, 5]
    expanded_b = [10, 11, 12]
    old_all_combos = list(itertools.product(expanded_a, expanded_b))  # 15 total

    import random
    seed = 42
    rng = random.Random(seed)
    old_indices = sorted(rng.sample(range(len(old_all_combos)), 5))
    old_selected = [old_all_combos[i] for i in old_indices]

    new_combos = _build_param_grid(param_grid, max_combinations=5, seed=seed)
    new_selected = [(c["a"], c["b"]) for c in new_combos]

    assert new_selected == old_selected


def test_build_param_grid_deterministic_with_fixed_seed():
    param_grid = {"fast": {"min": 1, "max": 50, "step": 1, "type": "int"}}
    a = _build_param_grid(param_grid, max_combinations=5, seed=7)
    b = _build_param_grid(param_grid, max_combinations=5, seed=7)
    assert a == b


def test_build_param_grid_respects_max_combinations_count():
    param_grid = {"fast": {"min": 1, "max": 100, "step": 1, "type": "int"}}
    combos = _build_param_grid(param_grid, max_combinations=10)
    assert len(combos) == 10


def test_build_param_grid_no_duplicate_combos_when_sampling():
    param_grid = {
        "a": {"min": 1, "max": 20, "step": 1, "type": "int"},
        "b": {"min": 1, "max": 20, "step": 1, "type": "int"},
    }
    combos = _build_param_grid(param_grid, max_combinations=50, seed=3)
    seen = {(c["a"], c["b"]) for c in combos}
    assert len(seen) == len(combos)


# ── _build_param_grid — the actual regression: astronomically large grids ──

def test_build_param_grid_handles_astronomically_large_grid_without_hanging():
    """The real bug: a grid this size used to attempt materializing hundreds
    of trillions of tuples via `list(itertools.product(...))`. This must
    return quickly (test itself has no explicit timeout, but pytest's
    default run will hang/OOM the whole suite if this regresses — that IS
    the point: this test existing at all is the regression guard)."""
    param_grid = {
        "trend_period":   {"min": 50, "max": 400, "step": 1, "type": "int"},   # 351 values
        "slope_lookback": {"min": 1,  "max": 50,  "step": 1, "type": "int"},   # 50 values
        "fast_period":    {"min": 5,  "max": 100, "step": 1, "type": "int"},   # 96 values
        "slow_period":    {"min": 10, "max": 200, "step": 1, "type": "int"},   # 191 values
        "atr_period":     {"min": 5,  "max": 50,  "step": 1, "type": "int"},   # 46 values
    }
    # 351 * 50 * 96 * 191 * 46 ≈ 1.48e11 combos — the exact class of size
    # that used to freeze the engine.
    combos = _build_param_grid(param_grid, max_combinations=6, seed=1)
    assert len(combos) == 6
    for c in combos:
        assert 50 <= c["trend_period"] <= 400
        assert 1 <= c["slope_lookback"] <= 50


def test_build_param_grid_max_combinations_zero_with_large_grid_is_caller_responsibility():
    """`max_combinations=0` means 'run the whole grid' — unchanged behavior,
    still the caller's job to bound grid size in that mode (documented in
    `_build_param_grid`'s own docstring). Verified here only for a grid
    small enough that materializing it is actually safe."""
    param_grid = {"fast": {"min": 1, "max": 20, "step": 1, "type": "int"}}
    combos = _build_param_grid(param_grid, max_combinations=0)
    assert len(combos) == 20
