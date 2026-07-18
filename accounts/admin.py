from django.contrib import admin
from django.contrib.admin.sites import NotRegistered
from django.contrib.auth.admin import UserAdmin
from django_otp.plugins.otp_totp.admin import TOTPDeviceAdmin
from django_otp.plugins.otp_totp.models import TOTPDevice

from .models import CustomUser


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        (
            'Emvera profile',
            {
                'fields': (
                    'profile_complete',
                    'two_factor_enabled',
                    'phone_number',
                )
            },
        ),
    )
    readonly_fields = ('two_factor_enabled',)
    list_display = UserAdmin.list_display + ('profile_complete', 'two_factor_enabled')


try:
    admin.site.unregister(TOTPDevice)
except NotRegistered:
    pass


@admin.register(TOTPDevice)
class ReadOnlyTOTPDeviceAdmin(TOTPDeviceAdmin):
    """Allow OTP status inspection without staff-created or mutated devices."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
