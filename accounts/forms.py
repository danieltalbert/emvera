"""Form definitions for the accounts app."""

from django import forms
from django.contrib.auth.forms import UserCreationForm, PasswordChangeForm
class ChangePasswordForm(PasswordChangeForm):
    pass
from .models import CustomUser

class CustomUserCreationForm(UserCreationForm):
    class Meta:
        model = CustomUser
        fields = ('username', 'email')
        # Add more fields if needed
