"""Versioned at-rest encryption for long-lived provider access tokens.

New production tokens use a dedicated Fernet key so Django's signing key can
rotate independently. Existing ciphertext derived from ``DJANGO_SECRET_KEY``
remains readable and can be rewritten with ``reencrypt_plaid_tokens``.
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

PREFIX = 'enc:'
DEDICATED_PREFIX = 'enc:v2:'


class TokenDecryptionError(RuntimeError):
    """Raised when ciphertext cannot be decrypted with any configured key."""


def _legacy_fernet() -> Fernet:
    digest = hashlib.sha256(settings.SECRET_KEY.encode('utf-8')).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _configured_fernet(raw_key: str) -> Fernet:
    try:
        return Fernet(raw_key.encode('ascii'))
    except (TypeError, ValueError) as exc:
        raise ImproperlyConfigured(
            'Plaid token encryption keys must be URL-safe base64 Fernet keys.'
        ) from exc


def has_dedicated_key() -> bool:
    return bool(getattr(settings, 'PLAID_TOKEN_ENCRYPTION_KEY', ''))


def validate_configured_keys() -> None:
    primary = getattr(settings, 'PLAID_TOKEN_ENCRYPTION_KEY', '')
    if primary:
        _configured_fernet(primary)
    for key in getattr(settings, 'PLAID_TOKEN_ENCRYPTION_PREVIOUS_KEYS', []):
        _configured_fernet(key)


def _dedicated_fernets() -> list[Fernet]:
    keys = []
    primary = getattr(settings, 'PLAID_TOKEN_ENCRYPTION_KEY', '')
    if primary:
        keys.append(_configured_fernet(primary))
    keys.extend(
        _configured_fernet(key)
        for key in getattr(settings, 'PLAID_TOKEN_ENCRYPTION_PREVIOUS_KEYS', [])
    )
    return keys


def encrypt(plaintext: str) -> str:
    if not plaintext:
        return ''
    if has_dedicated_key():
        fernet = _dedicated_fernets()[0]
        prefix = DEDICATED_PREFIX
    else:
        # Local sandbox compatibility; deployment checks reject this fallback
        # whenever Plaid credentials are enabled in a production check.
        fernet = _legacy_fernet()
        prefix = PREFIX
    token = fernet.encrypt(plaintext.encode('utf-8')).decode('ascii')
    return prefix + token


def decrypt(stored: str) -> str:
    if not stored:
        return ''
    if stored.startswith(DEDICATED_PREFIX):
        token = stored[len(DEDICATED_PREFIX) :].encode('ascii')
        for fernet in _dedicated_fernets():
            try:
                return fernet.decrypt(token).decode('utf-8')
            except InvalidToken:
                continue
        raise TokenDecryptionError('Plaid token could not be decrypted.')
    if stored.startswith(PREFIX):
        try:
            token = stored[len(PREFIX) :].encode('ascii')
            return _legacy_fernet().decrypt(token).decode('utf-8')
        except InvalidToken as exc:
            raise TokenDecryptionError('Plaid token could not be decrypted.') from exc

    # Pre-encryption rows remain readable so the rotation command can migrate
    # them immediately; new writes never use plaintext.
    return stored
