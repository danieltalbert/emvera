"""
Chart-data helpers for the investments app.

These build the plain {labels, values} payloads the front-end charts consume.
They are deliberately simple compound-growth projections (no Monte Carlo /
market data) so they work offline; live valuation lives in
data_integration/pricing.py once Alpaca is configured.
"""
from datetime import date
from data_integration.models import Investment, Account
from django.db import models


def project_investment_growth(current_value, annual_rate, years):
    """Compound `current_value` forward `years` years at a flat `annual_rate`."""
    return float(current_value * ((1 + annual_rate) ** years))


def get_portfolio_growth_data(user, years=5, annual_rate=0.07):
    """Year-by-year projected portfolio value for the next `years` years.

    Returns {"labels": [ISO dates], "values": [floats]} suitable for a line
    chart. The current portfolio total is the sum of the user's investment
    holdings; each future year compounds it at `annual_rate`.
    """
    accounts = Account.objects.filter(user=user, type='investment')
    investments = Investment.objects.filter(account__in=accounts)
    total_now = investments.aggregate(total=models.Sum('value'))['total'] or 0
    today = date.today()
    labels = []
    values = []
    for y in range(years + 1):
        # Use the same month/day one year at a time, guarding Feb 29 (which has
        # no counterpart in non-leap years) by falling back to Feb 28.
        try:
            future_date = today.replace(year=today.year + y)
        except ValueError:
            future_date = today.replace(month=2, day=28, year=today.year + y)
        projected = project_investment_growth(total_now, annual_rate, y)
        labels.append(future_date.strftime('%Y-%m-%d'))
        values.append(round(projected, 2))
    return {"labels": labels, "values": values}


def get_allocation_data(user):
    """Portfolio allocation by investment type, as {labels, values} for a pie/donut."""
    accounts = Account.objects.filter(user=user, type='investment')
    investments = Investment.objects.filter(account__in=accounts)
    by_type = (
        investments.values('type')
        .annotate(total=models.Sum('value'))
        .order_by('-total')
    )
    labels = [row['type'].capitalize() for row in by_type]
    values = [float(row['total']) for row in by_type]
    return {"labels": labels, "values": values}
