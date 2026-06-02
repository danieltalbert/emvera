"""
Pure-Python ML toolkit for the analytics platform.

WHY HAND-ROLLED (no numpy / scikit-learn): Emvera runs offline with no external
dependencies, and this is a "learn/inspect the fundamentals" layer — implementing
the algorithms directly keeps the math transparent and auditable. Everything
operates on plain Python lists/tuples of floats and is unit-tested against
closed-form or known-good answers (see tests.py / tests_ml.py).

CONTENTS
  Regression & forecasting
    - linear_regression / LinearModel      : ordinary least squares + r²
    - linear_regression_ci                 : slope/intercept standard errors
    - forecast_linear                      : project a daily series forward
    - holt_forecast                        : double-exponential (level+trend)
    - ewma                                 : exponentially weighted moving avg
    - moving_average                       : simple trailing mean
  Classification
    - LogisticRegression                   : gradient-descent binary classifier
  Clustering
    - kmeans (k-means++ init)              : Lloyd's algorithm
    - silhouette_score                     : cluster-quality metric in [-1, 1]
    - choose_k_elbow                       : inertia-vs-k for the elbow method
  Stats & scaling
    - pearson_correlation                  : linear correlation in [-1, 1]
    - standardize / minmax_normalize       : feature scaling
    - mean / stdev                         : small numeric helpers
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field


# ===========================================================================
# Small numeric helpers
# ===========================================================================
def mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def stdev(xs: list[float], population: bool = True) -> float:
    """Standard deviation. Population (÷n) by default; sample (÷n-1) optional."""
    n = len(xs)
    if n < 2:
        return 0.0
    m = mean(xs)
    ss = sum((x - m) ** 2 for x in xs)
    denom = n if population else (n - 1)
    return math.sqrt(ss / denom)


# ===========================================================================
# Linear regression  (Ordinary Least Squares)
# ===========================================================================
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

    Closed form:
        m = Σ((xᵢ-x̄)(yᵢ-ȳ)) / Σ((xᵢ-x̄)²)
        b = ȳ - m·x̄
    r² = 1 - SS_res/SS_tot is the fraction of variance the line explains.
    Degenerate inputs (n<2 or all-equal x) return a flat line at the mean.
    """
    n = len(xs)
    if n == 0:
        return LinearModel(0.0, 0.0, 0.0)
    if n != len(ys):
        raise ValueError('xs and ys must be the same length')

    mean_x = mean(xs)
    mean_y = mean(ys)
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


@dataclass
class RegressionCI:
    """Linear fit plus the standard errors of its coefficients.

    With Gaussian residuals, slope ± 1.96·se_slope is a ~95% confidence
    interval — useful for saying "the trend is *significantly* up" rather than
    just "the slope is positive".
    """
    model: LinearModel
    se_slope: float
    se_intercept: float
    n: int

    def slope_ci95(self) -> tuple[float, float]:
        return (self.model.slope - 1.96 * self.se_slope,
                self.model.slope + 1.96 * self.se_slope)

    def slope_is_significant(self) -> bool:
        """True when the 95% CI for the slope excludes zero."""
        lo, hi = self.slope_ci95()
        return lo > 0 or hi < 0


def linear_regression_ci(xs: list[float], ys: list[float]) -> RegressionCI:
    """OLS fit with standard errors derived from the residual variance.

        se_slope     = sqrt( s² / Σ(xᵢ-x̄)² )
        se_intercept = sqrt( s² · (1/n + x̄²/Σ(xᵢ-x̄)²) )
    where s² = SS_res / (n-2) is the unbiased residual variance.
    """
    n = len(xs)
    model = linear_regression(xs, ys)
    if n < 3:
        return RegressionCI(model, 0.0, 0.0, n)
    mean_x = mean(xs)
    sxx = sum((x - mean_x) ** 2 for x in xs)
    if sxx == 0:
        return RegressionCI(model, 0.0, 0.0, n)
    ss_res = sum((y - model.predict(x)) ** 2 for x, y in zip(xs, ys))
    s2 = ss_res / (n - 2)
    se_slope = math.sqrt(s2 / sxx)
    se_intercept = math.sqrt(s2 * (1.0 / n + mean_x ** 2 / sxx))
    return RegressionCI(model, se_slope, se_intercept, n)


def forecast_linear(series: list[float], horizon: int) -> list[float]:
    """Fit a trend over a daily `series` (x = day index) and project `horizon`
    days forward. Negative projections clamp to 0 (counts can't be < 0)."""
    if not series:
        return [0.0] * horizon
    xs = list(range(len(series)))
    model = linear_regression(xs, series)
    return [max(0.0, model.predict(i)) for i in range(len(series), len(series) + horizon)]


# ===========================================================================
# Exponential smoothing & forecasting
# ===========================================================================
def ewma(series: list[float], alpha: float = 0.3) -> list[float]:
    """Exponentially weighted moving average.

        s₀ = x₀ ;  sₜ = α·xₜ + (1-α)·sₜ₋₁
    Larger α reacts faster to recent values; smaller α is smoother. Unlike a
    simple moving average it weights *all* history with geometric decay.
    """
    if not series:
        return []
    alpha = min(max(alpha, 0.0), 1.0)
    out = [series[0]]
    for x in series[1:]:
        out.append(alpha * x + (1 - alpha) * out[-1])
    return out


def holt_forecast(series: list[float], horizon: int,
                  alpha: float = 0.5, beta: float = 0.3) -> list[float]:
    """Holt's linear (double-exponential) smoothing — level + trend.

        levelₜ = α·xₜ + (1-α)·(levelₜ₋₁ + trendₜ₋₁)
        trendₜ = β·(levelₜ - levelₜ₋₁) + (1-β)·trendₜ₋₁
        forecastₜ₊ₕ = levelₜ + h·trendₜ
    Captures a moving trend better than a single OLS line when the slope drifts
    over the window. Forecasts clamp at 0 (counts).
    """
    if not series:
        return [0.0] * horizon
    if len(series) == 1:
        return [max(0.0, series[0])] * horizon
    level = series[0]
    trend = series[1] - series[0]
    for x in series[1:]:
        prev_level = level
        level = alpha * x + (1 - alpha) * (level + trend)
        trend = beta * (level - prev_level) + (1 - beta) * trend
    return [max(0.0, level + (h + 1) * trend) for h in range(horizon)]


def moving_average(series: list[float], window: int = 7) -> list[float]:
    """Trailing simple moving average; short prefixes average what's available."""
    window = max(1, window)
    out = []
    for i in range(len(series)):
        chunk = series[max(0, i - window + 1):i + 1]
        out.append(sum(chunk) / len(chunk))
    return out


# ===========================================================================
# Anomaly detection
# ===========================================================================
@dataclass
class Anomaly:
    index: int
    value: float
    z: float
    direction: str  # 'spike' or 'dip'


def zscore_anomalies(series: list[float], threshold: float = 2.0) -> list[Anomaly]:
    """Flag points whose z-score exceeds `threshold`.

        z = (x - mean) / stdev
    |z| > 2 ≈ outside ~95% of a normal distribution. Returns spikes (z>0) and
    dips (z<0); empty if stdev is 0 or the series is too short.
    """
    n = len(series)
    if n < 3:
        return []
    m = mean(series)
    sd = stdev(series)
    if sd == 0:
        return []
    out = []
    for i, x in enumerate(series):
        z = (x - m) / sd
        if abs(z) >= threshold:
            out.append(Anomaly(i, x, z, 'spike' if z > 0 else 'dip'))
    return out


# ===========================================================================
# Correlation & feature scaling
# ===========================================================================
def pearson_correlation(xs: list[float], ys: list[float]) -> float:
    """Pearson r in [-1, 1]: cov(x,y) / (σx·σy). 0 if either series is constant."""
    n = len(xs)
    if n < 2 or n != len(ys):
        return 0.0
    mx, my = mean(xs), mean(ys)
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx == 0 or vy == 0:
        return 0.0
    return cov / math.sqrt(vx * vy)


def minmax_normalize(rows: list[list[float]]) -> list[list[float]]:
    """Scale each feature (column) to [0,1] so no single large-magnitude column
    dominates the Euclidean distance used by k-means."""
    if not rows:
        return []
    n_features = len(rows[0])
    mins = [min(r[j] for r in rows) for j in range(n_features)]
    maxs = [max(r[j] for r in rows) for j in range(n_features)]
    out = []
    for r in rows:
        out.append([
            (r[j] - mins[j]) / (maxs[j] - mins[j]) if maxs[j] > mins[j] else 0.0
            for j in range(n_features)
        ])
    return out


def standardize(rows: list[list[float]]) -> list[list[float]]:
    """Z-score each feature (column) to mean 0 / stdev 1 — the right scaling for
    gradient-descent classifiers like logistic regression (helps convergence)."""
    if not rows:
        return []
    n_features = len(rows[0])
    cols = [[r[j] for r in rows] for j in range(n_features)]
    means = [mean(c) for c in cols]
    sds = [stdev(c) or 1.0 for c in cols]
    return [[(r[j] - means[j]) / sds[j] for j in range(n_features)] for r in rows]


# ===========================================================================
# K-means clustering  (with k-means++ initialization)
# ===========================================================================
def _dist2(a: list[float], b: list[float]) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b))


@dataclass
class KMeansResult:
    labels: list[int]
    centroids: list[list[float]]
    inertia: float = 0.0
    sizes: list[int] = field(default_factory=list)


def _kmeans_plusplus_init(points, k, rng):
    """k-means++ seeding: spread initial centroids out so Lloyd's algorithm
    converges to a better optimum than uniformly-random seeds.

    Pick the first centroid at random, then pick each subsequent centroid with
    probability proportional to D(x)² (the squared distance to the nearest
    already-chosen centroid). This biases toward points far from existing
    centroids, avoiding the bad local optima random init often hits.
    """
    centroids = [list(rng.choice(points))]
    while len(centroids) < k:
        d2 = [min(_dist2(p, c) for c in centroids) for p in points]
        total = sum(d2)
        if total == 0:
            centroids.append(list(rng.choice(points)))
            continue
        # Weighted random choice proportional to D(x)².
        target = rng.random() * total
        acc = 0.0
        for p, d in zip(points, d2):
            acc += d
            if acc >= target:
                centroids.append(list(p))
                break
    return centroids


def kmeans(points: list[list[float]], k: int, iters: int = 100, seed: int = 42) -> KMeansResult:
    """Lloyd's algorithm with k-means++ initialization.

    Repeats until assignments stop changing (or `iters`):
      1. assign each point to the nearest centroid (squared Euclidean),
      2. recompute each centroid as the mean of its assigned points.
    `k` is clamped to the number of points. Inertia (Σ squared distance to the
    assigned centroid) is returned for elbow/quality comparisons.
    """
    n = len(points)
    if n == 0 or k < 1:
        return KMeansResult([], [], 0.0, [])
    k = min(k, n)
    rng = random.Random(seed)

    centroids = _kmeans_plusplus_init(points, k, rng)
    labels = [0] * n

    for _ in range(iters):
        changed = False
        for i, p in enumerate(points):
            best, best_d = 0, float('inf')
            for c, cen in enumerate(centroids):
                d = _dist2(p, cen)
                if d < best_d:
                    best, best_d = c, d
            if labels[i] != best:
                labels[i] = best
                changed = True
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


def silhouette_score(points: list[list[float]], labels: list[int]) -> float:
    """Mean silhouette over all points — a label-free cluster-quality metric.

    For point i:
        a(i) = mean distance to other points in its own cluster
        b(i) = min over other clusters of the mean distance to that cluster
        s(i) = (b - a) / max(a, b)        ∈ [-1, 1]
    ~1 = well-clustered, ~0 = on a boundary, <0 = probably mis-assigned.
    Returns 0 when there are fewer than two non-empty clusters.
    """
    n = len(points)
    if n < 2:
        return 0.0
    clusters: dict[int, list[int]] = {}
    for i, lbl in enumerate(labels):
        clusters.setdefault(lbl, []).append(i)
    if len(clusters) < 2:
        return 0.0

    def dist(i, j):
        return math.sqrt(_dist2(points[i], points[j]))

    total = 0.0
    for i in range(n):
        own = clusters[labels[i]]
        if len(own) > 1:
            a = sum(dist(i, j) for j in own if j != i) / (len(own) - 1)
        else:
            a = 0.0
        b = float('inf')
        for lbl, members in clusters.items():
            if lbl == labels[i]:
                continue
            mean_d = sum(dist(i, j) for j in members) / len(members)
            b = min(b, mean_d)
        denom = max(a, b)
        total += (b - a) / denom if denom > 0 else 0.0
    return total / n


def choose_k_elbow(points: list[list[float]], k_min: int = 2, k_max: int = 6) -> dict:
    """Run k-means across a range of k and report inertia + silhouette for each.

    Returns the per-k metrics plus a `suggested_k`: the k with the highest
    silhouette score (a defensible automatic choice; the elbow in the inertia
    curve is also exposed so a human can sanity-check it).
    """
    n = len(points)
    k_max = min(k_max, n)
    results = []
    for k in range(k_min, k_max + 1):
        if k < 2 or k > n:
            continue
        res = kmeans(points, k)
        sil = silhouette_score(points, res.labels)
        results.append({'k': k, 'inertia': round(res.inertia, 4), 'silhouette': round(sil, 4)})
    suggested = max(results, key=lambda r: r['silhouette'])['k'] if results else k_min
    return {'metrics': results, 'suggested_k': suggested}


# ===========================================================================
# Logistic regression  (binary classifier via gradient descent)
# ===========================================================================
def sigmoid(z: float) -> float:
    """Numerically-stable logistic function 1/(1+e^-z)."""
    if z >= 0:
        ez = math.exp(-z)
        return 1.0 / (1.0 + ez)
    ez = math.exp(z)
    return ez / (1.0 + ez)


@dataclass
class LogisticRegression:
    """Binary logistic-regression classifier trained by batch gradient descent.

    Predicts P(y=1 | x) = sigmoid(w·x + b). Trained by minimizing binary
    cross-entropy; the gradient of BCE w.r.t. each weight is the clean
    mean((pred - y)·xⱼ), which is what `fit` descends. Inputs should be
    standardized (see standardize()) so a single large-scale feature doesn't
    stall convergence. L2 regularization (`l2`) shrinks weights to curb
    overfitting on small datasets.
    """
    weights: list[float] = field(default_factory=list)
    bias: float = 0.0
    n_features: int = 0
    loss_history: list[float] = field(default_factory=list)

    def fit(self, X: list[list[float]], y: list[int], lr: float = 0.1,
            epochs: int = 500, l2: float = 0.0,
            class_weight: str | None = None) -> 'LogisticRegression':
        """Train by gradient descent on (optionally class-weighted) BCE.

        `class_weight='balanced'` weights each class inversely to its frequency
        (weight = n / (2·n_class)), the standard fix for imbalanced data: it
        stops the model from trivially predicting the majority class and ignoring
        the rare-but-important minority (e.g. churners). Without it, a 10%-churn
        dataset happily converges to "nobody churns" at 90% accuracy.
        """
        if not X:
            return self
        n, d = len(X), len(X[0])
        self.n_features = d
        self.weights = [0.0] * d
        self.bias = 0.0

        # Per-class weights (default 1.0 each unless 'balanced').
        w_pos = w_neg = 1.0
        if class_weight == 'balanced':
            n_pos = sum(y) or 1
            n_neg = (n - sum(y)) or 1
            w_pos = n / (2.0 * n_pos)
            w_neg = n / (2.0 * n_neg)

        for _ in range(epochs):
            grad_w = [0.0] * d
            grad_b = 0.0
            total_loss = 0.0
            weight_sum = 0.0
            for xi, yi in zip(X, y):
                cw = w_pos if yi == 1 else w_neg
                z = self.bias + sum(self.weights[j] * xi[j] for j in range(d))
                pred = sigmoid(z)
                err = cw * (pred - yi)            # weighted gradient
                for j in range(d):
                    grad_w[j] += err * xi[j]
                grad_b += err
                # Weighted binary cross-entropy, clamped to avoid log(0).
                p = min(max(pred, 1e-12), 1 - 1e-12)
                total_loss += -cw * (yi * math.log(p) + (1 - yi) * math.log(1 - p))
                weight_sum += cw
            for j in range(d):
                # Average gradient + L2 penalty (bias is not regularized).
                self.weights[j] -= lr * (grad_w[j] / n + l2 * self.weights[j])
            self.bias -= lr * (grad_b / n)
            self.loss_history.append(total_loss / weight_sum if weight_sum else 0.0)
        return self

    def predict_proba(self, xi: list[float]) -> float:
        z = self.bias + sum(self.weights[j] * xi[j] for j in range(len(xi)))
        return sigmoid(z)

    def predict(self, xi: list[float], threshold: float = 0.5) -> int:
        return 1 if self.predict_proba(xi) >= threshold else 0
