# data_integration/forms.py
from django import forms
from .models import Account, Transaction

class ManualAccountForm(forms.ModelForm):
    class Meta:
        model = Account
        fields = ['name', 'type', 'institution']

class ManualTransactionForm(forms.ModelForm):
    class Meta:
        model = Transaction
        fields = ['account', 'date', 'amount', 'category', 'description', 'source']

class CSVUploadForm(forms.Form):
    file = forms.FileField()
