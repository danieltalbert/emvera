import base64
import io

import pyotp
import qrcode
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django import forms
from django_otp import devices_for_user
from django_otp.plugins.otp_totp.models import TOTPDevice

from .forms import ChangePasswordForm, CustomUserCreationForm
from .require_2fa import require_2fa


class LoginForm(forms.Form):
    username = forms.CharField()
    password = forms.CharField(widget=forms.PasswordInput)


def user_login(request):
    if request.user.is_authenticated:
        return redirect('accounts:profile')
    next_url = request.GET.get('next')
    if request.method == 'POST':
        form = LoginForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data['username']
            password = form.cleaned_data['password']
            user = authenticate(request, username=username, password=password)
            if user is not None:
                login(request, user)
                next_url = request.POST.get('next')
                if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
                    return redirect(next_url)
                if not user.profile_complete:
                    return redirect('accounts:onboarding')
                return redirect('/')
            else:
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


def register(request):
    if request.user.is_authenticated:
        return redirect('accounts:onboarding')
    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            user.profile_complete = False
            user.save()
            login(request, user)
            return redirect('accounts:onboarding')
    else:
        form = CustomUserCreationForm()
    return render(request, 'registration/register.html', {'form': form})


@login_required
def onboarding(request):
    user = request.user
    email_verified = True
    twofa_complete = user.two_factor_enabled
    account_connected = user.accounts.exists()

    if email_verified and twofa_complete and account_connected:
        if not user.profile_complete:
            user.profile_complete = True
            user.save()

    return render(request, 'accounts/onboarding.html', {
        'email_verified': email_verified,
        'twofa_complete': twofa_complete,
        'account_connected': account_connected,
    })


@login_required
@require_2fa
def profile(request):
    return render(request, 'accounts/profile.html')


def _get_or_create_totp_secret(request):
    if 'totp_secret' not in request.session:
        request.session['totp_secret'] = pyotp.random_base32()
    return request.session['totp_secret']


def _confirm_totp_and_enable(user, totp_secret, code, request):
    if pyotp.TOTP(totp_secret).verify(code):
        TOTPDevice.objects.create(user=user, name='Authenticator App', confirmed=True)
        user.two_factor_enabled = True
        user.save()
        del request.session['totp_secret']
        messages.success(request, 'Two-factor authentication enabled!')
        return True
    messages.error(request, 'Invalid code. Please try again.')
    return False


@login_required
def two_factor_setup(request):
    user = request.user
    if user.two_factor_enabled:
        return redirect('accounts:two_factor_settings')

    totp_secret = _get_or_create_totp_secret(request)
    totp_uri = pyotp.totp.TOTP(totp_secret).provisioning_uri(
        name=user.username, issuer_name='Ridge & River Financial'
    )
    buf = io.BytesIO()
    qrcode.make(totp_uri).save(buf, format='PNG')
    qr_code = base64.b64encode(buf.getvalue()).decode('utf-8')

    if request.method == 'POST':
        if _confirm_totp_and_enable(user, totp_secret, request.POST.get('code'), request):
            return redirect('accounts:two_factor_settings')

    return render(request, 'accounts/two_factor_setup.html', {'qr_code': qr_code})


@login_required
def two_factor_verify(request):
    user = request.user
    totp_secret = request.session.get('totp_secret')
    if not totp_secret:
        return redirect('accounts:two_factor_setup')

    if request.method == 'POST':
        if _confirm_totp_and_enable(user, totp_secret, request.POST.get('code'), request):
            return redirect('accounts:two_factor_settings')

    return render(request, 'accounts/two_factor_verify.html')


@login_required
def two_factor_settings(request):
    user = request.user
    if request.method == 'POST' and request.POST.get('disable'):
        for device in devices_for_user(user, confirmed=True):
            device.delete()
        user.two_factor_enabled = False
        user.save()
        messages.success(request, 'Two-factor authentication disabled.')
        return redirect('accounts:two_factor_settings')
    return render(request, 'accounts/two_factor_settings.html')
