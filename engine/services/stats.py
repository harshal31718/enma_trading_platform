"""Standard-normal primitives + Deflated Sharpe Ratio (Plan 10 §2.2 "honesty
layer", Phase 3e).

Deferred across four prior Plan 10 sessions specifically because implementing
the Deflated Sharpe Ratio needs a numerically-verified normal-CDF/inverse-CDF
pair, and no prior session had pytest access to verify one. This session has
real Docker access, so it ships now — verified two ways in
``tests/test_stats.py``: round-trip (``norm_cdf(norm_ppf(p)) == p`` to
~1e-12) and against published reference quantiles (e.g. Φ⁻¹(0.975) ≈
1.959963985).

``norm_cdf`` is exact (``math.erf`` is a full-precision stdlib primitive, no
approximation). ``norm_ppf`` (the inverse) has no closed form — this uses
Peter Acklam's rational approximation (~1.15e-9 relative error) plus one step
of Halley's method refinement (pushes it to ~1e-12, using the exact CDF
above as the error signal). No scipy dependency — this is exactly the
scipy.stats.norm.cdf/.ppf pair, hand-rolled to stdlib only, since scipy isn't
in engine/requirements.txt.
"""
import math


def norm_cdf(x: float) -> float:
    """Standard normal CDF Φ(x). Exact (via math.erf)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def norm_pdf(x: float) -> float:
    """Standard normal PDF φ(x)."""
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


# Peter Acklam's published rational-approximation coefficients for the
# inverse standard normal CDF. See module docstring for verification method.
_ACKLAM_A = (
    -3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
    1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00,
)
_ACKLAM_B = (
    -5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
    6.680131188771972e+01, -1.328068155288572e+01,
)
_ACKLAM_C = (
    -7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
    -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00,
)
_ACKLAM_D = (
    7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
    3.754408661907416e+00,
)
_ACKLAM_P_LOW = 0.02425


def norm_ppf(p: float) -> float:
    """Inverse standard normal CDF (quantile function / probit), Φ⁻¹(p).

    Acklam's rational approximation + one Halley refinement step. See module
    docstring for the numerical-verification approach.
    """
    if not (0.0 < p < 1.0):
        raise ValueError(f"norm_ppf requires 0 < p < 1, got {p}")

    a, b, c, d = _ACKLAM_A, _ACKLAM_B, _ACKLAM_C, _ACKLAM_D
    p_low = _ACKLAM_P_LOW
    p_high = 1.0 - p_low

    if p < p_low:
        q = math.sqrt(-2.0 * math.log(p))
        x = (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
            ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1.0)
    elif p <= p_high:
        q = p - 0.5
        r = q * q
        x = (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / \
            (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1.0)
    else:
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        x = -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
             ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1.0)

    # Halley's method refinement step using the EXACT cdf above as the error
    # signal — takes Acklam's ~1.15e-9 relative error down to ~1e-12.
    e = norm_cdf(x) - p
    u = e * math.sqrt(2.0 * math.pi) * math.exp(x * x / 2.0)
    x = x - u / (1.0 + x * u / 2.0)
    return x


def expected_max_sharpe(sharpe_pool_std: float, n_trials: int) -> float:
    """SR_0 — the expected maximum Sharpe ratio across ``n_trials``
    independent trials under the null of zero true skill (Bailey & López de
    Prado 2014, extreme-value-theory approximation):

        SR_0 = std(SR_pool) * [ (1-γ)*Φ⁻¹(1 - 1/N) + γ*Φ⁻¹(1 - 1/(N·e)) ]

    where γ is the Euler-Mascheroni constant and ``sharpe_pool_std`` is the
    empirical std-dev of the Sharpe-like statistic across the N trials
    actually run (the selection pool this fold's `best` was picked from).
    """
    if n_trials < 2 or sharpe_pool_std <= 0:
        return 0.0
    euler_mascheroni = 0.5772156649015329
    n = float(n_trials)
    term1 = (1.0 - euler_mascheroni) * norm_ppf(1.0 - 1.0 / n)
    term2 = euler_mascheroni * norm_ppf(1.0 - 1.0 / (n * math.e))
    return sharpe_pool_std * (term1 + term2)


def deflated_sharpe_ratio(
    sr_trials: list[float],
    sr_selected: float,
    n_observations: int,
    skew: float,
    kurtosis: float,
) -> dict:
    """Deflated Sharpe Ratio (Bailey & López de Prado 2014) — corrects a
    selected-best-of-N Sharpe-like statistic for selection bias (picking the
    best of many trials inflates the apparent Sharpe even under zero true
    skill) and for non-normal returns (skew/kurtosis).

        DSR = Φ( (SR_hat - SR_0) * sqrt(T-1) / sqrt(1 - γ3·SR_hat + (γ4-1)/4·SR_hat²) )

    Returns a probability in [0, 1] — the probability the selected
    strategy's TRUE Sharpe ratio exceeds zero, after deflating for having
    picked the best of ``len(sr_trials)`` trials. Low DSR (e.g. < 0.95) means
    "this apparent edge is plausibly just the best of many noisy trials."

    ``skew``/``kurtosis`` here must be the RAW (non-excess) kurtosis (3.0 for
    a normal distribution, not 0.0) — matches this module's own
    `metrics.KurtosisStat` convention, documented there.

    Returns 0.5 (uninformative — "coin flip") when there isn't enough data
    (fewer than 2 trials, or fewer than 2 observations) to say anything,
    rather than raising or silently returning a misleadingly confident 0/1.
    """
    n_trials = len(sr_trials)
    if n_trials < 2 or n_observations < 2:
        return {"dsr": 0.5, "expectedMaxSharpe": None, "nTrials": n_trials, "insufficientData": True}

    pool_std = _std(sr_trials)
    sr_0 = expected_max_sharpe(pool_std, n_trials)

    denom_inner = 1.0 - skew * sr_selected + ((kurtosis - 1.0) / 4.0) * (sr_selected ** 2)
    if denom_inner <= 0:
        # Non-normality term went pathological (extreme skew/kurtosis on a
        # tiny sample) — cannot compute a meaningful denominator; report
        # uninformative rather than a divide-by-near-zero blowup.
        return {"dsr": 0.5, "expectedMaxSharpe": sr_0, "nTrials": n_trials, "insufficientData": True}

    z = (sr_selected - sr_0) * math.sqrt(n_observations - 1) / math.sqrt(denom_inner)
    return {
        "dsr": norm_cdf(z),
        "expectedMaxSharpe": sr_0,
        "nTrials": n_trials,
        "insufficientData": False,
    }


def _std(values: list[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / n
    return math.sqrt(var)
