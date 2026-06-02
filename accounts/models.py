"""Accounts models: the project's custom user."""
from django.db import models
from django.contrib.auth.models import AbstractUser


class CustomUser(AbstractUser):
    """Project user (AUTH_USER_MODEL).

    Extends Django's user with onboarding/2FA flags and an optional phone
    number used for SMS payment reminders.
    """
    profile_complete = models.BooleanField(default=False)
    two_factor_enabled = models.BooleanField(default=False)
    phone_number = models.CharField(
        max_length=20,
        blank=True,
        help_text='E.164 format (e.g. +15551234567). Required for SMS reminders.',
    )

    class Meta:
        app_label = 'accounts'
