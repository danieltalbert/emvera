from django.db import models
from django.contrib.auth.models import AbstractUser

class CustomUser(AbstractUser):
    profile_complete = models.BooleanField(default=False)
    two_factor_enabled = models.BooleanField(default=False)

    class Meta:
        app_label = 'accounts'
