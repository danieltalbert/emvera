"""Tests for stickiness (DAU/WAU/MAU) and the Day-N retention curve."""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from .models import PageView
from . import insights


def _pv(session, ts):
    return PageView(user=None, session_hash=session, path='/x/', section='Investments',
                    method='GET', status_code=200, response_ms=5, is_authenticated=False,
                    timestamp=ts, hour=ts.hour, weekday=ts.weekday())


class StickinessTests(TestCase):
    def test_basic_dau_wau_mau(self):
        now = timezone.now()
        # 'a' active 3 distinct days this week; 'b' active once 20 days ago.
        PageView.objects.bulk_create([
            _pv('a', now), _pv('a', now - timedelta(days=1)), _pv('a', now - timedelta(days=2)),
            _pv('b', now - timedelta(days=20)),
        ])
        s = insights.stickiness()
        self.assertEqual(s['mau'], 2)       # a and b within 30 days
        self.assertEqual(s['wau'], 1)       # only a within 7 days
        self.assertGreater(s['dau'], 0)
        self.assertGreaterEqual(s['stickiness'], 0)
        self.assertLessEqual(s['stickiness'], 1)


class RetentionCurveTests(TestCase):
    def test_day0_is_full_and_returns_counted(self):
        now = timezone.now()
        # Visitor 'r' first seen 10 days ago, returns on day 3.
        first = now - timedelta(days=10)
        PageView.objects.bulk_create([
            _pv('r', first), _pv('r', first + timedelta(days=3)),
        ])
        curve = {pt['day']: pt for pt in insights.retention_curve(30)['curve']}
        self.assertEqual(curve[0]['retention'], 1.0)   # day 0 always 100%
        self.assertEqual(curve[3]['retention'], 1.0)   # they returned on day 3
        self.assertEqual(curve[1]['retention'], 0.0)   # not on day 1

    def test_eligibility_excludes_too_recent(self):
        now = timezone.now()
        # First seen yesterday -> eligible for day 0/1 but not day 7+.
        PageView.objects.create(**{
            'session_hash': 'new', 'path': '/x/', 'section': 'X', 'method': 'GET',
            'status_code': 200, 'response_ms': 1, 'is_authenticated': False,
            'timestamp': now - timedelta(days=1), 'hour': 1, 'weekday': 1})
        curve = {pt['day']: pt for pt in insights.retention_curve(30)['curve']}
        self.assertEqual(curve[7]['eligible'], 0)
