from functools import wraps

from django.contrib import messages
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.urls import reverse
from django_otp import devices_for_user


def has_confirmed_totp(user):
    """Return whether the user has a confirmed OTP device bound to the account."""
    return next(devices_for_user(user, confirmed=True), None) is not None


def require_2fa(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        user = request.user
        if not user.is_authenticated:
            return view_func(request, *args, **kwargs)

        if not getattr(user, 'two_factor_enabled', False) or not has_confirmed_totp(user):
            messages.info(request, 'Please set up 2FA to continue.')
            return redirect('accounts:two_factor_setup')

        if not getattr(user, 'is_verified', lambda: False)():
            # Existing sessions created before the OTP challenge was introduced
            # must re-authenticate instead of inheriting privileged access.
            next_url = request.get_full_path()
            logout(request)
            messages.info(request, 'Enter your password and authenticator code to continue.')
            return redirect(f'{reverse("accounts:login")}?next={next_url}')

        return view_func(request, *args, **kwargs)

    return _wrapped_view
