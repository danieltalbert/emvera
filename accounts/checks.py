from django.conf import settings
from django.core.checks import Error, Tags, register


@register(Tags.security, deploy=True)
def production_email_backend_check(app_configs, **kwargs):
    """Fail deployment validation when account tokens have nowhere safe to go."""
    unsafe_backends = {
        'django.core.mail.backends.console.EmailBackend',
        'django.core.mail.backends.dummy.EmailBackend',
    }
    if not settings.DEBUG and settings.EMAIL_BACKEND in unsafe_backends:
        return [
            Error(
                'Production email delivery is not configured.',
                hint='Set EMAIL_HOST and SMTP credentials before deployment.',
                id='emvera.E001',
            )
        ]
    return []
