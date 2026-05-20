from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages

def require_2fa(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        user = request.user
        if user.is_authenticated and not getattr(user, 'two_factor_enabled', False):
            messages.info(request, 'Please set up 2FA to continue.')
            return redirect('accounts:two_factor_setup')
        return view_func(request, *args, **kwargs)
    return _wrapped_view
