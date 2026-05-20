# data_integration/admin.py
from django.contrib import admin
from .models import Account, Transaction, Investment, Debt

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
    list_display = ('account', 'name', 'balance', 'interest_rate', 'as_of')
    search_fields = ('name', 'account__name')
