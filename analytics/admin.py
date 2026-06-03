"""Django admin registrations for the analytics app."""

from django.contrib import admin

from .models import PageView


@admin.register(PageView)
class PageViewAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'path', 'section', 'user', 'is_authenticated', 'status_code', 'response_ms')
    list_filter = ('section', 'is_authenticated', 'weekday')
    search_fields = ('path', 'user__username', 'session_hash')
    date_hierarchy = 'timestamp'
    # This table is append-only telemetry; viewing is fine, editing is not.
    readonly_fields = [f.name for f in PageView._meta.fields]

    def has_add_permission(self, request):
        return False
