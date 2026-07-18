import io
import os
import sys
from datetime import date, timedelta
from decimal import Decimal
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.testing import force_login_with_otp

from . import plaid_client
from .checks import production_plaid_configuration_check
from .crypto import (
    DEDICATED_PREFIX,
    PREFIX,
    TokenDecryptionError,
    decrypt,
    encrypt,
)
from .csv_import import (
    MAX_TRANSACTION_AMOUNT,
    _parse_amount,
    _parse_date,
    _resolve_columns,
    import_transactions,
)
from .models import Account, Debt, Investment, PlaidItem, Transaction
from .plaid_sync import (
    PlaidItemOwnershipError,
    SyncSummary,
    _sync_transactions,
    link_and_sync,
)

# ---------- CSV importer ----------


class CSVHelperTests(SimpleTestCase):
    def test_resolve_columns_accepts_aliases(self):
        mapping = _resolve_columns(['Transaction Date', 'Amount', 'Type', 'Memo'])
        self.assertEqual(mapping['date'], 'Transaction Date')
        self.assertEqual(mapping['category'], 'Type')
        self.assertEqual(mapping['description'], 'Memo')

    def test_parse_date_multiple_formats(self):
        self.assertEqual(_parse_date('2026-01-15'), date(2026, 1, 15))
        self.assertEqual(_parse_date('01/15/2026'), date(2026, 1, 15))
        self.assertIsNone(_parse_date('not a date'))
        self.assertIsNone(_parse_date(''))

    def test_parse_amount_handles_currency_and_parens(self):
        self.assertEqual(_parse_amount('$1,234.56'), Decimal('1234.56'))
        self.assertEqual(_parse_amount('(42.50)'), Decimal('-42.50'))
        self.assertEqual(_parse_amount('-99'), Decimal('-99'))
        self.assertIsNone(_parse_amount('bad'))
        self.assertIsNone(_parse_amount('NaN'))
        self.assertIsNone(_parse_amount('Infinity'))
        self.assertIsNone(_parse_amount(str(MAX_TRANSACTION_AMOUNT + Decimal('0.01'))))
        self.assertIsNone(_parse_amount(str(-MAX_TRANSACTION_AMOUNT - Decimal('0.01'))))


class CSVImportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username='csv', password='x')
        cls.account = Account.objects.create(user=cls.user, name='Acct', type='checking')

    def _import(self, text):
        return import_transactions(io.BytesIO(text.encode('utf-8')), self.account)

    def test_creates_transactions_with_aliases(self):
        csv = (
            'Transaction Date,Amount,Category,Memo\n'
            '2026-01-15,-42.50,Groceries,Whole Foods\n'
            '01/20/2026,1500.00,Salary,Acme\n'
        )
        result = self._import(csv)
        self.assertEqual(result.created, 2)
        self.assertEqual(result.skipped, 0)
        rows = list(Transaction.objects.filter(account=self.account).order_by('date'))
        self.assertEqual(rows[0].category, 'Groceries')
        self.assertEqual(rows[1].amount, Decimal('1500.00'))

    def test_parenthesised_negatives(self):
        csv = 'date,amount,category\n2026-01-15,(75.00),Gas\n'
        self._import(csv)
        t = Transaction.objects.get(category='Gas')
        self.assertEqual(t.amount, Decimal('-75.00'))

    def test_handles_utf8_bom(self):
        csv = '﻿date,amount,category\n2026-01-15,10.00,Coffee\n'
        result = self._import(csv)
        self.assertEqual(result.created, 1)

    def test_missing_required_column_short_circuits(self):
        csv = 'date,description\n2026-01-15,Coffee\n'  # missing amount + category
        result = self._import(csv)
        self.assertEqual(result.created, 0)
        self.assertTrue(any('Missing required column' in e for e in result.row_errors))

    def test_per_row_errors_listed_with_line_numbers(self):
        csv = 'date,amount,category\n2026-01-15,10.00,Coffee\nbad,bad,bad\n2026-01-17,,Lunch\n'
        result = self._import(csv)
        self.assertEqual(result.created, 1)
        self.assertEqual(result.skipped, 2)
        self.assertTrue(any('Line 3' in e for e in result.row_errors))
        self.assertTrue(any('Line 4' in e for e in result.row_errors))

    def test_nonfinite_amounts_are_skipped(self):
        csv = 'date,amount,category\n2026-01-15,NaN,Adjustment\n2026-01-16,Infinity,Adjustment\n'

        result = self._import(csv)

        self.assertEqual(result.created, 0)
        self.assertEqual(result.skipped, 2)
        self.assertTrue(any('Line 2' in e for e in result.row_errors))
        self.assertTrue(any('Line 3' in e for e in result.row_errors))
        self.assertFalse(Transaction.objects.filter(account=self.account).exists())

    def test_out_of_range_amounts_are_skipped(self):
        csv = (
            'date,amount,category\n'
            f'2026-01-15,{MAX_TRANSACTION_AMOUNT + Decimal("0.01")},Adjustment\n'
            f'2026-01-16,{-MAX_TRANSACTION_AMOUNT - Decimal("0.01")},Adjustment\n'
        )

        result = self._import(csv)

        self.assertEqual(result.created, 0)
        self.assertEqual(result.skipped, 2)
        self.assertTrue(any('Line 2' in e for e in result.row_errors))
        self.assertTrue(any('Line 3' in e for e in result.row_errors))
        self.assertFalse(Transaction.objects.filter(account=self.account).exists())

    def test_invalid_utf8_file_returns_error_result(self):
        result = import_transactions(io.BytesIO(b'\xff\xfe\x00'), self.account)

        self.assertEqual(result.created, 0)
        self.assertEqual(result.skipped, 0)
        self.assertEqual(result.row_errors, ['CSV file must be UTF-8 encoded.'])
        self.assertFalse(Transaction.objects.filter(account=self.account).exists())

    def test_empty_file(self):
        result = self._import('')
        self.assertEqual(result.created, 0)
        self.assertTrue(result.row_errors)


# ---------- Crypto helper + PlaidItem token round-trip ----------


class FakeLinkClient:
    def __init__(self):
        self.request = None

    def link_token_create(self, request):
        self.request = request
        return SimpleNamespace(link_token='link-sandbox-test')


class PlaidClientConfigurationTests(SimpleTestCase):
    def test_unknown_environment_is_not_silently_treated_as_sandbox(self):
        with patch.dict(
            os.environ,
            {
                'PLAID_CLIENT_ID': 'client-id',
                'PLAID_SECRET': 'secret',
                'PLAID_ENV': 'typo-environment',
            },
            clear=True,
        ):
            self.assertFalse(plaid_client.is_configured())
            with self.assertRaisesMessage(
                plaid_client.PlaidNotConfigured,
                'PLAID_ENV must be sandbox, development, or production.',
            ):
                plaid_client._client()

    def test_link_token_includes_configured_oauth_redirect(self):
        fake_client = FakeLinkClient()
        user = SimpleNamespace(pk=42)
        with (
            patch.object(plaid_client, '_client', return_value=fake_client),
            patch.dict(
                os.environ,
                {
                    'PLAID_PRODUCTS': 'transactions',
                    'PLAID_REDIRECT_URI': 'https://example.com/plaid/oauth/',
                },
                clear=False,
            ),
        ):
            token = plaid_client.create_link_token(user)

        self.assertEqual(token, 'link-sandbox-test')
        self.assertEqual(
            fake_client.request.redirect_uri,
            'https://example.com/plaid/oauth/',
        )


class CryptoRoundTripTests(SimpleTestCase):
    def test_round_trip(self):
        original = 'access-sandbox-abc123'
        ciphertext = encrypt(original)
        self.assertTrue(ciphertext.startswith(PREFIX))
        self.assertNotIn(original, ciphertext)
        self.assertEqual(decrypt(ciphertext), original)

    def test_empty(self):
        self.assertEqual(encrypt(''), '')
        self.assertEqual(decrypt(''), '')

    def test_legacy_plaintext_passes_through(self):
        # Pre-encryption rows are stored without the prefix.
        self.assertEqual(decrypt('plaintext-legacy'), 'plaintext-legacy')

    def test_dedicated_key_encrypts_with_versioned_prefix(self):
        key = Fernet.generate_key().decode('ascii')
        with override_settings(
            PLAID_TOKEN_ENCRYPTION_KEY=key,
            PLAID_TOKEN_ENCRYPTION_PREVIOUS_KEYS=[],
        ):
            ciphertext = encrypt('access-sandbox-dedicated')

            self.assertTrue(ciphertext.startswith(DEDICATED_PREFIX))
            self.assertEqual(decrypt(ciphertext), 'access-sandbox-dedicated')

    def test_legacy_secret_key_ciphertext_remains_readable_during_migration(self):
        with override_settings(
            PLAID_TOKEN_ENCRYPTION_KEY='',
            PLAID_TOKEN_ENCRYPTION_PREVIOUS_KEYS=[],
        ):
            legacy_ciphertext = encrypt('access-sandbox-legacy')

        with override_settings(
            PLAID_TOKEN_ENCRYPTION_KEY=Fernet.generate_key().decode('ascii'),
            PLAID_TOKEN_ENCRYPTION_PREVIOUS_KEYS=[],
        ):
            self.assertEqual(decrypt(legacy_ciphertext), 'access-sandbox-legacy')

    def test_previous_dedicated_key_supports_safe_rotation(self):
        old_key = Fernet.generate_key().decode('ascii')
        new_key = Fernet.generate_key().decode('ascii')
        with override_settings(
            PLAID_TOKEN_ENCRYPTION_KEY=old_key,
            PLAID_TOKEN_ENCRYPTION_PREVIOUS_KEYS=[],
        ):
            old_ciphertext = encrypt('access-sandbox-rotating')

        with override_settings(
            PLAID_TOKEN_ENCRYPTION_KEY=new_key,
            PLAID_TOKEN_ENCRYPTION_PREVIOUS_KEYS=[old_key],
        ):
            self.assertEqual(decrypt(old_ciphertext), 'access-sandbox-rotating')

    def test_unreadable_ciphertext_fails_closed(self):
        with override_settings(
            PLAID_TOKEN_ENCRYPTION_KEY=Fernet.generate_key().decode('ascii'),
            PLAID_TOKEN_ENCRYPTION_PREVIOUS_KEYS=[],
        ):
            with self.assertRaises(TokenDecryptionError):
                decrypt(f'{DEDICATED_PREFIX}not-a-valid-token')


class PlaidDeploymentCheckTests(SimpleTestCase):
    @override_settings(
        PLAID_TOKEN_ENCRYPTION_KEY='',
        PLAID_TOKEN_ENCRYPTION_PREVIOUS_KEYS=[],
    )
    @patch.dict(
        os.environ,
        {
            'PLAID_CLIENT_ID': 'sandbox-client',
            'PLAID_SECRET': 'sandbox-secret',
            'PLAID_ENV': 'sandbox',
        },
        clear=False,
    )
    def test_configured_plaid_requires_independent_encryption_key(self):
        errors = production_plaid_configuration_check(None)

        self.assertIn('emvera.E003', {error.id for error in errors})

    @override_settings(
        PLAID_TOKEN_ENCRYPTION_KEY='invalid-key',
        PLAID_TOKEN_ENCRYPTION_PREVIOUS_KEYS=[],
    )
    @patch.dict(os.environ, {'PLAID_CLIENT_ID': '', 'PLAID_SECRET': ''}, clear=False)
    def test_invalid_fernet_key_is_rejected_even_before_plaid_is_enabled(self):
        errors = production_plaid_configuration_check(None)

        self.assertIn('emvera.E004', {error.id for error in errors})


class PlaidItemTokenTests(TestCase):
    def test_token_is_encrypted_at_rest(self):
        user = get_user_model().objects.create_user(username='p', password='x')
        item = PlaidItem(user=user, item_id='item_1')
        item.set_access_token('access-sandbox-secret')
        item.save()

        # Round-trip through the DB to be sure.
        reloaded = PlaidItem.objects.get(pk=item.pk)
        self.assertTrue(reloaded.access_token.startswith(PREFIX))
        self.assertNotIn('secret', reloaded.access_token)
        self.assertEqual(reloaded.get_access_token(), 'access-sandbox-secret')

    def test_rotation_command_rewrites_legacy_ciphertext(self):
        user = get_user_model().objects.create_user(username='rotate', password='x')
        with override_settings(
            PLAID_TOKEN_ENCRYPTION_KEY='',
            PLAID_TOKEN_ENCRYPTION_PREVIOUS_KEYS=[],
        ):
            item = PlaidItem(user=user, item_id='item-rotate')
            item.set_access_token('access-sandbox-rotate')
            item.save()
            self.assertFalse(item.access_token.startswith(DEDICATED_PREFIX))

        output = io.StringIO()
        with override_settings(
            PLAID_TOKEN_ENCRYPTION_KEY=Fernet.generate_key().decode('ascii'),
            PLAID_TOKEN_ENCRYPTION_PREVIOUS_KEYS=[],
        ):
            call_command('reencrypt_plaid_tokens', stdout=output)
            item.refresh_from_db()
            self.assertTrue(item.access_token.startswith(DEDICATED_PREFIX))
            self.assertEqual(item.get_access_token(), 'access-sandbox-rotate')

        self.assertIn('Re-encrypted 1 token(s).', output.getvalue())


class FakeTransactionsSyncRequest:
    def __init__(self, **kwargs):
        self.access_token = kwargs['access_token']
        self.cursor = kwargs.get('cursor', '')


class FakePlaidTransactionsClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def transactions_sync(self, request):
        self.requests.append(request)
        return self.responses.pop(0)


class PlaidSyncTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username='sync-user', password='x')
        self.other_user = User.objects.create_user(username='other-sync-user', password='x')
        self.account = Account.objects.create(
            user=self.user,
            name='Sync Checking',
            type='checking',
            external_id='plaid-account-1',
        )
        self.other_account = Account.objects.create(
            user=self.other_user,
            name='Other Checking',
            type='checking',
            external_id='plaid-account-2',
        )
        self.item = PlaidItem(user=self.user, item_id='item-sync', cursor='cursor-0')
        self.item.set_access_token('access-sync')
        self.item.save()

    def plaid_modules(self):
        plaid_package = ModuleType('plaid')
        plaid_package.__path__ = []
        model_package = ModuleType('plaid.model')
        model_package.__path__ = []
        sync_request_module = ModuleType('plaid.model.transactions_sync_request')
        sync_request_module.TransactionsSyncRequest = FakeTransactionsSyncRequest
        return {
            'plaid': plaid_package,
            'plaid.model': model_package,
            'plaid.model.transactions_sync_request': sync_request_module,
        }

    def response(
        self, *, added=(), modified=(), removed=(), next_cursor='cursor-next', has_more=False
    ):
        return SimpleNamespace(
            added=list(added),
            modified=list(modified),
            removed=list(removed),
            next_cursor=next_cursor,
            has_more=has_more,
        )

    def plaid_transaction(self, transaction_id, *, account_id='plaid-account-1', amount=12.34):
        return SimpleNamespace(
            account_id=account_id,
            transaction_id=transaction_id,
            date=date(2026, 7, 10),
            amount=Decimal(str(amount)),
            category=['Groceries'],
            name='Market',
        )

    def run_sync(self, responses):
        client = FakePlaidTransactionsClient(responses)
        summary = SyncSummary()
        with (
            patch.dict(sys.modules, self.plaid_modules()),
            patch('data_integration.plaid_client._client', return_value=client),
        ):
            _sync_transactions(self.user, self.item, summary)
        self.item.refresh_from_db()
        return client, summary

    def test_sync_transactions_persists_cursor_across_pages(self):
        client, summary = self.run_sync(
            [
                self.response(
                    added=[self.plaid_transaction('tx-1')],
                    next_cursor='cursor-1',
                    has_more=True,
                ),
                self.response(next_cursor='cursor-2'),
            ]
        )

        self.assertEqual([request.cursor for request in client.requests], ['cursor-0', 'cursor-1'])
        self.assertEqual(self.item.cursor, 'cursor-2')
        self.assertEqual(summary.transactions_added, 1)
        transaction = Transaction.objects.get(account=self.account, external_id='tx-1')
        self.assertEqual(transaction.amount, Decimal('-12.34'))
        self.assertEqual(transaction.category, 'Groceries')

    def test_sync_transactions_replays_added_transaction_without_duplicate(self):
        Transaction.objects.create(
            account=self.account,
            external_id='tx-existing',
            date=date(2026, 7, 9),
            amount=Decimal('-10.00'),
            category='Old',
            description='Old market',
            source='api',
        )

        _, summary = self.run_sync(
            [
                self.response(
                    added=[self.plaid_transaction('tx-existing', amount=14.56)],
                    next_cursor='cursor-1',
                ),
            ]
        )

        self.assertEqual(
            Transaction.objects.filter(account=self.account, external_id='tx-existing').count(), 1
        )
        transaction = Transaction.objects.get(account=self.account, external_id='tx-existing')
        self.assertEqual(transaction.amount, Decimal('-14.56'))
        self.assertEqual(transaction.category, 'Groceries')
        self.assertEqual(summary.transactions_added, 0)

    def test_sync_transactions_does_not_hijack_another_users_same_external_id(self):
        other_transaction = Transaction.objects.create(
            account=self.other_account,
            external_id='tx-shared',
            date=date(2026, 7, 9),
            amount=Decimal('-99.00'),
            category='Other',
            description='Other user row',
            source='api',
        )

        _, summary = self.run_sync(
            [
                self.response(
                    added=[self.plaid_transaction('tx-shared', amount=20.00)],
                    next_cursor='cursor-1',
                ),
            ]
        )

        other_transaction.refresh_from_db()
        self.assertEqual(other_transaction.account, self.other_account)
        self.assertEqual(other_transaction.amount, Decimal('-99.00'))
        self.assertEqual(Transaction.objects.filter(external_id='tx-shared').count(), 2)
        self.assertTrue(
            Transaction.objects.filter(account=self.account, external_id='tx-shared').exists()
        )
        self.assertEqual(summary.transactions_added, 1)

    def test_sync_transactions_does_not_modify_or_remove_another_users_rows(self):
        modified = Transaction.objects.create(
            account=self.other_account,
            external_id='tx-modified',
            date=date(2026, 7, 9),
            amount=Decimal('-99.00'),
            category='Other',
            description='Other user modified row',
            source='api',
        )
        removed = Transaction.objects.create(
            account=self.other_account,
            external_id='tx-removed',
            date=date(2026, 7, 9),
            amount=Decimal('-50.00'),
            category='Other',
            description='Other user removed row',
            source='api',
        )

        _, summary = self.run_sync(
            [
                self.response(
                    modified=[self.plaid_transaction('tx-modified', amount=20.00)],
                    removed=[SimpleNamespace(transaction_id='tx-removed')],
                    next_cursor='cursor-1',
                ),
            ]
        )

        modified.refresh_from_db()
        removed.refresh_from_db()
        self.assertEqual(modified.amount, Decimal('-99.00'))
        self.assertEqual(removed.account, self.other_account)
        self.assertEqual(summary.transactions_modified, 0)
        self.assertEqual(summary.transactions_removed, 0)

    def test_sync_transactions_updates_and_removes_current_users_rows(self):
        Transaction.objects.create(
            account=self.account,
            external_id='tx-modified',
            date=date(2026, 7, 9),
            amount=Decimal('-99.00'),
            category='Old',
            description='Old row',
            source='api',
        )
        Transaction.objects.create(
            account=self.account,
            external_id='tx-removed',
            date=date(2026, 7, 9),
            amount=Decimal('-50.00'),
            category='Old',
            description='Removed row',
            source='api',
        )

        _, summary = self.run_sync(
            [
                self.response(
                    modified=[self.plaid_transaction('tx-modified', amount=20.00)],
                    removed=[SimpleNamespace(transaction_id='tx-removed')],
                    next_cursor='cursor-1',
                ),
            ]
        )

        modified = Transaction.objects.get(account=self.account, external_id='tx-modified')
        self.assertEqual(modified.amount, Decimal('-20.00'))
        self.assertFalse(
            Transaction.objects.filter(account=self.account, external_id='tx-removed').exists()
        )
        self.assertEqual(summary.transactions_modified, 1)
        self.assertEqual(summary.transactions_removed, 1)

    @patch('data_integration.plaid_sync._sync_transactions')
    @patch('data_integration.plaid_sync._sync_accounts', return_value={})
    @patch('data_integration.plaid_client.get_institution_name', return_value='Sandbox Bank')
    @patch('data_integration.plaid_client.exchange_public_token')
    def test_link_rejects_cross_user_item_without_changing_owner_or_token(
        self,
        exchange_public_token,
        _get_institution_name,
        _sync_accounts_mock,
        _sync_transactions_mock,
    ):
        exchange_public_token.return_value = {
            'item_id': self.item.item_id,
            'access_token': 'attacker-token',
        }

        with self.assertRaises(PlaidItemOwnershipError):
            link_and_sync(self.other_user, 'public-sandbox-token')

        self.item.refresh_from_db()
        self.assertEqual(self.item.user, self.user)
        self.assertEqual(self.item.get_access_token(), 'access-sync')
        _sync_accounts_mock.assert_not_called()
        _sync_transactions_mock.assert_not_called()


class PlaidResyncCommandTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username='resync-user', password='x')
        self.other_user = User.objects.create_user(username='other-resync-user', password='x')
        self.item = self.create_item(self.user, 'item-resync', 'Ridge Bank')
        self.other_item = self.create_item(self.other_user, 'item-other-resync', 'River Bank')

    def create_item(self, user, item_id, institution):
        item = PlaidItem(user=user, item_id=item_id, institution_name=institution)
        item.set_access_token(f'access-{item_id}')
        item.save()
        return item

    @patch.dict(os.environ, {'PLAID_CLIENT_ID': '', 'PLAID_SECRET': ''})
    def test_dry_run_reports_filtered_items_without_plaid_credentials(self):
        stdout = io.StringIO()

        call_command('plaid_resync', '--dry-run', f'--user={self.user.username}', stdout=stdout)

        output = stdout.getvalue()
        self.assertIn('Syncing 1 item(s)...', output)
        self.assertIn(f'- processing linked item {self.item.pk}', output)
        self.assertNotIn('resync-user', output)
        self.assertNotIn('Ridge Bank', output)
        self.assertNotIn('other-resync-user', output)
        self.item.refresh_from_db()
        self.assertIsNone(self.item.last_synced_at)

    @patch.dict(os.environ, {'PLAID_CLIENT_ID': '', 'PLAID_SECRET': ''})
    def test_dry_run_honors_stale_hours_filter_without_side_effects(self):
        self.item.last_synced_at = timezone.now()
        self.item.save(update_fields=['last_synced_at'])
        self.other_item.last_synced_at = timezone.now() - timedelta(hours=48)
        self.other_item.save(update_fields=['last_synced_at'])
        stdout = io.StringIO()

        call_command('plaid_resync', '--dry-run', '--stale-hours=24', stdout=stdout)

        output = stdout.getvalue()
        self.assertIn('Syncing 1 item(s)...', output)
        self.assertIn(f'- processing linked item {self.other_item.pk}', output)
        self.assertNotIn('other-resync-user', output)
        self.assertNotIn('River Bank', output)
        self.assertNotIn(f'- processing linked item {self.item.pk}', output)
        self.other_item.refresh_from_db()
        self.assertLess(self.other_item.last_synced_at, timezone.now() - timedelta(hours=24))

    @patch.dict(os.environ, {'PLAID_CLIENT_ID': '', 'PLAID_SECRET': ''})
    def test_resync_requires_plaid_credentials_when_not_dry_run(self):
        with self.assertRaisesMessage(CommandError, 'Plaid is not configured'):
            call_command('plaid_resync', stdout=io.StringIO())


# ---------- Legacy model + view tests, kept passing ----------


class AccountModelTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='m1', password='x')
        self.account = Account.objects.create(user=self.user, name='Test Checking', type='checking')

    def test_account_str(self):
        self.assertIn('Test Checking', str(self.account))


class TransactionModelTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='m2', password='x')
        self.account = Account.objects.create(user=self.user, name='Test Checking', type='checking')
        self.transaction = Transaction.objects.create(
            account=self.account,
            date='2026-03-18',
            amount=100.00,
            category='Groceries',
            description='Test',
            source='manual',
        )

    def test_transaction_str(self):
        self.assertIn('Groceries', str(self.transaction))


class InvestmentModelTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='m3', password='x')
        self.account = Account.objects.create(
            user=self.user, name='Test Investment', type='investment'
        )
        self.investment = Investment.objects.create(
            account=self.account,
            name='Test Fund',
            type='mutual',
            value=1000.00,
            quantity=10,
            symbol='TST',
            as_of='2026-03-18',
        )

    def test_investment_str(self):
        self.assertIn('Test Fund', str(self.investment))


class DebtModelTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='m4', password='x')
        self.account = Account.objects.create(user=self.user, name='Test Debt', type='debt')
        self.debt = Debt.objects.create(
            account=self.account,
            name='Test Loan',
            principal=5000.00,
            interest_rate=5.0,
            balance=4500.00,
            due_date='2026-04-01',
            as_of='2026-03-18',
        )

    def test_debt_str(self):
        self.assertIn('Test Loan', str(self.debt))


class DataIntegrationViewsTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='viewer',
            password='x',
            two_factor_enabled=True,
        )
        self.account = Account.objects.create(user=self.user, name='Checking', type='checking')
        self.other_user = get_user_model().objects.create_user(
            username='other-viewer',
            password='x',
            two_factor_enabled=True,
        )
        self.other_account = Account.objects.create(
            user=self.other_user,
            name='Other Checking',
            type='checking',
        )
        self.debt_account = Account.objects.create(
            user=self.user,
            name='Auto Loan',
            type='debt',
        )
        self.other_debt_account = Account.objects.create(
            user=self.other_user,
            name='Other Auto Loan',
            type='debt',
        )
        force_login_with_otp(self.client, self.user)

    def test_connect_plaid_view(self):
        response = self.client.get(reverse('data_integration:connect_plaid'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'data_integration/connect_plaid.html')

    @patch.dict(os.environ, {'PLAID_CLIENT_ID': '', 'PLAID_SECRET': ''})
    def test_plaid_link_token_returns_configuration_error_when_unconfigured(self):
        response = self.client.post(reverse('data_integration:plaid_link_token'))
        self.assertEqual(response.status_code, 503)
        self.assertIn('PLAID_CLIENT_ID', response.json()['error'])

    @patch('data_integration.plaid_client.create_link_token')
    def test_plaid_link_token_redacts_unexpected_errors(self, create_link_token):
        create_link_token.side_effect = RuntimeError('provider secret leaked')

        with self.assertLogs('data_integration.views', level='ERROR') as logs:
            response = self.client.post(reverse('data_integration:plaid_link_token'))

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()['error'], 'Plaid is temporarily unavailable.')
        self.assertNotIn('provider secret leaked', response.content.decode('utf-8'))
        self.assertIn('Failed to create Plaid link token', '\n'.join(logs.output))

    def test_plaid_link_token_rejects_get(self):
        response = self.client.get(reverse('data_integration:plaid_link_token'))
        self.assertEqual(response.status_code, 405)
        self.assertEqual(response.json()['error'], 'POST required.')

    def test_plaid_exchange_requires_public_token(self):
        response = self.client.post(reverse('data_integration:plaid_exchange'))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['error'], 'public_token is required.')

    @patch.dict(os.environ, {'PLAID_CLIENT_ID': '', 'PLAID_SECRET': ''})
    def test_plaid_exchange_returns_configuration_error_when_unconfigured(self):
        response = self.client.post(
            reverse('data_integration:plaid_exchange'),
            {
                'public_token': 'public-sandbox-test',
            },
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn('PLAID_CLIENT_ID', response.json()['error'])

    @patch('data_integration.plaid_sync.link_and_sync')
    def test_plaid_exchange_redacts_unexpected_errors(self, link_and_sync):
        link_and_sync.side_effect = RuntimeError('raw access token leaked')

        with self.assertLogs('data_integration.views', level='ERROR') as logs:
            response = self.client.post(
                reverse('data_integration:plaid_exchange'),
                {
                    'public_token': 'public-sandbox-test',
                },
            )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()['error'], 'Plaid sync is temporarily unavailable.')
        self.assertNotIn('raw access token leaked', response.content.decode('utf-8'))
        self.assertIn('Failed to exchange Plaid public token', '\n'.join(logs.output))

    @patch('data_integration.plaid_sync.link_and_sync')
    def test_plaid_exchange_returns_stable_conflict_for_cross_user_item(self, sync):
        sync.side_effect = PlaidItemOwnershipError('sensitive ownership detail')

        with self.assertLogs('data_integration.views', level='WARNING'):
            response = self.client.post(
                reverse('data_integration:plaid_exchange'),
                {
                    'public_token': 'public-sandbox-test',
                },
            )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json()['error'],
            'This bank connection is already linked to another account.',
        )
        self.assertNotIn('sensitive ownership detail', response.content.decode('utf-8'))

    def test_manual_account_entry_view(self):
        response = self.client.get(reverse('data_integration:manual_account_entry'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'data_integration/manual_account_entry.html')

    def test_manual_account_entry_redirects_incomplete_user_to_onboarding(self):
        response = self.client.post(
            reverse('data_integration:manual_account_entry'),
            {
                'name': 'Savings',
                'type': 'savings',
                'institution': 'Local Credit Union',
            },
        )
        self.assertRedirects(response, reverse('accounts:onboarding'))
        self.assertTrue(Account.objects.filter(user=self.user, name='Savings').exists())

    def test_manual_account_entry_redirects_complete_user_to_portfolio(self):
        self.user.profile_complete = True
        self.user.save()
        response = self.client.post(
            reverse('data_integration:manual_account_entry'),
            {
                'name': 'Brokerage',
                'type': 'investment',
                'institution': 'Local Broker',
            },
        )
        self.assertRedirects(response, reverse('investments:portfolio_overview'))
        self.assertTrue(Account.objects.filter(user=self.user, name='Brokerage').exists())

    def test_manual_account_entry_requires_name_and_type(self):
        response = self.client.post(
            reverse('data_integration:manual_account_entry'),
            {
                'name': '',
                'type': '',
                'institution': 'Local Credit Union',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].has_error('name', 'required'))
        self.assertTrue(response.context['form'].has_error('type', 'required'))
        self.assertFalse(
            Account.objects.filter(user=self.user, institution='Local Credit Union').exists()
        )

    def test_manual_transaction_entry_view(self):
        response = self.client.get(reverse('data_integration:manual_transaction_entry'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'data_integration/manual_transaction_entry.html')

    def test_manual_transaction_entry_redirects_to_portfolio(self):
        response = self.client.post(
            reverse('data_integration:manual_transaction_entry'),
            {
                'account': self.account.pk,
                'date': '2026-07-09',
                'amount': '42.50',
                'category': 'Groceries',
                'description': 'Market',
            },
        )
        self.assertRedirects(response, reverse('investments:portfolio_overview'))
        transaction = Transaction.objects.get(account=self.account, category='Groceries')
        self.assertEqual(transaction.source, 'manual')

    def test_manual_transaction_entry_forces_manual_source(self):
        response = self.client.post(
            reverse('data_integration:manual_transaction_entry'),
            {
                'account': self.account.pk,
                'date': '2026-07-09',
                'amount': '42.50',
                'category': 'Groceries',
                'description': 'Forged source',
                'source': 'api',
            },
        )

        self.assertRedirects(response, reverse('investments:portfolio_overview'))
        transaction = Transaction.objects.get(account=self.account, description='Forged source')
        self.assertEqual(transaction.source, 'manual')

    def test_manual_transaction_rejects_another_users_account(self):
        response = self.client.post(
            reverse('data_integration:manual_transaction_entry'),
            {
                'account': self.other_account.pk,
                'date': '2026-07-09',
                'amount': '42.50',
                'category': 'Leaked',
                'description': 'Wrong account',
                'source': 'manual',
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Transaction.objects.filter(account=self.other_account).exists())
        self.assertFormError(
            response.context['form'],
            'account',
            'Select a valid choice. That choice is not one of the available choices.',
        )

    def test_manual_transaction_entry_rejects_invalid_required_fields(self):
        response = self.client.post(
            reverse('data_integration:manual_transaction_entry'),
            {
                'account': self.account.pk,
                'date': 'not-a-date',
                'amount': 'not-a-number',
                'category': '',
                'description': 'Invalid transaction',
                'source': 'manual',
            },
        )

        self.assertEqual(response.status_code, 200)
        form = response.context['form']
        self.assertTrue(form.has_error('date', 'invalid'))
        self.assertTrue(form.has_error('amount', 'invalid'))
        self.assertTrue(form.has_error('category', 'required'))
        self.assertFalse(
            Transaction.objects.filter(
                account=self.account, description='Invalid transaction'
            ).exists()
        )

    def test_csv_upload_view(self):
        response = self.client.get(reverse('data_integration:csv_upload'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'data_integration/csv_upload.html')

    def test_csv_upload_imports_transactions_for_selected_account(self):
        upload = SimpleUploadedFile(
            'transactions.csv',
            (
                b'date,amount,category,description\n'
                b'2026-07-09,-42.50,Groceries,Market\n'
                b'2026-07-10,1500.00,Salary,Payroll\n'
            ),
            content_type='text/csv',
        )

        response = self.client.post(
            reverse('data_integration:csv_upload'),
            {
                'account': self.account.pk,
                'file': upload,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'data_integration/csv_upload.html')
        self.assertContains(response, 'Imported 2 transaction(s).')
        self.assertEqual(Transaction.objects.filter(account=self.account, source='csv').count(), 2)
        self.assertTrue(
            Transaction.objects.filter(account=self.account, category='Groceries').exists()
        )

    def test_csv_upload_rejects_another_users_account(self):
        upload = SimpleUploadedFile(
            'transactions.csv',
            b'date,amount,category\n2026-07-09,-42.50,Leaked\n',
            content_type='text/csv',
        )

        response = self.client.post(
            reverse('data_integration:csv_upload'),
            {
                'account': self.other_account.pk,
                'file': upload,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Transaction.objects.filter(account=self.other_account).exists())
        self.assertFormError(
            response.context['form'],
            'account',
            'Select a valid choice. That choice is not one of the available choices.',
        )

    def test_manual_debt_entry_rejects_invalid_required_fields(self):
        response = self.client.post(
            reverse('data_integration:manual_debt_entry'),
            {
                'account': self.debt_account.pk,
                'name': '',
                'principal': 'not-a-number',
                'interest_rate': 'bad-rate',
                'balance': '',
                'minimum_payment': 'bad-payment',
                'due_date': 'not-a-date',
                'as_of': '',
            },
        )

        self.assertEqual(response.status_code, 200)
        form = response.context['form']
        self.assertTrue(form.has_error('name', 'required'))
        self.assertTrue(form.has_error('principal', 'invalid'))
        self.assertTrue(form.has_error('interest_rate', 'invalid'))
        self.assertTrue(form.has_error('balance', 'required'))
        self.assertTrue(form.has_error('minimum_payment', 'invalid'))
        self.assertTrue(form.has_error('due_date', 'invalid'))
        self.assertTrue(form.has_error('as_of', 'required'))
        self.assertFalse(Debt.objects.filter(account=self.debt_account, name='').exists())

    def test_manual_debt_entry_rejects_values_outside_server_bounds(self):
        response = self.client.post(
            reverse('data_integration:manual_debt_entry'),
            {
                'account': self.debt_account.pk,
                'name': 'Impossible Debt',
                'principal': '-1.00',
                'interest_rate': '101.00',
                'balance': '-5.00',
                'minimum_payment': '-10.00',
                'due_date': '2026-08-15',
                'as_of': '2026-07-15',
            },
        )

        self.assertEqual(response.status_code, 200)
        form = response.context['form']
        self.assertTrue(form.has_error('principal'))
        self.assertTrue(form.has_error('interest_rate'))
        self.assertTrue(form.has_error('balance'))
        self.assertTrue(form.has_error('minimum_payment'))
        self.assertFalse(
            Debt.objects.filter(account=self.debt_account, name='Impossible Debt').exists()
        )

    def test_manual_debt_entry_view(self):
        response = self.client.get(reverse('data_integration:manual_debt_entry'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'data_integration/manual_debt_entry.html')

    def test_manual_debt_entry_creates_debt_for_selected_account(self):
        response = self.client.post(
            reverse('data_integration:manual_debt_entry'),
            {
                'account': self.debt_account.pk,
                'name': 'Auto Loan Balance',
                'principal': '24000.00',
                'interest_rate': '6.25',
                'balance': '19000.00',
                'minimum_payment': '425.00',
                'due_date': '2026-08-15',
                'as_of': '2026-07-09',
            },
        )

        self.assertRedirects(response, reverse('debt_management:debt_dashboard'))
        debt = Debt.objects.get(account=self.debt_account, name='Auto Loan Balance')
        self.assertEqual(debt.balance, Decimal('19000.00'))
        self.assertEqual(debt.minimum_payment, Decimal('425.00'))

    def test_manual_debt_entry_rejects_another_users_account(self):
        response = self.client.post(
            reverse('data_integration:manual_debt_entry'),
            {
                'account': self.other_debt_account.pk,
                'name': 'Leaked Loan',
                'principal': '24000.00',
                'interest_rate': '6.25',
                'balance': '19000.00',
                'minimum_payment': '425.00',
                'due_date': '2026-08-15',
                'as_of': '2026-07-09',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Debt.objects.filter(account=self.other_debt_account).exists())
        self.assertFormError(
            response.context['form'],
            'account',
            'Select a valid choice. That choice is not one of the available choices.',
        )
