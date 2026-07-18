from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower


class CustomUser(AbstractUser):
    profile_complete = models.BooleanField(default=False)
    two_factor_enabled = models.BooleanField(default=False)
    phone_number = models.CharField(
        max_length=20,
        blank=True,
        help_text='E.164 format (e.g. +15551234567). Required for SMS reminders.',
    )

    class Meta:
        app_label = 'accounts'
        constraints = [
            models.UniqueConstraint(
                Lower('email'),
                condition=~Q(email=''),
                name='unique_customuser_email_ci',
            )
        ]
