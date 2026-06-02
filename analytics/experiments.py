"""
A/B experiment runtime: deterministic assignment + results with significance.

This is the application layer over analytics/ab_test.py (the pure statistics).
- assign(): hash a visitor into an arm so bucketing is stable, even, and needs
  no coordination — the same visitor always lands in the same arm.
- record_conversion(): mark a visitor's goal completion (idempotent).
- results(): aggregate per-arm counts and run the frequentist + Bayesian tests,
  returning a single dashboard-ready dict.
"""
from __future__ import annotations

import hashlib

from django.utils import timezone

from .models import Experiment, ExperimentAssignment
from . import ab_test


def assign(experiment: Experiment, visitor_key: str) -> int:
    """Deterministically bucket a visitor into arm 0 (control) or 1 (variant).

    We hash "<experiment.key>:<visitor_key>" and use the low bit, so assignment
    is stable across requests, ~50/50 in expectation, and independent between
    experiments (the key salts the hash). Persists the assignment row (once).
    """
    digest = hashlib.sha256(f'{experiment.key}:{visitor_key}'.encode()).hexdigest()
    variant = int(digest, 16) & 1
    ExperimentAssignment.objects.get_or_create(
        experiment=experiment, visitor_key=visitor_key,
        defaults={'variant': variant},
    )
    return variant


def record_conversion(experiment: Experiment, visitor_key: str) -> None:
    """Mark a visitor as converted (idempotent; assigns them first if needed)."""
    obj, _ = ExperimentAssignment.objects.get_or_create(
        experiment=experiment, visitor_key=visitor_key,
        defaults={'variant': assign_variant_only(experiment, visitor_key)},
    )
    if not obj.converted:
        obj.converted = True
        obj.converted_at = timezone.now()
        obj.save(update_fields=['converted', 'converted_at'])


def assign_variant_only(experiment: Experiment, visitor_key: str) -> int:
    """Compute the arm without persisting (used inside record_conversion)."""
    digest = hashlib.sha256(f'{experiment.key}:{visitor_key}'.encode()).hexdigest()
    return int(digest, 16) & 1


def results(experiment: Experiment) -> dict:
    """Per-arm counts + frequentist and Bayesian verdicts for one experiment."""
    qs = experiment.assignments.all()
    n_a = qs.filter(variant=0).count()
    n_b = qs.filter(variant=1).count()
    c_a = qs.filter(variant=0, converted=True).count()
    c_b = qs.filter(variant=1, converted=True).count()

    ztest = ab_test.two_proportion_ztest(c_a, n_a, c_b, n_b)
    bayes = ab_test.bayesian_ab(c_a, n_a, c_b, n_b)
    chi = ab_test.chi_square_2x2(c_a, n_a, c_b, n_b)

    # Relative lift in conversion rate, for plain-language reporting.
    rel_lift = ((ztest.rate_b - ztest.rate_a) / ztest.rate_a) if ztest.rate_a > 0 else 0.0

    return {
        'experiment': experiment,
        'control': {'label': experiment.control_label, 'n': n_a, 'conversions': c_a,
                    'rate': round(ztest.rate_a, 4)},
        'variant': {'label': experiment.variant_label, 'n': n_b, 'conversions': c_b,
                    'rate': round(ztest.rate_b, 4)},
        'abs_diff': round(ztest.diff, 4),
        'rel_lift': round(rel_lift, 4),
        'z': round(ztest.z, 3),
        'p_value': round(ztest.p_value, 4),
        'significant': ztest.significant,
        'ci95': [round(ztest.ci95[0], 4), round(ztest.ci95[1], 4)],
        'chi2': round(chi['chi2'], 3),
        'prob_b_beats_a': round(bayes['prob_b_beats_a'], 4),
        'expected_lift': round(bayes['expected_lift'], 4),
        'enough_data': n_a >= 30 and n_b >= 30,
    }


def all_results() -> list[dict]:
    """Results for every experiment, newest first (for the dashboard)."""
    return [results(exp) for exp in Experiment.objects.all()]
