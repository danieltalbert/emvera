import csv

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.require_2fa import require_2fa
from data_integration.models import Account, Investment
from .models import InvestmentProjection, InvestmentRecommendation
from .recommendation_utils import generate_recommendations


def _user_investments(user):
    accounts = Account.objects.filter(user=user, type='investment')
    return Investment.objects.filter(account__in=accounts)


@login_required
@require_2fa
def export_investments_csv(request):
    investments = _user_investments(request.user)
    projections = InvestmentProjection.objects.filter(
        user=request.user, investment__in=investments
    )
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="investments.csv"'
    writer = csv.writer(response)
    writer.writerow(['Name', 'Type', 'Current Value', 'As Of', 'Projections'])
    for inv in investments:
        inv_projs = projections.filter(investment=inv)
        proj_str = "; ".join([
            f"{p.projection_date}: ${p.projected_value:,.2f} ({p.growth_rate:.2f}%)"
            for p in inv_projs
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
    investment_returns = []
    for inv in investments:
        inv_projs = projections.filter(investment=inv)
        returns = [p.annualized_return() for p in inv_projs if hasattr(p, 'annualized_return')]
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
    recommendations = list(InvestmentRecommendation.objects.filter(
        user=request.user, investment__in=investments
    ))

    if investments.exists():
        seen = {
            (rec.recommendation_type, rec.message, rec.investment_id)
            for rec in recommendations
        }
        for rec in generate_recommendations(request.user):
            key = (rec.recommendation_type, rec.message, rec.investment_id)
            if key not in seen:
                recommendations.append(rec)
                seen.add(key)

    total_recommendation_count = len(recommendations)
    new_recommendation_count = sum(1 for rec in recommendations if not rec.reviewed)

    return render(request, 'investments/investment_recommendations.html', {
        'recommendations': recommendations,
        'total_recommendation_count': total_recommendation_count,
        'new_recommendation_count': new_recommendation_count,
        'reviewed_recommendation_count': total_recommendation_count - new_recommendation_count,
    })


@login_required
@require_2fa
@require_POST
def mark_recommendation_reviewed(request, pk):
    investments = _user_investments(request.user)
    recommendation = get_object_or_404(
        InvestmentRecommendation,
        pk=pk,
        user=request.user,
        investment__in=investments,
    )
    if recommendation.reviewed:
        messages.info(request, 'Recommendation was already reviewed.')
    else:
        recommendation.reviewed = True
        recommendation.save(update_fields=['reviewed'])
        messages.success(request, 'Recommendation marked reviewed.')
    return redirect('investments:investment_recommendations')


@login_required
@require_2fa
def investment_comparison(request):
    investments = _user_investments(request.user)
    comparison = (
        investments.values('type')
        .annotate(total_value=Sum('value'))
        .order_by('-total_value')
    )
    projections = InvestmentProjection.objects.filter(
        user=request.user, investment__in=investments
    )
    type_returns = {}
    for inv in investments:
        inv_projs = projections.filter(investment=inv)
        returns = [
            p.annualized_return() for p in inv_projs
            if hasattr(p, 'annualized_return') and p.annualized_return() is not None
        ]
        if returns:
            avg_return = sum(returns) / len(returns)
            type_returns[inv.type] = max(type_returns.get(inv.type, float('-inf')), avg_return)
    top_type = max(type_returns, key=type_returns.get) if type_returns else None
    return render(request, 'investments/investment_comparison.html', {
        'comparison': comparison,
        'top_type': top_type,
    })
