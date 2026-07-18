"""Environment-driven Django settings for Emvera."""

import os
import sys
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.lower() in {'1', 'true', 'yes', 'on'}


def env_list(name, default=''):
    """Read a comma-separated environment value without retaining whitespace."""
    return [item.strip() for item in os.environ.get(name, default).split(',') if item.strip()]


SECRET_KEY = os.environ['DJANGO_SECRET_KEY']
DEBUG = env_bool('DJANGO_DEBUG')
ALLOWED_HOSTS = env_list('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1')
CSRF_TRUSTED_ORIGINS = env_list('DJANGO_CSRF_TRUSTED_ORIGINS')

# Deployment security stays explicit so local HTTP remains usable. Production
# configuration is validated with `manage.py check --deploy` in CI.
SECURE_SSL_REDIRECT = env_bool('DJANGO_SECURE_SSL_REDIRECT')
SECURE_HSTS_SECONDS = int(os.environ.get('DJANGO_SECURE_HSTS_SECONDS', '0'))
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool('DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS')
SECURE_HSTS_PRELOAD = env_bool('DJANGO_SECURE_HSTS_PRELOAD')
SESSION_COOKIE_SECURE = env_bool('DJANGO_SESSION_COOKIE_SECURE')
CSRF_COOKIE_SECURE = env_bool('DJANGO_CSRF_COOKIE_SECURE')
X_FRAME_OPTIONS = 'DENY'
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'same-origin'
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_AGE = int(os.environ.get('DJANGO_SESSION_COOKIE_AGE', '3600'))
SESSION_SAVE_EVERY_REQUEST = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = env_bool('DJANGO_SESSION_EXPIRE_AT_BROWSER_CLOSE', True)

# Trust this header only behind a controlled TLS-terminating proxy.
if env_bool('DJANGO_TRUST_X_FORWARDED_PROTO'):
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')


INSTALLED_APPS = [
    'core.apps.CoreConfig',
    'core.apps.EmveraAdminConfig',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django_otp',
    'django_otp.plugins.otp_totp',
    'accounts',
    'investments',
    'data_integration',
    'debt_management',
    'competition',
]

MIDDLEWARE = [
    'core.middleware.InternalProbeMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django_otp.middleware.OTPMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'core.urls'
WSGI_APPLICATION = 'core.wsgi.application'
ASGI_APPLICATION = 'core.asgi.application'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]


# SQLite is deliberately development-only. Any configured DATABASE_URL is
# parsed into a persistent production database with connection health checks.
DATABASE_URL = os.environ.get('DATABASE_URL', '').strip()
if DATABASE_URL:
    DATABASES = {
        'default': dj_database_url.parse(
            DATABASE_URL,
            conn_max_age=int(os.environ.get('DJANGO_CONN_MAX_AGE', '600')),
            conn_health_checks=True,
        )
    }
    if DATABASES['default']['ENGINE'] == 'django.db.backends.postgresql':
        sslmode = os.environ.get('DJANGO_DB_SSLMODE', 'require' if not DEBUG else 'prefer')
        DATABASES['default'].setdefault('OPTIONS', {})['sslmode'] = sslmode
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }


AUTH_USER_MODEL = 'accounts.CustomUser'
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
        'OPTIONS': {'min_length': 12},
    },
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]
LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/accounts/profile/'
PASSWORD_RESET_TIMEOUT = int(os.environ.get('DJANGO_PASSWORD_RESET_TIMEOUT', '3600'))
OTP_TOTP_ISSUER = 'Emvera'
# Even OTP-verified staff must not be able to clone another user's device.
OTP_ADMIN_HIDE_SENSITIVE_DATA = True


LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True


STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']
RUNNING_TESTS = 'test' in sys.argv
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {
        'BACKEND': (
            'django.contrib.staticfiles.storage.StaticFilesStorage'
            if DEBUG or RUNNING_TESTS
            else 'whitenoise.storage.CompressedManifestStaticFilesStorage'
        ),
    },
}


# Email tokens must never be printed in production logs. `check --deploy`
# rejects the dummy fallback, while local development may explicitly opt into
# the console backend.
if os.environ.get('EMAIL_HOST'):
    EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
    EMAIL_HOST = os.environ['EMAIL_HOST']
    EMAIL_PORT = int(os.environ.get('EMAIL_PORT', '587'))
    EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
    EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
    EMAIL_USE_TLS = env_bool('EMAIL_USE_TLS', True)
    EMAIL_USE_SSL = env_bool('EMAIL_USE_SSL')
elif DEBUG or env_bool('DJANGO_ALLOW_CONSOLE_EMAIL'):
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
else:
    EMAIL_BACKEND = 'django.core.mail.backends.dummy.EmailBackend'

EMAIL_TIMEOUT = int(os.environ.get('EMAIL_TIMEOUT', '10'))
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'Emvera <noreply@emvera.local>')
SERVER_EMAIL = os.environ.get('SERVER_EMAIL', DEFAULT_FROM_EMAIL)

TWILIO_ACCOUNT_SID = os.environ.get('TWILIO_ACCOUNT_SID', '')
TWILIO_AUTH_TOKEN = os.environ.get('TWILIO_AUTH_TOKEN', '')
TWILIO_FROM_NUMBER = os.environ.get('TWILIO_FROM_NUMBER', '')

PLAID_TOKEN_ENCRYPTION_KEY = os.environ.get('PLAID_TOKEN_ENCRYPTION_KEY', '').strip()
PLAID_TOKEN_ENCRYPTION_PREVIOUS_KEYS = env_list('PLAID_TOKEN_ENCRYPTION_PREVIOUS_KEYS')


LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO').upper()
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'standard': {
            'format': '{asctime} {levelname} {name}: {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'standard',
        },
    },
    'root': {'handlers': ['console'], 'level': LOG_LEVEL},
    'loggers': {
        'django.request': {
            'handlers': ['console'],
            'level': os.environ.get('DJANGO_REQUEST_LOG_LEVEL', 'WARNING').upper(),
            'propagate': False,
        },
    },
}
