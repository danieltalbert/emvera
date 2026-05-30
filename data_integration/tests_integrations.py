"""Tests for the optional brokerage/market-data integrations.

These verify the GATED behavior (nothing runs without keys) and the pure
mapping/encryption logic that doesn't need network access. Env vars are forced
empty so the "not configured" paths are deterministic regardless of the host.
"""
from datetime import date
from decimal import Decimal
from unittest import mock

from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model

from . import alpaca_client, snaptrade_client, brokerage_sync, pricing
from .models import Account, Investment, BrokerageLink

User = get_user_model()

# Force every integration env var empty so is_configured() is False.
NO_KEYS = mock.patch.dict('os.environ', {
    'ALPACA_API_KEY': '', 'ALPACA_SECRET_KEY': '',
    'SNAPTRADE_CLIENT_ID': '', 'SNAPTRADE_CONSUMER_KEY': '',
})


class GatingTests(TestCase):
    @NO_KEYS
    def test_alpaca_not_configured_by_default(self):
        self.assertFalse(alpaca_client.is_configured())
        self.assertEqual(alpaca_client.get_latest_prices([]), {})
        with self.assertRaises(alpaca_client.AlpacaNotConfigured):
            alpaca_client.get_latest_prices(['AAPL'])

    @NO_KEYS
    def test_snaptrade_not_configured_by_default(self):
        self.assertFalse(snaptrade_client.is_configured())
        user = User.objects.create_user(username='g', password='pw12345!xZ')
        with self.assertRaises(snaptrade_client.SnapTradeNotConfigured):
            snaptrade_client.register_user(user)

    def test_alpaca_defaults_to_paper(self):
        with mock.patch.dict('os.environ', {'ALPACA_PAPER': 'True'}):
            self.assertTrue(alpaca_client.is_paper())
        with mock.patch.dict('os.environ', {'ALPACA_PAPER': 'False'}):
            self.assertFalse(alpaca_client.is_paper())


class BrokerageSyncTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='sync', password='pw12345!xZ')
        self.link = BrokerageLink.objects.create(user=self.user)

    def test_sync_account_holdings_upserts_account_and_investments(self):
        acct = {'account_id': 'abc123', 'name': 'My Brokerage', 'institution': 'Robinhood'}
        holdings = [
            {'symbol': 'aapl', 'quantity': 5, 'price': 100},
            {'symbol': '', 'quantity': 1, 'price': 1},  # no symbol -> skipped
        ]
        count = brokerage_sync._sync_account_holdings(self.link, acct, holdings)
        self.assertEqual(count, 1)

        account = Account.objects.get(user=self.user, external_id='snaptrade:abc123')
        self.assertEqual(account.type, 'investment')
        self.assertEqual(account.institution, 'Robinhood')

        inv = Investment.objects.get(account=account, symbol='AAPL')
        self.assertEqual(inv.quantity, Decimal('5'))
        self.assertEqual(inv.value, Decimal('500.00'))

    def test_resync_updates_existing_rows(self):
        acct = {'account_id': 'x', 'name': 'B', 'institution': ''}
        brokerage_sync._sync_account_holdings(self.link, acct, [{'symbol': 'AAPL', 'quantity': 2, 'price': 50}])
        brokerage_sync._sync_account_holdings(self.link, acct, [{'symbol': 'AAPL', 'quantity': 3, 'price': 50}])
        self.assertEqual(Account.objects.filter(user=self.user).count(), 1)
        self.assertEqual(Investment.objects.filter(symbol='AAPL').count(), 1)
        self.assertEqual(Investment.objects.get(symbol='AAPL').value, Decimal('150.00'))


class PricingTests(TestCase):
    def test_apply_prices_updates_values(self):
        user = User.objects.create_user(username='p', password='pw12345!xZ')
        account = Account.objects.create(user=user, name='B', type='investment')
        inv = Investment.objects.create(
            account=account, name='AAPL', type='stock', value=Decimal('0'),
            quantity=Decimal('4'), symbol='AAPL', as_of=date(2026, 1, 1),
        )
        result = pricing._apply_prices([inv], {'AAPL': Decimal('125')})
        inv.refresh_from_db()
        self.assertEqual(inv.value, Decimal('500.00'))
        self.assertEqual(result['updated'], 1)


class BrokerageLinkCryptoTests(TestCase):
    def test_user_secret_is_encrypted_at_rest(self):
        user = User.objects.create_user(username='c', password='pw12345!xZ')
        link = BrokerageLink(user=user)
        link.set_user_secret('super-secret-value')
        link.save()
        link.refresh_from_db()
        self.assertTrue(link.user_secret.startswith('enc:'))
        self.assertNotIn('super-secret-value', link.user_secret)
        self.assertEqual(link.get_user_secret(), 'super-secret-value')


class ConnectBrokerageViewTests(TestCase):
    @NO_KEYS
    def test_connect_brokerage_renders_not_configured(self):
        user = User.objects.create_user(
            username='v', password='pw12345!xZ', two_factor_enabled=True,
        )
        self.client.force_login(user)
        r = self.client.get(reverse('data_integration:connect_brokerage'))
        self.assertEqual(r.status_code, 200)
        self.assertTemplateUsed(r, 'data_integration/connect_brokerage.html')
        self.assertFalse(r.context['snaptrade_configured'])
