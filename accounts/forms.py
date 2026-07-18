from django import forms
from django.contrib.auth.forms import PasswordChangeForm, UserCreationForm

from .models import CustomUser


class LoginForm(forms.Form):
    username = forms.CharField()
    password = forms.CharField(widget=forms.PasswordInput)


class ChangePasswordForm(PasswordChangeForm):
    """Project hook for future password-form policy without changing callers."""


class CustomUserCreationForm(UserCreationForm):
    class Meta:
        model = CustomUser
        fields = ('first_name', 'last_name', 'username', 'email')

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if not email:
            raise forms.ValidationError('Email is required.')
        if CustomUser.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('An account already uses this email address.')
        return email


class ResendVerificationForm(forms.Form):
    email = forms.EmailField()


class ProfileForm(forms.ModelForm):
    phone_number = forms.RegexField(
        regex=r'^\+[1-9]\d{7,14}$',
        required=False,
        error_messages={'invalid': 'Use international E.164 format, such as +15551234567.'},
    )

    class Meta:
        model = CustomUser
        fields = ('first_name', 'last_name', 'phone_number')
