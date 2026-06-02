"""Tests for the conversion-propensity model + driver analysis."""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from .models import PageView
from . import conversion


def _pv(session, section, ts):
    return PageView(user=None, session_hash=session, path='/' + section[:4].lower() + '/',
                    section=section, method='GET', status_code=200, response_ms=10,
                    is_authenticated=False, timestamp=ts, hour=ts.hour, weekday=ts.weekday())


class ConversionModelTests(TestCase):
    def test_insufficient_data(self):
        now = timezone.now()
        PageView.objects.bulk_create([_pv('only', 'Investments', now)])
        self.assertFalse(conversion.conversion_model(30)['available'])

    def test_models_and_finds_breadth_driver(self):
        now = timezone.now()
        rows = []
        # 12 "broad" visitors: explore many sections AND reach Paper Trading.
        for i in range(12):
            for sec in ['Investments', 'Debt Management', 'Competition', 'Paper Trading']:
                for d in range(3):
                    rows.append(_pv(f'broad{i}', sec, now - timedelta(days=d)))
        # 12 "narrow" visitors: only Investments, never reach the goal.
        for i in range(12):
            rows.append(_pv(f'narrow{i}', 'Investments', now - timedelta(days=1)))
        PageView.objects.bulk_create(rows)

        out = conversion.conversion_model(30, goal_section='Paper Trading')
        self.assertTrue(out['available'])
        self.assertEqual(out['goal_section'], 'Paper Trading')
        # Cleanly separable -> strong AUC.
        self.assertGreaterEqual(out['report']['roc_auc'], 0.8)
        # Goal section must NOT be among the features (no leakage).
        feats = [c['feature'] for c in out['correlations']]
        self.assertNotIn('Paper Trading', feats)
        # Broad engagement (Competition / Debt) should correlate positively.
        top = out['correlations'][0]
        self.assertGreater(abs(top['corr']), 0.2)
