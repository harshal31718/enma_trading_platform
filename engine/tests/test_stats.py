"""Numerical verification for `services/stats.py` (Plan 10 Phase 3e — DSR).

This is the verification prior sessions repeatedly deferred DSR for lack of:
a pytest-checked round-trip (norm_cdf(norm_ppf(p)) == p) plus published
reference quantiles, so the inverse-CDF primitive DSR depends on is provably
correct before any statistical claim is built on top of it.
"""
import math

import pytest

from services.stats import (
    deflated_sharpe_ratio,
    expected_max_sharpe,
    norm_cdf,
    norm_pdf,
    norm_ppf,
)


# ── norm_cdf — exact via math.erf, sanity-checked against known values ─────

def test_norm_cdf_at_zero_is_half():
    assert norm_cdf(0.0) == pytest.approx(0.5, abs=1e-12)


def test_norm_cdf_known_reference_values():
    # Standard normal table values.
    assert norm_cdf(1.0) == pytest.approx(0.8413447460685429, abs=1e-12)
    assert norm_cdf(1.96) == pytest.approx(0.9750021048517795, abs=1e-9)
    assert norm_cdf(-1.0) == pytest.approx(1 - 0.8413447460685429, abs=1e-12)


def test_norm_cdf_symmetry():
    for x in (0.3, 1.5, 2.7, 4.0):
        assert norm_cdf(-x) == pytest.approx(1.0 - norm_cdf(x), abs=1e-12)


# ── norm_ppf — Acklam's approximation + Halley refinement ──────────────────

def test_norm_ppf_known_reference_quantiles():
    # Textbook two-tailed 95%/99% critical values.
    assert norm_ppf(0.975) == pytest.approx(1.959963985, abs=1e-6)
    assert norm_ppf(0.995) == pytest.approx(2.575829304, abs=1e-6)
    assert norm_ppf(0.5) == pytest.approx(0.0, abs=1e-9)


def test_norm_ppf_matches_cdf_inverse_at_known_points():
    # Phi(1) = 0.8413447460685429 -> ppf of that should be ~1.0
    assert norm_ppf(0.8413447460685429) == pytest.approx(1.0, abs=1e-6)
    assert norm_ppf(0.9772498680518208) == pytest.approx(2.0, abs=1e-6)


@pytest.mark.parametrize("p", [0.001, 0.01, 0.02425, 0.1, 0.3, 0.5, 0.7, 0.9, 0.97575, 0.99, 0.999])
def test_norm_ppf_cdf_round_trip(p):
    """The core numerical-verification property: applying cdf after ppf must
    recover the original probability to near machine precision. This is
    checked across both Acklam approximation branches (p < 0.02425, the
    central branch, and p > 0.97575) plus the branch boundary itself."""
    x = norm_ppf(p)
    assert norm_cdf(x) == pytest.approx(p, abs=1e-9)


def test_norm_ppf_rejects_out_of_range():
    with pytest.raises(ValueError):
        norm_ppf(0.0)
    with pytest.raises(ValueError):
        norm_ppf(1.0)
    with pytest.raises(ValueError):
        norm_ppf(-0.1)
    with pytest.raises(ValueError):
        norm_ppf(1.1)


def test_norm_ppf_antisymmetric():
    for p in (0.1, 0.3, 0.4999):
        assert norm_ppf(1 - p) == pytest.approx(-norm_ppf(p), abs=1e-9)


def test_norm_pdf_peak_at_zero():
    assert norm_pdf(0.0) == pytest.approx(1.0 / math.sqrt(2 * math.pi), abs=1e-12)
    assert norm_pdf(0.0) > norm_pdf(1.0) > norm_pdf(2.0)


# ── expected_max_sharpe (SR_0) ───────────────────────────────────────────────

def test_expected_max_sharpe_zero_when_pool_has_no_spread():
    assert expected_max_sharpe(0.0, 10) == 0.0


def test_expected_max_sharpe_zero_with_too_few_trials():
    assert expected_max_sharpe(1.0, 1) == 0.0
    assert expected_max_sharpe(1.0, 0) == 0.0


def test_expected_max_sharpe_grows_with_trial_count():
    """The whole point of the deflation: MORE trials -> a HIGHER bar for
    "genuine skill" (more opportunities for a lucky-noise combo to look
    good), holding the trial pool's spread fixed."""
    sr_0_few = expected_max_sharpe(1.0, 5)
    sr_0_many = expected_max_sharpe(1.0, 500)
    assert sr_0_many > sr_0_few > 0


def test_expected_max_sharpe_scales_with_pool_std():
    sr_0_a = expected_max_sharpe(0.5, 50)
    sr_0_b = expected_max_sharpe(1.0, 50)
    assert sr_0_b == pytest.approx(sr_0_a * 2.0, rel=1e-9)


# ── deflated_sharpe_ratio ─────────────────────────────────────────────────

def test_dsr_insufficient_data_returns_uninformative_half():
    result = deflated_sharpe_ratio(sr_trials=[1.0], sr_selected=1.0, n_observations=10, skew=0.0, kurtosis=3.0)
    assert result["dsr"] == 0.5
    assert result["insufficientData"] is True

    result2 = deflated_sharpe_ratio(sr_trials=[1.0, 2.0], sr_selected=2.0, n_observations=1, skew=0.0, kurtosis=3.0)
    assert result2["dsr"] == 0.5
    assert result2["insufficientData"] is True


def test_dsr_high_when_selected_sharpe_towers_over_the_pool():
    # A trial pool clustered near 0 with the selected one far above the
    # pool's expected max -> should read as high-confidence genuine skill.
    sr_trials = [0.05, -0.02, 0.03, 0.01, -0.01, 0.02, 0.0, 0.04, -0.03, 0.02] * 5
    result = deflated_sharpe_ratio(sr_trials=sr_trials, sr_selected=5.0, n_observations=200, skew=0.0, kurtosis=3.0)
    assert result["insufficientData"] is False
    assert result["dsr"] > 0.99


def test_dsr_low_when_selected_sharpe_is_merely_the_pool_max():
    # The selected value IS the pool's own maximum, drawn from a noisy
    # cluster -> after deflation this should read as low-to-mid confidence,
    # not "definitely genuine skill".
    sr_trials = [0.1, 0.15, 0.2, 0.05, 0.12, 0.18, 0.22, 0.08, 0.11, 0.19]
    sr_selected = max(sr_trials)
    result = deflated_sharpe_ratio(sr_trials=sr_trials, sr_selected=sr_selected, n_observations=30, skew=0.0, kurtosis=3.0)
    assert result["dsr"] < 0.9


def test_dsr_decreases_as_trial_count_increases_for_the_same_selected_sharpe():
    """Core deflation property, directly verified: picking the best of MORE
    trials should make the SAME apparent Sharpe look LESS convincing."""
    import random
    rng = random.Random(7)
    small_pool = [rng.gauss(0, 0.3) for _ in range(10)]
    large_pool = small_pool + [rng.gauss(0, 0.3) for _ in range(490)]

    sr_selected = 1.5
    dsr_small = deflated_sharpe_ratio(small_pool, sr_selected, n_observations=100, skew=0.0, kurtosis=3.0)
    dsr_large = deflated_sharpe_ratio(large_pool, sr_selected, n_observations=100, skew=0.0, kurtosis=3.0)
    assert dsr_large["dsr"] <= dsr_small["dsr"]


def test_dsr_returns_uninformative_on_pathological_denominator():
    # 1 - skew*SR + (kurt-1)/4*SR^2 = 1 - 5*1.5 + 0.5*1.5^2 = -5.375 < 0.
    result = deflated_sharpe_ratio(
        sr_trials=[0.1, 0.2, 0.3], sr_selected=1.5, n_observations=10, skew=5.0, kurtosis=3.0,
    )
    assert result["dsr"] == 0.5
    assert result["insufficientData"] is True


def test_dsr_output_always_in_unit_interval():
    import random
    rng = random.Random(11)
    for _ in range(50):
        pool = [rng.gauss(0, 1) for _ in range(rng.randint(2, 50))]
        selected = rng.gauss(0, 2)
        n_obs = rng.randint(2, 500)
        result = deflated_sharpe_ratio(pool, selected, n_obs, skew=rng.uniform(-1, 1), kurtosis=rng.uniform(1, 6))
        assert 0.0 <= result["dsr"] <= 1.0
