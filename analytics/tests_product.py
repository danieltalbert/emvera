"""
Tests for the product-analytics layer (sessionization, funnel, cohorts, churn,
paths). These build controlled PageView fixtures and assert the behavioral
metrics come out as designed.
"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from .models import PageView
from . import product_analytics as pa


def _pv(session, path, section, ts):
    return PageView(
        user=None, session_hash=session, path=path, section=section,
        method='GET', status_code=200, response_ms=20, is_authenticated=False,
        timestamp=ts, hour=ts.hour, weekday=ts.weekday(),
    )


class SessionizeTests(TestCase):
    def test_splits_on_timeout(self):
        now = timezone.now()
        # Two views 5 min apart (same session) then one 2 hours later (new).
        PageView.objects.bulk_create([
            _pv('a', '/investments/', 'Investments', now),
            _pv('a', '/competition/', 'Competition', now + timedelta(minutes=5)),
            _pv('a', '/paper-trading/', 'Paper Trading', now + timedelta(hours=2)),
        ])
        s = pa.sessionize(30)
        self.assertEqual(s['sessions'], 2)

    def test_bounce_rate(self):
        now = timezone.now()
        # One single-page session (bounce) + one two-page session.
        PageView.objects.bulk_create([
            _pv('b', '/investments/', 'Investments', now),                       # bounce
            _pv('c', '/investments/', 'Investments', now),
            _pv('c', '/competition/', 'Competition', now + timedelta(minutes=2)),
        ])
        s = pa.sessionize(30)
        self.assertEqual(s['sessions'], 2)
        self.assertAlmostEqual(s['bounce_rate'], 0.5, places=3)


class FunnelTests(TestCase):
    def test_sequential_dropoff(self):
        now = timezone.now()
        # v1 completes 3 steps; v2 completes 1; v3 completes 2.
        rows = []
        rows += [_pv('v1', '/investments/', 'Investments', now),
                 _pv('v1', '/debt-management/dashboard/', 'Debt Management', now),
                 _pv('v1', '/competition/', 'Competition', now)]
        rows += [_pv('v2', '/investments/', 'Investments', now)]
        rows += [_pv('v3', '/investments/', 'Investments', now),
                 _pv('v3', '/debt-management/dashboard/', 'Debt Management', now)]
        PageView.objects.bulk_create(rows)
        f = pa.funnel(30)
        counts = [s['count'] for s in f['steps']]
        # Step 0: all 3; step 1: v1+v3=2; step 2: v1=1; step 3: 0
        self.assertEqual(counts[0], 3)
        self.assertEqual(counts[1], 2)
        self.assertEqual(counts[2], 1)
        self.assertEqual(counts[3], 0)


class CohortTests(TestCase):
    def test_week0_is_full_retention(self):
        now = timezone.now()
        PageView.objects.bulk_create([
            _pv('x', '/investments/', 'Investments', now - timedelta(days=2)),
            _pv('y', '/investments/', 'Investments', now - timedelta(days=1)),
        ])
        c = pa.cohort_retention(weeks=4)
        # The most recent cohort exists and its week-0 retention is 1.0.
        nonempty = [row for row in c['cohorts'] if row['size'] > 0]
        self.assertTrue(nonempty)
        for row in nonempty:
            self.assertEqual(row['retention'][0], 1.0)


class TransitionTests(TestCase):
    def test_counts_directed_transitions(self):
        now = timezone.now()
        PageView.objects.bulk_create([
            _pv('p', '/investments/', 'Investments', now),
            _pv('p', '/competition/', 'Competition', now + timedelta(minutes=1)),
        ])
        t = pa.transition_matrix(30)
        self.assertEqual(t['total_transitions'], 1)
        self.assertEqual(t['transitions'][0]['from'], '/investments/')
        self.assertEqual(t['transitions'][0]['to'], '/competition/')


class ChurnModelTests(TestCase):
    def test_insufficient_data_is_reported(self):
        now = timezone.now()
        PageView.objects.bulk_create([_pv('only', '/investments/', 'Investments', now)])
        out = pa.churn_model(30)
        self.assertFalse(out['available'])

    def test_trains_and_reports_when_enough_data(self):
        now = timezone.now()
        rows = []
        # 10 "active" visitors: recent + lots of activity (label 0).
        for i in range(10):
            vid = f'active{i}'
            for d in range(5):
                ts = now - timedelta(days=d, hours=i % 3)
                rows.append(_pv(vid, '/investments/', 'Investments', ts))
                rows.append(_pv(vid, '/competition/', 'Competition', ts + timedelta(minutes=3)))
        # 10 "churned" visitors: only old activity, little of it (label 1).
        for i in range(10):
            vid = f'gone{i}'
            ts = now - timedelta(days=20 + i)
            rows.append(_pv(vid, '/investments/', 'Investments', ts))
        PageView.objects.bulk_create(rows)

        out = pa.churn_model(40, churn_after_days=7)
        self.assertTrue(out['available'])
        # With cleanly separated behavior, ROC-AUC should be well above chance.
        self.assertGreaterEqual(out['report']['roc_auc'], 0.7)
        self.assertIn('importances', out)
        # All feature-store features except the recency label source.
        from analytics import features as fs
        self.assertEqual(len(out['importances']), len(fs.FEATURE_NAMES) - 1)
        self.assertNotIn('recency_days', [imp['feature'] for imp in out['importances']])
