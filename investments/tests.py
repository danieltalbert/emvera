from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from data_integration.models import Account, Investment

from .models import InvestmentProjection


class AnnualizedReturnTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username='ret', password='x')
        cls.account = Account.objects.create(user=cls.user, name='Brokerage', type='investment')

    def _inv(self, value, as_of):
        return Investment.objects.create(
            account=self.account, name='VOO', type='etf',
            value=Decimal(value), quantity=Decimal('1'), symbol='VOO', as_of=as_of,
        )

    def test_ten_percent_over_five_years(self):
        inv = self._inv('10000', date(2025, 1, 1))
        p = InvestmentProjection.objects.create(
            investment=inv, user=self.user, projection_date=date(2030, 1, 1),
            projected_value=Decimal('16105.10'), growth_rate=10.0,
        )
        self.assertAlmostEqual(p.annualized_return(), 10.0, places=2)

    def test_zero_current_value_returns_none(self):
        inv = self._inv('0', date(2025, 1, 1))
        p = InvestmentProjection.objects.create(
            investment=inv, user=self.user, projection_date=date(2030, 1, 1),
            projected_value=Decimal('100'), growth_rate=5.0,
        )
        self.assertIsNone(p.annualized_return())

    def test_zero_or_negative_days_returns_none(self):
        inv = self._inv('1000', date(2030, 1, 1))
        p = InvestmentProjection.objects.create(
            investment=inv, user=self.user, projection_date=date(2025, 1, 1),
            projected_value=Decimal('500'), growth_rate=0.0,
        )
        self.assertIsNone(p.annualized_return())

    def test_loss_returns_negative_cagr(self):
        inv = self._inv('1000', date(2025, 1, 1))
        p = InvestmentProjection.objects.create(
            investment=inv, user=self.user, projection_date=date(2030, 1, 1),
            projected_value=Decimal('500'), growth_rate=-10.0,
        )
        result = p.annualized_return()
        self.assertLess(result, 0)


class InvestmentsViewsTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='viewer', password='x', two_factor_enabled=True,
        )
        self.client.login(username='viewer', password='x')
        self.account = Account.objects.create(user=self.user, name='Test Investment', type='investment')

    def test_portfolio_overview_view(self):
        response = self.client.get(reverse('investments:portfolio_overview'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'investments/portfolio_overview.html')

    def test_investment_growth_chart_view(self):
        response = self.client.get(reverse('investments:investment_growth_chart'))
        self.assertEqual(response.status_code, 200)

    def test_investment_projections_view(self):
        response = self.client.get(reverse('investments:investment_projections'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'investments/investment_projections.html')

    def test_investment_recommendations_view(self):
        response = self.client.get(reverse('investments:investment_recommendations'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'investments/investment_recommendations.html')
