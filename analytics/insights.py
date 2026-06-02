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
    last = since + timedelta(days=days - 1)
    forecast_labels = [(last + timedelta(days=i + 1)).strftime('%b %d') for i in range(horizon)]

    # Seasonal-aware where we have >=2 weeks of data (keeps the weekly rhythm in
    # the forecast and only flags anomalies that survive deseasonalizing);
    # otherwise fall back to the simple linear trend + flat z-score.
    seasonal = len(counts) >= 14
    if seasonal:
        forecast = ml.seasonal_forecast(counts, horizon, period=7)
        anomalies = ml.seasonal_anomalies(counts, period=7, threshold=2.0)
    else:
        forecast = ml.forecast_linear(counts, horizon)
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
        'seasonal_adjusted': seasonal,
        'anomalies': [
            {'label': labels[a.index], 'value': a.value, 'z': round(a.z, 2), 'direction': a.direction}
            for a in anomalies
        ],
    }


def performance(days: int = 30, slow_limit: int = 8) -> dict:
    """Server render-time health: latency percentiles + the slowest pages.

    Averages hide tail latency, so we report p50/p90/p99 across all page views,
    and rank pages by their p90 (the experience a frustrated user actually has)
    rather than the mean. Also returns a daily p90 trend for the chart.
    """
    since = timezone.now() - timedelta(days=days)
    qs = PageView.objects.filter(timestamp__gte=since)
    all_ms = list(qs.values_list('response_ms', flat=True))
    if not all_ms:
        return {'available': False}

    # Per-path latency lists for the slow-page ranking.
    per_path = defaultdict(list)
    for path, ms in qs.values_list('path', 'response_ms'):
        per_path[path].append(ms)
    slow = []
    for path, vals in per_path.items():
        slow.append({'path': path, 'count': len(vals),
                     'p50': round(ml.percentile(vals, 50)),
                     'p90': round(ml.percentile(vals, 90)),
                     'avg': round(sum(vals) / len(vals))})
    slow.sort(key=lambda d: d['p90'], reverse=True)

    # Daily p90 trend.
    per_day = defaultdict(list)
    for d, ms in qs.values_list('timestamp__date', 'response_ms'):
        per_day[d].append(ms)
    trend_days = sorted(per_day)
    trend = [{'label': d.strftime('%b %d'), 'p90': round(ml.percentile(per_day[d], 90))}
             for d in trend_days]

    return {
        'available': True,
        'p50': round(ml.percentile(all_ms, 50)),
        'p90': round(ml.percentile(all_ms, 90)),
        'p99': round(ml.percentile(all_ms, 99)),
        'slow_pages': slow[:slow_limit],
        'trend': trend,
    }


def stickiness() -> dict:
    """DAU / WAU / MAU and the stickiness ratio (DAU÷MAU).

    The canonical "is the product becoming a habit?" metric. DAU is the average
    distinct visitors per active day; WAU/MAU are distinct visitors over the last
    7/30 days. Stickiness = DAU/MAU (≈ what fraction of monthly users show up on
    a given day) — higher is stickier. Always computed over a fixed 30-day
    window, independent of the dashboard's selected range.
    """
    now = timezone.now()
    end = now.date()
    since = end - timedelta(days=29)
    rows = (PageView.objects.filter(timestamp__date__gte=since)
            .exclude(session_hash='', user_id__isnull=True)
            .values_list('user_id', 'session_hash', 'timestamp'))
    by_day = defaultdict(set)
    last7, last30 = set(), set()
    week_cut = end - timedelta(days=6)
    for uid, sh, ts in rows:
        vid = f'u{uid}' if uid else f's{sh}'
        d = ts.date()
        by_day[d].add(vid)
        last30.add(vid)
        if d >= week_cut:
            last7.add(vid)
    dau = (sum(len(v) for v in by_day.values()) / len(by_day)) if by_day else 0.0
    mau = len(last30)
    return {'dau': round(dau, 1), 'wau': len(last7), 'mau': mau,
            'stickiness': round(dau / mau, 3) if mau else 0.0}


def retention_curve(days: int = 30) -> dict:
    """Day-N retention: of visitors who could have returned on day N after their
    first visit, what fraction did?

    For each offset (0,1,2,3,7,14,21,28 within the window) we count visitors
    whose first-seen date is at least N days before the window end (so they had
    the *chance* to return) and check whether they were active on day first+N.
    Day 0 is 100% by definition — a good sanity anchor.
    """
    now = timezone.now()
    end = now.date()
    since = end - timedelta(days=days - 1)
    rows = (PageView.objects.filter(timestamp__date__gte=since)
            .exclude(session_hash='', user_id__isnull=True)
            .values_list('user_id', 'session_hash', 'timestamp'))
    active = defaultdict(set)
    first = {}
    for uid, sh, ts in rows:
        vid = f'u{uid}' if uid else f's{sh}'
        d = ts.date()
        active[vid].add(d)
        if vid not in first or d < first[vid]:
            first[vid] = d

    offsets = [o for o in (0, 1, 2, 3, 7, 14, 21, 28) if o < days]
    curve = []
    for n in offsets:
        eligible = [vid for vid, fd in first.items() if fd <= end - timedelta(days=n)]
        if not eligible:
            curve.append({'day': n, 'retention': 0.0, 'eligible': 0})
            continue
        returned = sum(1 for vid in eligible
                       if (first[vid] + timedelta(days=n)) in active[vid])
        curve.append({'day': n, 'retention': round(returned / len(eligible), 3),
                      'eligible': len(eligible)})
    return {'curve': curve}


def live_activity(minutes: int = 30) -> dict:
    """Near-real-time snapshot: who's active right now + a recent-events feed.

    Powers the auto-refreshing 'Live' panel. 'Active' = distinct visitors with a
    page view in the last `minutes`. Also returns today's running view total and
    the most recent events (path, section, seconds-ago) for a live ticker.
    """
    now = timezone.now()
    since = now - timedelta(minutes=minutes)
    window = PageView.objects.filter(timestamp__gte=since)
    real = window.exclude(session_hash='', user_id__isnull=True)
    users = real.filter(is_authenticated=True).values('user').distinct().count()
    anon = real.filter(is_authenticated=False).values('session_hash').distinct().count()

    recent = list(window.order_by('-timestamp')[:12]
                  .values('path', 'section', 'timestamp', 'is_authenticated'))
    feed = [{'path': r['path'], 'section': r['section'],
             'ago_s': max(0, int((now - r['timestamp']).total_seconds())),
             'auth': r['is_authenticated']} for r in recent]

    return {
        'window_min': minutes,
        'active_visitors': users + anon,
        'views_in_window': window.count(),
        'today_views': PageView.objects.filter(timestamp__date=now.date()).count(),
        'recent': feed,
    }


def weekly_pattern(days: int = 30) -> dict:
    """Day-of-week effect: each weekday's average daily views vs the overall mean.

    Computed directly from the data (group by weekday) so it's easy to read:
    'Mondays run +18% above an average day, Sundays -40%'. This is the human-
    facing companion to the seasonal index used in forecasting.
    """
    since = (timezone.now() - timedelta(days=days - 1)).date()
    rows = (PageView.objects.filter(timestamp__date__gte=since)
            .values('timestamp__date', 'weekday').annotate(c=Count('id')))
    per_weekday = defaultdict(list)
    for r in rows:
        per_weekday[r['weekday']].append(r['c'])
    # Average daily count per weekday (days with zero views still count as 0 —
    # approximate by averaging observed days, which is fine for a pattern view).
    avg = {wd: (sum(v) / len(v)) if v else 0.0 for wd, v in per_weekday.items()}
    overall = (sum(avg.values()) / len(avg)) if avg else 0.0
    out = []
    for wd in range(7):
        a = avg.get(wd, 0.0)
        rel = ((a - overall) / overall) if overall else 0.0
        out.append({'weekday': WEEKDAY_NAMES[wd], 'avg': round(a, 1),
                    'rel_pct': round(rel * 100, 1)})
    return {'pattern': out, 'overall_avg': round(overall, 1)}


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
