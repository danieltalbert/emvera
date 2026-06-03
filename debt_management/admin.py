"""Django admin registrations for the debt management app."""

from django.contrib import admin

from .models import CreditScore, PaymentReminder


@admin.register(CreditScore)
class CreditScoreAdmin(admin.ModelAdmin):
    list_display = ('user', 'score', 'band', 'bureau', 'recorded_on')
    list_filter = ('bureau',)
    search_fields = ('user__username', 'user__email')
    date_hierarchy = 'recorded_on'


@admin.register(PaymentReminder)
class PaymentReminderAdmin(admin.ModelAdmin):
    list_display = ('user', 'name', 'amount', 'due_date', 'is_paid')
    list_filter = ('is_paid', 'notify_via_email')
    search_fields = ('user__username', 'name', 'institution')
    date_hierarchy = 'due_date'
