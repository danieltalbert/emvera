"""
Seed synthetic PageView data so the analytics dashboard and its ML have
something realistic to chew on before the site has real traffic.

The generator bakes in patterns the ML should then *discover*:
- a gentle upward weekly trend (linear regression should report 'up'),
- diurnal + weekday rhythm (heatmap should light up daytime/weekdays),
- one planted spike day (z-score anomaly detection should flag it),
- three visitor archetypes (k-means should separate roughly 3 segments).

Usage:
    python manage.py seed_analytics --days 30 --visitors 60
    python manage.py seed_analytics --clear      # wipe seeded data first
"""
import hashlib
import random
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from analytics.models import PageView

SECTIONS = [
    ('Investments', ['/investments/', '/investments/performance/', '/investments/projections/']),
    ('Debt Management', ['/debt-management/dashboard/', '/debt-management/payoff/avalanche/']),
    ('Competition', ['/competition/', '/competition/create/']),
    ('Paper Trading', ['/paper-trading/']),
    ('Data & Accounts', ['/data/connect-plaid/', '/data/csv-upload/']),
    ('Account', ['/accounts/profile/']),
]


def _hash(s: str) -> str:
    return hashlib.sha256(f'{settings.SECRET_KEY}:{s}'.encode()).hexdigest()


class Command(BaseCommand):
    help = 'Generate synthetic page-view data for the analytics dashboard.'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=30)
        parser.add_argument('--visitors', type=int, default=60)
        parser.add_argument('--clear', action='store_true',
                            help='Delete all existing PageView rows first.')

    def handle(self, *args, **opts):
        rng = random.Random(7)
        if opts['clear']:
            n, _ = PageView.objects.all().delete()
            self.stdout.write(self.style.WARNING(f'Cleared {n} existing rows.'))

        days = opts['days']
        n_visitors = opts['visitors']
        now = timezone.now()

        # Four archetypes. The first three drive k-means segmentation; the
        # 'churning' archetype gives the churn model a *learnable behavioral*
        # signal — they engage shallowly (few sections, few views) AND only in
        # the first ~40% of the window, then go silent. So low engagement
        # genuinely predicts going quiet (not via recency, which the model
        # excludes to avoid leakage).
        #   power:    many views, many sections, most days, throughout
        #   regular:  moderate, throughout
        #   casual:   light, throughout
        #   churning: light + narrow, active only early in the window
        archetypes = (
            ['power'] * max(1, n_visitors // 10) +
            ['regular'] * max(1, n_visitors // 3) +
            ['churning'] * max(1, n_visitors // 4) +
            ['casual'] * n_visitors
        )[:n_visitors]
        rng.shuffle(archetypes)
        visitors = [(_hash(f'seed-visitor-{i}'), archetypes[i]) for i in range(n_visitors)]

        spike_day = rng.randint(days // 3, days - 3)  # plant one anomaly
        # Churners stop showing up after this fraction of the window.
        churn_cutoff_day = int(days * 0.4)
        bulk = []

        for d in range(days):
            day = now - timedelta(days=(days - 1 - d))
            weekday = day.weekday()
            # Weekly trend (rises over the window) + weekend dip.
            trend = 1.0 + 0.04 * d
            weekend = 0.55 if weekday >= 5 else 1.0
            spike = 3.2 if d == spike_day else 1.0
            day_intensity = trend * weekend * spike

            for vhash, kind in visitors:
                # Churners only appear early in the window, then vanish.
                if kind == 'churning' and d > churn_cutoff_day:
                    continue
                base = {'power': 14, 'regular': 5, 'casual': 1.2, 'churning': 1.5}[kind]
                # Probability this visitor is active on a day they *could* be.
                p_active = {'power': 0.92, 'regular': 0.5, 'casual': 0.18, 'churning': 0.35}[kind]
                if rng.random() > p_active:
                    continue
                n_views = max(1, int(rng.gauss(base, base * 0.4) * day_intensity))
                n_views = min(n_views, 60)
                # Which sections this visitor touches (churners stay narrow).
                n_sec = {'power': 5, 'regular': 3, 'casual': 1, 'churning': 1}[kind]
                visitor_sections = rng.sample(SECTIONS, min(n_sec, len(SECTIONS)))

                for _ in range(n_views):
                    sec_name, paths = rng.choice(visitor_sections)
                    path = rng.choice(paths)
                    # Diurnal hour distribution peaking ~13:00–20:00 UTC.
                    hour = int(min(23, max(0, rng.gauss(15, 4))))
                    ts = day.replace(hour=hour, minute=rng.randint(0, 59),
                                     second=rng.randint(0, 59), microsecond=0)
                    bulk.append(PageView(
                        user=None, session_hash=vhash, path=path, section=sec_name,
                        method='GET', status_code=200,
                        response_ms=int(abs(rng.gauss(35, 15))) + 5,
                        is_authenticated=(kind == 'power'),
                        timestamp=ts, hour=hour, weekday=ts.weekday(),
                    ))

        PageView.objects.bulk_create(bulk, batch_size=1000)
        self.stdout.write(self.style.SUCCESS(
            f'Seeded {len(bulk)} page views across {days} days and {n_visitors} visitors '
            f'(spike planted on day index {spike_day}).'
        ))

        self._seed_experiment(rng)

    def _seed_experiment(self, rng):
        """Seed one demo A/B experiment with a genuine, detectable effect so the
        dashboard's significance tests have something real to report."""
        from analytics.models import Experiment, ExperimentAssignment
        exp, created = Experiment.objects.get_or_create(
            key='onboarding-cta',
            defaults={
                'name': 'Onboarding CTA wording',
                'description': 'Does "Start investing" convert better than "Get started"?',
                'control_label': 'A · "Get started"',
                'variant_label': 'B · "Start investing"',
            },
        )
        if not created and exp.assignments.exists():
            self.stdout.write('Demo experiment already seeded; skipping.')
            return
        # Control converts ~12%, variant ~17% — a real lift the z-test should catch.
        rows = []
        for i in range(300):
            rows.append(ExperimentAssignment(experiment=exp, visitor_key=f'exp-a-{i}',
                                             variant=0, converted=(rng.random() < 0.12)))
        for i in range(300):
            rows.append(ExperimentAssignment(experiment=exp, visitor_key=f'exp-b-{i}',
                                             variant=1, converted=(rng.random() < 0.17)))
        ExperimentAssignment.objects.bulk_create(rows, batch_size=500)
        self.stdout.write(self.style.SUCCESS(
            f'Seeded demo experiment "{exp.name}" with {len(rows)} assignments.'
        ))
