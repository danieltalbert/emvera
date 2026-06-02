"""Tests for the engagement health score."""
from datetime import timedelta

from django.test import TestCase, SimpleTestCase
from django.utils import timezone

from .models import PageView
from . import health


class ScoreUnitTests(SimpleTestCase):
    def test_champion_scores_high(self):
        s = health.score_features({
            'recency_days': 0, 'active_days': 14, 'distinct_sections': 6,
            'avg_session_pages': 5, 'total_views': 50,
        })
        self.assertGreaterEqual(s, 95)
        self.assertEqual(health.band(s), 'Champion')

    def test_dormant_scores_low(self):
        s = health.score_features({
            'recency_days': 30, 'active_days': 0, 'distinct_sections': 0,
            'avg_session_pages': 0, 'total_views': 0,
        })
        self.assertLessEqual(s, 5)
        self.assertEqual(health.band(s), 'Dormant')

    def test_bands_boundaries(self):
        self.assertEqual(health.band(80), 'Champion')
        self.assertEqual(health.band(60), 'Engaged')
        self.assertEqual(health.band(40), 'Casual')
        self.assertEqual(health.band(20), 'At risk')
        self.assertEqual(health.band(0), 'Dormant')


class EngagementHealthTests(TestCase):
    def test_summary_shapes(self):
        now = timezone.now()
        rows = []
        # A champion: many recent days + sections.
        for d in range(10):
            for sec in ['Investments', 'Competition', 'Paper Trading']:
                rows.append(PageView(user=None, session_hash='champ', path='/x/', section=sec,
                                     method='GET', status_code=200, response_ms=5,
                                     is_authenticated=False, timestamp=now - timedelta(days=d),
                                     hour=1, weekday=1))
        # A dormant-ish visitor: one old view.
        rows.append(PageView(user=None, session_hash='ghost', path='/x/', section='Account',
                             method='GET', status_code=200, response_ms=5, is_authenticated=False,
                             timestamp=now - timedelta(days=25), hour=1, weekday=1))
        PageView.objects.bulk_create(rows)

        h = health.engagement_health(30)
        self.assertTrue(h['available'])
        self.assertEqual(h['total'], 2)
        self.assertEqual(sum(b['count'] for b in h['distribution']), 2)
        # Champion ranks first and outscores the ghost.
        self.assertGreater(h['champions'][0]['score'], h['champions'][-1]['score'])

    def test_empty(self):
        self.assertFalse(health.engagement_health(30)['available'])
