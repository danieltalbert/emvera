"""
Unit tests for the expanded ML toolkit (ml.py) and evaluation suite (metrics.py).

These assert on closed-form / known-good answers so the math is provably
correct — a model that "runs" but computes the wrong thing is worse than none.
"""
import math
import random

from django.test import SimpleTestCase

from . import ml
from . import metrics


class HelpersTests(SimpleTestCase):
    def test_mean_stdev(self):
        self.assertAlmostEqual(ml.mean([2, 4, 6]), 4.0)
        # population stdev of [2,4,6] = sqrt(8/3)
        self.assertAlmostEqual(ml.stdev([2, 4, 6]), math.sqrt(8 / 3), places=6)
        self.assertAlmostEqual(ml.stdev([2, 4, 6], population=False), 2.0, places=6)

    def test_pearson_perfect_and_anti(self):
        self.assertAlmostEqual(ml.pearson_correlation([1, 2, 3], [2, 4, 6]), 1.0, places=6)
        self.assertAlmostEqual(ml.pearson_correlation([1, 2, 3], [6, 4, 2]), -1.0, places=6)
        self.assertEqual(ml.pearson_correlation([1, 1, 1], [1, 2, 3]), 0.0)


class RegressionCITests(SimpleTestCase):
    def test_significant_upward_trend(self):
        # Real signal + small noise: slope ~2 and significantly > 0. (Noiseless
        # data gives se=0 and a degenerate point CI, so we add light noise to
        # exercise the standard-error path the way real traffic would.)
        rng = random.Random(3)
        xs = list(range(30))
        ys = [2 * x + 1 + rng.gauss(0, 1.5) for x in xs]
        ci = ml.linear_regression_ci(xs, ys)
        self.assertAlmostEqual(ci.model.slope, 2.0, places=0)
        self.assertTrue(ci.slope_is_significant())
        lo, hi = ci.slope_ci95()
        self.assertLess(lo, ci.model.slope)
        self.assertGreater(hi, ci.model.slope)

    def test_flat_noise_not_significant(self):
        rng = random.Random(0)
        xs = list(range(30))
        ys = [rng.gauss(10, 1) for _ in xs]  # no real trend
        ci = ml.linear_regression_ci(xs, ys)
        self.assertFalse(ci.slope_is_significant())


class SmoothingTests(SimpleTestCase):
    def test_ewma_tracks_then_smooths(self):
        out = ml.ewma([0, 0, 0, 10], alpha=0.5)
        self.assertEqual(out[0], 0)
        self.assertAlmostEqual(out[-1], 5.0)  # 0.5*10 + 0.5*0

    def test_holt_continues_linear_trend(self):
        series = [float(i) for i in range(10)]  # slope 1
        fc = ml.holt_forecast(series, horizon=3, alpha=0.6, beta=0.4)
        self.assertEqual(len(fc), 3)
        # Should keep rising past the last value (9).
        self.assertGreater(fc[0], 9)
        self.assertGreater(fc[2], fc[0])

    def test_holt_clamps_nonnegative(self):
        fc = ml.holt_forecast([10, 8, 6, 4, 2, 0], horizon=5)
        self.assertTrue(all(v >= 0 for v in fc))


class ClusteringQualityTests(SimpleTestCase):
    def test_silhouette_high_for_separated_blobs(self):
        pts = [[0, 0], [0.1, 0], [0, 0.1], [10, 10], [10.1, 10], [10, 10.1]]
        res = ml.kmeans(pts, k=2)
        sil = ml.silhouette_score(pts, res.labels)
        self.assertGreater(sil, 0.8)  # very well separated

    def test_elbow_picks_two_for_two_blobs(self):
        rng = random.Random(1)
        blob_a = [[rng.gauss(0, 0.3), rng.gauss(0, 0.3)] for _ in range(15)]
        blob_b = [[rng.gauss(8, 0.3), rng.gauss(8, 0.3)] for _ in range(15)]
        res = ml.choose_k_elbow(blob_a + blob_b, k_min=2, k_max=5)
        self.assertEqual(res['suggested_k'], 2)

    def test_standardize_zero_mean_unit_var(self):
        rows = [[1.0], [2.0], [3.0], [4.0]]
        std = ml.standardize(rows)
        col = [r[0] for r in std]
        self.assertAlmostEqual(ml.mean(col), 0.0, places=6)
        self.assertAlmostEqual(ml.stdev(col), 1.0, places=6)


class LogisticRegressionTests(SimpleTestCase):
    def test_learns_separable_problem(self):
        # 1-D: negatives near -2, positives near +2 -> trivially separable.
        X = [[-2.0], [-1.5], [-1.8], [2.0], [1.6], [1.9]]
        y = [0, 0, 0, 1, 1, 1]
        Xs = ml.standardize(X)
        model = ml.LogisticRegression().fit(Xs, y, lr=0.5, epochs=800)
        preds = [model.predict(xi) for xi in Xs]
        self.assertEqual(preds, y)
        # Loss should decrease over training.
        self.assertLess(model.loss_history[-1], model.loss_history[0])

    def test_proba_in_unit_interval(self):
        model = ml.LogisticRegression().fit([[0.0], [1.0]], [0, 1], epochs=50)
        p = model.predict_proba([0.5])
        self.assertGreaterEqual(p, 0.0)
        self.assertLessEqual(p, 1.0)

    def test_sigmoid_stable_at_extremes(self):
        self.assertAlmostEqual(ml.sigmoid(0), 0.5)
        self.assertGreater(ml.sigmoid(50), 0.999)
        self.assertLess(ml.sigmoid(-50), 0.001)


class MetricsTests(SimpleTestCase):
    def test_confusion_and_derived(self):
        y_true = [1, 1, 0, 0, 1, 0]
        y_pred = [1, 0, 0, 1, 1, 0]
        cm = metrics.confusion_matrix(y_true, y_pred)
        self.assertEqual((cm.tp, cm.fp, cm.fn, cm.tn), (2, 1, 1, 2))
        self.assertAlmostEqual(metrics.accuracy(cm), 4 / 6, places=6)
        self.assertAlmostEqual(metrics.precision(cm), 2 / 3, places=6)
        self.assertAlmostEqual(metrics.recall(cm), 2 / 3, places=6)
        self.assertAlmostEqual(metrics.f1_score(cm), 2 / 3, places=6)

    def test_roc_auc_perfect_and_chance(self):
        # Perfect ranking: all positives score above all negatives -> AUC 1.
        y = [0, 0, 1, 1]
        perfect = [0.1, 0.2, 0.8, 0.9]
        self.assertAlmostEqual(metrics.roc_auc(y, perfect), 1.0, places=6)
        # Reversed ranking -> AUC 0.
        self.assertAlmostEqual(metrics.roc_auc(y, [0.9, 0.8, 0.2, 0.1]), 0.0, places=6)

    def test_roc_auc_handles_ties(self):
        y = [0, 1, 0, 1]
        scores = [0.5, 0.5, 0.5, 0.5]  # all tied -> chance
        self.assertAlmostEqual(metrics.roc_auc(y, scores), 0.5, places=6)

    def test_train_test_split_sizes(self):
        X = list(range(100))
        y = list(range(100))
        Xtr, Xte, ytr, yte = metrics.train_test_split(X, y, test_frac=0.25)
        self.assertEqual(len(Xtr), 75)
        self.assertEqual(len(Xte), 25)
        # No overlap between train and test.
        self.assertEqual(set(Xtr) & set(Xte), set())

    def test_kfold_covers_all_once(self):
        folds = metrics.kfold_indices(20, k=5)
        self.assertEqual(len(folds), 5)
        test_union = set()
        for _, te in folds:
            test_union |= set(te)
        self.assertEqual(test_union, set(range(20)))

    def test_evaluate_classifier_report(self):
        y = [1, 0, 1, 0, 1, 0]
        scores = [0.9, 0.1, 0.8, 0.2, 0.6, 0.3]
        rep = metrics.evaluate_classifier(y, scores).as_dict()
        self.assertEqual(rep['accuracy'], 1.0)
        self.assertEqual(rep['roc_auc'], 1.0)
        self.assertEqual(rep['confusion']['tp'], 3)
