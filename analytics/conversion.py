"""
Conversion propensity + driver analysis.

Question answered: "which behaviors predict that a visitor *activates*?" We
define activation as reaching a goal section (default: Paper Trading — the
deepest feature) and model the probability of activating from a visitor's
engagement with the OTHER sections.

Leakage matters here: the goal section's own views trivially encode the label,
so they're excluded from the features. What's left — how broadly and how often
someone engages elsewhere — is a genuine, actionable predictor.

Two complementary views are returned:
  - a logistic-regression propensity model (held-out precision/recall/F1/AUC),
  - per-feature point-biserial correlations with the outcome (a simple,
    assumption-light "what correlates with converting?" ranking).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from django.utils import timezone

from .models import PageView
from . import ml
from . import metrics

# Friendly section labels produced by the middleware (excluding 'Other').
SECTIONS = ['Investments', 'Debt Management', 'Data & Accounts',
            'Competition', 'Paper Trading', 'Account']
DEFAULT_GOAL = 'Paper Trading'


def conversion_model(days: int = 30, goal_section: str = DEFAULT_GOAL) -> dict:
    """Model P(visitor reaches `goal_section`) from their other-section behavior.

    Features (all leakage-free — the goal section is excluded): per-section view
    counts for every non-goal section, plus active_days. Standardized, split,
    trained with balanced class weights, evaluated on a held-out set. Also
    returns point-biserial correlations (Pearson vs the 0/1 label) per feature.
    """
    since = timezone.now() - timedelta(days=days)
    rows = (PageView.objects.filter(timestamp__gte=since)
            .exclude(session_hash='', user_id__isnull=True)
            .values_list('user_id', 'session_hash', 'section', 'timestamp'))

    per_section = defaultdict(lambda: defaultdict(int))
    active_days = defaultdict(set)
    for uid, sh, section, ts in rows:
        vid = f'u{uid}' if uid else f's{sh}'
        per_section[vid][section] += 1
        active_days[vid].add(ts.date())

    visitors = list(per_section.keys())
    n = len(visitors)
    if n < 12:
        return {'available': False,
                'note': f'Need ~12+ distinct visitors to model conversion (have {n}).'}

    feature_sections = [s for s in SECTIONS if s != goal_section]
    feature_names = feature_sections + ['active_days']

    X, y = [], []
    for vid in visitors:
        secs = per_section[vid]
        X.append([float(secs.get(s, 0)) for s in feature_sections] + [float(len(active_days[vid]))])
        y.append(1 if secs.get(goal_section, 0) > 0 else 0)

    pos = sum(y)
    if pos == 0 or pos == n:
        return {'available': False,
                'note': f'Every visitor is on the same side of "{goal_section}" — nothing to model yet.'}

    # Point-biserial correlation per feature (Pearson of column vs binary label).
    correlations = []
    for j, name in enumerate(feature_names):
        col = [row[j] for row in X]
        corr = round(ml.pearson_correlation(col, [float(v) for v in y]), 3)
        # corr_abs_pct: half-width (0-50) for the template's diverging bar.
        correlations.append({'feature': name, 'corr': corr,
                             'corr_abs_pct': round(abs(corr) * 50, 1)})
    correlations.sort(key=lambda d: abs(d['corr']), reverse=True)

    # Logistic propensity model, honestly evaluated.
    Xs = ml.standardize(X)
    Xtr, Xte, ytr, yte = metrics.train_test_split(Xs, y, test_frac=0.3)
    if sum(ytr) == 0 or sum(ytr) == len(ytr):
        Xtr, ytr, Xte, yte = Xs, y, Xs, y
    model = ml.LogisticRegression().fit(Xtr, ytr, lr=0.3, epochs=600, l2=0.01,
                                        class_weight='balanced')
    test_scores = [model.predict_proba(xi) for xi in Xte]
    report = metrics.evaluate_classifier(yte, test_scores)

    importances = sorted(
        ({'feature': feature_names[j], 'weight': round(model.weights[j], 3)}
         for j in range(len(feature_names))),
        key=lambda d: abs(d['weight']), reverse=True)

    return {
        'available': True,
        'goal_section': goal_section,
        'n_visitors': n,
        'conversion_rate': round(pos / n, 3),
        'report': report.as_dict(),
        'importances': importances,
        'correlations': correlations,
    }
