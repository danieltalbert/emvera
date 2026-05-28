# data_integration/admin.py
from django.contrib import admin
from .models import Account, Transaction, Investment, Debt, PlaidItem

@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ('name', 'type', 'user', 'institution', 'created_at')
    search_fields = ('name', 'institution', 'user__username')
    list_filter = ('type',)

@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ('account', 'date', 'amount', 'category', 'source')
    search_fields = ('account__name', 'category', 'description')
    list_filter = ('source', 'category')

@admin.register(Investment)
class InvestmentAdmin(admin.ModelAdmin):
    list_display = ('account', 'name', 'type', 'value', 'as_of')
    search_fields = ('name', 'type', 'account__name')

@admin.register(Debt)
class DebtAdmin(admin.ModelAdmin):
    list_display = ('account', 'name', 'balance', 'interest_rate', 'minimum_payment', 'as_of')
    search_fields = ('name', 'account__name')


@admin.register(PlaidItem)
class PlaidItemAdmin(admin.ModelAdmin):
    list_display = ('user', 'institution_name', 'item_id', 'last_synced_at')
    search_fields = ('user__username', 'institution_name', 'item_id')
    readonly_fields = ('access_token', 'cursor', 'last_synced_at', 'created_at')
