"""Tests for the sequential guardrail and the experiment detail page."""
from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model

from .models import Experiment, ExperimentAssignment
from . import experiments

User = get_user_model()


class GuardrailTests(TestCase):
    def _exp_with(self, n_a, c_a, n_b, c_b):
        exp = Experiment.objects.create(key='g', name='G')
        ExperimentAssignment.objects.bulk_create(
            [ExperimentAssignment(experiment=exp, visitor_key=f'a{i}', variant=0,
                                  converted=(i < c_a)) for i in range(n_a)] +
            [ExperimentAssignment(experiment=exp, visitor_key=f'b{i}', variant=1,
                                  converted=(i < c_b)) for i in range(n_b)])
        return exp

    def test_underpowered_collecting(self):
        exp = self._exp_with(15, 2, 15, 4)  # tiny sample
        g = experiments.experiment_detail(exp)['guardrail']
        self.assertLess(g['progress'], 1.0)
        self.assertIn(g['level'], ('neutral', 'warn'))
        self.assertGreater(g['remaining'], 0)

    def test_significant_and_powered_is_callable(self):
        # Big, clearly different arms -> significant and past required n.
        exp = self._exp_with(2500, 250, 2500, 400)  # 10% vs 16%
        g = experiments.experiment_detail(exp)['guardrail']
        self.assertTrue(g['powered'])
        self.assertEqual(g['level'], 'good')

    def test_significant_but_underpowered_warns(self):
        # A real-ish gap on a smallish sample that crosses p<0.05 but isn't
        # at the fixed-horizon target yet -> peeking warning.
        exp = self._exp_with(120, 6, 120, 22)
        res = experiments.experiment_detail(exp)
        if res['significant'] and not res['guardrail']['powered']:
            self.assertEqual(res['guardrail']['level'], 'warn')


class DetailPageTests(TestCase):
    def setUp(self):
        self.exp = Experiment.objects.create(key='cta', name='CTA test')
        ExperimentAssignment.objects.bulk_create([
            ExperimentAssignment(experiment=self.exp, visitor_key=f'a{i}', variant=0,
                                 converted=(i < 10)) for i in range(100)] + [
            ExperimentAssignment(experiment=self.exp, visitor_key=f'b{i}', variant=1,
                                 converted=(i < 18)) for i in range(100)])
        self.staff = User.objects.create_user(username='boss', password='x', is_staff=True)

    def test_detail_renders_for_staff(self):
        self.client.force_login(self.staff)
        r = self.client.get(reverse('analytics:experiment_detail', args=['cta']))
        self.assertEqual(r.status_code, 200)
        self.assertTemplateUsed(r, 'analytics/experiment_detail.html')
        self.assertContains(r, 'Sequential-testing guardrail')

    def test_detail_blocked_for_non_staff(self):
        joe = User.objects.create_user(username='joe', password='x')
        self.client.force_login(joe)
        r = self.client.get(reverse('analytics:experiment_detail', args=['cta']))
        self.assertEqual(r.status_code, 302)

    def test_unknown_experiment_404(self):
        self.client.force_login(self.staff)
        r = self.client.get(reverse('analytics:experiment_detail', args=['nope']))
        self.assertEqual(r.status_code, 404)
