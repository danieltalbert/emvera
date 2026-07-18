"""Small authentication helpers shared by the Django test suite."""

from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.plugins.otp_totp.models import TOTPDevice


def force_login_with_otp(client, user):
    """Create a confirmed test device and mark the client's session OTP-verified."""
    device, _ = TOTPDevice.objects.get_or_create(
        user=user,
        name='Test Authenticator',
        defaults={'confirmed': True},
    )
    if not device.confirmed:
        device.confirmed = True
        device.save(update_fields=['confirmed'])
    if not user.two_factor_enabled:
        user.two_factor_enabled = True
        user.save(update_fields=['two_factor_enabled'])

    client.force_login(user)
    session = client.session
    session[DEVICE_ID_SESSION_KEY] = device.persistent_id
    session.save()
    return device
