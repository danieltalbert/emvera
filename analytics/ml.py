"""
Pure-Python ML toolkit for the analytics dashboard.

WHY HAND-ROLLED (no numpy / scikit-learn): Emvera is built to run offline with
no external dependencies, and these are the *fundamentals* — implementing them
directly keeps the math transparent and auditable, which is the point of a
"learn the basics" analytics layer. Each function is small, documented with the
formula it implements, and independently unit-tested (see tests.py).

Contents:
- linear_regression / predict_linear : ordinary least squares (trend line).
- forecast_linear                    : project a daily series forward N days.
- zscore_anomalies                   : flag points far from the mean (spikes/dips).
- moving_average                     : smoothing for noisy daily counts.
- kmeans / assign_clusters           : k-means clustering for user segmentation.
- minmax_normalize                   : feature scaling so clustering is fair.

All functions operate on plain Python lists/tuples of floats.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Linear regression  (Ordinary Least Squares)
# ---------------------------------------------------------------------------
@dataclass
class LinearModel:
    """y = slope * x + intercept, with the coefficient of determination r²."""
    slope: float
    intercept: float
    r_squared: float

    def predict(self, x: float) -> float:
        return self.slope * x + self.intercept


def linear_regression(xs: list[float], ys: list[float]) -> LinearModel:
    """Fit y = mx + b by ordinary least squares.

    Closed-form solution:
        m = Σ((xᵢ-x̄)(yᵢ-ȳ)) / Σ((xᵢ-x̄)²)
        b = ȳ - m·x̄
    r² = 1 - SS_res/SS_tot measures how much variance the line explains.
    Degenerate inputs (n<2 or all-equal x) return a flat line at the mean.
    """
    n = len(xs)
    if n == 0:
        return LinearModel(0.0, 0.0, 0.0)
    if n != len(ys):
        raise ValueError('xs and ys must be the same length')

    mean_x = sum(xs) / n
    mean_y = sum(ys) / n

    var_x = sum((x - mean_x) ** 2 for x in xs)
    if n < 2 or var_x == 0:
        return LinearModel(0.0, mean_y, 0.0)

    cov_xy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    slope = cov_xy / var_x
    intercept = mean_y - slope * mean_x

    ss_tot = sum((y - mean_y) ** 2 for y in ys)
    ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(xs, ys))
    r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0

    return LinearModel(slope, intercept, r_squared)


def forecast_linear(series: list[float], horizon: int) -> list[float]:
    """Fit a trend over a daily `series` (x = day index) and project `horizon`
    days forward. Negative projections are clamped to 0 (counts can't be < 0)."""
    if not series:
        return [0.0] * horizon
    xs = list(range(len(series)))
    model = linear_regression(xs, series)
    out = []
    for i in range(len(series), len(series) + horizon):
        out.append(max(0.0, model.predict(i)))
    return out


# ---------------------------------------------------------------------------
# Smoothing & anomaly detection
# ---------------------------------------------------------------------------
def moving_average(series: list[float], window: int = 7) -> list[float]:
    """Trailing simple moving average; short prefixes average what's available."""
    if window < 1:
        window = 1
    out = []
    for i in range(len(series)):
        lo = max(0, i - window + 1)
        chunk = series[lo:i + 1]
        out.append(sum(chunk) / len(chunk))
    return out


@dataclass
class Anomaly:
    index: int
    value: float
    z: float
    direction: str  # 'spike' or 'dip'


def zscore_anomalies(series: list[float], threshold: float = 2.0) -> list[Anomaly]:
    """Flag points whose z-score exceeds `threshold`.

        z = (x - mean) / stdev
    A common, defensible rule of thumb: |z| > 2 ≈ outside ~95% of a normal
    distribution. Returns spikes (z>0) and dips (z<0). Empty if stdev is 0.
    """
    n = len(series)
    if n < 3:
        return []
    mean = sum(series) / n
    var = sum((x - mean) ** 2 for x in series) / n
    stdev = math.sqrt(var)
    if stdev == 0:
        return []
    out = []
    for i, x in enumerate(series):
        z = (x - mean) / stdev
        if abs(z) >= threshold:
            out.append(Anomaly(i, x, z, 'spike' if z > 0 else 'dip'))
    return out


# ---------------------------------------------------------------------------
# Feature scaling + k-means clustering
# ---------------------------------------------------------------------------
def minmax_normalize(rows: list[list[float]]) -> list[list[float]]:
    """Scale each feature (column) to [0,1] so no single large-magnitude feature
    dominates the Euclidean distance used by k-means."""
    if not rows:
        return []
    n_features = len(rows[0])
    mins = [min(r[j] for r in rows) for j in range(n_features)]
    maxs = [max(r[j] for r in rows) for j in range(n_features)]
    out = []
    for r in rows:
        scaled = []
        for j in range(n_features):
            span = maxs[j] - mins[j]
            scaled.append((r[j] - mins[j]) / span if span > 0 else 0.0)
        out.append(scaled)
    return out


def _dist2(a: list[float], b: list[float]) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b))


@dataclass
class KMeansResult:
    labels: list[int]
    centroids: list[list[float]]
    inertia: float = 0.0
    sizes: list[int] = field(default_factory=list)


def kmeans(points: list[list[float]], k: int, iters: int = 50, seed: int = 42) -> KMeansResult:
    """Lloyd's algorithm for k-means clustering.

    Steps, repeated `iters` times (or until assignments stop changing):
      1. assign each point to the nearest centroid (squared Euclidean),
      2. recompute each centroid as the mean of its assigned points.
    A fixed `seed` makes results reproducible. `k` is clamped to the number of
    distinct points so we never ask for more clusters than data supports.
    Inertia (sum of squared distances to assigned centroid) is returned so
    callers can compare cluster tightness.
    """
    n = len(points)
    if n == 0 or k < 1:
        return KMeansResult([], [], 0.0, [])
    k = min(k, n)
    rng = random.Random(seed)

    # k-means++ style spread would be nicer, but for small dashboards a seeded
    # sample of distinct points is reproducible and good enough.
    centroids = [list(p) for p in rng.sample(points, k)]
    labels = [0] * n

    for _ in range(iters):
        changed = False
        # 1. Assign.
        for i, p in enumerate(points):
            best, best_d = 0, float('inf')
            for c, cen in enumerate(centroids):
                d = _dist2(p, cen)
                if d < best_d:
                    best, best_d = c, d
            if labels[i] != best:
                labels[i] = best
                changed = True
        # 2. Update.
        dims = len(points[0])
        sums = [[0.0] * dims for _ in range(k)]
        counts = [0] * k
        for i, p in enumerate(points):
            counts[labels[i]] += 1
            for j in range(dims):
                sums[labels[i]][j] += p[j]
        for c in range(k):
            if counts[c]:
                centroids[c] = [s / counts[c] for s in sums[c]]
        if not changed:
            break

    inertia = sum(_dist2(points[i], centroids[labels[i]]) for i in range(n))
    sizes = [labels.count(c) for c in range(k)]
    return KMeansResult(labels, centroids, inertia, sizes)
