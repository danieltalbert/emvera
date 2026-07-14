from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from data_integration.models import Account, Investment

from .models import InvestmentProjection, InvestmentRecommendation


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

    def test_portfolio_performance_uses_current_branding(self):
        response = self.client.get(reverse('investments:portfolio_performance'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'investments/portfolio_performance.html')
        self.assertContains(response, 'Portfolio Performance — Ridge &amp; River Financial')

    def test_investment_comparison_view_uses_responsive_layout(self):
        Investment.objects.create(
            account=self.account,
            name='Balanced Fund',
            type='fund',
            value=Decimal('2500.00'),
            quantity=Decimal('5.0000'),
            symbol='BAL',
            as_of=date(2026, 7, 10),
        )

        response = self.client.get(reverse('investments:investment_comparison'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'investments/investment_comparison.html')
        self.assertContains(response, 'layout-with-sidebar')

    def test_investment_comparison_shows_user_scoped_allocations(self):
        Investment.objects.create(
            account=self.account,
            name='Stock Fund',
            type='stock',
            value=Decimal('300.00'),
            quantity=Decimal('3.0000'),
            symbol='STK',
            as_of=date(2026, 7, 12),
        )
        Investment.objects.create(
            account=self.account,
            name='Bond Fund',
            type='bond',
            value=Decimal('100.00'),
            quantity=Decimal('1.0000'),
            symbol='BND',
            as_of=date(2026, 7, 12),
        )
        other_user = get_user_model().objects.create_user(
            username='comparison-other',
            password='x',
            two_factor_enabled=True,
        )
        other_account = Account.objects.create(
            user=other_user,
            name='Other Brokerage',
            type='investment',
        )
        Investment.objects.create(
            account=other_account,
            name='Hidden Stock Fund',
            type='stock',
            value=Decimal('9600.00'),
            quantity=Decimal('96.0000'),
            symbol='HID',
            as_of=date(2026, 7, 12),
        )

        response = self.client.get(reverse('investments:investment_comparison'))

        self.assertEqual(response.status_code, 200)
        allocations = {
            row['type']: row['allocation_pct']
            for row in response.context['comparison']
        }
        self.assertAlmostEqual(float(allocations['stock']), 75.0)
        self.assertAlmostEqual(float(allocations['bond']), 25.0)
        self.assertContains(response, '75.0%')
        self.assertContains(response, '25.0%')
        self.assertNotContains(response, 'Hidden Stock Fund')

    def test_investment_projections_view(self):
        response = self.client.get(reverse('investments:investment_projections'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'investments/investment_projections.html')

    def test_investment_recommendations_view(self):
        response = self.client.get(reverse('investments:investment_recommendations'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'investments/investment_recommendations.html')

    def test_investment_recommendations_empty_state_has_next_actions(self):
        response = self.client.get(reverse('investments:investment_recommendations'))

        self.assertContains(response, 'No recommendations yet')
        self.assertContains(response, 'Add investment holdings first')
        self.assertContains(response, 'Add Investments')

    def test_investment_recommendations_include_generated_portfolio_wide_items(self):
        Investment.objects.create(
            account=self.account,
            name='Total Market Fund',
            type='stock',
            value=Decimal('10000.00'),
            quantity=Decimal('10.0000'),
            symbol='TMF',
            as_of=date(2026, 7, 10),
        )

        response = self.client.get(reverse('investments:investment_recommendations'))

        self.assertContains(response, 'Consider rebalancing.')
        self.assertContains(response, 'Portfolio-wide')
        self.assertNotContains(response, 'No recommendations yet')
        self.assertEqual(InvestmentRecommendation.objects.count(), 0)

    def test_investment_recommendations_counts_reviewed_and_new_items(self):
        investment = Investment.objects.create(
            account=self.account,
            name='Target Fund',
            type='401k',
            value=Decimal('2500.00'),
            quantity=Decimal('5.0000'),
            symbol='TGT',
            as_of=date(2026, 7, 10),
        )
        InvestmentRecommendation.objects.create(
            user=self.user,
            investment=investment,
            recommendation_type='increase_contribution',
            message='Increase monthly contribution.',
            reviewed=False,
        )
        InvestmentRecommendation.objects.create(
            user=self.user,
            investment=investment,
            recommendation_type='rebalance',
            message='Already reviewed recommendation.',
            reviewed=True,
        )

        response = self.client.get(reverse('investments:investment_recommendations'))

        self.assertEqual(response.context['total_recommendation_count'], 3)
        self.assertEqual(response.context['new_recommendation_count'], 2)
        self.assertEqual(response.context['reviewed_recommendation_count'], 1)
        self.assertContains(response, '<div class="stat-value">3</div>', html=True)
        self.assertContains(response, '<div class="stat-value">2</div>', html=True)
        self.assertContains(response, '<div class="stat-value">1</div>', html=True)

    def test_persisted_recommendation_can_be_marked_reviewed(self):
        investment = Investment.objects.create(
            account=self.account,
            name='Target Fund',
            type='401k',
            value=Decimal('2500.00'),
            quantity=Decimal('5.0000'),
            symbol='TGT',
            as_of=date(2026, 7, 10),
        )
        recommendation = InvestmentRecommendation.objects.create(
            user=self.user,
            investment=investment,
            recommendation_type='increase_contribution',
            message='Increase monthly contribution.',
            reviewed=False,
        )

        page_response = self.client.get(reverse('investments:investment_recommendations'))
        self.assertContains(page_response, 'Mark Reviewed')

        response = self.client.post(
            reverse('investments:mark_recommendation_reviewed', args=[recommendation.pk]),
            follow=True,
        )

        self.assertRedirects(response, reverse('investments:investment_recommendations'))
        recommendation.refresh_from_db()
        self.assertTrue(recommendation.reviewed)
        self.assertContains(response, 'Recommendation marked reviewed.')

    def test_mark_recommendation_reviewed_requires_post(self):
        investment = Investment.objects.create(
            account=self.account,
            name='Target Fund',
            type='401k',
            value=Decimal('2500.00'),
            quantity=Decimal('5.0000'),
            symbol='TGT',
            as_of=date(2026, 7, 10),
        )
        recommendation = InvestmentRecommendation.objects.create(
            user=self.user,
            investment=investment,
            recommendation_type='increase_contribution',
            message='Increase monthly contribution.',
            reviewed=False,
        )

        response = self.client.get(
            reverse('investments:mark_recommendation_reviewed', args=[recommendation.pk])
        )

        self.assertEqual(response.status_code, 405)
        recommendation.refresh_from_db()
        self.assertFalse(recommendation.reviewed)

    def test_mark_recommendation_reviewed_rejects_other_users_investment(self):
        other_user = get_user_model().objects.create_user(
            username='other-investor',
            password='x',
            two_factor_enabled=True,
        )
        other_account = Account.objects.create(
            user=other_user,
            name='Other Brokerage',
            type='investment',
        )
        other_investment = Investment.objects.create(
            account=other_account,
            name='Hidden Fund',
            type='401k',
            value=Decimal('5000.00'),
            quantity=Decimal('10.0000'),
            symbol='HID',
            as_of=date(2026, 7, 10),
        )
        recommendation = InvestmentRecommendation.objects.create(
            user=self.user,
            investment=other_investment,
            recommendation_type='rebalance',
            message='This recommendation points at an outside investment.',
            reviewed=False,
        )

        response = self.client.post(
            reverse('investments:mark_recommendation_reviewed', args=[recommendation.pk])
        )

        self.assertEqual(response.status_code, 404)
        recommendation.refresh_from_db()
        self.assertFalse(recommendation.reviewed)

    def test_export_investments_csv_only_includes_signed_in_user_data(self):
        own_investment = Investment.objects.create(
            account=self.account,
            name='Visible Index Fund',
            type='etf',
            value=Decimal('1000.00'),
            quantity=Decimal('2.0000'),
            symbol='VIS',
            as_of=date(2026, 7, 9),
        )
        InvestmentProjection.objects.create(
            investment=own_investment,
            user=self.user,
            projection_date=date(2030, 1, 1),
            projected_value=Decimal('2000.00'),
            growth_rate=8.0,
        )
        other_user = get_user_model().objects.create_user(
            username='other-investor',
            password='x',
            two_factor_enabled=True,
        )
        other_account = Account.objects.create(
            user=other_user,
            name='Other Brokerage',
            type='investment',
        )
        other_investment = Investment.objects.create(
            account=other_account,
            name='Hidden Index Fund',
            type='etf',
            value=Decimal('9000.00'),
            quantity=Decimal('9.0000'),
            symbol='HID',
            as_of=date(2026, 7, 9),
        )
        InvestmentProjection.objects.create(
            investment=other_investment,
            user=other_user,
            projection_date=date(2030, 1, 1),
            projected_value=Decimal('18000.00'),
            growth_rate=8.0,
        )

        response = self.client.get(reverse('investments:export_investments_csv'))

        self.assertEqual(response.status_code, 200)
        csv_body = response.content.decode('utf-8')
        self.assertIn('Visible Index Fund', csv_body)
        self.assertIn('$2,000.00', csv_body)
        self.assertNotIn('Hidden Index Fund', csv_body)
        self.assertNotIn('$18,000.00', csv_body)
