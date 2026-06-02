"""Tests for the live-activity insight and its polling JSON endpoint."""
import json
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.utils import timezone

from .models import PageView
from . import insights

User = get_user_model()


def _pv(session, ts):
    return PageView(user=None, session_hash=session, path='/investments/', section='Investments',
                    method='GET', status_code=200, response_ms=10, is_authenticated=False,
                    timestamp=ts, hour=ts.hour, weekday=ts.weekday())


class LiveActivityTests(TestCase):
    def test_counts_recent_excludes_old(self):
        now = timezone.now()
        PageView.objects.bulk_create([
            _pv('a', now - timedelta(minutes=2)),
            _pv('b', now - timedelta(minutes=10)),
            _pv('a', now - timedelta(minutes=1)),   # same visitor 'a' again
            _pv('c', now - timedelta(hours=5)),      # too old for a 30-min window
        ])
        live = insights.live_activity(30)
        self.assertEqual(live['active_visitors'], 2)   # a, b (not c)
        self.assertEqual(live['views_in_window'], 3)
        self.assertTrue(live['recent'])
        self.assertGreaterEqual(live['recent'][0]['ago_s'], 0)

    def test_empty_when_no_recent(self):
        PageView.objects.create(**{
            'session_hash': 'old', 'path': '/x/', 'section': 'Other', 'method': 'GET',
            'status_code': 200, 'response_ms': 1, 'is_authenticated': False,
            'timestamp': timezone.now() - timedelta(days=2), 'hour': 1, 'weekday': 1,
        })
        live = insights.live_activity(30)
        self.assertEqual(live['active_visitors'], 0)
        self.assertEqual(live['recent'], [])


class ApiLiveTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(username='boss', password='x', is_staff=True)
        PageView.objects.create(**{
            'session_hash': 'now', 'path': '/competition/', 'section': 'Competition',
            'method': 'GET', 'status_code': 200, 'response_ms': 5, 'is_authenticated': False,
            'timestamp': timezone.now(), 'hour': 1, 'weekday': 1,
        })

    def test_staff_json(self):
        self.client.force_login(self.staff)
        r = self.client.get(reverse('analytics:api_live') + '?minutes=30')
        self.assertEqual(r.status_code, 200)
        data = json.loads(r.content)
        self.assertEqual(data['active_visitors'], 1)
        self.assertIn('recent', data)

    def test_non_staff_blocked(self):
        joe = User.objects.create_user(username='joe', password='x')
        self.client.force_login(joe)
        r = self.client.get(reverse('analytics:api_live'))
        self.assertEqual(r.status_code, 302)
