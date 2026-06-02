"""
Feature store — the single, documented source of per-visitor features.

WHY A FEATURE STORE: segmentation (k-means) and churn (logistic regression)
must see the SAME features, computed the SAME way, or their outputs disagree and
become untrustworthy. This module is the one place features are defined, named,
and described, which gives:

  - reuse without drift (every model calls build_matrix()),
  - self-documentation (each feature carries a human description),
  - point-in-time consistency (all features come from one pass over PageView),
  - optional materialization to the VisitorFeatures table for caching.

TO ADD A FEATURE: append a Feature(...) to FEATURE_REGISTRY. Every consumer
(segments, churn, the dashboard's feature catalog) picks it up automatically.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Callable

from django.utils import timezone

from .models import PageView

# Sessions break after 30 minutes of inactivity (mirrors product_analytics).
SESSION_TIMEOUT = timedelta(minutes=30)


def visitor_id(user_id, session_hash) -> str:
    """Unify authenticated (u<pk>) and anonymous (s<hash>) identities."""
    return f'u{user_id}' if user_id else f's{session_hash}'


@dataclass
class VisitorAggregate:
    """Raw per-visitor rollup that every feature is derived from."""
    views: int = 0
    sections: set = field(default_factory=set)
    active_days: set = field(default_factory=set)
    timestamps: list = field(default_factory=list)
    resp_ms: list = field(default_factory=list)
    last_seen: object = None

    @property
    def session_count(self) -> int:
        ts = sorted(self.timestamps)
        if not ts:
            return 0
        n = 1
        for prev, cur in zip(ts, ts[1:]):
            if (cur - prev) > SESSION_TIMEOUT:
                n += 1
        return n

    @property
    def recency_days(self) -> int:
        if self.last_seen is None:
            return 9999
        # Clamp at 0: a last-seen timestamp later today (or minor clock skew)
        # would otherwise round to -1 days, which is nonsensical for "recency".
        return max(0, (timezone.now() - self.last_seen).days)


@dataclass
class Feature:
    """A named, described scalar feature computed from a VisitorAggregate."""
    name: str
    description: str
    fn: Callable  # (VisitorAggregate) -> float


# The canonical feature set. Order here = column order in the matrix.
FEATURE_REGISTRY: list[Feature] = [
    Feature('total_views', 'Total page views in the window.',
            lambda a: float(a.views)),
    Feature('distinct_sections', 'How many distinct site sections they touched.',
            lambda a: float(len(a.sections))),
    Feature('active_days', 'Number of distinct calendar days they were active.',
            lambda a: float(len(a.active_days))),
    Feature('avg_session_pages', 'Average pages per session (engagement depth).',
            lambda a: float(a.views / a.session_count) if a.session_count else float(a.views)),
    Feature('avg_response_ms', 'Average server render time they experienced.',
            lambda a: float(sum(a.resp_ms) / len(a.resp_ms)) if a.resp_ms else 0.0),
    Feature('recency_days', 'Days since their most recent visit (lower = fresher).',
            lambda a: float(a.recency_days)),
]

FEATURE_NAMES = [f.name for f in FEATURE_REGISTRY]


def build_aggregates(days: int = 30) -> dict[str, VisitorAggregate]:
    """One pass over PageView -> {visitor_id: VisitorAggregate}."""
    since = timezone.now() - timedelta(days=days)
    rows = (PageView.objects.filter(timestamp__gte=since)
            .exclude(session_hash='', user_id__isnull=True)
            .values_list('user_id', 'session_hash', 'section', 'timestamp', 'response_ms'))
    aggs: dict[str, VisitorAggregate] = defaultdict(VisitorAggregate)
    for uid, sh, section, ts, ms in rows:
        a = aggs[visitor_id(uid, sh)]
        a.views += 1
        a.sections.add(section)
        a.active_days.add(ts.date())
        a.timestamps.append(ts)
        a.resp_ms.append(ms)
        if a.last_seen is None or ts > a.last_seen:
            a.last_seen = ts
    return aggs


def build_matrix(days: int = 30, exclude: tuple = ()):
    """Build the per-visitor feature matrix from the registry.

    Returns (visitor_ids, rows, feature_names, meta) where:
      - rows[i] is the feature vector for visitor_ids[i] (registry order, minus
        any names in `exclude` — used to drop the churn label's source feature),
      - meta[i] carries non-feature context (recency_days, last_seen) handy for
        labeling/inspection without re-querying.
    """
    aggs = build_aggregates(days)
    features = [f for f in FEATURE_REGISTRY if f.name not in exclude]
    visitor_ids, rows, meta = [], [], []
    for vid, agg in aggs.items():
        visitor_ids.append(vid)
        rows.append([f.fn(agg) for f in features])
        meta.append({'recency_days': agg.recency_days, 'last_seen': agg.last_seen,
                     'views': agg.views})
    names = [f.name for f in features]
    return visitor_ids, rows, names, meta


def feature_catalog() -> list[dict]:
    """Human-readable description of every registered feature (for the UI/docs)."""
    return [{'name': f.name, 'description': f.description} for f in FEATURE_REGISTRY]


def materialize(days: int = 30) -> int:
    """Snapshot the current feature matrix into the VisitorFeatures table.

    This is the 'store' half: persisting features lets the dashboard read cached
    values (and supports point-in-time/audit use) instead of recomputing on every
    load. Returns the number of visitor rows written. Idempotent per visitor
    (update_or_create), stamped with computed_at.
    """
    from .models import VisitorFeatures
    visitor_ids, rows, names, meta = build_matrix(days)
    now = timezone.now()
    written = 0
    for vid, vec, m in zip(visitor_ids, rows, meta):
        VisitorFeatures.objects.update_or_create(
            visitor_key=vid,
            defaults={'features': dict(zip(names, vec)),
                      'recency_days': int(m['recency_days']),
                      'computed_at': now, 'window_days': days},
        )
        written += 1
    return written
