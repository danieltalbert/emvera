# data_integration/admin.py
import hashlib

from django.contrib import admin

from .models import Account, Debt, Investment, PlaidItem, Transaction


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
    list_display = ('user', 'institution_name', 'item_fingerprint', 'last_synced_at')
    search_fields = ('user__username', 'institution_name')
    fields = (
        'user',
        'institution_name',
        'item_fingerprint',
        'token_status',
        'cursor_status',
        'last_synced_at',
        'created_at',
    )
    readonly_fields = fields

    @admin.display(description='Item fingerprint')
    def item_fingerprint(self, obj):
        if not obj or not obj.item_id:
            return 'Not assigned'
        return hashlib.sha256(obj.item_id.encode('utf-8')).hexdigest()[:12]

    @admin.display(description='Access token')
    def token_status(self, obj):
        if not obj or not obj.access_token:
            return 'Missing'
        if obj.access_token.startswith('enc:'):
            return 'Encrypted token present'
        return 'Legacy plaintext token requires rotation'

    @admin.display(description='Sync cursor')
    def cursor_status(self, obj):
        return 'Established' if obj and obj.cursor else 'Not established'

    def has_add_permission(self, request):
        # Provider Items must enter through the ownership-checked Link flow.
        return False
