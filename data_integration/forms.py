# data_integration/forms.py
from decimal import Decimal

from django import forms
from .models import Account, Debt, Transaction


MIN_MONEY_VALUE = Decimal('0.00')
MIN_INTEREST_RATE = Decimal('0.00')
MAX_INTEREST_RATE = Decimal('100.00')

class ManualAccountForm(forms.ModelForm):
    class Meta:
        model = Account
        fields = ['name', 'type', 'institution']

class ManualTransactionForm(forms.ModelForm):
    class Meta:
        model = Transaction
        fields = ['account', 'date', 'amount', 'category', 'description', 'source']

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields['account'].queryset = Account.objects.filter(user=user)

class ManualDebtForm(forms.ModelForm):
    class Meta:
        model = Debt
        fields = [
            'account',
            'name',
            'principal',
            'interest_rate',
            'balance',
            'minimum_payment',
            'due_date',
            'as_of',
        ]
        widgets = {
            'due_date': forms.DateInput(attrs={'type': 'date'}),
            'as_of': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields['account'].queryset = Account.objects.filter(
                user=user, type__in=['credit', 'debt']
            )

    def clean_principal(self):
        principal = self.cleaned_data['principal']
        if principal < MIN_MONEY_VALUE:
            raise forms.ValidationError('Original principal cannot be negative.')
        return principal

    def clean_interest_rate(self):
        interest_rate = self.cleaned_data['interest_rate']
        if interest_rate < MIN_INTEREST_RATE or interest_rate > MAX_INTEREST_RATE:
            raise forms.ValidationError('APR must be between 0 and 100.')
        return interest_rate

    def clean_balance(self):
        balance = self.cleaned_data['balance']
        if balance < MIN_MONEY_VALUE:
            raise forms.ValidationError('Current balance cannot be negative.')
        return balance

    def clean_minimum_payment(self):
        minimum_payment = self.cleaned_data.get('minimum_payment')
        if minimum_payment is not None and minimum_payment < MIN_MONEY_VALUE:
            raise forms.ValidationError('Minimum payment cannot be negative.')
        return minimum_payment

class CSVUploadForm(forms.Form):
    account = forms.ModelChoiceField(queryset=Account.objects.none())
    file = forms.FileField()

    MAX_BYTES = 10 * 1024 * 1024  # 10 MB

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields['account'].queryset = Account.objects.filter(user=user)

    def clean_file(self):
        f = self.cleaned_data['file']
        if f.size > self.MAX_BYTES:
            raise forms.ValidationError('File is larger than 10 MB.')
        name = (f.name or '').lower()
        if not name.endswith('.csv'):
            raise forms.ValidationError('Please upload a .csv file.')
        return f
