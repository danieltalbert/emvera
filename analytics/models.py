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

    # Time-on-page (dwell), filled in asynchronously by a client beacon. The
    # token is minted per request and embedded in the page; the browser beacons
    # it back with elapsed visible time when the user leaves. 0 = no beacon yet.
    view_token = models.CharField(max_length=32, blank=True, db_index=True)
    dwell_ms = models.PositiveIntegerField(default=0)

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


class VisitorFeatures(models.Model):
    """Materialized per-visitor feature snapshot (the 'store' in feature store).

    Written by analytics.features.materialize() / the materialize_features
    command. Lets the dashboard read cached features and supports point-in-time
    / audit use instead of recomputing the matrix on every request. The feature
    values live in a JSON blob so adding a feature to FEATURE_REGISTRY needs no
    schema migration.
    """
    class Meta:
        app_label = 'analytics'
        ordering = ['-computed_at']

    visitor_key = models.CharField(max_length=80, unique=True, db_index=True)
    features = models.JSONField(default=dict)
    recency_days = models.PositiveIntegerField(default=0)
    window_days = models.PositiveSmallIntegerField(default=30)
    computed_at = models.DateTimeField(db_index=True)

    def __str__(self):
        return f'features[{self.visitor_key}] @ {self.computed_at:%Y-%m-%d %H:%M}'


class Experiment(models.Model):
    """A two-arm A/B experiment (control vs. variant).

    Visitors are deterministically hashed into an arm (see analytics.experiments
    .assign), so assignment is stable and roughly 50/50 without storing a row
    until a conversion or exposure is recorded. Results + significance are
    computed by analytics.experiments.results using analytics.ab_test.
    """
    STATUS_RUNNING = 'running'
    STATUS_STOPPED = 'stopped'
    STATUS_CHOICES = [(STATUS_RUNNING, 'Running'), (STATUS_STOPPED, 'Stopped')]

    class Meta:
        app_label = 'analytics'
        ordering = ['-created_at']

    key = models.SlugField(max_length=60, unique=True, help_text='Stable id used for hashing.')
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    control_label = models.CharField(max_length=40, default='A (control)')
    variant_label = models.CharField(max_length=40, default='B (variant)')
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_RUNNING)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.name} [{self.status}]'


class ExperimentAssignment(models.Model):
    """One visitor's membership in an experiment arm, plus whether they converted.

    `variant` is 0 (control) or 1 (variant). `converted` flips to True the first
    time the visitor completes the experiment's goal. Unique per (experiment,
    visitor) so a visitor is counted once per arm.
    """
    class Meta:
        app_label = 'analytics'
        unique_together = ('experiment', 'visitor_key')
        indexes = [models.Index(fields=['experiment', 'variant'])]

    experiment = models.ForeignKey(Experiment, on_delete=models.CASCADE, related_name='assignments')
    visitor_key = models.CharField(max_length=80, db_index=True)
    variant = models.PositiveSmallIntegerField(default=0)  # 0 = control, 1 = variant
    converted = models.BooleanField(default=False)
    assigned_at = models.DateTimeField(auto_now_add=True)
    converted_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        arm = 'B' if self.variant else 'A'
        return f'{self.experiment.key}:{arm} {self.visitor_key[:8]} conv={self.converted}'
