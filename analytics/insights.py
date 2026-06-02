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

from django.db.models import Avg, Count
from django.utils import timezone

from .models import PageView
from . import ml


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
    """Most-viewed paths, with their friendly section label."""
    since = timezone.now() - timedelta(days=days)
    rows = (PageView.objects.filter(timestamp__gte=since)
            .values('path', 'section')
            .annotate(c=Count('id'))
            .order_by('-c')[:limit])
    return [{'path': r['path'], 'section': r['section'], 'count': r['c']} for r in rows]


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


def user_segments(days: int = 30, k: int = 3) -> dict:
    """Cluster visitors by behavior using k-means.

    Per-visitor features (a compact, interpretable behavioral fingerprint):
      [ total_views, distinct_sections, active_days, avg_response_ms ]
    Features are min-max normalized so one large-magnitude column (e.g. views)
    doesn't dominate the distance metric. Clusters are then labeled by their
    average activity so the names are stable and meaningful.
    """
    since = timezone.now() - timedelta(days=days)
    qs = PageView.objects.filter(timestamp__gte=since)

    # Build per-visitor aggregates keyed by a unified visitor id.
    views = defaultdict(int)
    sections = defaultdict(set)
    active_days = defaultdict(set)
    resp = defaultdict(list)
    for pv in qs.values('user_id', 'session_hash', 'section', 'timestamp', 'response_ms'):
        vid = f'u{pv["user_id"]}' if pv['user_id'] else f's{pv["session_hash"]}'
        if vid in ('s', 's '):
            continue
        views[vid] += 1
        sections[vid].add(pv['section'])
        active_days[vid].add(pv['timestamp'].date())
        resp[vid].append(pv['response_ms'])

    visitor_ids = list(views.keys())
    if len(visitor_ids) < 2:
        return {'segments': [], 'note': 'Not enough distinct visitors yet to segment.'}

    features = [[
        float(views[v]),
        float(len(sections[v])),
        float(len(active_days[v])),
        float(sum(resp[v]) / len(resp[v])) if resp[v] else 0.0,
    ] for v in visitor_ids]

    normalized = ml.minmax_normalize(features)
    result = ml.kmeans(normalized, k=min(k, len(visitor_ids)))

    # Summarize each cluster from the ORIGINAL (un-normalized) features.
    clusters = defaultdict(list)
    for idx, label in enumerate(result.labels):
        clusters[label].append(features[idx])

    summaries = []
    for label, rows in clusters.items():
        n = len(rows)
        avg_views = sum(r[0] for r in rows) / n
        avg_sections = sum(r[1] for r in rows) / n
        avg_days = sum(r[2] for r in rows) / n
        summaries.append({
            'size': n,
            'avg_views': round(avg_views, 1),
            'avg_sections': round(avg_sections, 1),
            'avg_active_days': round(avg_days, 1),
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
        'k': result_k(result),
    }


def result_k(result) -> int:
    return len([s for s in result.sizes if s > 0]) if result.sizes else 0
