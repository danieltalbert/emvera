"""Tests for funnel-by-engagement-tier."""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from .models import PageView
from . import product_analytics as pa


def _pv(session, path, ts):
    return PageView(user=None, session_hash=session, path=path, section='X',
                    method='GET', status_code=200, response_ms=5, is_authenticated=False,
                    timestamp=ts, hour=ts.hour, weekday=ts.weekday())


class FunnelBySegmentTests(TestCase):
    def test_tiers_and_progression(self):
        now = timezone.now()
        rows = []
        # Loyal visitor: active 4 distinct days, completes all 4 funnel steps.
        for d in range(4):
            rows += [_pv('loyal', '/investments/', now - timedelta(days=d))]
        rows += [_pv('loyal', '/debt-management/x/', now),
                 _pv('loyal', '/competition/', now),
                 _pv('loyal', '/paper-trading/', now)]
        # New visitor: one day, only the first step.
        rows += [_pv('new', '/investments/', now)]
        PageView.objects.bulk_create(rows)

        out = pa.funnel_by_segment(30)
        by_seg = {s['segment']: s for s in out['segments']}
        self.assertEqual(by_seg['Loyal (4+ days)']['size'], 1)
        self.assertEqual(by_seg['New (1 day)']['size'], 1)
        # Loyal reaches the final step; New does not.
        self.assertEqual(by_seg['Loyal (4+ days)']['steps'][-1]['count'], 1)
        self.assertEqual(by_seg['New (1 day)']['steps'][-1]['count'], 0)
        # Step labels align with the funnel definition.
        self.assertEqual(len(out['step_labels']), 4)
