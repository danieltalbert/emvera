from django.conf import settings
from django.core.checks import Error, Tags, register


@register(Tags.security, deploy=True)
def production_database_backend_check(app_configs, **kwargs):
    """Reject the local SQLite fallback during a production deployment review."""
    engine = settings.DATABASES.get('default', {}).get('ENGINE', '')
    if engine != 'django.db.backends.postgresql':
        return [
            Error(
                'Production is not configured to use PostgreSQL.',
                hint='Set DATABASE_URL to the managed PostgreSQL connection string.',
                id='emvera.E005',
            )
        ]
    return []


@register(Tags.security, deploy=True)
def production_allowed_hosts_check(app_configs, **kwargs):
    """Prevent an unrestricted Host header policy from reaching production."""
    if not settings.ALLOWED_HOSTS or '*' in settings.ALLOWED_HOSTS:
        return [
            Error(
                'Production hosts are empty or unrestricted.',
                hint='Set DJANGO_ALLOWED_HOSTS to the exact application hostnames.',
                id='emvera.E006',
            )
        ]
    return []


@register(Tags.security, deploy=True)
def production_database_tls_check(app_configs, **kwargs):
    """Require encrypted transport for the configured PostgreSQL connection."""
    database = settings.DATABASES.get('default', {})
    if database.get('ENGINE') != 'django.db.backends.postgresql':
        return []
    sslmode = database.get('OPTIONS', {}).get('sslmode', '')
    if sslmode not in {'require', 'verify-ca', 'verify-full'}:
        return [
            Error(
                'Production PostgreSQL transport encryption is disabled or opportunistic.',
                hint='Set DJANGO_DB_SSLMODE to require, verify-ca, or verify-full.',
                id='emvera.E007',
            )
        ]
    return []
