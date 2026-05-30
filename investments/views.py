"""Views for the investments app: portfolio overview/performance, projections,
recommendations, comparison, and CSV export.

Performance note: several pages need each investment's projections. Rather than
querying projections once per investment (an N+1 pattern), the helpers below
load them in a single `select_related` query and group them in memory.
"""
import csv
from collections import defaultdict

from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render

from accounts.require_2fa import require_2fa
from data_integration.models import Account, Investment
from .models import InvestmentProjection, InvestmentRecommendation


def _user_investments(user):
    accounts = Account.objects.filter(user=user, type='investment')
    return Investment.objects.filter(account__in=accounts)


def _projections_by_investment(user, investments):
    """Return {investment_id: [InvestmentProjection, ...]} in one query.

    `select_related('investment')` means `projection.annualized_return()` can
    read `projection.investment` without an extra query per row.
    """
    grouped = defaultdict(list)
    qs = (
        InvestmentProjection.objects
        .filter(user=user, investment__in=investments)
        .select_related('investment')
    )
    for proj in qs:
        grouped[proj.investment_id].append(proj)
    return grouped


@login_required
@require_2fa
def export_investments_csv(request):
    investments = list(_user_investments(request.user))
    projections_by_inv = _projections_by_investment(request.user, investments)
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="investments.csv"'
    writer = csv.writer(response)
    writer.writerow(['Name', 'Type', 'Current Value', 'As Of', 'Projections'])
    for inv in investments:
        proj_str = "; ".join([
            f"{p.projection_date}: ${p.projected_value:,.2f} ({p.growth_rate:.2f}%)"
            for p in projections_by_inv.get(inv.id, [])
        ])
        writer.writerow([inv.name, inv.type, inv.value, inv.as_of, proj_str])
    return response


@login_required
@require_2fa
def portfolio_performance(request):
    investments = _user_investments(request.user)
    projections = InvestmentProjection.objects.filter(
        user=request.user, investment__in=investments
    )
    total_invested = investments.aggregate(total=Sum('value'))['total'] or 0
    total_projected = projections.aggregate(total=Sum('projected_value'))['total'] or 0
    roi = None
    if total_invested and total_projected:
        roi = ((float(total_projected) / float(total_invested)) - 1) * 100
    projections_by_inv = _projections_by_investment(request.user, investments)
    investment_returns = []
    for inv in investments:
        returns = [p.annualized_return() for p in projections_by_inv.get(inv.id, [])]
        investment_returns.append({'investment': inv, 'returns': returns})
    context = {
        'total_invested': total_invested,
        'total_projected': total_projected,
        'roi': roi,
        'investment_returns': investment_returns,
    }
    return render(request, 'investments/portfolio_performance.html', context)


@login_required
@require_2fa
def portfolio_overview(request):
    investments = _user_investments(request.user).order_by('-as_of')
    return render(request, 'investments/portfolio_overview.html', {'investments': investments})


@login_required
@require_2fa
def investment_growth_chart(request):
    investments = _user_investments(request.user)
    growth = (
        investments.values('as_of')
        .annotate(total_value=Sum('value'))
        .order_by('as_of')
    )
    return JsonResponse(list(growth), safe=False)


@login_required
@require_2fa
def investment_projections(request):
    investments = _user_investments(request.user)
    projections = InvestmentProjection.objects.filter(
        user=request.user, investment__in=investments
    )
    return render(request, 'investments/investment_projections.html', {'projections': projections})


@login_required
@require_2fa
def investment_recommendations(request):
    investments = _user_investments(request.user)
    recommendations = InvestmentRecommendation.objects.filter(
        user=request.user, investment__in=investments
    )
    return render(request, 'investments/investment_recommendations.html', {'recommendations': recommendations})


@login_required
@require_2fa
def investment_comparison(request):
    investments = _user_investments(request.user)
    comparison = (
        investments.values('type')
        .annotate(total_value=Sum('value'))
        .order_by('-total_value')
    )
    projections_by_inv = _projections_by_investment(request.user, investments)
    type_returns = {}
    for inv in investments:
        # Compute each annualized return once, then drop the Nones.
        returns = [
            r for r in (p.annualized_return() for p in projections_by_inv.get(inv.id, []))
            if r is not None
        ]
        if returns:
            avg_return = sum(returns) / len(returns)
            type_returns[inv.type] = max(type_returns.get(inv.type, float('-inf')), avg_return)
    top_type = max(type_returns, key=type_returns.get) if type_returns else None
    return render(request, 'investments/investment_comparison.html', {
        'comparison': comparison,
        'top_type': top_type,
    })
