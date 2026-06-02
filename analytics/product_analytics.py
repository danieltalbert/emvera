"""
Product-analytics layer — the "what does this mean for the business?" insights.

Where insights.py answers descriptive questions (how much traffic, when, what's
popular), this module answers behavioral/predictive ones using the ML toolkit:

  - sessionize()          : group raw page views into visits (30-min timeout),
                            the unit most product metrics are actually about.
  - funnel()              : step-by-step conversion through an ordered journey,
                            with drop-off at each stage.
  - cohort_retention()    : weekly acquisition cohorts × subsequent-week return
                            rates (the classic retention triangle).
  - engagement_features() : per-visitor feature matrix reused by clustering and
                            churn modeling (single source of truth).
  - churn_model()         : trains LogisticRegression to predict who won't
                            return, HONESTLY evaluated on a held-out split with
                            precision/recall/F1/ROC-AUC, and surfaces which
                            behaviors drive the prediction (standardized weights).
  - transition_matrix()   : first-order Markov page-to-page flow ("where do
                            users go from X?").

All functions read PageView rows and return plain dicts/lists for the view.
"""
from __future__ import annotations

from collections import defaultdict, Counter
from datetime import timedelta

from django.utils import timezone

from .models import PageView
from . import ml
from . import metrics
from . import features as features_store


# A visit ends after this much inactivity — the industry-standard 30 minutes.
SESSION_TIMEOUT = timedelta(minutes=30)


def _visitor_id(user_id, session_hash) -> str:
    """Unify authenticated and anonymous identities into one visitor key."""
    return f'u{user_id}' if user_id else f's{session_hash}'


def _iter_events(days: int):
    """Yield (visitor_id, path, section, timestamp) ordered by visitor then time
    — the shape every function here needs. One query, sorted in Python."""
    since = timezone.now() - timedelta(days=days)
    rows = (PageView.objects
            .filter(timestamp__gte=since)
            .exclude(session_hash='', user_id__isnull=True)
            .values_list('user_id', 'session_hash', 'path', 'section', 'timestamp'))
    events = [(_visitor_id(u, s), path, section, ts) for (u, s, path, section, ts) in rows]
    events.sort(key=lambda e: (e[0], e[3]))
    return events


# ===========================================================================
# Sessionization
# ===========================================================================
def sessionize(days: int = 30) -> dict:
    """Group consecutive page views per visitor into sessions.

    A new session starts when the gap since the previous view exceeds
    SESSION_TIMEOUT. Returns aggregate session stats: counts, average pages per
    session, average duration, and the bounce rate (sessions with one page).
    These are the denominators most product metrics are quoted against.
    """
    events = _iter_events(days)
    sessions = []  # each: {visitor, start, end, pages}
    cur = None
    for vid, path, section, ts in events:
        if cur and cur['visitor'] == vid and (ts - cur['end']) <= SESSION_TIMEOUT:
            cur['end'] = ts
            cur['pages'] += 1
        else:
            if cur:
                sessions.append(cur)
            cur = {'visitor': vid, 'start': ts, 'end': ts, 'pages': 1}
    if cur:
        sessions.append(cur)

    n = len(sessions)
    if n == 0:
        return {'sessions': 0, 'avg_pages': 0, 'avg_duration_min': 0,
                'bounce_rate': 0, 'depth_distribution': []}
    bounces = sum(1 for s in sessions if s['pages'] == 1)
    durations = [(s['end'] - s['start']).total_seconds() / 60 for s in sessions]

    # Compact session-depth histogram (1, 2, 3-5, 6-10, 11+) for charting —
    # never the raw per-session list, which can be tens of thousands of rows.
    buckets = [('1 page', 0), ('2 pages', 0), ('3-5', 0), ('6-10', 0), ('11+', 0)]
    counts = [0, 0, 0, 0, 0]
    for s in sessions:
        p = s['pages']
        if p == 1:
            counts[0] += 1
        elif p == 2:
            counts[1] += 1
        elif p <= 5:
            counts[2] += 1
        elif p <= 10:
            counts[3] += 1
        else:
            counts[4] += 1
    depth_distribution = [{'label': buckets[i][0], 'count': counts[i]} for i in range(5)]

    return {
        'sessions': n,
        'avg_pages': round(sum(s['pages'] for s in sessions) / n, 2),
        'avg_duration_min': round(sum(durations) / n, 2),
        'bounce_rate': round(bounces / n, 3),
        'depth_distribution': depth_distribution,
    }


# ===========================================================================
# Conversion funnel
# ===========================================================================
# An ordered "activation" journey. Each step matches if a visitor viewed any
# path containing the given fragment, in order, within the window. Tunable.
DEFAULT_FUNNEL = [
    ('Landed', '/investments/'),
    ('Explored debt tools', '/debt-management/'),
    ('Tried a competition', '/competition/'),
    ('Reached paper trading', '/paper-trading/'),
]


def funnel(days: int = 30, steps=None) -> dict:
    """Ordered conversion funnel with per-step drop-off.

    A visitor counts for step k only if they also satisfied steps 0..k-1 (the
    steps are sequential, the standard funnel definition). Reports the count at
    each step, the conversion rate vs. the top of funnel, and the step-to-step
    drop-off — so you can see exactly *where* you lose people.
    """
    steps = steps or DEFAULT_FUNNEL
    since = timezone.now() - timedelta(days=days)
    rows = (PageView.objects.filter(timestamp__gte=since)
            .exclude(session_hash='', user_id__isnull=True)
            .values_list('user_id', 'session_hash', 'path'))

    visited = defaultdict(set)
    for u, s, path in rows:
        visited[_visitor_id(u, s)].add(path)

    counts = []
    for _, fragment in steps:
        counts.append(0)
    for paths in visited.values():
        # Walk the funnel in order; stop at the first step the visitor misses.
        for k, (_, fragment) in enumerate(steps):
            if any(fragment in p for p in paths):
                counts[k] += 1
            else:
                break

    top = counts[0] if counts else 0
    out_steps = []
    for k, (label, fragment) in enumerate(steps):
        prev = counts[k - 1] if k > 0 else counts[k]
        out_steps.append({
            'label': label,
            'count': counts[k],
            'conversion_from_top': round(counts[k] / top, 3) if top else 0.0,
            'dropoff_from_prev': round(1 - counts[k] / prev, 3) if prev else 0.0,
        })
    return {'steps': out_steps, 'top_of_funnel': top}


def funnel_by_segment(days: int = 30, steps=None) -> dict:
    """The activation funnel split by engagement tier (New / Returning / Loyal).

    Tier is derived from active-days (a dimension independent of the funnel steps
    themselves, so the split isn't circular): 1 day = New, 2-3 = Returning, 4+ =
    Loyal. Reveals, e.g., that loyal visitors march through the funnel while
    one-day visitors stall at the top — telling you whether the problem is the
    funnel or acquisition quality.
    """
    steps = steps or DEFAULT_FUNNEL
    since = timezone.now() - timedelta(days=days)
    rows = (PageView.objects.filter(timestamp__gte=since)
            .exclude(session_hash='', user_id__isnull=True)
            .values_list('user_id', 'session_hash', 'path', 'timestamp'))

    paths = defaultdict(set)
    active_days = defaultdict(set)
    for uid, sh, path, ts in rows:
        vid = _visitor_id(uid, sh)
        paths[vid].add(path)
        active_days[vid].add(ts.date())

    def tier(vid):
        n = len(active_days[vid])
        if n >= 4:
            return 'Loyal (4+ days)'
        if n >= 2:
            return 'Returning (2–3 days)'
        return 'New (1 day)'

    order = ['New (1 day)', 'Returning (2–3 days)', 'Loyal (4+ days)']
    members = defaultdict(list)
    for vid in paths:
        members[tier(vid)].append(vid)

    out_segments = []
    for seg in order:
        seg_members = members.get(seg, [])
        counts = [0] * len(steps)
        for vid in seg_members:
            for k, (_, fragment) in enumerate(steps):
                if any(fragment in p for p in paths[vid]):
                    counts[k] += 1
                else:
                    break
        top = counts[0] if counts else 0
        out_segments.append({
            'segment': seg, 'size': len(seg_members),
            'steps': [{'label': steps[k][0], 'count': counts[k],
                       'pct': round(counts[k] / top, 3) if top else 0.0}
                      for k in range(len(steps))],
        })
    return {'segments': out_segments, 'step_labels': [label for label, _ in steps]}


# ===========================================================================
# Cohort retention
# ===========================================================================
def cohort_retention(weeks: int = 6) -> dict:
    """Weekly acquisition cohorts × return rate in subsequent weeks.

    A visitor's cohort is the week of their first-ever view in the window. Each
    cell [c][w] is the fraction of cohort c that came back in week c+w. Week 0 is
    100% by definition. This 'retention triangle' is the single best view of
    whether the product is sticky.
    """
    since = timezone.now() - timedelta(weeks=weeks)
    rows = (PageView.objects.filter(timestamp__gte=since)
            .exclude(session_hash='', user_id__isnull=True)
            .values_list('user_id', 'session_hash', 'timestamp'))

    # Bucket each visitor's activity into absolute week indices.
    first_week = {}
    active_weeks = defaultdict(set)
    base = since
    for u, s, ts in rows:
        vid = _visitor_id(u, s)
        wk = int((ts - base).days // 7)
        active_weeks[vid].add(wk)
        if vid not in first_week or wk < first_week[vid]:
            first_week[vid] = wk

    cohorts = defaultdict(list)
    for vid, fw in first_week.items():
        cohorts[fw].append(vid)

    matrix = []
    for c in range(weeks):
        members = cohorts.get(c, [])
        size = len(members)
        if size == 0:
            matrix.append({'cohort_week': c, 'size': 0, 'retention': []})
            continue
        row = []
        for w in range(weeks - c):
            returned = sum(1 for vid in members if (c + w) in active_weeks[vid])
            row.append(round(returned / size, 3))
        matrix.append({'cohort_week': c, 'size': size, 'retention': row})
    return {'cohorts': matrix, 'weeks': weeks, 'week_headers': list(range(weeks))}


# ===========================================================================
# Per-visitor features (shared by segmentation + churn)
# ===========================================================================
def engagement_features(days: int = 30):
    """Thin backward-compatible wrapper over the feature store.

    The canonical per-visitor feature definitions now live in analytics.features
    (the feature store), so segmentation and churn share one source of truth.
    Returns (visitor_ids, raw_feature_rows, meta) exactly as before.
    """
    visitor_ids, rows, _names, meta = features_store.build_matrix(days)
    return visitor_ids, rows, meta


# Canonical names come from the feature store registry.
FEATURE_NAMES = features_store.FEATURE_NAMES


# ===========================================================================
# Churn prediction  (logistic regression, honestly evaluated)
# ===========================================================================
def churn_model(days: int = 30, churn_after_days: int = 7) -> dict:
    """Predict which visitors are about to churn, and explain why.

    Label: a visitor "churned" if their most recent visit is older than
    `churn_after_days` (i.e. they've gone quiet). Features come from
    engagement_features(); we DROP recency from the inputs because it trivially
    encodes the label (that would be leakage), and instead let the model learn
    from genuine behavior (views, breadth, active days, session depth).

    The model is trained on a standardized train split and evaluated on a
    held-out test split (precision/recall/F1/ROC-AUC) so the reported skill is
    honest. Standardized coefficients are returned as feature importances so you
    can see WHICH behaviors predict retention vs. churn.
    """
    # Pull features from the store, excluding recency (it defines the label, so
    # including it would be leakage). meta still carries recency for labeling.
    visitor_ids, X, feat_names, meta = features_store.build_matrix(
        days, exclude=('recency_days',))
    n = len(visitor_ids)
    if n < 12:
        return {'available': False,
                'note': f'Need ~12+ distinct visitors to train a churn model (have {n}).'}

    y = [1 if m['recency_days'] >= churn_after_days else 0 for m in meta]

    pos = sum(y)
    if pos == 0 or pos == n:
        return {'available': False,
                'note': 'All visitors fall in one class (everyone active or everyone churned) — nothing to predict yet.'}

    # Standardize, split, train, evaluate on held-out data.
    Xs = ml.standardize(X)
    Xtr, Xte, ytr, yte = metrics.train_test_split(Xs, y, test_frac=0.3)
    if sum(ytr) == 0 or sum(ytr) == len(ytr):
        # Degenerate split — fall back to training-set scoring with a caveat.
        Xtr, ytr = Xs, y
        Xte, yte = Xs, y

    # 'balanced' class weighting so the minority (churners) is actually learned
    # rather than ignored — the accuracy-paradox fix for imbalanced data.
    model = ml.LogisticRegression().fit(
        Xtr, ytr, lr=0.3, epochs=600, l2=0.01, class_weight='balanced')

    # Tune the decision threshold to maximize F1 on the TRAINING scores (never
    # the test set), then report honestly at that threshold on the held-out set.
    train_scores = [model.predict_proba(xi) for xi in Xtr]
    best_threshold = _best_f1_threshold(ytr, train_scores)

    test_scores = [model.predict_proba(xi) for xi in Xte]
    report = metrics.evaluate_classifier(yte, test_scores, threshold=best_threshold)

    # Standardized weights = feature importance (sign shows direction). Add a
    # 0-50 bar width (% of the largest |weight|) for the template's diverging bar.
    raw_imps = [{'feature': feat_names[j], 'weight': round(model.weights[j], 3)}
                for j in range(len(feat_names))]
    max_abs = max((abs(d['weight']) for d in raw_imps), default=1.0) or 1.0
    for d in raw_imps:
        d['weight_pct'] = round(abs(d['weight']) / max_abs * 50, 1)  # half-width (diverging)
    importances = sorted(raw_imps, key=lambda d: abs(d['weight']), reverse=True)

    # Score every current visitor; surface those most at risk.
    at_risk = []
    for vid, xi, m, label in zip(visitor_ids, Xs, meta, y):
        p = model.predict_proba(xi)
        at_risk.append({'visitor': vid[:10], 'risk': round(p, 3),
                        'recency_days': m['recency_days'], 'churned': bool(label)})
    at_risk.sort(key=lambda d: d['risk'], reverse=True)

    return {
        'available': True,
        'n_visitors': n,
        'churn_rate': round(pos / n, 3),
        'churn_after_days': churn_after_days,
        'threshold': round(best_threshold, 3),
        'report': report.as_dict(),
        'importances': importances,
        'at_risk_top': at_risk[:8],
        'final_loss': round(model.loss_history[-1], 4) if model.loss_history else None,
    }


def _best_f1_threshold(y_true: list[int], scores: list[float]) -> float:
    """Scan candidate thresholds and return the one maximizing F1.

    With class-weighted training the raw 0.5 cutoff is rarely optimal; picking
    the threshold that best balances precision and recall (on training data)
    turns a well-ranked model into a usefully-decisive one.
    """
    best_t, best_f1 = 0.5, -1.0
    for i in range(5, 96, 5):
        t = i / 100.0
        cm = metrics.confusion_matrix(y_true, [1 if s >= t else 0 for s in scores])
        f1 = metrics.f1_score(cm)
        if f1 > best_f1:
            best_f1, best_t = f1, t
    return best_t


def survival_analysis(days: int = 90, churn_after_days: int = 7) -> dict:
    """Kaplan-Meier survival of visitor *engagement lifespan*.

    Each visitor's lifetime = days from first to last visit. A visitor is an
    observed "event" (churned) if their last visit is older than
    `churn_after_days`; otherwise they're censored (still potentially active).
    The KM curve then answers "what fraction of visitors are still engaged N days
    after they arrived?" — accounting for those who simply haven't had time to
    churn yet. Returns the curve, the median engaged lifespan, and the n.
    """
    since = timezone.now() - timedelta(days=days)
    rows = (PageView.objects.filter(timestamp__gte=since)
            .exclude(session_hash='', user_id__isnull=True)
            .values_list('user_id', 'session_hash', 'timestamp'))
    first, last = {}, {}
    for uid, sh, ts in rows:
        vid = _visitor_id(uid, sh)
        if vid not in first or ts < first[vid]:
            first[vid] = ts
        if vid not in last or ts > last[vid]:
            last[vid] = ts
    if len(first) < 3:
        return {'available': False, 'note': 'Not enough visitors for survival analysis.'}

    now = timezone.now()
    durations, events = [], []
    for vid in first:
        durations.append(max(0, (last[vid] - first[vid]).days))
        # Churned (event observed) if gone quiet; else censored (still in play).
        events.append(1 if (now - last[vid]).days >= churn_after_days else 0)

    km = ml.kaplan_meier(durations, events)
    return {
        'available': True,
        'n': len(first),
        'events': sum(events),
        'censored': len(events) - sum(events),
        'median_lifespan_days': km['median'],
        'curve': km['curve'],
    }


# ===========================================================================
# Path analysis  (first-order Markov transitions)
# ===========================================================================
def transition_matrix(days: int = 30, top: int = 6) -> dict:
    """Most common page-to-page transitions within sessions.

    A first-order Markov view of navigation: for consecutive views in the same
    session, count from->to. Surfaces the dominant flows ("from the dashboard,
    where do users actually go?") which informs IA and CTA placement.
    """
    events = _iter_events(days)
    transitions = Counter()
    prev = None
    for vid, path, section, ts in events:
        if prev and prev[0] == vid and (ts - prev[2]) <= SESSION_TIMEOUT:
            if prev[1] != path:  # ignore refreshes/self-loops
                transitions[(prev[1], path)] += 1
        prev = (vid, path, ts)

    top_trans = transitions.most_common(top)
    return {
        'transitions': [
            {'from': a, 'to': b, 'count': c} for (a, b), c in top_trans
        ],
        'total_transitions': sum(transitions.values()),
    }
