"""Tests for competitions, including the paper-trading wiring.

The paper-trading standings are tested both without Alpaca (cost-basis fallback)
and with prices mocked, so no API keys or network are needed.
"""
from decimal import Decimal
from unittest import mock

from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model

from .models import Competition, CompetitionParticipant
from . import services
from paper_trading.models import PaperAccount
from paper_trading.execution import execute_fill

User = get_user_model()


def _make_competition(creator, paper=False, goal='5000'):
    return Competition.objects.create(
        name='Test Cup', created_by=creator,
        starting_balance=Decimal('1000.00'), investment_goal=Decimal(goal),
        uses_paper_trading=paper,
    )


class StartProvisioningTests(TestCase):
    def setUp(self):
        self.a = User.objects.create_user(username='a', password='pw12345!xZ')
        self.b = User.objects.create_user(username='b', password='pw12345!xZ')

    def test_paper_competition_seeds_accounts_on_start(self):
        comp = _make_competition(self.a, paper=True)
        CompetitionParticipant.objects.create(competition=comp, user=self.a, portfolio_value=comp.starting_balance)
        CompetitionParticipant.objects.create(competition=comp, user=self.b, portfolio_value=comp.starting_balance)
        comp.start()
        accounts = PaperAccount.objects.filter(competition=comp)
        self.assertEqual(accounts.count(), 2)
        self.assertEqual(accounts.first().cash, Decimal('1000.00'))

    def test_classic_competition_creates_no_paper_accounts(self):
        comp = _make_competition(self.a, paper=False)
        CompetitionParticipant.objects.create(competition=comp, user=self.a, portfolio_value=comp.starting_balance)
        comp.start()
        self.assertEqual(PaperAccount.objects.filter(competition=comp).count(), 0)


class StandingsTests(TestCase):
    def setUp(self):
        self.a = User.objects.create_user(username='a', password='pw12345!xZ')
        self.b = User.objects.create_user(username='b', password='pw12345!xZ')
        self.comp = _make_competition(self.a, paper=True)
        self.pa = CompetitionParticipant.objects.create(competition=self.comp, user=self.a, portfolio_value=self.comp.starting_balance)
        self.pb = CompetitionParticipant.objects.create(competition=self.comp, user=self.b, portfolio_value=self.comp.starting_balance)
        self.comp.start()

    def test_refresh_is_noop_for_classic(self):
        classic = _make_competition(self.b, paper=False)
        self.assertEqual(services.refresh_standings(classic), {})

    def test_refresh_values_holdings_at_cost_without_alpaca(self):
        acct = PaperAccount.objects.get(competition=self.comp, user=self.a)
        execute_fill(acct, 'AAPL', 'buy', Decimal('5'), Decimal('100'))  # cash 500 + 5 sh @100
        services.refresh_standings(self.comp)
        self.pa.refresh_from_db()
        # Valued at cost basis -> equity unchanged at the starting balance.
        self.assertEqual(self.pa.portfolio_value, Decimal('1000.00'))

    def test_refresh_with_live_prices_updates_equity_and_ranks(self):
        acct = PaperAccount.objects.get(competition=self.comp, user=self.a)
        execute_fill(acct, 'AAPL', 'buy', Decimal('5'), Decimal('100'))  # cash 500, 5 sh
        with mock.patch('data_integration.alpaca_client.is_configured', return_value=True), \
             mock.patch('data_integration.alpaca_client.get_latest_prices',
                        return_value={'AAPL': Decimal('300')}):
            services.refresh_standings(self.comp)
        self.pa.refresh_from_db()
        self.assertEqual(self.pa.portfolio_value, Decimal('2000.00'))  # 500 + 5*300
        # A (2000) now outranks B (1000).
        leader = self.comp.participants.order_by('-portfolio_value').first()
        self.assertEqual(leader.user, self.a)

    def test_reaching_goal_auto_finishes(self):
        acct = PaperAccount.objects.get(competition=self.comp, user=self.a)
        execute_fill(acct, 'AAPL', 'buy', Decimal('5'), Decimal('100'))
        with mock.patch('data_integration.alpaca_client.is_configured', return_value=True), \
             mock.patch('data_integration.alpaca_client.get_latest_prices',
                        return_value={'AAPL': Decimal('2000')}):  # equity 500 + 10000
            services.refresh_standings(self.comp)
        self.comp.refresh_from_db()
        self.assertEqual(self.comp.status, Competition.STATUS_FINISHED)


class TradeViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='trader', password='pw12345!xZ')
        self.comp = _make_competition(self.user, paper=True)
        CompetitionParticipant.objects.create(competition=self.comp, user=self.user, portfolio_value=self.comp.starting_balance)
        self.comp.start()
        self.client.force_login(self.user)

    def test_trade_panel_renders(self):
        r = self.client.get(reverse('competition:trade', args=[self.comp.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertTemplateUsed(r, 'competition/trade.html')

    def test_place_trade_without_alpaca_is_rejected(self):
        r = self.client.post(reverse('competition:place_trade', args=[self.comp.pk]),
                             {'symbol': 'AAPL', 'side': 'buy', 'quantity': '3'})
        self.assertEqual(r.status_code, 302)
        acct = PaperAccount.objects.get(competition=self.comp, user=self.user)
        self.assertEqual(acct.orders.first().status, 'rejected')


class CreateFormTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='creator', password='pw12345!xZ', two_factor_enabled=True,
        )
        self.client.force_login(self.user)

    def test_create_page_exposes_paper_trading_toggle_and_both_rule_sets(self):
        r = self.client.get(reverse('competition:create'))
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        # The mode toggle and both mode-aware rule lists are present so the JS
        # preview can swap between them.
        self.assertIn('id_uses_paper_trading', body)
        self.assertIn('rules-classic', body)
        self.assertIn('rules-paper', body)

    def test_can_create_paper_trading_competition(self):
        r = self.client.post(reverse('competition:create'), {
            'name': 'Trading Cup', 'description': '',
            'starting_balance': '1000', 'investment_goal': '5000',
            'mini_game_bonus': '50', 'max_players': '8',
            'uses_paper_trading': 'on',
        })
        self.assertEqual(r.status_code, 302)
        comp = Competition.objects.get(name='Trading Cup')
        self.assertTrue(comp.uses_paper_trading)
