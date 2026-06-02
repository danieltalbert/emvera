"""
Analytics dashboard view — STAFF ONLY.

Assembles the insights layer (analytics/insights.py) into one context and
renders the dashboard. The `@staff_member_required` gate means only users with
is_staff=True (you / admins) can see user-activity statistics; regular users
never reach it. A `?days=` query param (7/30/90) sets the look-back window.
"""
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render

from . import insights
from . import product_analytics as pa


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
    }
    return render(request, 'analytics/dashboard.html', context)
