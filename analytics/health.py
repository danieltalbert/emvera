"""
Engagement health score — a single 0-100 number per visitor.

Inspired by RFM (Recency, Frequency, Monetary) scoring from CRM analytics, but
adapted to product engagement. It blends five normalized signals from the
feature store into one interpretable score, then buckets visitors into bands
(Champion → Dormant). It answers "who are my best users, and who's slipping?"
at a glance and gives outreach/retention a concrete target list.

Weights are explicit and documented so the score is auditable; tweak them in
one place (_WEIGHTS) and every consumer updates.
"""
from __future__ import annotations

from . import features

# How much each normalized signal contributes (sums to 1.0). Recency and
# frequency dominate — they're the strongest leading indicators of retention.
_WEIGHTS = {
    'recency': 0.30,    # fresher = healthier
    'frequency': 0.25,  # more active days
    'breadth': 0.15,    # explores more of the product
    'depth': 0.15,      # deeper sessions
    'volume': 0.15,     # more total activity
}

# Caps used to normalize each raw signal into [0, 1] before weighting.
_RECENCY_CAP_DAYS = 30
_FREQUENCY_CAP_DAYS = 14
_BREADTH_CAP_SECTIONS = 6
_DEPTH_CAP_PAGES = 5
_VOLUME_CAP_VIEWS = 50

BANDS = ['Champion', 'Engaged', 'Casual', 'At risk', 'Dormant']


def band(score: float) -> str:
    """Bucket a 0-100 score into a named engagement band."""
    if score >= 80:
        return 'Champion'
    if score >= 60:
        return 'Engaged'
    if score >= 40:
        return 'Casual'
    if score >= 20:
        return 'At risk'
    return 'Dormant'


def score_features(fmap: dict) -> float:
    """Compute the 0-100 health score from a {feature_name: value} mapping."""
    recency = fmap.get('recency_days', _RECENCY_CAP_DAYS)
    rec = max(0.0, 1 - recency / _RECENCY_CAP_DAYS)
    freq = min(fmap.get('active_days', 0) / _FREQUENCY_CAP_DAYS, 1.0)
    breadth = min(fmap.get('distinct_sections', 0) / _BREADTH_CAP_SECTIONS, 1.0)
    depth = min(fmap.get('avg_session_pages', 0) / _DEPTH_CAP_PAGES, 1.0)
    volume = min(fmap.get('total_views', 0) / _VOLUME_CAP_VIEWS, 1.0)
    score = 100 * (_WEIGHTS['recency'] * rec + _WEIGHTS['frequency'] * freq
                   + _WEIGHTS['breadth'] * breadth + _WEIGHTS['depth'] * depth
                   + _WEIGHTS['volume'] * volume)
    return round(score, 1)


def engagement_health(days: int = 30) -> dict:
    """Score every visitor and summarize the distribution + notable lists."""
    ids, rows, names, _meta = features.build_matrix(days)
    if not ids:
        return {'available': False, 'note': 'No visitors yet to score.'}

    scored = []
    for vid, vec in zip(ids, rows):
        fmap = dict(zip(names, vec))
        s = score_features(fmap)
        scored.append({
            'visitor': vid[:10], 'score': s, 'band': band(s),
            'recency_days': int(fmap.get('recency_days', 0)),
            'views': int(fmap.get('total_views', 0)),
            'active_days': int(fmap.get('active_days', 0)),
        })
    scored.sort(key=lambda d: d['score'], reverse=True)

    counts = {b: 0 for b in BANDS}
    for s in scored:
        counts[s['band']] += 1
    distribution = [{'band': b, 'count': counts[b]} for b in BANDS]

    at_risk = [s for s in scored if s['band'] in ('At risk', 'Dormant')]
    return {
        'available': True,
        'total': len(scored),
        'avg_score': round(sum(s['score'] for s in scored) / len(scored), 1),
        'distribution': distribution,
        'champions': scored[:6],
        'at_risk': at_risk[:6],
        'at_risk_count': len(at_risk),
    }
