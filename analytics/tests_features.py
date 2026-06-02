"""Tests for the feature store (analytics/features.py) and materialization."""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from .models import PageView, VisitorFeatures
from . import features


def _pv(session, section, ts, ms=20):
    return PageView(
        user=None, session_hash=session, path='/' + section.lower() + '/',
        section=section, method='GET', status_code=200, response_ms=ms,
        is_authenticated=False, timestamp=ts, hour=ts.hour, weekday=ts.weekday(),
    )


class FeatureStoreTests(TestCase):
    def setUp(self):
        now = timezone.now()
        # Visitor 'a': 3 views across 2 sections, 2 active days, one session gap.
        PageView.objects.bulk_create([
            _pv('a', 'Investments', now - timedelta(days=1)),
            _pv('a', 'Competition', now - timedelta(days=1, minutes=5)),
            _pv('a', 'Investments', now - timedelta(hours=2)),  # new session (>30m gap)
        ])

    def test_build_matrix_shapes_and_names(self):
        ids, rows, names, meta = features.build_matrix(30)
        self.assertIn('sa', ids)  # anonymous visitor id = 's' + session_hash
        self.assertEqual(len(rows[0]), len(names))
        self.assertEqual(names, features.FEATURE_NAMES)
        i = ids.index('sa')
        self.assertEqual(rows[i][names.index('total_views')], 3.0)
        self.assertEqual(rows[i][names.index('distinct_sections')], 2.0)
        self.assertEqual(rows[i][names.index('active_days')], 2.0)
        # meta carries recency for labeling.
        self.assertIn('recency_days', meta[i])

    def test_exclude_drops_named_feature(self):
        ids, rows, names, meta = features.build_matrix(30, exclude=('recency_days',))
        self.assertNotIn('recency_days', names)
        self.assertEqual(len(rows[0]), len(features.FEATURE_NAMES) - 1)
        # recency still available in meta even when excluded from features.
        self.assertIn('recency_days', meta[0])

    def test_session_count_uses_30min_timeout(self):
        aggs = features.build_aggregates(30)
        # Two views 5 min apart + one 2h later => 2 sessions.
        self.assertEqual(aggs['sa'].session_count, 2)

    def test_feature_catalog_documents_every_feature(self):
        cat = features.feature_catalog()
        self.assertEqual(len(cat), len(features.FEATURE_NAMES))
        self.assertTrue(all(c['description'] for c in cat))

    def test_materialize_writes_snapshots(self):
        n = features.materialize(30)
        self.assertEqual(n, VisitorFeatures.objects.count())
        vf = VisitorFeatures.objects.get(visitor_key='sa')
        self.assertEqual(vf.features['total_views'], 3.0)
        # Re-materializing updates in place, not duplicates.
        features.materialize(30)
        self.assertEqual(VisitorFeatures.objects.filter(visitor_key='sa').count(), 1)
