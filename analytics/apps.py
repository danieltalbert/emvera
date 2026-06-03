"""AppConfig for the analytics app."""

from django.apps import AppConfig


class AnalyticsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'analytics'
    verbose_name = 'Analytics & ML'

    def ready(self):
        # Swap the Django admin home page for one that links to the staff
        # Analytics & ML dashboard, so admin users discover it from /admin/.
        from django.contrib import admin
        admin.site.index_template = 'admin/analytics_index.html'
