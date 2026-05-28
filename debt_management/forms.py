from django import forms

from .models import CreditScore, PaymentReminder


class CreditScoreForm(forms.ModelForm):
    class Meta:
        model = CreditScore
        fields = ['score', 'bureau', 'recorded_on', 'notes']
        widgets = {
            'recorded_on': forms.DateInput(attrs={'type': 'date'}),
            'notes': forms.TextInput(),
        }


class PaymentReminderForm(forms.ModelForm):
    class Meta:
        model = PaymentReminder
        fields = [
            'debt',
            'name',
            'institution',
            'amount',
            'due_date',
            'notify_via_email',
            'notify_via_sms',
            'notify_days_before',
        ]
        widgets = {
            'due_date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            from data_integration.models import Debt
            self.fields['debt'].queryset = Debt.objects.filter(account__user=user)
            self.fields['debt'].required = False


class CustomPayoffForm(forms.Form):
    extra_payment = forms.DecimalField(
        min_value=0,
        max_digits=12,
        decimal_places=2,
        required=False,
        widget=forms.NumberInput(attrs={
            'class': 'form-input font-mono',
            'placeholder': '$0.00',
            'step': '10',
        }),
    )
    order = forms.CharField(required=False, widget=forms.HiddenInput())
