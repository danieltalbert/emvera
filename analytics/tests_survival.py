"""Tests for the Kaplan-Meier estimator and survival_analysis."""
from datetime import timedelta

from django.test import TestCase, SimpleTestCase
from django.utils import timezone

from .models import PageView
from . import ml
from . import product_analytics as pa


class KaplanMeierTests(SimpleTestCase):
    def test_all_events_drops_stepwise(self):
        # 5 subjects, all events at 1..5 -> S drops 1/n each step.
        km = ml.kaplan_meier([1, 2, 3, 4, 5], [1, 1, 1, 1, 1])
        pts = {p['t']: p['survival'] for p in km['curve']}
        self.assertEqual(pts[0], 1.0)
        self.assertAlmostEqual(pts[1], 0.8, places=4)   # 1 - 1/5
        self.assertAlmostEqual(pts[2], 0.6, places=4)   # 0.8 * (1 - 1/4)
        self.assertAlmostEqual(pts[3], 0.4, places=4)
        self.assertAlmostEqual(pts[5], 0.0, places=4)
        self.assertEqual(km['median'], 3)               # first t with S<=0.5

    def test_censoring_keeps_survival_higher(self):
        # Censored subjects don't cause steps; survival stays >0 even if last
        # subject is censored.
        km = ml.kaplan_meier([1, 2, 3, 4, 5], [1, 1, 0, 0, 0])
        # Only events at t=1,2. After t=2: 0.8 * (1 - 1/4) = 0.6, then flat.
        last = km['curve'][-1]['survival']
        self.assertGreater(last, 0.5)
        self.assertIsNone(km['median'])  # never reaches 0.5

    def test_empty(self):
        km = ml.kaplan_meier([], [])
        self.assertEqual(km['curve'][0]['survival'], 1.0)
        self.assertIsNone(km['median'])


class SurvivalAnalysisTests(TestCase):
    def test_builds_curve_with_events_and_censoring(self):
        now = timezone.now()
        rows = []
        # Churned visitors: short lifespan, last visit long ago (event).
        for i in range(5):
            rows += [PageView(user=None, session_hash=f'c{i}', path='/x/', section='X',
                              method='GET', status_code=200, response_ms=5, is_authenticated=False,
                              timestamp=now - timedelta(days=40), hour=1, weekday=1),
                     PageView(user=None, session_hash=f'c{i}', path='/x/', section='X',
                              method='GET', status_code=200, response_ms=5, is_authenticated=False,
                              timestamp=now - timedelta(days=35), hour=1, weekday=1)]
        # Active visitors: still visiting now (censored).
        for i in range(5):
            rows += [PageView(user=None, session_hash=f'a{i}', path='/x/', section='X',
                              method='GET', status_code=200, response_ms=5, is_authenticated=False,
                              timestamp=now - timedelta(days=20), hour=1, weekday=1),
                     PageView(user=None, session_hash=f'a{i}', path='/x/', section='X',
                              method='GET', status_code=200, response_ms=5, is_authenticated=False,
                              timestamp=now, hour=1, weekday=1)]
        PageView.objects.bulk_create(rows)

        s = pa.survival_analysis(90)
        self.assertTrue(s['available'])
        self.assertEqual(s['n'], 10)
        self.assertEqual(s['events'], 5)     # the churned ones
        self.assertEqual(s['censored'], 5)   # the still-active ones
        self.assertEqual(s['curve'][0]['survival'], 1.0)
