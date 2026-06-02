"""
Model-evaluation utilities — the "did the model actually learn?" layer.

A classifier is only trustworthy if it's measured honestly: on data it didn't
train on, with metrics that survive class imbalance. This module provides the
standard toolkit, hand-implemented and unit-tested:

- train_test_split        : reproducible hold-out split
- confusion_matrix        : TP / FP / FN / TN counts
- precision/recall/f1     : imbalance-aware metrics derived from the matrix
- accuracy                : overall correctness (reported, but never alone)
- roc_auc                 : threshold-independent ranking quality (Mann-Whitney)
- evaluate_classifier     : one call -> a full, dashboard-ready report
- kfold_indices           : k-fold cross-validation splits

Everything works on plain lists so it composes with analytics/ml.py.
"""
from __future__ import annotations

import random
from dataclasses import dataclass


def train_test_split(X: list, y: list, test_frac: float = 0.25, seed: int = 42):
    """Shuffle (reproducibly) and split into train/test.

    Returns (X_train, X_test, y_train, y_test). A fixed seed keeps results
    stable across dashboard refreshes so the reported scores don't jitter.
    """
    n = len(X)
    idx = list(range(n))
    random.Random(seed).shuffle(idx)
    cut = int(n * (1 - test_frac))
    tr, te = idx[:cut], idx[cut:]
    return ([X[i] for i in tr], [X[i] for i in te],
            [y[i] for i in tr], [y[i] for i in te])


@dataclass
class ConfusionMatrix:
    tp: int = 0
    fp: int = 0
    fn: int = 0
    tn: int = 0

    @property
    def total(self) -> int:
        return self.tp + self.fp + self.fn + self.tn


def confusion_matrix(y_true: list[int], y_pred: list[int]) -> ConfusionMatrix:
    """Tally TP/FP/FN/TN for binary labels (1 = positive class)."""
    cm = ConfusionMatrix()
    for t, p in zip(y_true, y_pred):
        if t == 1 and p == 1:
            cm.tp += 1
        elif t == 0 and p == 1:
            cm.fp += 1
        elif t == 1 and p == 0:
            cm.fn += 1
        else:
            cm.tn += 1
    return cm


def accuracy(cm: ConfusionMatrix) -> float:
    return (cm.tp + cm.tn) / cm.total if cm.total else 0.0


def precision(cm: ConfusionMatrix) -> float:
    """Of those predicted positive, how many were right? TP/(TP+FP)."""
    denom = cm.tp + cm.fp
    return cm.tp / denom if denom else 0.0


def recall(cm: ConfusionMatrix) -> float:
    """Of the actual positives, how many did we catch? TP/(TP+FN)."""
    denom = cm.tp + cm.fn
    return cm.tp / denom if denom else 0.0


def f1_score(cm: ConfusionMatrix) -> float:
    """Harmonic mean of precision and recall — punishes lopsided models."""
    p, r = precision(cm), recall(cm)
    return 2 * p * r / (p + r) if (p + r) else 0.0


def roc_auc(y_true: list[int], scores: list[float]) -> float:
    """ROC-AUC via the Mann-Whitney U identity.

    AUC = P(score(random positive) > score(random negative)). Equivalently, the
    normalized rank-sum of the positive class. This is threshold-independent —
    it measures how well the model *ranks* positives above negatives — and is
    robust to class imbalance. Returns 0.5 (chance) when one class is absent.
    """
    pos = [s for s, t in zip(scores, y_true) if t == 1]
    neg = [s for s, t in zip(scores, y_true) if t == 0]
    if not pos or not neg:
        return 0.5
    # Rank all scores (average ranks for ties), then use the rank-sum formula.
    paired = sorted(zip(scores, range(len(scores))), key=lambda p: p[0])
    ranks = [0.0] * len(scores)
    i = 0
    while i < len(paired):
        j = i
        while j + 1 < len(paired) and paired[j + 1][0] == paired[i][0]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0  # ranks are 1-based
        for k in range(i, j + 1):
            ranks[paired[k][1]] = avg_rank
        i = j + 1
    sum_ranks_pos = sum(r for r, t in zip(ranks, y_true) if t == 1)
    n_pos, n_neg = len(pos), len(neg)
    u = sum_ranks_pos - n_pos * (n_pos + 1) / 2.0
    return u / (n_pos * n_neg)


@dataclass
class ClassifierReport:
    accuracy: float
    precision: float
    recall: float
    f1: float
    roc_auc: float
    confusion: ConfusionMatrix
    n_test: int
    positive_rate: float  # base rate of the positive class in the test set

    def as_dict(self) -> dict:
        """Flatten for templates/JSON (percentages where it reads naturally)."""
        return {
            'accuracy': round(self.accuracy, 3),
            'precision': round(self.precision, 3),
            'recall': round(self.recall, 3),
            'f1': round(self.f1, 3),
            'roc_auc': round(self.roc_auc, 3),
            'n_test': self.n_test,
            'positive_rate': round(self.positive_rate, 3),
            'confusion': {'tp': self.confusion.tp, 'fp': self.confusion.fp,
                          'fn': self.confusion.fn, 'tn': self.confusion.tn},
        }


def evaluate_classifier(y_true: list[int], scores: list[float],
                        threshold: float = 0.5) -> ClassifierReport:
    """Turn predicted probabilities + true labels into a full report."""
    y_pred = [1 if s >= threshold else 0 for s in scores]
    cm = confusion_matrix(y_true, y_pred)
    n = len(y_true)
    pos_rate = sum(y_true) / n if n else 0.0
    return ClassifierReport(
        accuracy=accuracy(cm), precision=precision(cm), recall=recall(cm),
        f1=f1_score(cm), roc_auc=roc_auc(y_true, scores), confusion=cm,
        n_test=n, positive_rate=pos_rate,
    )


def kfold_indices(n: int, k: int = 5, seed: int = 42) -> list[tuple[list[int], list[int]]]:
    """Yield (train_idx, test_idx) for k-fold cross-validation.

    Cross-validation gives a less luck-dependent estimate of generalization
    than a single split: each fold is held out once while the rest train.
    """
    idx = list(range(n))
    random.Random(seed).shuffle(idx)
    folds = [idx[i::k] for i in range(k)]  # round-robin assignment
    out = []
    for i in range(k):
        test = folds[i]
        train = [j for f in range(k) if f != i for j in folds[f]]
        if test and train:
            out.append((train, test))
    return out
