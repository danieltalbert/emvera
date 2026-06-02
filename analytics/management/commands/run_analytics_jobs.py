"""
Run all periodic analytics jobs in one shot — the single entry point a scheduler
should call. Keeps cron/systemd config to one line and one place.

Runs (in order):
  1. materialize_features  — refresh the cached per-visitor feature snapshots.
  2. check_anomalies       — detect/persist new traffic anomalies + email staff.

Schedule examples:
  # crontab: every day at 06:00
  0 6 * * * cd /app && python manage.py run_analytics_jobs >> /var/log/emvera-analytics.log 2>&1

  # or a systemd timer / Celery beat task calling the same command.

Each sub-job is isolated: a failure in one is reported but doesn't stop the rest.
"""
import time

from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Run all periodic analytics jobs (feature materialization + anomaly check).'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=30)

    def handle(self, *args, **opts):
        days = str(opts['days'])
        jobs = [
            ('materialize_features', ['--days', days]),
            ('check_anomalies', ['--days', days]),
        ]
        overall = time.monotonic()
        for name, job_args in jobs:
            start = time.monotonic()
            self.stdout.write(f'→ {name} ...')
            try:
                call_command(name, *job_args)
                self.stdout.write(self.style.SUCCESS(
                    f'  ✓ {name} ({time.monotonic() - start:.1f}s)'))
            except Exception as exc:  # one job failing must not abort the rest
                self.stderr.write(self.style.ERROR(f'  ✗ {name} failed: {exc}'))
        self.stdout.write(self.style.SUCCESS(
            f'All analytics jobs finished in {time.monotonic() - overall:.1f}s.'))
