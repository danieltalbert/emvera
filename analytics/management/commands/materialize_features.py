"""
Materialize the per-visitor feature matrix into the VisitorFeatures table.

This is the "store" half of the feature store: instead of recomputing features
on every dashboard load, run this on a schedule (cron / Celery beat) so reads
are cheap and features are point-in-time consistent.

    python manage.py materialize_features --days 30
"""
from django.core.management.base import BaseCommand

from analytics import features


class Command(BaseCommand):
    help = 'Snapshot per-visitor features into the VisitorFeatures table.'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=30)

    def handle(self, *args, **opts):
        n = features.materialize(days=opts['days'])
        self.stdout.write(self.style.SUCCESS(
            f'Materialized features for {n} visitor(s) over a {opts["days"]}-day window.'
        ))
