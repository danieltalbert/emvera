"""Tests for the ops layer: the scheduled-jobs runner and the JSON metrics API."""
import json
from datetime import timedelta

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.utils import timezone

from .models import PageView, VisitorFeatures

User = get_user_model()


def _seed(n_days=20):
    now = timezone.now()
    rows = []
    for d in range(n_days):
        day = now - timedelta(days=d)
        for v in range(4):
            rows.append(PageView(user=None, session_hash=f'v{v}', path='/investments/',
                                 section='Investments', method='GET', status_code=200,
                                 response_ms=12, is_authenticated=False, timestamp=day,
                                 hour=day.hour, weekday=day.weekday()))
    PageView.objects.bulk_create(rows)


class RunAnalyticsJobsTests(TestCase):
    def test_runs_all_jobs(self):
        _seed()
        self.assertEqual(VisitorFeatures.objects.count(), 0)
        call_command('run_analytics_jobs', '--days', '20')
        # materialize_features should have written snapshots.
        self.assertGreater(VisitorFeatures.objects.count(), 0)

    def test_idempotent(self):
        _seed()
        call_command('run_analytics_jobs', '--days', '20')
        n = VisitorFeatures.objects.count()
        call_command('run_analytics_jobs', '--days', '20')
        self.assertEqual(VisitorFeatures.objects.count(), n)  # update_or_create, no dupes


class ApiMetricsTests(TestCase):
    def setUp(self):
        _seed()
        self.staff = User.objects.create_user(username='boss', password='x', is_staff=True)

    def test_staff_gets_json(self):
        self.client.force_login(self.staff)
        r = self.client.get(reverse('analytics:api_metrics') + '?days=30')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/json')
        data = json.loads(r.content)
        self.assertIn('kpis', data)
        self.assertIn('trend', data)
        self.assertIn('forecast_next7', data)
        self.assertEqual(data['window_days'], 30)

    def test_non_staff_blocked(self):
        joe = User.objects.create_user(username='joe', password='x')
        self.client.force_login(joe)
        r = self.client.get(reverse('analytics:api_metrics'))
        self.assertEqual(r.status_code, 302)  # bounced to admin login
