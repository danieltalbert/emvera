"""
Analytics dashboard view — STAFF ONLY.

Assembles the insights layer (analytics/insights.py) into one context and
renders the dashboard. The `@staff_member_required` gate means only users with
is_staff=True (you / admins) can see user-activity statistics; regular users
never reach it. A `?days=` query param (7/30/90) sets the look-back window.
"""
import json

from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from . import insights
from . import product_analytics as pa
from . import experiments as exp_runtime
from . import features
from . import reporting
from . import conversion
from . import health
from django.contrib import messages
from django.shortcuts import redirect, get_object_or_404
from django.utils import timezone

from .models import PageView, AnomalyAlert


# Cap dwell at 30 minutes — a longer "visible" time almost always means a
# backgrounded/abandoned tab rather than genuine reading.
MAX_DWELL_MS = 30 * 60 * 1000


@csrf_exempt
@require_POST
def beacon(request):
    """Receive a time-on-page beacon and attach dwell time to its PageView.

    Called via navigator.sendBeacon() when the user leaves a page, so it must be
    CSRF-exempt (beacons can't carry the CSRF cookie/header reliably) and ultra-
    cheap. We authenticate implicitly by the unguessable per-view token rather
    than by session, and clamp the reported time. Returns 204 regardless so the
    browser never retries telemetry.
    """
    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
        token = str(payload.get('token', ''))[:32]
        dwell = int(payload.get('dwell_ms', 0))
    except (ValueError, TypeError, UnicodeDecodeError):
        return HttpResponseBadRequest('bad payload')
    if token and 0 < dwell <= MAX_DWELL_MS:
        # update() keeps it to a single cheap UPDATE; matches at most one row.
        PageView.objects.filter(view_token=token).update(dwell_ms=dwell)
    return HttpResponse(status=204)


ALLOWED_WINDOWS = (7, 30, 90)


@staff_member_required
def dashboard(request):
    try:
        days = int(request.GET.get('days', 30))
    except (TypeError, ValueError):
        days = 30
    if days not in ALLOWED_WINDOWS:
        days = 30

    context = {
        'days': days,
        'windows': ALLOWED_WINDOWS,
        # Descriptive insights (insights.py)
        'kpis': insights.kpis(days),
        'live': insights.live_activity(30),
        'traffic': insights.daily_traffic(days),
        'weekly_pattern': insights.weekly_pattern(days),
        'stickiness': insights.stickiness(),
        'retention_curve': insights.retention_curve(days),
        'performance': insights.performance(days),
        'top_pages': insights.top_pages(days),
        'sections': insights.section_breakdown(days),
        'heatmap': insights.hourly_heatmap(days),
        'peak': insights.peak_activity(days),
        'segments': insights.user_segments(days),
        # Behavioral / predictive insights (product_analytics.py)
        'sessions': pa.sessionize(days),
        'funnel': pa.funnel(days),
        'funnel_by_segment': pa.funnel_by_segment(days),
        'cohorts': pa.cohort_retention(min(8, max(2, days // 7 + 1))),
        'churn': pa.churn_model(days),
        'conversion': conversion.conversion_model(days),
        'health': health.engagement_health(days),
        'paths': pa.transition_matrix(days),
        # A/B experiments + the feature catalog (self-documentation).
        'experiments': exp_runtime.all_results(),
        'feature_catalog': features.feature_catalog(),
        # Persisted anomaly alerts (unacknowledged first).
        'alerts': AnomalyAlert.objects.order_by('acknowledged', '-date')[:10],
        'open_alert_count': AnomalyAlert.objects.filter(acknowledged=False).count(),
        'pdf_available': reporting.pdf_available(),
    }
    return render(request, 'analytics/dashboard.html', context)


@staff_member_required
def export_csv(request):
    """Download the analytics report as CSV (native; always available)."""
    days = _window(request)
    resp = HttpResponse(reporting.report_csv(days), content_type='text/csv')
    resp['Content-Disposition'] = f'attachment; filename="emvera-analytics-{days}d.csv"'
    return resp


@staff_member_required
def export_pdf(request):
    """Download the report as PDF when reportlab is installed; else explain how."""
    days = _window(request)
    if not reporting.pdf_available():
        messages.info(request, 'PDF export needs reportlab — run `pip install reportlab`. '
                               'CSV export works without it.')
        return redirect(f'{request.path.rsplit("/", 2)[0]}/?days={days}')
    resp = HttpResponse(reporting.build_pdf(days), content_type='application/pdf')
    resp['Content-Disposition'] = f'attachment; filename="emvera-analytics-{days}d.pdf"'
    return resp


@staff_member_required
def api_live(request):
    """Staff-only JSON for the auto-refreshing live-activity panel."""
    from django.http import JsonResponse
    try:
        minutes = int(request.GET.get('minutes', 30))
    except (TypeError, ValueError):
        minutes = 30
    minutes = min(max(minutes, 1), 240)
    return JsonResponse(insights.live_activity(minutes))


@staff_member_required
def api_metrics(request):
    """Staff-only JSON snapshot of headline metrics — for external dashboards,
    monitoring, or Slack bots. Mirrors the dashboard's key numbers in a compact,
    machine-readable shape. ?days=7|30|90."""
    from django.http import JsonResponse
    days = _window(request)
    k = insights.kpis(days)
    t = insights.daily_traffic(days)
    churn = pa.churn_model(days)
    return JsonResponse({
        'window_days': days,
        'generated_at': timezone.now().isoformat(),
        'kpis': k,
        'trend': {
            'direction': t['trend_direction'], 'per_day': t['trend_per_day'],
            'r_squared': t['r_squared'], 'seasonal_adjusted': t['seasonal_adjusted'],
        },
        'forecast_next7': t['forecast'],
        'open_anomaly_alerts': AnomalyAlert.objects.filter(acknowledged=False).count(),
        'churn': {
            'available': churn.get('available', False),
            'rate': churn.get('churn_rate'),
            'roc_auc': churn['report']['roc_auc'] if churn.get('available') else None,
        },
        'experiments': [
            {'name': e['experiment'].name, 'significant': e['significant'],
             'p_value': e['p_value'], 'prob_b_beats_a': e['prob_b_beats_a']}
            for e in exp_runtime.all_results()
        ],
    })


def _window(request) -> int:
    try:
        d = int(request.GET.get('days', 30))
    except (TypeError, ValueError):
        d = 30
    return d if d in ALLOWED_WINDOWS else 30


@staff_member_required
def experiment_detail(request, key):
    """Single-experiment detail with the sequential-testing guardrail."""
    from .models import Experiment
    experiment = get_object_or_404(Experiment, key=key)
    return render(request, 'analytics/experiment_detail.html', {
        'r': exp_runtime.experiment_detail(experiment),
    })


@staff_member_required
@require_POST
def acknowledge_alert(request, pk):
    """Mark an anomaly alert as handled (staff only)."""
    alert = get_object_or_404(AnomalyAlert, pk=pk)
    if not alert.acknowledged:
        alert.acknowledged = True
        alert.acknowledged_at = timezone.now()
        alert.save(update_fields=['acknowledged', 'acknowledged_at'])
    return redirect(request.META.get('HTTP_REFERER') or 'analytics:dashboard')
