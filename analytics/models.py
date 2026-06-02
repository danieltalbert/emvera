"""
Analytics models.

A single lightweight event table, `PageView`, records each viewer-facing page
hit (written by analytics.middleware.PageViewMiddleware). It is intentionally
denormalized and cheap to write so logging never slows a request, and it
carries exactly the dimensions the ML/insights layer needs:

- which page (path + a friendly section label),
- who (user FK when authenticated; a hashed session key otherwise, so we can
  count distinct anonymous visitors without storing anything identifying),
- when (timestamp, plus pre-extracted hour/weekday for fast grouping),
- how the response went (status code, render time in ms).

Everything downstream (trends, forecasts, anomalies, segments) is computed from
this one table — see analytics/ml.py and analytics/insights.py.
"""
from django.conf import settings
from django.db import models


class PageView(models.Model):
    # Null for anonymous visitors; we still get a stable per-session id below.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='page_views',
    )
    # Hashed session key — lets us count distinct anonymous visitors and build
    # per-visitor features for clustering WITHOUT storing the raw session id.
    session_hash = models.CharField(max_length=64, blank=True, db_index=True)

    path = models.CharField(max_length=255, db_index=True)
    # Friendly grouping (e.g. "Investments", "Paper Trading") resolved from the
    # URL namespace at write time, so dashboards don't have to parse paths.
    section = models.CharField(max_length=64, blank=True, db_index=True)

    method = models.CharField(max_length=8, default='GET')
    status_code = models.PositiveSmallIntegerField(default=200)
    response_ms = models.PositiveIntegerField(default=0)

    is_authenticated = models.BooleanField(default=False)

    # Denormalized time parts — extracted once at write time so grouping by
    # hour-of-day / day-of-week is a cheap GROUP BY rather than per-row work.
    timestamp = models.DateTimeField(db_index=True)
    hour = models.PositiveSmallIntegerField(default=0)        # 0-23 (UTC)
    weekday = models.PositiveSmallIntegerField(default=0)     # 0=Mon … 6=Sun

    class Meta:
        app_label = 'analytics'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['timestamp', 'section']),
            models.Index(fields=['section', 'timestamp']),
        ]

    def __str__(self):
        who = self.user_id or (self.session_hash[:8] + '…' if self.session_hash else 'anon')
        return f'{self.path} [{who}] @ {self.timestamp:%Y-%m-%d %H:%M}'
