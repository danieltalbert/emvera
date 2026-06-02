"""Tests for the percentile helper and performance monitoring insight."""
from django.test import TestCase, SimpleTestCase
from django.utils import timezone

from .models import PageView
from . import ml
from . import insights


class PercentileTests(SimpleTestCase):
    def test_known_percentiles(self):
        data = list(range(1, 101))  # 1..100
        self.assertAlmostEqual(ml.percentile(data, 50), 50.5)
        self.assertAlmostEqual(ml.percentile(data, 0), 1)
        self.assertAlmostEqual(ml.percentile(data, 100), 100)
        # p90 of 1..100 (linear) = 90.1
        self.assertAlmostEqual(ml.percentile(data, 90), 90.1)

    def test_edge_cases(self):
        self.assertEqual(ml.percentile([], 50), 0.0)
        self.assertEqual(ml.percentile([7], 99), 7.0)


class PerformanceTests(TestCase):
    def test_percentiles_and_slow_ranking(self):
        now = timezone.now()
        rows = []
        # Fast page (~10ms) and a slow page (~500ms).
        for _ in range(50):
            rows.append(PageView(user=None, session_hash='s', path='/fast/', section='X',
                                 method='GET', status_code=200, response_ms=10,
                                 is_authenticated=False, timestamp=now, hour=1, weekday=1))
        for _ in range(50):
            rows.append(PageView(user=None, session_hash='s', path='/slow/', section='X',
                                 method='GET', status_code=200, response_ms=500,
                                 is_authenticated=False, timestamp=now, hour=1, weekday=1))
        PageView.objects.bulk_create(rows)

        perf = insights.performance(30)
        self.assertTrue(perf['available'])
        self.assertLess(perf['p50'], perf['p90'])
        self.assertLessEqual(perf['p90'], perf['p99'])
        # /slow/ should rank first by p90.
        self.assertEqual(perf['slow_pages'][0]['path'], '/slow/')
        self.assertGreater(perf['slow_pages'][0]['p90'], 400)

    def test_unavailable_when_empty(self):
        self.assertFalse(insights.performance(30)['available'])
