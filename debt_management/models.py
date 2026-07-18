"""
Debt management models.

These supplement the shared Debt model in data_integration with:
- CreditScore: per-user history of credit score values for trend tracking.
- PaymentReminder: user-defined payment reminders, optionally linked to a Debt.
"""

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from data_integration.models import Debt


class CreditScore(models.Model):
    BUREAU_CHOICES = [
        ('experian', 'Experian'),
        ('equifax', 'Equifax'),
        ('transunion', 'TransUnion'),
        ('vantage', 'VantageScore'),
        ('other', 'Other / Unknown'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='credit_scores',
    )
    score = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(300), MaxValueValidator(850)],
    )
    bureau = models.CharField(max_length=20, choices=BUREAU_CHOICES, default='other')
    recorded_on = models.DateField()
    notes = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-recorded_on', '-created_at']

    def __str__(self):
        return f'{self.user} — {self.score} ({self.recorded_on})'

    @property
    def band(self):
        if self.score >= 800:
            return 'Excellent'
        if self.score >= 740:
            return 'Very Good'
        if self.score >= 670:
            return 'Good'
        if self.score >= 580:
            return 'Fair'
        return 'Poor'


class PaymentReminder(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='payment_reminders',
    )
    debt = models.ForeignKey(
        Debt,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='reminders',
    )
    name = models.CharField(max_length=120)
    institution = models.CharField(max_length=120, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    due_date = models.DateField()
    is_paid = models.BooleanField(default=False)
    paid_on = models.DateField(null=True, blank=True)
    notify_via_email = models.BooleanField(default=True)
    notify_via_sms = models.BooleanField(default=False)
    notify_days_before = models.PositiveSmallIntegerField(default=3)
    email_last_notified_at = models.DateTimeField(null=True, blank=True)
    sms_last_notified_at = models.DateTimeField(null=True, blank=True)
    last_notified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['due_date']

    def __str__(self):
        return f'{self.name} — {self.amount} due {self.due_date}'
