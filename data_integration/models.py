# data_integration/models.py
"""
Models for integrating user financial data from APIs, manual entry, and CSV upload.

- Account: Bank, credit, investment, debt, etc.
- Transaction: Linked to Account, with date, amount, category, and source.
- Investment: Holdings, value, type, linked to Account.
- Debt: Loans, credit cards, balances, linked to Account.

See documentation for required API keys and environment variables for Plaid or similar integrations.
"""
from django.db import models
from django.conf import settings

class Account(models.Model):
    class Meta:
        app_label = 'data_integration'
    ACCOUNT_TYPES = [
        ('checking', 'Checking'),
        ('savings', 'Savings'),
        ('credit', 'Credit Card'),
        ('investment', 'Investment'),
        ('debt', 'Debt'),
    ]
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='accounts')
    name = models.CharField(max_length=100)
    type = models.CharField(max_length=20, choices=ACCOUNT_TYPES)
    institution = models.CharField(max_length=100, blank=True)
    external_id = models.CharField(max_length=128, blank=True, help_text='ID from Plaid or other API')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.get_type_display()})"

class Transaction(models.Model):
    class Meta:
        app_label = 'data_integration'
    SOURCE_CHOICES = [
        ('api', 'API'),
        ('manual', 'Manual'),
        ('csv', 'CSV Upload'),
    ]
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name='transactions')
    date = models.DateField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    category = models.CharField(max_length=100)
    description = models.CharField(max_length=255, blank=True)
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES)
    external_id = models.CharField(max_length=128, blank=True, help_text='ID from Plaid or other API')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.date} {self.amount} {self.category}"

class Investment(models.Model):
    class Meta:
        app_label = 'data_integration'
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name='investments')
    name = models.CharField(max_length=100)
    type = models.CharField(max_length=50)
    value = models.DecimalField(max_digits=14, decimal_places=2)
    quantity = models.DecimalField(max_digits=14, decimal_places=4)
    symbol = models.CharField(max_length=20, blank=True)
    as_of = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.symbol})"

class Debt(models.Model):
    class Meta:
        app_label = 'data_integration'
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name='debts')
    name = models.CharField(max_length=100)
    principal = models.DecimalField(max_digits=14, decimal_places=2)
    interest_rate = models.DecimalField(max_digits=5, decimal_places=2)
    balance = models.DecimalField(max_digits=14, decimal_places=2)
    due_date = models.DateField(null=True, blank=True)
    as_of = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} - {self.balance}"
