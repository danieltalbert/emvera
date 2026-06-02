"""
Insights layer: turn raw PageView rows into dashboard-ready structures, applying
the pure-Python ML toolkit (analytics/ml.py).

Each function returns plain dicts/lists (JSON-friendly) so the view stays thin
and the template / Chart.js can consume them directly. The ML touch-points:
- daily_traffic + forecast      -> linear_regression / forecast_linear
- daily traffic anomalies       -> zscore_anomalies
- user_segments                 -> kmeans over per-visitor behavioral features
"""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from django.db.models import Avg, Count, Q
from django.utils import timezone

from .models import PageView
from . import ml
from . import features


WEEKDAY_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']


def kpis(days: int = 30) -> dict:
    """Headline numbers for the top of the dashboard."""
    since = timezone.now() - timedelta(days=days)
    qs = PageView.objects.filter(timestamp__gte=since)
    total = qs.count()
    distinct_users = qs.filter(is_authenticated=True).values('user').distinct().count()
    distinct_anon = (qs.filter(is_authenticated=False)
                       .exclude(session_hash='')
                       .values('session_hash').distinct().count())
    avg_ms = qs.aggregate(a=Avg('response_ms'))['a'] or 0
    return {
        'total_views': total,
        'distinct_visitors': distinct_users + distinct_anon,
        'signed_in_visitors': distinct_users,
        'avg_response_ms': round(avg_ms, 1),
        'days': days,
    }


def daily_traffic(days: int = 30) -> dict:
    """Per-day view counts + a 7-day forecast + flagged anomalies.

    This is the ML centerpiece: we fit a least-squares trend line to the daily
    counts (giving direction + r²), project the next 7 days, and z-score the
    history to surface unusual spikes/dips.
    """
    since = (timezone.now() - timedelta(days=days - 1)).date()
    rows = (PageView.objects
            .filter(timestamp__date__gte=since)
            .values('timestamp__date')
            .annotate(c=Count('id')))
    by_date = {r['timestamp__date']: r['c'] for r in rows}

    labels, counts = [], []
    for i in range(days):
        d = since + timedelta(days=i)
        labels.append(d.strftime('%b %d'))
        counts.append(float(by_date.get(d, 0)))

    model = ml.linear_regression(list(range(len(counts))), counts)
    horizon = 7
    forecast = ml.forecast_linear(counts, horizon)
    last = since + timedelta(days=days - 1)
    forecast_labels = [(last + timedelta(days=i + 1)).strftime('%b %d') for i in range(horizon)]

    anomalies = ml.zscore_anomalies(counts, threshold=2.0)
    trend_dir = 'flat'
    if model.slope > 0.05:
        trend_dir = 'up'
    elif model.slope < -0.05:
        trend_dir = 'down'

    return {
        'labels': labels,
        'counts': counts,
        'trend': [round(model.predict(i), 2) for i in range(len(counts))],
        'forecast_labels': forecast_labels,
        'forecast': [round(v, 1) for v in forecast],
        'trend_direction': trend_dir,
        'trend_per_day': round(model.slope, 2),
        'r_squared': round(model.r_squared, 3),
        'anomalies': [
            {'label': labels[a.index], 'value': a.value, 'z': round(a.z, 2), 'direction': a.direction}
            for a in anomalies
        ],
    }


def top_pages(days: int = 30, limit: int = 8) -> list[dict]:
    """Most-viewed paths, with their section and average time-on-page.

    avg_dwell_s is computed only over views that received a client beacon
    (dwell_ms > 0), so it reflects real reading time, not page-view count.
    """
    since = timezone.now() - timedelta(days=days)
    rows = (PageView.objects.filter(timestamp__gte=since)
            .values('path', 'section')
            .annotate(c=Count('id'),
                      avg_dwell=Avg('dwell_ms', filter=Q(dwell_ms__gt=0)))
            .order_by('-c')[:limit])
    return [{'path': r['path'], 'section': r['section'], 'count': r['c'],
             'avg_dwell_s': round((r['avg_dwell'] or 0) / 1000, 1)} for r in rows]


def section_breakdown(days: int = 30) -> list[dict]:
    """View share by section (for a donut chart)."""
    since = timezone.now() - timedelta(days=days)
    rows = (PageView.objects.filter(timestamp__gte=since)
            .values('section').annotate(c=Count('id')).order_by('-c'))
    return [{'section': r['section'] or 'Other', 'count': r['c']} for r in rows]


def hourly_heatmap(days: int = 30) -> dict:
    """Weekday × hour activity grid — answers 'when are users most active?'.

    Returns `rows` already paired with their weekday label so the template can
    iterate without slice gymnastics, plus the raw grid (for JS coloring) and
    the peak value (for the intensity scale).
    """
    since = timezone.now() - timedelta(days=days)
    grid = [[0] * 24 for _ in range(7)]
    rows = (PageView.objects.filter(timestamp__gte=since)
            .values('weekday', 'hour').annotate(c=Count('id')))
    peak = 0
    for r in rows:
        wd, hr = r['weekday'], r['hour']
        if 0 <= wd < 7 and 0 <= hr < 24:
            grid[wd][hr] = r['c']
            peak = max(peak, r['c'])
    labeled = [{'name': WEEKDAY_NAMES[i], 'cells': grid[i]} for i in range(7)]
    return {'grid': grid, 'rows': labeled, 'weekday_names': WEEKDAY_NAMES,
            'hours': list(range(24)), 'peak': peak}


def peak_activity(days: int = 30) -> dict:
    """The single busiest hour and weekday, in plain language."""
    since = timezone.now() - timedelta(days=days)
    qs = PageView.objects.filter(timestamp__gte=since)
    hour_rows = qs.values('hour').annotate(c=Count('id')).order_by('-c')
    day_rows = qs.values('weekday').annotate(c=Count('id')).order_by('-c')
    best_hour = hour_rows[0]['hour'] if hour_rows else None
    best_day = day_rows[0]['weekday'] if day_rows else None
    return {
        'busiest_hour': f'{best_hour:02d}:00–{(best_hour + 1) % 24:02d}:00 UTC' if best_hour is not None else '—',
        'busiest_day': WEEKDAY_NAMES[best_day] if best_day is not None else '—',
    }


# --- ML: user segmentation via k-means ------------------------------------
# Human-readable names for the discovered clusters, chosen by ranking each
# cluster's average total activity (see user_segments).
_SEGMENT_NAMES = ['Power users', 'Regulars', 'Casual visitors', 'One-and-done']


def user_segments(days: int = 30) -> dict:
    """Cluster visitors by behavior using k-means, with k chosen by silhouette.

    Features come from the feature store (analytics.features) — the SAME ones the
    churn model uses, minus recency (segments describe *how* people engage, not
    *when* they last did). They're min-max normalized so no single large column
    dominates the Euclidean distance. Rather than hard-coding k, we run the
    elbow/silhouette sweep (ml.choose_k_elbow) and use the suggested k — a more
    principled choice than picking 3 by hand. Clusters are named by activity rank.
    """
    visitor_ids, rows, names, _meta = features.build_matrix(days, exclude=('recency_days',))
    if len(visitor_ids) < 2:
        return {'segments': [], 'note': 'Not enough distinct visitors yet to segment.'}

    normalized = ml.minmax_normalize(rows)

    # Principled k: try k=2..4 and take the best silhouette (falls back to 2).
    elbow = ml.choose_k_elbow(normalized, k_min=2, k_max=min(4, len(visitor_ids)))
    k = elbow['suggested_k']
    result = ml.kmeans(normalized, k=k)
    sil = ml.silhouette_score(normalized, result.labels)

    # Summarize each cluster from the ORIGINAL (un-normalized) features.
    idx = {name: i for i, name in enumerate(names)}
    clusters = defaultdict(list)
    for i, label in enumerate(result.labels):
        clusters[label].append(rows[i])

    summaries = []
    for label, members in clusters.items():
        m = len(members)
        avg_views = sum(r[idx['total_views']] for r in members) / m
        summaries.append({
            'size': m,
            'avg_views': round(avg_views, 1),
            'avg_sections': round(sum(r[idx['distinct_sections']] for r in members) / m, 1),
            'avg_active_days': round(sum(r[idx['active_days']] for r in members) / m, 1),
            '_rank': avg_views,
        })

    # Name clusters by activity rank (busiest -> "Power users").
    summaries.sort(key=lambda s: s['_rank'], reverse=True)
    for i, s in enumerate(summaries):
        s['name'] = _SEGMENT_NAMES[i] if i < len(_SEGMENT_NAMES) else f'Segment {i + 1}'
        del s['_rank']

    return {
        'segments': summaries,
        'total_visitors': len(visitor_ids),
        'k': k,
        'silhouette': round(sil, 3),
        'elbow': elbow['metrics'],
    }
