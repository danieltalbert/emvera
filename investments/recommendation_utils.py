from data_integration.models import Investment, Account, Debt
from .models import InvestmentRecommendation
from django.db.models import Sum

def generate_recommendations(user, target_allocation=None, annual_goal=None, projections=None):
    """
    Generate investment recommendations for the user.
    - Rebalance: if any single asset > 40% of portfolio
    - Increase contribution: if projected value < target
    Returns a list of InvestmentRecommendation objects (not saved).
    """
    recs = []
    accounts = Account.objects.filter(user=user, type='investment')
    investments = Investment.objects.filter(account__in=accounts)
    total_value = investments.aggregate(Sum('value'))['value__sum'] or 0
    # Rebalance recommendation
    allocs = investments.values('type').annotate(total=Sum('value'))
    for row in allocs:
        pct = (row['total'] / total_value) * 100 if total_value else 0
        if pct > 40:
            message = f"{row['type'].capitalize()} makes up {pct:.1f}% of your portfolio. Consider rebalancing."
            recs.append(InvestmentRecommendation(
                user=user,
                investment=None,
                recommendation_type="rebalance",
                message=message
            ))
    # Increase contribution recommendation
    if projections and annual_goal:
        for proj in projections:
            if proj.projected_value < annual_goal:
                message = f"Projected value ${proj.projected_value:,.2f} is below your target of ${annual_goal:,.2f}. Consider increasing contributions."
                recs.append(InvestmentRecommendation(
                    user=user,
                    investment=proj.investment,
                    recommendation_type="increase_contribution",
                    message=message
                ))
    # Emergency fund recommendation
    savings_accounts = Account.objects.filter(user=user, type='savings')
    total_debt = Debt.objects.filter(account__user=user).aggregate(Sum('balance'))['balance__sum'] or 0
    if not savings_accounts.exists() and total_debt > 0:
        message = "You have outstanding debt but no savings account. Consider building an emergency fund before investing further."
        recs.append(InvestmentRecommendation(
            user=user,
            investment=None,
            recommendation_type="emergency_fund",
            message=message
        ))

    # Tax-advantaged account recommendation
    tax_adv_types = ['401k', 'IRA', 'Roth IRA']
    has_tax_adv = investments.filter(type__in=tax_adv_types).exists()
    if not has_tax_adv:
        message = "You do not have any tax-advantaged retirement accounts (401k, IRA, Roth IRA). Consider opening one to maximize your investment returns."
        recs.append(InvestmentRecommendation(
            user=user,
            investment=None,
            recommendation_type="tax_advantaged",
            message=message
        ))
    return recs
