"""Tests for the paper-trading simulator.

The fill math is tested directly via execute_fill (pure, no network). The
"Alpaca not configured" path is tested through submit_order. None of these need
Alpaca keys or network access.
"""
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model

from .models import PaperAccount, PaperPosition, PaperOrder
from .execution import execute_fill, submit_order, OrderError

User = get_user_model()


class FillMathTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='trader', password='pw12345!xZ')
        self.account = PaperAccount.objects.create(
            user=self.user, cash=Decimal('10000.00'), starting_cash=Decimal('10000.00'),
        )

    def test_buy_then_sell_updates_cash_and_positions(self):
        execute_fill(self.account, 'AAPL', 'buy', Decimal('10'), Decimal('100'))
        self.account.refresh_from_db()
        self.assertEqual(self.account.cash, Decimal('9000.00'))
        pos = PaperPosition.objects.get(account=self.account, symbol='AAPL')
        self.assertEqual(pos.quantity, Decimal('10'))
        self.assertEqual(pos.avg_cost, Decimal('100.0000'))

        execute_fill(self.account, 'AAPL', 'sell', Decimal('4'), Decimal('150'))
        self.account.refresh_from_db()
        self.assertEqual(self.account.cash, Decimal('9600.00'))  # 9000 + 4*150
        pos.refresh_from_db()
        self.assertEqual(pos.quantity, Decimal('6'))

    def test_weighted_average_cost_basis(self):
        execute_fill(self.account, 'MSFT', 'buy', Decimal('10'), Decimal('100'))
        execute_fill(self.account, 'MSFT', 'buy', Decimal('10'), Decimal('200'))
        pos = PaperPosition.objects.get(account=self.account, symbol='MSFT')
        self.assertEqual(pos.quantity, Decimal('20'))
        self.assertEqual(pos.avg_cost, Decimal('150.0000'))

    def test_buy_more_than_cash_rejected(self):
        with self.assertRaises(OrderError):
            execute_fill(self.account, 'AAPL', 'buy', Decimal('1000'), Decimal('100'))

    def test_sell_more_than_held_rejected(self):
        with self.assertRaises(OrderError):
            execute_fill(self.account, 'TSLA', 'sell', Decimal('5'), Decimal('100'))

    def test_equity_combines_cash_and_holdings(self):
        execute_fill(self.account, 'AAPL', 'buy', Decimal('10'), Decimal('100'))
        self.account.refresh_from_db()
        equity = self.account.equity({'AAPL': Decimal('120')})
        self.assertEqual(equity, Decimal('10200.00'))  # 9000 cash + 10*120

    def test_submit_order_without_alpaca_records_rejection(self):
        # No ALPACA_* env vars in the test environment -> not configured.
        order = submit_order(self.account, 'AAPL', 'buy', Decimal('1'))
        self.assertEqual(order.status, PaperOrder.STATUS_REJECTED)
        self.assertIn('Alpaca', order.note)
        self.account.refresh_from_db()
        self.assertEqual(self.account.cash, Decimal('10000.00'))  # unchanged


class PaperTradingViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='trader2', password='pw12345!xZ', two_factor_enabled=True,
        )
        self.client.force_login(self.user)

    def test_dashboard_renders_and_creates_practice_account(self):
        r = self.client.get(reverse('paper_trading:dashboard'))
        self.assertEqual(r.status_code, 200)
        self.assertTemplateUsed(r, 'paper_trading/dashboard.html')
        self.assertTrue(PaperAccount.objects.filter(user=self.user, competition=None).exists())

    def test_place_order_without_alpaca_redirects_gracefully(self):
        r = self.client.post(reverse('paper_trading:place_order'),
                             {'symbol': 'AAPL', 'side': 'buy', 'quantity': '5'})
        self.assertEqual(r.status_code, 302)
        order = PaperOrder.objects.get(account__user=self.user)
        self.assertEqual(order.status, PaperOrder.STATUS_REJECTED)
