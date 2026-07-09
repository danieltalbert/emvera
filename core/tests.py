from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from competition.models import Competition, CompetitionParticipant, MiniGame
from data_integration.models import Account, Debt, Investment


class AuthenticatedRouteSmokeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username='route-smoke',
            password='testpass',
            two_factor_enabled=True,
        )
        cls.investment_account = Account.objects.create(
            user=cls.user,
            name='Brokerage',
            type='investment',
            institution='Codex Bank',
        )
        cls.debt_account = Account.objects.create(
            user=cls.user,
            name='Rewards Card',
            type='debt',
            institution='Codex Card',
        )
        Investment.objects.create(
            account=cls.investment_account,
            name='Index Fund',
            type='etf',
            value=Decimal('1000.00'),
            quantity=Decimal('2.0000'),
            symbol='IDX',
            as_of=date(2026, 7, 9),
        )
        Debt.objects.create(
            account=cls.debt_account,
            name='Rewards Card Balance',
            principal=Decimal('1000.00'),
            balance=Decimal('900.00'),
            interest_rate=Decimal('19.99'),
            minimum_payment=Decimal('35.00'),
            due_date=date(2026, 8, 1),
            as_of=date(2026, 7, 9),
        )
        cls.lobby_competition = Competition.objects.create(
            name='Smoke Cup',
            created_by=cls.user,
        )
        CompetitionParticipant.objects.create(
            competition=cls.lobby_competition,
            user=cls.user,
            portfolio_value=cls.lobby_competition.starting_balance,
        )
        cls.active_competition = Competition.objects.create(
            name='Active Smoke Cup',
            created_by=cls.user,
            status=Competition.STATUS_ACTIVE,
        )
        CompetitionParticipant.objects.create(
            competition=cls.active_competition,
            user=cls.user,
            portfolio_value=cls.active_competition.starting_balance,
        )
        cls.active_mini_game = MiniGame.objects.create(
            competition=cls.active_competition,
            game_type=MiniGame.GAME_PAINTBALL,
            bonus_amount=cls.active_competition.mini_game_bonus,
        )
        cls.finished_competition = Competition.objects.create(
            name='Finished Smoke Cup',
            created_by=cls.user,
            status=Competition.STATUS_FINISHED,
        )
        CompetitionParticipant.objects.create(
            competition=cls.finished_competition,
            user=cls.user,
            portfolio_value=cls.finished_competition.starting_balance,
        )

    def setUp(self):
        self.client.force_login(self.user)

    def assertPageRenders(self, route_name, url, template_name):
        with self.subTest(route=route_name):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertTemplateUsed(response, template_name)
            self.assertIn('text/html', response['Content-Type'])

    def test_authenticated_page_routes_render(self):
        routes = (
            ('accounts:profile', reverse('accounts:profile'), 'accounts/profile.html'),
            ('accounts:change_password', reverse('accounts:change_password'), 'accounts/change_password.html'),
            ('accounts:onboarding', reverse('accounts:onboarding'), 'accounts/onboarding.html'),
            (
                'data_integration:connect_plaid',
                reverse('data_integration:connect_plaid'),
                'data_integration/connect_plaid.html',
            ),
            (
                'data_integration:manual_account_entry',
                reverse('data_integration:manual_account_entry'),
                'data_integration/manual_account_entry.html',
            ),
            (
                'data_integration:manual_transaction_entry',
                reverse('data_integration:manual_transaction_entry'),
                'data_integration/manual_transaction_entry.html',
            ),
            (
                'data_integration:manual_debt_entry',
                reverse('data_integration:manual_debt_entry'),
                'data_integration/manual_debt_entry.html',
            ),
            (
                'data_integration:csv_upload',
                reverse('data_integration:csv_upload'),
                'data_integration/csv_upload.html',
            ),
            (
                'investments:portfolio_overview',
                reverse('investments:portfolio_overview'),
                'investments/portfolio_overview.html',
            ),
            (
                'investments:investment_projections',
                reverse('investments:investment_projections'),
                'investments/investment_projections.html',
            ),
            (
                'investments:investment_recommendations',
                reverse('investments:investment_recommendations'),
                'investments/investment_recommendations.html',
            ),
            (
                'investments:investment_comparison',
                reverse('investments:investment_comparison'),
                'investments/investment_comparison.html',
            ),
            (
                'investments:portfolio_performance',
                reverse('investments:portfolio_performance'),
                'investments/portfolio_performance.html',
            ),
            (
                'debt_management:debt_dashboard',
                reverse('debt_management:debt_dashboard'),
                'debt_management/debt_dashboard.html',
            ),
            (
                'debt_management:payoff_avalanche',
                reverse('debt_management:payoff_avalanche'),
                'debt_management/payoff_avalanche.html',
            ),
            (
                'debt_management:payoff_snowball',
                reverse('debt_management:payoff_snowball'),
                'debt_management/payoff_snowball.html',
            ),
            (
                'debt_management:payoff_custom',
                reverse('debt_management:payoff_custom'),
                'debt_management/payoff_custom.html',
            ),
            (
                'debt_management:debt_reminders',
                reverse('debt_management:debt_reminders'),
                'debt_management/debt_reminders.html',
            ),
            (
                'debt_management:consolidation_suggestion',
                reverse('debt_management:consolidation_suggestion'),
                'debt_management/consolidation_suggestion.html',
            ),
            (
                'debt_management:credit_score_tracking',
                reverse('debt_management:credit_score_tracking'),
                'debt_management/credit_score_tracking.html',
            ),
            ('competition:lobby', reverse('competition:lobby'), 'competition/lobby.html'),
            ('competition:create', reverse('competition:create'), 'competition/create.html'),
            (
                'competition:dashboard',
                reverse('competition:dashboard', kwargs={'pk': self.lobby_competition.pk}),
                'competition/dashboard.html',
            ),
            (
                'competition:paintball',
                reverse(
                    'competition:paintball',
                    kwargs={
                        'pk': self.active_competition.pk,
                        'game_pk': self.active_mini_game.pk,
                    },
                ),
                'competition/paintball.html',
            ),
            (
                'competition:winner',
                reverse('competition:winner', kwargs={'pk': self.finished_competition.pk}),
                'competition/winner.html',
            ),
        )
        for route_name, url, template_name in routes:
            self.assertPageRenders(route_name, url, template_name)

    def test_authenticated_data_routes_return_expected_formats(self):
        checks = (
            (
                'investments:investment_growth_chart',
                reverse('investments:investment_growth_chart'),
                'application/json',
            ),
            (
                'competition:state',
                reverse('competition:state', kwargs={'pk': self.active_competition.pk}),
                'application/json',
            ),
            (
                'investments:export_investments_csv',
                reverse('investments:export_investments_csv'),
                'text/csv',
            ),
        )
        for route_name, url, content_type in checks:
            with self.subTest(route=route_name):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertIn(content_type, response['Content-Type'])

        state_response = self.client.get(
            reverse('competition:state', kwargs={'pk': self.active_competition.pk})
        )
        self.assertEqual(state_response.json()['status'], Competition.STATUS_ACTIVE)

        csv_response = self.client.get(reverse('investments:export_investments_csv'))
        self.assertTrue(csv_response.content.startswith(b'Name,Type,Current Value'))

    def test_accessibility_markup_regressions_stay_fixed(self):
        portfolio_response = self.client.get(reverse('investments:portfolio_overview'))
        self.assertContains(portfolio_response, 'class="portfolio-main-grid"')

        lobby_response = self.client.get(reverse('competition:lobby'))
        self.assertContains(
            lobby_response,
            '<h2 class="section-label">Your Active Competitions</h2>',
            html=True,
        )
        self.assertContains(
            lobby_response,
            '<h2 class="section-label">Open Lobbies &mdash; Join Now</h2>',
            html=True,
        )
        self.assertContains(
            lobby_response,
            '<h2 class="section-label">In Progress</h2>',
            html=True,
        )
