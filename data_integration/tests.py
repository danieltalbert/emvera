import io
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from .crypto import PREFIX, decrypt, encrypt
from .csv_import import _parse_amount, _parse_date, _resolve_columns, import_transactions
from .models import Account, Debt, Investment, PlaidItem, Transaction


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
        csv = (
            'date,amount,category\n'
            '2026-01-15,10.00,Coffee\n'
            'bad,bad,bad\n'
            '2026-01-17,,Lunch\n'
        )
        result = self._import(csv)
        self.assertEqual(result.created, 1)
        self.assertEqual(result.skipped, 2)
        self.assertTrue(any('Line 3' in e for e in result.row_errors))
        self.assertTrue(any('Line 4' in e for e in result.row_errors))

    def test_empty_file(self):
        result = self._import('')
        self.assertEqual(result.created, 0)
        self.assertTrue(result.row_errors)


# ---------- Crypto helper + PlaidItem token round-trip ----------

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
            account=self.account, date='2026-03-18', amount=100.00,
            category='Groceries', description='Test', source='manual',
        )

    def test_transaction_str(self):
        self.assertIn('Groceries', str(self.transaction))


class InvestmentModelTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='m3', password='x')
        self.account = Account.objects.create(user=self.user, name='Test Investment', type='investment')
        self.investment = Investment.objects.create(
            account=self.account, name='Test Fund', type='mutual',
            value=1000.00, quantity=10, symbol='TST', as_of='2026-03-18',
        )

    def test_investment_str(self):
        self.assertIn('Test Fund', str(self.investment))


class DebtModelTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='m4', password='x')
        self.account = Account.objects.create(user=self.user, name='Test Debt', type='debt')
        self.debt = Debt.objects.create(
            account=self.account, name='Test Loan', principal=5000.00,
            interest_rate=5.0, balance=4500.00, due_date='2026-04-01', as_of='2026-03-18',
        )

    def test_debt_str(self):
        self.assertIn('Test Loan', str(self.debt))


class DataIntegrationViewsTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='viewer', password='x', two_factor_enabled=True,
        )
        self.account = Account.objects.create(user=self.user, name='Checking', type='checking')
        self.other_user = get_user_model().objects.create_user(
            username='other-viewer', password='x', two_factor_enabled=True,
        )
        self.other_account = Account.objects.create(
            user=self.other_user, name='Other Checking', type='checking',
        )
        self.client.login(username='viewer', password='x')

    def test_connect_plaid_view(self):
        response = self.client.get(reverse('data_integration:connect_plaid'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'data_integration/connect_plaid.html')

    def test_manual_account_entry_view(self):
        response = self.client.get(reverse('data_integration:manual_account_entry'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'data_integration/manual_account_entry.html')

    def test_manual_account_entry_redirects_incomplete_user_to_onboarding(self):
        response = self.client.post(reverse('data_integration:manual_account_entry'), {
            'name': 'Savings',
            'type': 'savings',
            'institution': 'Local Credit Union',
        })
        self.assertRedirects(response, reverse('accounts:onboarding'))
        self.assertTrue(Account.objects.filter(user=self.user, name='Savings').exists())

    def test_manual_account_entry_redirects_complete_user_to_portfolio(self):
        self.user.profile_complete = True
        self.user.save()
        response = self.client.post(reverse('data_integration:manual_account_entry'), {
            'name': 'Brokerage',
            'type': 'investment',
            'institution': 'Local Broker',
        })
        self.assertRedirects(response, reverse('investments:portfolio_overview'))
        self.assertTrue(Account.objects.filter(user=self.user, name='Brokerage').exists())

    def test_manual_transaction_entry_view(self):
        response = self.client.get(reverse('data_integration:manual_transaction_entry'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'data_integration/manual_transaction_entry.html')

    def test_manual_transaction_entry_redirects_to_portfolio(self):
        response = self.client.post(reverse('data_integration:manual_transaction_entry'), {
            'account': self.account.pk,
            'date': '2026-07-09',
            'amount': '42.50',
            'category': 'Groceries',
            'description': 'Market',
            'source': 'manual',
        })
        self.assertRedirects(response, reverse('investments:portfolio_overview'))
        self.assertTrue(Transaction.objects.filter(account=self.account, category='Groceries').exists())

    def test_manual_transaction_rejects_another_users_account(self):
        response = self.client.post(reverse('data_integration:manual_transaction_entry'), {
            'account': self.other_account.pk,
            'date': '2026-07-09',
            'amount': '42.50',
            'category': 'Leaked',
            'description': 'Wrong account',
            'source': 'manual',
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Transaction.objects.filter(account=self.other_account).exists())
        self.assertFormError(
            response.context['form'],
            'account',
            'Select a valid choice. That choice is not one of the available choices.',
        )

    def test_csv_upload_view(self):
        response = self.client.get(reverse('data_integration:csv_upload'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'data_integration/csv_upload.html')

    def test_manual_debt_entry_view(self):
        response = self.client.get(reverse('data_integration:manual_debt_entry'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'data_integration/manual_debt_entry.html')
