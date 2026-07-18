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
        self.user = user
        if user is not None:
            from data_integration.models import Debt

            self.fields['debt'].queryset = Debt.objects.filter(account__user=user)
            self.fields['debt'].required = False

    def clean_amount(self):
        amount = self.cleaned_data['amount']
        if amount <= 0:
            raise forms.ValidationError('Amount must be greater than $0.')
        return amount

    def clean(self):
        cleaned_data = super().clean()
        notify_email = cleaned_data.get('notify_via_email')
        notify_sms = cleaned_data.get('notify_via_sms')
        if not notify_email and not notify_sms:
            raise forms.ValidationError('Choose email, SMS, or both for this reminder.')
        if notify_email and self.user is not None and not self.user.email:
            self.add_error('notify_via_email', 'Add an email address to your profile first.')
        if notify_sms and self.user is not None and not self.user.phone_number:
            self.add_error('notify_via_sms', 'Add a phone number to your profile first.')
        return cleaned_data


class CustomPayoffForm(forms.Form):
    extra_payment = forms.DecimalField(
        min_value=0,
        max_digits=12,
        decimal_places=2,
        required=False,
        widget=forms.NumberInput(
            attrs={
                'class': 'form-input font-mono',
                'placeholder': '$0.00',
                'step': '10',
            }
        ),
    )
    order = forms.CharField(required=False, widget=forms.HiddenInput())
