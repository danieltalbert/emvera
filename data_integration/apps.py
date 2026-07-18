from django.apps import AppConfig


class DataIntegrationConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'data_integration'

    def ready(self):
        # Register integration-specific deployment checks after app loading.
        from . import checks  # noqa: F401
