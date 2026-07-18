from django.apps import AppConfig
from django.contrib.admin.apps import AdminConfig


class EmveraAdminConfig(AdminConfig):
    """Install the OTP-enforcing admin site as Django's default admin."""

    default_site = 'core.admin.EmveraAdminSite'


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'

    def ready(self):
        # Deployment-only checks catch infrastructure fallbacks that are safe
        # locally but would lose data or broaden host trust in production.
        from . import checks  # noqa: F401
