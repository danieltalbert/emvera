"""
Detect traffic anomalies, persist new ones, and email staff.

Designed to run on a schedule (e.g. daily cron). It z-scores the daily page-view
series, raises an AnomalyAlert for any day that exceeds the threshold (dedup'd by
date so the same day is never alerted twice), and emails staff a summary of the
NEW alerts. Email uses Django's configured backend — the console backend in dev,
so it works offline.

    python manage.py check_anomalies --days 30 --threshold 2.5
"""
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.db.models import Count
from django.utils import timezone

from analytics.models import PageView, AnomalyAlert
from analytics import ml


class Command(BaseCommand):
    help = 'Detect daily-traffic anomalies, persist new ones, and email staff.'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=30)
        parser.add_argument('--threshold', type=float, default=2.5,
                            help='z-score magnitude to flag (default 2.5).')
        parser.add_argument('--no-email', action='store_true')

    def handle(self, *args, **opts):
        days = opts['days']
        since = (timezone.now() - timedelta(days=days - 1)).date()

        # Build the daily count series with its calendar dates.
        rows = (PageView.objects.filter(timestamp__date__gte=since)
                .values('timestamp__date').annotate(c=Count('id')))
        by_date = {r['timestamp__date']: r['c'] for r in rows}
        dates = [since + timedelta(days=i) for i in range(days)]
        series = [float(by_date.get(d, 0)) for d in dates]

        anomalies = ml.zscore_anomalies(series, threshold=opts['threshold'])
        new_alerts = []
        for a in anomalies:
            alert, created = AnomalyAlert.objects.get_or_create(
                metric='daily_traffic', date=dates[a.index],
                defaults={'value': a.value, 'z_score': a.z, 'direction': a.direction},
            )
            if created:
                new_alerts.append(alert)

        self.stdout.write(
            f'Scanned {days} days: {len(anomalies)} anomalies present, '
            f'{len(new_alerts)} new.'
        )

        if new_alerts and not opts['no_email']:
            self._email_staff(new_alerts)

    def _email_staff(self, alerts):
        User = get_user_model()
        recipients = list(
            User.objects.filter(is_staff=True).exclude(email='').values_list('email', flat=True)
        )
        if not recipients:
            self.stdout.write('No staff emails on file; skipping notification.')
            return
        lines = [f'- {a.direction.upper()} on {a.date}: {a.value:.0f} views (z={a.z_score:.1f})'
                 for a in alerts]
        body = ('Emvera analytics detected new traffic anomalies:\n\n'
                + '\n'.join(lines)
                + '\n\nReview them on the analytics dashboard.')
        try:
            send_mail(
                subject=f'[Emvera] {len(alerts)} new traffic anomaly alert(s)',
                message=body,
                from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'analytics@emvera.local'),
                recipient_list=recipients,
                fail_silently=True,
            )
            self.stdout.write(self.style.SUCCESS(f'Emailed {len(recipients)} staff recipient(s).'))
        except Exception as exc:  # never let alerting crash the job
            self.stdout.write(self.style.WARNING(f'Email failed: {exc}'))
