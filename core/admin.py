from django_otp.admin import OTPAdminSite


class EmveraAdminSite(OTPAdminSite):
    """Admin site that requires staff credentials and a verified OTP device."""

    site_header = 'Emvera administration'
    site_title = 'Emvera admin'
    index_title = 'Application administration'

    def __init__(self, name='admin'):
        # Preserve Django's conventional `admin:` URL namespace while adding
        # OTPAdminSite's verified-device permission check and login form.
        super().__init__(name=name)
