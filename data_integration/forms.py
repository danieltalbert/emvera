"""Form definitions for the data integration app."""
# data_integration/forms.py
from django import forms
from .models import Account, Debt, Transaction

class ManualAccountForm(forms.ModelForm):
    class Meta:
        model = Account
        fields = ['name', 'type', 'institution']

class ManualTransactionForm(forms.ModelForm):
    class Meta:
        model = Transaction
        fields = ['account', 'date', 'amount', 'category', 'description', 'source']

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
