"""
A/B-test statistics — frequentist and Bayesian, hand-implemented.

Comparing two conversion rates honestly means more than "B looks higher". This
module provides the standard toolkit, each function documented with the formula
and unit-tested against known values:

  - norm_cdf / norm_ppf       : standard-normal CDF (via erf) and its inverse
                                (Acklam's approximation) — the basis of p-values
                                and sample-size math.
  - two_proportion_ztest      : is the difference in conversion rates real?
  - confidence_interval_diff  : a 95% CI on (rate_B - rate_A).
  - chi_square_2x2            : independence test on the 2x2 outcome table.
  - bayesian_ab              : P(B > A) and expected lift from Beta posteriors.
  - required_sample_size      : per-arm n to detect a given effect at a target
                                significance/power (so you don't peek early).

Everything works on plain integers/floats — no scipy.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Normal distribution helpers
# ---------------------------------------------------------------------------
def norm_cdf(z: float) -> float:
    """Standard-normal CDF Φ(z) = ½(1 + erf(z/√2)). Exact via math.erf."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def norm_ppf(p: float) -> float:
    """Inverse standard-normal CDF (quantile) via Acklam's approximation.

    Maps a probability to its z-score, e.g. ppf(0.975) ≈ 1.95996. Accurate to
    ~1e-9 in the central region, which is far more than analytics needs. Used to
    turn a desired significance/power into the z multipliers for sample sizing.
    """
    if p <= 0.0:
        return -math.inf
    if p >= 1.0:
        return math.inf
    # Coefficients for Acklam's rational approximation.
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
               ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
                ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    q = p - 0.5
    r = q * q
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / \
           (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)


# ---------------------------------------------------------------------------
# Frequentist tests
# ---------------------------------------------------------------------------
@dataclass
class ZTestResult:
    rate_a: float
    rate_b: float
    diff: float
    z: float
    p_value: float
    significant: bool          # at the chosen alpha (two-sided)
    ci95: tuple                 # (low, high) on rate_b - rate_a


def two_proportion_ztest(conv_a: int, n_a: int, conv_b: int, n_b: int,
                         alpha: float = 0.05) -> ZTestResult:
    """Pooled two-proportion z-test for a difference in conversion rates.

        p_pool = (x_a + x_b) / (n_a + n_b)
        SE     = √( p_pool·(1-p_pool)·(1/n_a + 1/n_b) )
        z      = (p_b - p_a) / SE,   two-sided p = 2·(1 - Φ(|z|))
    The reported CI uses the *unpooled* SE (the right one for estimating the
    difference itself). Returns zeros safely if either arm is empty.
    """
    if n_a == 0 or n_b == 0:
        return ZTestResult(0, 0, 0, 0, 1.0, False, (0.0, 0.0))
    pa, pb = conv_a / n_a, conv_b / n_b
    p_pool = (conv_a + conv_b) / (n_a + n_b)
    se_pool = math.sqrt(p_pool * (1 - p_pool) * (1 / n_a + 1 / n_b))
    z = (pb - pa) / se_pool if se_pool > 0 else 0.0
    p_value = 2 * (1 - norm_cdf(abs(z)))
    lo, hi = confidence_interval_diff(conv_a, n_a, conv_b, n_b, alpha)
    return ZTestResult(pa, pb, pb - pa, z, p_value, p_value < alpha, (lo, hi))


def confidence_interval_diff(conv_a, n_a, conv_b, n_b, alpha=0.05) -> tuple:
    """(1-alpha) CI on (rate_b - rate_a) using the unpooled standard error."""
    if n_a == 0 or n_b == 0:
        return (0.0, 0.0)
    pa, pb = conv_a / n_a, conv_b / n_b
    se = math.sqrt(pa * (1 - pa) / n_a + pb * (1 - pb) / n_b)
    z = norm_ppf(1 - alpha / 2)
    margin = z * se
    return (pb - pa - margin, pb - pa + margin)


def chi_square_2x2(conv_a, n_a, conv_b, n_b) -> dict:
    """Pearson chi-square test of independence on the 2x2 outcome table.

    Table = [[conv_a, n_a-conv_a], [conv_b, n_b-conv_b]]. χ² = Σ (O-E)²/E with
    expected counts from the margins. For df=1, p = 2·(1 - Φ(√χ²)). Equivalent
    in spirit to the z-test; offered because it's the form many analysts expect.
    """
    a, b = conv_a, n_a - conv_a
    c, d = conv_b, n_b - conv_b
    total = a + b + c + d
    if total == 0:
        return {'chi2': 0.0, 'p_value': 1.0}
    row1, row2 = a + b, c + d
    col1, col2 = a + c, b + d
    expected = [row1 * col1, row1 * col2, row2 * col1, row2 * col2]
    observed = [a, b, c, d]
    chi2 = 0.0
    for o, e in zip(observed, expected):
        e = e / total
        if e > 0:
            chi2 += (o - e) ** 2 / e
    p_value = 2 * (1 - norm_cdf(math.sqrt(chi2))) if chi2 >= 0 else 1.0
    return {'chi2': chi2, 'p_value': p_value}


# ---------------------------------------------------------------------------
# Bayesian comparison
# ---------------------------------------------------------------------------
def bayesian_ab(conv_a, n_a, conv_b, n_b, samples: int = 20000, seed: int = 42) -> dict:
    """Bayesian A/B test with uniform Beta(1,1) priors.

    Posterior for each arm is Beta(1+conversions, 1+failures). We draw `samples`
    from each posterior and estimate P(B > A) and the expected lift E[B-A] by
    Monte Carlo (seeded → reproducible). This answers the question teams
    actually ask — "what's the probability B is better?" — without p-value
    ceremony, and degrades gracefully on small samples.
    """
    rng = random.Random(seed)
    alpha_a, beta_a = 1 + conv_a, 1 + (n_a - conv_a)
    alpha_b, beta_b = 1 + conv_b, 1 + (n_b - conv_b)
    wins = 0
    lift_sum = 0.0
    for _ in range(samples):
        sa = rng.betavariate(alpha_a, beta_a)
        sb = rng.betavariate(alpha_b, beta_b)
        if sb > sa:
            wins += 1
        lift_sum += (sb - sa)
    return {
        'prob_b_beats_a': wins / samples,
        'expected_lift': lift_sum / samples,
        'mean_a': alpha_a / (alpha_a + beta_a),
        'mean_b': alpha_b / (alpha_b + beta_b),
    }


# ---------------------------------------------------------------------------
# Experiment design
# ---------------------------------------------------------------------------
def required_sample_size(baseline_rate: float, mde: float,
                         alpha: float = 0.05, power: float = 0.8) -> int:
    """Per-arm sample size to detect an absolute effect `mde` at given α/power.

        n = (z_{1-α/2} + z_{power})² · (p₁(1-p₁) + p₂(1-p₂)) / (p₂ - p₁)²
    where p₁ = baseline, p₂ = baseline + mde. This is the classic two-proportion
    formula; computing it up front stops "peeking" and underpowered calls.
    Returns the (rounded-up) n per arm.
    """
    if mde <= 0:
        return 0
    p1 = baseline_rate
    p2 = min(max(baseline_rate + mde, 0.0), 1.0)
    z_alpha = norm_ppf(1 - alpha / 2)
    z_beta = norm_ppf(power)
    numerator = (z_alpha + z_beta) ** 2 * (p1 * (1 - p1) + p2 * (1 - p2))
    denominator = (p2 - p1) ** 2
    return math.ceil(numerator / denominator) if denominator > 0 else 0
