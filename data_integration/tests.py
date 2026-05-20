from django.test import TestCase
from django.urls import reverse
from .models import Account, Transaction, Investment, Debt
from django.contrib.auth import get_user_model

class AccountModelTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='testuser', password='testpass')
        self.account = Account.objects.create(user=self.user, name='Test Checking', type='checking')

    def test_account_str(self):
        self.assertIn('Test Checking', str(self.account))

class TransactionModelTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='testuser', password='testpass')
        self.account = Account.objects.create(user=self.user, name='Test Checking', type='checking')
        self.transaction = Transaction.objects.create(account=self.account, date='2026-03-18', amount=100.00, category='Groceries', description='Test', source='manual')

    def test_transaction_str(self):
        self.assertIn('Groceries', str(self.transaction))

class InvestmentModelTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='testuser', password='testpass')
        self.account = Account.objects.create(user=self.user, name='Test Investment', type='investment')
        self.investment = Investment.objects.create(account=self.account, name='Test Fund', type='mutual', value=1000.00, quantity=10, symbol='TST', as_of='2026-03-18')

    def test_investment_str(self):
        self.assertIn('Test Fund', str(self.investment))

class DebtModelTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='testuser', password='testpass')
        self.account = Account.objects.create(user=self.user, name='Test Debt', type='debt')
        self.debt = Debt.objects.create(account=self.account, name='Test Loan', principal=5000.00, interest_rate=5.0, balance=4500.00, due_date='2026-04-01', as_of='2026-03-18')

    def test_debt_str(self):
        self.assertIn('Test Loan', str(self.debt))

class DataIntegrationViewsTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='testuser', password='testpass')
        self.client.login(username='testuser', password='testpass')

    def test_connect_plaid_view(self):
        response = self.client.get(reverse('data_integration:connect_plaid'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'data_integration/connect_plaid.html')

    def test_manual_account_entry_view(self):
        response = self.client.get(reverse('data_integration:manual_account_entry'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'data_integration/manual_account_entry.html')

    def test_manual_transaction_entry_view(self):
        response = self.client.get(reverse('data_integration:manual_transaction_entry'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'data_integration/manual_transaction_entry.html')

    def test_csv_upload_view(self):
        response = self.client.get(reverse('data_integration:csv_upload'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'data_integration/csv_upload.html')
