"""
Tests for the analytics ML toolkit, insights layer, middleware, and the
staff-gated dashboard. The ML tests assert on known closed-form answers so the
math is provably correct, not just "runs without error".
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from . import ml
from .models import PageView
from . import insights

User = get_user_model()


class LinearRegressionTests(TestCase):
    def test_perfect_line(self):
        # y = 2x + 1 exactly -> slope 2, intercept 1, r²=1.
        xs = [0, 1, 2, 3, 4]
        ys = [1, 3, 5, 7, 9]
        m = ml.linear_regression(xs, ys)
        self.assertAlmostEqual(m.slope, 2.0, places=6)
        self.assertAlmostEqual(m.intercept, 1.0, places=6)
        self.assertAlmostEqual(m.r_squared, 1.0, places=6)
        self.assertAlmostEqual(m.predict(5), 11.0, places=6)

    def test_flat_series(self):
        m = ml.linear_regression([0, 1, 2], [5, 5, 5])
        self.assertAlmostEqual(m.slope, 0.0, places=6)
        self.assertAlmostEqual(m.intercept, 5.0, places=6)

    def test_degenerate_inputs(self):
        self.assertEqual(ml.linear_regression([], []).slope, 0.0)
        self.assertEqual(ml.linear_regression([3], [9]).intercept, 9.0)

    def test_forecast_extends_trend(self):
        # Rising series -> forecast should continue rising and be non-negative.
        f = ml.forecast_linear([1, 2, 3, 4, 5], horizon=3)
        self.assertEqual(len(f), 3)
        self.assertGreater(f[0], 5)
        self.assertTrue(all(v >= 0 for v in f))

    def test_forecast_clamps_negative(self):
        # Steeply falling series must not forecast negative counts.
        f = ml.forecast_linear([10, 8, 6, 4, 2], horizon=5)
        self.assertTrue(all(v >= 0 for v in f))


class AnomalyTests(TestCase):
    def test_detects_spike(self):
        series = [10, 11, 9, 10, 50, 10, 9]  # index 4 is a clear spike
        anomalies = ml.zscore_anomalies(series, threshold=2.0)
        self.assertTrue(any(a.index == 4 and a.direction == 'spike' for a in anomalies))

    def test_flat_series_has_no_anomalies(self):
        self.assertEqual(ml.zscore_anomalies([5, 5, 5, 5, 5]), [])

    def test_moving_average_smooths(self):
        avg = ml.moving_average([0, 0, 0, 9], window=2)
        self.assertEqual(len(avg), 4)
        self.assertAlmostEqual(avg[-1], 4.5)  # mean of last two (0, 9)


class KMeansTests(TestCase):
    def test_separates_two_obvious_clusters(self):
        # Two tight, far-apart blobs -> the two points in a blob share a label.
        pts = [[0, 0], [0.1, 0.1], [0.0, 0.2], [9, 9], [9.1, 9.0], [8.9, 9.2]]
        res = ml.kmeans(pts, k=2)
        self.assertEqual(res.labels[0], res.labels[1])
        self.assertEqual(res.labels[3], res.labels[4])
        self.assertNotEqual(res.labels[0], res.labels[3])
        self.assertEqual(sum(res.sizes), 6)

    def test_k_clamped_to_point_count(self):
        res = ml.kmeans([[1, 1]], k=5)
        self.assertEqual(len(res.centroids), 1)

    def test_normalize_scales_to_unit_range(self):
        norm = ml.minmax_normalize([[0, 10], [5, 20], [10, 30]])
        self.assertEqual(norm[0], [0.0, 0.0])
        self.assertEqual(norm[2], [1.0, 1.0])


class InsightsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='viewer', password='x')
        now = timezone.now()
        # Seed a few days of views across two sections.
        for d in range(5):
            ts = now - timedelta(days=d)
            for _ in range(d + 1):  # increasing daily volume
                PageView.objects.create(
                    user=self.user, session_hash='', path='/investments/',
                    section='Investments', status_code=200, response_ms=20,
                    is_authenticated=True, timestamp=ts, hour=ts.hour, weekday=ts.weekday(),
                )

    def test_kpis_counts(self):
        k = insights.kpis(30)
        self.assertEqual(k['total_views'], 1 + 2 + 3 + 4 + 5)
        self.assertEqual(k['signed_in_visitors'], 1)

    def test_daily_traffic_has_forecast_and_trend(self):
        t = insights.daily_traffic(7)
        self.assertEqual(len(t['forecast']), 7)
        self.assertIn(t['trend_direction'], ('up', 'down', 'flat'))
        self.assertEqual(len(t['counts']), 7)

    def test_top_pages_returns_section(self):
        pages = insights.top_pages(30)
        self.assertTrue(pages)
        self.assertEqual(pages[0]['path'], '/investments/')
        self.assertEqual(pages[0]['section'], 'Investments')


class DashboardAccessTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(username='boss', password='x', is_staff=True)
        self.regular = User.objects.create_user(username='joe', password='x')

    def test_staff_can_view(self):
        self.client.force_login(self.staff)
        r = self.client.get(reverse('analytics:dashboard'))
        self.assertEqual(r.status_code, 200)
        self.assertTemplateUsed(r, 'analytics/dashboard.html')

    def test_regular_user_is_redirected(self):
        self.client.force_login(self.regular)
        r = self.client.get(reverse('analytics:dashboard'))
        # staff_member_required bounces non-staff to the admin login.
        self.assertEqual(r.status_code, 302)


class MiddlewareTests(TestCase):
    def test_get_html_is_logged(self):
        User.objects.create_user(username='surf', password='x')
        self.client.login(username='surf', password='x')
        before = PageView.objects.count()
        self.client.get(reverse('competition:lobby'))
        self.assertEqual(PageView.objects.count(), before + 1)
        pv = PageView.objects.latest('timestamp')
        self.assertEqual(pv.section, 'Competition')

    def test_analytics_path_is_not_logged(self):
        staff = User.objects.create_user(username='boss2', password='x', is_staff=True)
        self.client.force_login(staff)
        before = PageView.objects.count()
        self.client.get(reverse('analytics:dashboard'))
        self.assertEqual(PageView.objects.count(), before)  # self-excluded
