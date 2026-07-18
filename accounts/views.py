import base64
import io
import logging
import time

import qrcode
from django.contrib import messages
from django.contrib.auth import (
    authenticate,
    get_user_model,
    login,
    logout,
    update_session_auth_hash,
)
from django.contrib.auth.decorators import login_required
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.encoding import force_bytes, force_str
from django.utils.http import (
    url_has_allowed_host_and_scheme,
    urlsafe_base64_decode,
    urlsafe_base64_encode,
)
from django.views.decorators.cache import never_cache
from django_otp import DEVICE_ID_SESSION_KEY, devices_for_user
from django_otp import login as otp_login
from django_otp.plugins.otp_totp.models import TOTPDevice

from .forms import (
    ChangePasswordForm,
    CustomUserCreationForm,
    LoginForm,
    ProfileForm,
    ResendVerificationForm,
)
from .require_2fa import has_confirmed_totp, require_2fa

logger = logging.getLogger(__name__)

PREAUTH_SESSION_KEY = 'accounts_2fa_preauth'
PENDING_DEVICE_SESSION_KEY = 'accounts_2fa_pending_device'
PREAUTH_TTL_SECONDS = 5 * 60
MAX_OTP_ATTEMPTS = 5


class VerificationEmailDeliveryError(RuntimeError):
    """Raised when the configured backend does not accept an activation email."""


def _safe_next_url(request, next_url):
    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return next_url
    return None


def _post_login_redirect(request, user, next_url=None):
    safe_next = _safe_next_url(request, next_url)
    if safe_next:
        return redirect(safe_next)
    if not user.profile_complete:
        return redirect('accounts:onboarding')
    return redirect('/')


def _begin_two_factor_challenge(request, user, next_url):
    # Rotate the anonymous session identifier before storing pre-auth state.
    request.session.cycle_key()
    request.session[PREAUTH_SESSION_KEY] = {
        'user_id': user.pk,
        'backend': user.backend,
        'next': _safe_next_url(request, next_url),
        'created_at': time.time(),
        'attempts': 0,
    }


def _clear_two_factor_challenge(request):
    request.session.pop(PREAUTH_SESSION_KEY, None)


def _preauthenticated_user(request):
    challenge = request.session.get(PREAUTH_SESSION_KEY)
    if not isinstance(challenge, dict):
        return None, None

    created_at = challenge.get('created_at')
    if not isinstance(created_at, (int, float)) or time.time() - created_at > PREAUTH_TTL_SECONDS:
        _clear_two_factor_challenge(request)
        return None, None

    if challenge.get('attempts', 0) >= MAX_OTP_ATTEMPTS:
        _clear_two_factor_challenge(request)
        return None, None

    user = (
        get_user_model()
        .objects.filter(
            pk=challenge.get('user_id'),
            is_active=True,
        )
        .first()
    )
    if user is None or not has_confirmed_totp(user):
        _clear_two_factor_challenge(request)
        return None, None
    return user, challenge


def _verify_confirmed_device(user, token):
    """Verify a token against a specific confirmed device with row-level serialization."""
    with transaction.atomic():
        devices = TOTPDevice.objects.select_for_update().filter(
            user=user,
            confirmed=True,
        )
        for device in devices:
            if device.verify_token(token):
                return device
    return None


@never_cache
def user_login(request):
    if request.user.is_authenticated:
        return redirect('accounts:profile')

    next_url = request.GET.get('next')
    if request.method == 'POST':
        form = LoginForm(request.POST)
        if form.is_valid():
            user = authenticate(
                request,
                username=form.cleaned_data['username'],
                password=form.cleaned_data['password'],
            )
            if user is not None:
                next_url = request.POST.get('next')
                confirmed_device = next(devices_for_user(user, confirmed=True), None)
                if confirmed_device is not None:
                    if not user.two_factor_enabled:
                        user.two_factor_enabled = True
                        user.save(update_fields=['two_factor_enabled'])
                    _begin_two_factor_challenge(request, user, next_url)
                    return redirect('accounts:two_factor_verify')

                # Repair legacy Boolean-only state. Without a confirmed device,
                # protected routes remain unavailable until setup completes.
                if user.two_factor_enabled:
                    user.two_factor_enabled = False
                    user.save(update_fields=['two_factor_enabled'])
                login(request, user)
                return redirect('accounts:two_factor_setup')

            messages.error(request, 'Invalid username or password.')
    else:
        form = LoginForm()
    return render(request, 'registration/login.html', {'form': form, 'next': next_url})


@login_required
@require_2fa
def change_password(request):
    if request.method == 'POST':
        form = ChangePasswordForm(user=request.user, data=request.POST)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)
            messages.success(request, 'Password changed successfully.')
            return redirect('accounts:profile')
    else:
        form = ChangePasswordForm(user=request.user)
    return render(request, 'accounts/change_password.html', {'form': form})


def _send_verification_email(request, user):
    uidb64 = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    verification_url = request.build_absolute_uri(
        reverse('accounts:verify_email', kwargs={'uidb64': uidb64, 'token': token})
    )
    body = render_to_string(
        'registration/email_verification_email.txt',
        {'user': user, 'verification_url': verification_url},
    )
    delivered = send_mail(
        'Verify your Emvera email address',
        body,
        None,
        [user.email],
    )
    if delivered != 1:
        raise VerificationEmailDeliveryError('Verification email was not accepted.')


@never_cache
def register(request):
    if request.user.is_authenticated:
        return redirect('accounts:onboarding')
    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    user = form.save(commit=False)
                    user.profile_complete = False
                    user.is_active = False
                    user.save()
            except IntegrityError:
                # The database constraint closes the race between form
                # validation and save without exposing which identity won.
                form.add_error(
                    'email',
                    'An account already uses this email address.',
                )
                return render(request, 'registration/register.html', {'form': form})
            try:
                _send_verification_email(request, user)
            except Exception as exc:
                logger.error('Failed to send verification email (%s).', type(exc).__name__)
                messages.error(
                    request,
                    'Your account was created, but the email could not be sent. Try resending it below.',
                )
            return redirect('accounts:verification_sent')
    else:
        form = CustomUserCreationForm()
    return render(request, 'registration/register.html', {'form': form})


def verification_sent(request):
    form = ResendVerificationForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = (
            get_user_model()
            .objects.filter(
                email__iexact=form.cleaned_data['email'],
                is_active=False,
            )
            .first()
        )
        if user is not None:
            try:
                _send_verification_email(request, user)
            except Exception as exc:
                logger.error('Failed to resend verification email (%s).', type(exc).__name__)
        messages.success(
            request,
            'If an unverified account matches that address, a new verification email has been sent.',
        )
    return render(request, 'registration/email_verification_sent.html', {'form': form})


@never_cache
def verify_email(request, uidb64, token):
    try:
        user_id = force_str(urlsafe_base64_decode(uidb64))
        user = get_user_model().objects.get(pk=user_id)
    except (TypeError, ValueError, OverflowError, get_user_model().DoesNotExist):
        user = None

    if user is None or not default_token_generator.check_token(user, token):
        return render(request, 'registration/email_verification_invalid.html', status=400)

    if not user.is_active:
        user.is_active = True
        user.save(update_fields=['is_active'])
    login(request, user, backend='django.contrib.auth.backends.ModelBackend')
    messages.success(request, 'Email verified. Finish securing your account with 2FA.')
    return redirect('accounts:onboarding')


@login_required
def onboarding(request):
    user = request.user
    email_verified = user.is_active
    twofa_complete = user.two_factor_enabled and has_confirmed_totp(user)
    account_connected = user.accounts.exists()

    if email_verified and twofa_complete and account_connected and not user.profile_complete:
        user.profile_complete = True
        user.save(update_fields=['profile_complete'])

    return render(
        request,
        'accounts/onboarding.html',
        {
            'email_verified': email_verified,
            'twofa_complete': twofa_complete,
            'account_connected': account_connected,
        },
    )


@login_required
@require_2fa
def profile(request):
    form = ProfileForm(request.POST or None, instance=request.user)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Profile details updated.')
        return redirect('accounts:profile')
    return render(request, 'accounts/profile.html', {'form': form})


def _pending_totp_device(request):
    device_id = request.session.get(PENDING_DEVICE_SESSION_KEY)
    device = TOTPDevice.objects.filter(
        pk=device_id,
        user=request.user,
        confirmed=False,
    ).first()
    if device is None:
        device = TOTPDevice.objects.filter(
            user=request.user,
            name='Authenticator App',
            confirmed=False,
        ).first()
        if device is None:
            device = TOTPDevice.objects.create(
                user=request.user,
                name='Authenticator App',
                confirmed=False,
            )
        request.session[PENDING_DEVICE_SESSION_KEY] = device.pk
    return device


@never_cache
@login_required
def two_factor_setup(request):
    user = request.user
    confirmed_device = next(devices_for_user(user, confirmed=True), None)
    if confirmed_device is not None:
        if getattr(user, 'is_verified', lambda: False)():
            return redirect('accounts:two_factor_settings')
        logout(request)
        messages.info(request, 'Sign in again and enter your authenticator code.')
        return redirect('accounts:login')

    device = _pending_totp_device(request)
    buf = io.BytesIO()
    qrcode.make(device.config_url).save(buf, format='PNG')
    qr_code = base64.b64encode(buf.getvalue()).decode('ascii')

    if request.method == 'POST':
        if device.verify_token(request.POST.get('code', '')):
            device.confirmed = True
            device.save(update_fields=['confirmed'])
            TOTPDevice.objects.filter(user=user, confirmed=False).exclude(pk=device.pk).delete()
            user.two_factor_enabled = True
            user.save(update_fields=['two_factor_enabled'])
            request.session.pop(PENDING_DEVICE_SESSION_KEY, None)
            otp_login(request, device)
            messages.success(request, 'Two-factor authentication enabled.')
            return redirect('accounts:two_factor_settings')
        messages.error(request, 'Invalid code. Please try again.')

    return render(request, 'accounts/two_factor_setup.html', {'qr_code': qr_code})


@never_cache
def two_factor_verify(request):
    if request.user.is_authenticated:
        return redirect('accounts:profile')

    user, challenge = _preauthenticated_user(request)
    if user is None:
        messages.info(request, 'Your verification session expired. Sign in again.')
        return redirect('accounts:login')

    if request.method == 'POST':
        device = _verify_confirmed_device(user, request.POST.get('code', ''))
        if device is not None:
            backend = challenge.get('backend') or 'django.contrib.auth.backends.ModelBackend'
            next_url = challenge.get('next')
            login(request, user, backend=backend)
            otp_login(request, device)
            _clear_two_factor_challenge(request)
            return _post_login_redirect(request, user, next_url)

        challenge['attempts'] = challenge.get('attempts', 0) + 1
        request.session[PREAUTH_SESSION_KEY] = challenge
        remaining = MAX_OTP_ATTEMPTS - challenge['attempts']
        if remaining <= 0:
            _clear_two_factor_challenge(request)
            messages.error(request, 'Too many invalid codes. Sign in again.')
            return redirect('accounts:login')
        messages.error(request, 'Invalid code. Please try again.')

    return render(request, 'accounts/two_factor_verify.html')


@login_required
@require_2fa
def two_factor_settings(request):
    user = request.user
    if request.method == 'POST' and request.POST.get('disable'):
        for device in devices_for_user(user, confirmed=True):
            device.delete()
        request.session.pop(DEVICE_ID_SESSION_KEY, None)
        user.two_factor_enabled = False
        user.save(update_fields=['two_factor_enabled'])
        messages.success(request, 'Two-factor authentication disabled.')
        return redirect('accounts:two_factor_setup')
    return render(request, 'accounts/two_factor_settings.html')
