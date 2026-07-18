from django.contrib import admin

from .models import InvestmentProjection, InvestmentRecommendation


@admin.register(InvestmentRecommendation)
class InvestmentRecommendationAdmin(admin.ModelAdmin):
    list_display = (
        'investment',
        'user',
        'recommendation_type',
        'reviewed',
        'created_at',
    )
    list_filter = ('recommendation_type', 'reviewed')
    search_fields = ('investment__name', 'user__username', 'message')
    readonly_fields = ('created_at',)


@admin.register(InvestmentProjection)
class InvestmentProjectionAdmin(admin.ModelAdmin):
    list_display = (
        'investment',
        'user',
        'projection_date',
        'projected_value',
        'growth_rate',
    )
    search_fields = ('investment__name', 'user__username')
    date_hierarchy = 'projection_date'
    readonly_fields = ('created_at',)
