"""Django admin registrations for the paper trading app."""

from django.contrib import admin

from .models import PaperAccount, PaperPosition, PaperOrder


@admin.register(PaperAccount)
class PaperAccountAdmin(admin.ModelAdmin):
    list_display = ('user', 'competition', 'cash', 'starting_cash', 'created_at')
    search_fields = ('user__username',)
    list_filter = ('competition',)


@admin.register(PaperPosition)
class PaperPositionAdmin(admin.ModelAdmin):
    list_display = ('account', 'symbol', 'quantity', 'avg_cost')
    search_fields = ('symbol', 'account__user__username')


@admin.register(PaperOrder)
class PaperOrderAdmin(admin.ModelAdmin):
    list_display = ('account', 'side', 'symbol', 'quantity', 'fill_price', 'status', 'created_at')
    list_filter = ('status', 'side')
    search_fields = ('symbol', 'account__user__username')
