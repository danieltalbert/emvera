"""
Lightweight at-rest encryption for sensitive strings (e.g. Plaid access tokens).

The Fernet key is derived from DJANGO_SECRET_KEY so deploys don't need a
separate KMS just for this. If you rotate SECRET_KEY you'll need to re-link
Plaid items; that's the trade-off for not adding a key-management service.

Stored values are prefixed with `enc:` so legacy plaintext values from before
this change keep working — `decrypt()` returns them unchanged.
"""
import base64
import hashlib

from django.conf import settings
from cryptography.fernet import Fernet, InvalidToken


PREFIX = 'enc:'


def _fernet() -> Fernet:
    key = hashlib.sha256(settings.SECRET_KEY.encode('utf-8')).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt(plaintext: str) -> str:
    if not plaintext:
        return ''
    token = _fernet().encrypt(plaintext.encode('utf-8')).decode('ascii')
    return PREFIX + token


def decrypt(stored: str) -> str:
    if not stored:
        return ''
    if not stored.startswith(PREFIX):
        return stored  # legacy plaintext — caller will rewrite on next save
    try:
        return _fernet().decrypt(stored[len(PREFIX):].encode('ascii')).decode('utf-8')
    except InvalidToken:
        return ''
