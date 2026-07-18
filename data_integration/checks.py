import os

from django.core.checks import Error, Tags, register
from django.core.exceptions import ImproperlyConfigured

from .crypto import has_dedicated_key, validate_configured_keys
from .plaid_client import PlaidNotConfigured, _environment


@register(Tags.security, deploy=True)
def production_plaid_configuration_check(app_configs, **kwargs):
    """Require a valid, independent token key when Plaid credentials are live."""
    errors = []
    has_credentials = bool(os.environ.get('PLAID_CLIENT_ID') and os.environ.get('PLAID_SECRET'))

    if has_credentials:
        try:
            _environment()
        except PlaidNotConfigured as exc:
            errors.append(
                Error(
                    str(exc),
                    id='emvera.E002',
                )
            )
        if not has_dedicated_key():
            errors.append(
                Error(
                    'Plaid token encryption uses the Django signing-key fallback.',
                    hint='Set PLAID_TOKEN_ENCRYPTION_KEY to a generated Fernet key.',
                    id='emvera.E003',
                )
            )

    try:
        validate_configured_keys()
    except ImproperlyConfigured as exc:
        errors.append(Error(str(exc), id='emvera.E004'))
    return errors
