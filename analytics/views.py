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
from .models import PageView


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
        'traffic': insights.daily_traffic(days),
        'top_pages': insights.top_pages(days),
        'sections': insights.section_breakdown(days),
        'heatmap': insights.hourly_heatmap(days),
        'peak': insights.peak_activity(days),
        'segments': insights.user_segments(days),
        # Behavioral / predictive insights (product_analytics.py)
        'sessions': pa.sessionize(days),
        'funnel': pa.funnel(days),
        'cohorts': pa.cohort_retention(min(8, max(2, days // 7 + 1))),
        'churn': pa.churn_model(days),
        'paths': pa.transition_matrix(days),
        # A/B experiments + the feature catalog (self-documentation).
        'experiments': exp_runtime.all_results(),
        'feature_catalog': features.feature_catalog(),
    }
    return render(request, 'analytics/dashboard.html', context)
