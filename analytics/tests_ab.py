"""Tests for A/B statistics (ab_test.py) and the experiment runtime."""
from django.test import TestCase, SimpleTestCase

from . import ab_test
from .models import Experiment, ExperimentAssignment
from . import experiments


class NormalHelpersTests(SimpleTestCase):
    def test_norm_cdf_known_points(self):
        self.assertAlmostEqual(ab_test.norm_cdf(0), 0.5, places=6)
        self.assertAlmostEqual(ab_test.norm_cdf(1.96), 0.975, places=3)
        self.assertAlmostEqual(ab_test.norm_cdf(-1.96), 0.025, places=3)

    def test_norm_ppf_inverts_cdf(self):
        self.assertAlmostEqual(ab_test.norm_ppf(0.975), 1.95996, places=3)
        self.assertAlmostEqual(ab_test.norm_ppf(0.5), 0.0, places=6)
        # ppf(cdf(z)) == z round-trip
        for z in (-1.5, 0.3, 2.1):
            self.assertAlmostEqual(ab_test.norm_ppf(ab_test.norm_cdf(z)), z, places=4)


class ZTestTests(SimpleTestCase):
    def test_significant_difference(self):
        # 10% vs 13% at n=1000 each is significant (~z=2.1, p~0.036).
        r = ab_test.two_proportion_ztest(100, 1000, 130, 1000)
        self.assertAlmostEqual(r.rate_a, 0.10, places=6)
        self.assertAlmostEqual(r.rate_b, 0.13, places=6)
        self.assertGreater(r.z, 2.0)
        self.assertLess(r.p_value, 0.05)
        self.assertTrue(r.significant)
        lo, hi = r.ci95
        self.assertLess(lo, r.diff)
        self.assertGreater(hi, r.diff)

    def test_no_difference_not_significant(self):
        r = ab_test.two_proportion_ztest(100, 1000, 102, 1000)
        self.assertFalse(r.significant)
        self.assertGreater(r.p_value, 0.05)

    def test_empty_arm_is_safe(self):
        r = ab_test.two_proportion_ztest(0, 0, 5, 50)
        self.assertEqual(r.p_value, 1.0)
        self.assertFalse(r.significant)

    def test_chi_square_agrees_with_ztest_direction(self):
        chi = ab_test.chi_square_2x2(100, 1000, 130, 1000)
        self.assertLess(chi['p_value'], 0.05)


class BayesianTests(SimpleTestCase):
    def test_clear_winner_high_probability(self):
        b = ab_test.bayesian_ab(100, 1000, 160, 1000)
        self.assertGreater(b['prob_b_beats_a'], 0.95)
        self.assertGreater(b['expected_lift'], 0)

    def test_tie_near_half(self):
        b = ab_test.bayesian_ab(100, 1000, 100, 1000)
        self.assertAlmostEqual(b['prob_b_beats_a'], 0.5, delta=0.1)


class SampleSizeTests(SimpleTestCase):
    def test_plausible_size_for_known_effect(self):
        # Detecting 10% -> 13% at alpha .05 / power .8 is ~1700-1800 per arm.
        n = ab_test.required_sample_size(0.10, 0.03)
        self.assertGreater(n, 1500)
        self.assertLess(n, 2100)

    def test_smaller_effect_needs_more_data(self):
        big = ab_test.required_sample_size(0.10, 0.05)
        small = ab_test.required_sample_size(0.10, 0.01)
        self.assertGreater(small, big)


class ExperimentRuntimeTests(TestCase):
    def setUp(self):
        self.exp = Experiment.objects.create(key='cta-color', name='CTA color')

    def test_assignment_is_deterministic(self):
        a1 = experiments.assign(self.exp, 'visitor-123')
        a2 = experiments.assign(self.exp, 'visitor-123')
        self.assertEqual(a1, a2)
        self.assertEqual(ExperimentAssignment.objects.filter(visitor_key='visitor-123').count(), 1)

    def test_assignment_is_roughly_balanced(self):
        for i in range(400):
            experiments.assign(self.exp, f'v{i}')
        n_a = ExperimentAssignment.objects.filter(experiment=self.exp, variant=0).count()
        n_b = ExperimentAssignment.objects.filter(experiment=self.exp, variant=1).count()
        self.assertEqual(n_a + n_b, 400)
        # Within a reasonable band of 50/50.
        self.assertGreater(n_a, 150)
        self.assertGreater(n_b, 150)

    def test_record_conversion_idempotent(self):
        experiments.assign(self.exp, 'buyer')
        experiments.record_conversion(self.exp, 'buyer')
        experiments.record_conversion(self.exp, 'buyer')
        obj = ExperimentAssignment.objects.get(experiment=self.exp, visitor_key='buyer')
        self.assertTrue(obj.converted)

    def test_results_detects_real_effect(self):
        # Control: 200 visitors, 20 conversions (10%). Variant: 200, 40 (20%).
        for i in range(200):
            ExperimentAssignment.objects.create(experiment=self.exp, visitor_key=f'a{i}',
                                                variant=0, converted=(i < 20))
        for i in range(200):
            ExperimentAssignment.objects.create(experiment=self.exp, visitor_key=f'b{i}',
                                                variant=1, converted=(i < 40))
        res = experiments.results(self.exp)
        self.assertEqual(res['control']['n'], 200)
        self.assertEqual(res['variant']['conversions'], 40)
        self.assertTrue(res['significant'])
        self.assertGreater(res['prob_b_beats_a'], 0.95)
        self.assertGreater(res['rel_lift'], 0.9)  # ~100% relative lift
