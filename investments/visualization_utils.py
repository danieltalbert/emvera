from datetime import date

from django.db import models

from data_integration.models import Account, Investment


def project_investment_growth(current_value, annual_rate, years):
    return float(current_value * ((1 + annual_rate) ** years))


def get_portfolio_growth_data(user, years=5, annual_rate=0.07):
    accounts = Account.objects.filter(user=user, type='investment')
    investments = Investment.objects.filter(account__in=accounts)
    total_now = investments.aggregate(total=models.Sum('value'))['total'] or 0
    today = date.today()
    labels = []
    values = []
    for y in range(years + 1):
        future_date = today.replace(year=today.year + y)
        projected = project_investment_growth(total_now, annual_rate, y)
        labels.append(future_date.strftime('%Y-%m-%d'))
        values.append(round(projected, 2))
    return {'labels': labels, 'values': values}


def get_allocation_data(user):
    accounts = Account.objects.filter(user=user, type='investment')
    investments = Investment.objects.filter(account__in=accounts)
    by_type = investments.values('type').annotate(total=models.Sum('value')).order_by('-total')
    labels = [row['type'].capitalize() for row in by_type]
    values = [float(row['total']) for row in by_type]
    return {'labels': labels, 'values': values}
