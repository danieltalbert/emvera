from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'accounts'

    def ready(self):
        # Import deploy checks only after Django's app registry is ready.
        from . import checks  # noqa: F401
