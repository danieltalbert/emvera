import time
from unittest.mock import patch
from urllib.parse import urlparse

from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django_otp.oath import TOTP
from django_otp.plugins.otp_totp.models import TOTPDevice

from data_integration.models import Account

from .testing import force_login_with_otp


def current_token(device):
    totp = TOTP(device.bin_key, device.step, device.t0, device.digits, device.drift)
    totp.time = time.time()
    return str(totp.token()).zfill(device.digits)


class RegistrationViewTest(TestCase):
    def _registration_data(self, **overrides):
        data = {
            'username': 'newuser',
            'email': 'newuser@example.com',
            'password1': 'StrongPass123!',
            'password2': 'StrongPass123!',
        }
        data.update(overrides)
        return data

    def test_register_page_loads(self):
        response = self.client.get(reverse('accounts:register'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'registration/register.html')

    def test_register_creates_inactive_user_and_sends_verification(self):
        response = self.client.post(reverse('accounts:register'), self._registration_data())

        self.assertRedirects(response, reverse('accounts:verification_sent'))
        user = get_user_model().objects.get(username='newuser')
        self.assertFalse(user.is_active)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('/accounts/verify-email/', mail.outbox[0].body)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_verification_link_activates_and_signs_in_user(self):
        self.client.post(reverse('accounts:register'), self._registration_data())
        verification_url = next(
            line for line in mail.outbox[0].body.splitlines() if '/accounts/verify-email/' in line
        )

        response = self.client.get(urlparse(verification_url).path)

        self.assertRedirects(response, reverse('accounts:onboarding'))
        user = get_user_model().objects.get(username='newuser')
        self.assertTrue(user.is_active)
        self.assertEqual(int(self.client.session['_auth_user_id']), user.pk)

    def test_invalid_verification_link_fails_closed(self):
        response = self.client.get(
            reverse('accounts:verify_email', kwargs={'uidb64': 'invalid', 'token': 'invalid'})
        )

        self.assertEqual(response.status_code, 400)
        self.assertTemplateUsed(response, 'registration/email_verification_invalid.html')

    def test_email_is_required_and_unique_case_insensitively(self):
        get_user_model().objects.create_user(username='existing', email='Taken@Example.com')

        response = self.client.post(
            reverse('accounts:register'),
            self._registration_data(email='taken@example.com'),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn('email', response.context['form'].errors)
        self.assertFalse(get_user_model().objects.filter(username='newuser').exists())

    def test_database_rejects_case_variant_email_duplicates(self):
        get_user_model().objects.create_user(username='existing', email='Taken@Example.com')

        with self.assertRaises(IntegrityError), transaction.atomic():
            get_user_model().objects.create_user(
                username='duplicate',
                email='taken@example.com',
            )

    @patch('accounts.views.send_mail', return_value=0)
    def test_registration_reports_backend_that_accepts_no_email(self, send_mail_mock):
        response = self.client.post(
            reverse('accounts:register'),
            self._registration_data(),
            follow=True,
        )

        self.assertContains(response, 'the email could not be sent')
        self.assertTrue(
            get_user_model().objects.filter(username='newuser', is_active=False).exists()
        )
        send_mail_mock.assert_called_once()

    def test_resend_response_does_not_disclose_account_existence(self):
        response = self.client.post(
            reverse('accounts:verification_sent'),
            {'email': 'missing@example.com'},
            follow=True,
        )

        self.assertContains(response, 'If an unverified account matches that address')
        self.assertEqual(len(mail.outbox), 0)


class LoginViewTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='testuser',
            password='testpass',
        )

    def test_login_page_loads(self):
        response = self.client.get(reverse('accounts:login'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'registration/login.html')

    def test_password_reset_link_is_outside_password_label(self):
        response = self.client.get(reverse('accounts:login'))
        content = response.content.decode()
        label_start = content.index('<label class="form-label" for="id_password">')
        label_end = content.index('</label>', label_start)

        self.assertIn('Password', content[label_start:label_end])
        self.assertNotIn('Forgot password?', content[label_start:label_end])
        self.assertContains(response, 'Forgot password?')

    def test_password_login_without_device_is_limited_to_setup(self):
        response = self.client.post(
            reverse('accounts:login'),
            {
                'username': 'testuser',
                'password': 'testpass',
            },
        )

        self.assertRedirects(response, reverse('accounts:two_factor_setup'))
        self.assertEqual(int(self.client.session['_auth_user_id']), self.user.pk)
        profile_response = self.client.get(reverse('accounts:profile'))
        self.assertRedirects(profile_response, reverse('accounts:two_factor_setup'))

    def test_confirmed_device_requires_otp_before_session_login(self):
        device = TOTPDevice.objects.create(
            user=self.user,
            name='Authenticator App',
            confirmed=True,
        )
        self.user.two_factor_enabled = True
        self.user.save(update_fields=['two_factor_enabled'])

        password_response = self.client.post(
            reverse('accounts:login'),
            {
                'username': 'testuser',
                'password': 'testpass',
            },
        )

        self.assertRedirects(password_response, reverse('accounts:two_factor_verify'))
        self.assertNotIn('_auth_user_id', self.client.session)

        otp_response = self.client.post(
            reverse('accounts:two_factor_verify'),
            {'code': current_token(device)},
        )
        self.assertRedirects(otp_response, reverse('accounts:onboarding'))
        self.assertEqual(int(self.client.session['_auth_user_id']), self.user.pk)
        self.assertEqual(self.client.get(reverse('accounts:profile')).status_code, 200)

    def test_otp_challenge_locks_after_five_invalid_codes(self):
        TOTPDevice.objects.create(user=self.user, name='Authenticator App', confirmed=True)
        self.user.two_factor_enabled = True
        self.user.save(update_fields=['two_factor_enabled'])
        self.client.post(
            reverse('accounts:login'),
            {
                'username': 'testuser',
                'password': 'testpass',
            },
        )

        for _ in range(4):
            response = self.client.post(reverse('accounts:two_factor_verify'), {'code': '000000'})
            self.assertEqual(response.status_code, 200)
        response = self.client.post(reverse('accounts:two_factor_verify'), {'code': '000000'})

        self.assertRedirects(response, reverse('accounts:login'))
        self.assertNotIn('_auth_user_id', self.client.session)


class ProfileViewTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='testuser',
            password='testpass',
            two_factor_enabled=True,
        )

    def test_profile_requires_login(self):
        response = self.client.get(reverse('accounts:profile'))
        self.assertEqual(response.status_code, 302)

    def test_profile_page_loads_for_otp_verified_user(self):
        force_login_with_otp(self.client, self.user)
        response = self.client.get(reverse('accounts:profile'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'accounts/profile.html')

    def test_profile_links_to_custom_change_password_route(self):
        force_login_with_otp(self.client, self.user)
        response = self.client.get(reverse('accounts:profile'))
        self.assertContains(response, f'href="{reverse("accounts:change_password")}"')

    def test_profile_updates_contact_details(self):
        force_login_with_otp(self.client, self.user)

        response = self.client.post(
            reverse('accounts:profile'),
            {
                'first_name': 'Demo',
                'last_name': 'User',
                'phone_number': '+15551234567',
            },
        )

        self.assertRedirects(response, reverse('accounts:profile'))
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, 'Demo')
        self.assertEqual(self.user.phone_number, '+15551234567')

    def test_profile_rejects_non_e164_phone_number(self):
        force_login_with_otp(self.client, self.user)

        response = self.client.post(
            reverse('accounts:profile'),
            {'phone_number': '555-123-4567'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn('phone_number', response.context['form'].errors)

    def test_logout_uses_post(self):
        force_login_with_otp(self.client, self.user)
        response = self.client.post(reverse('accounts:logout'))
        self.assertRedirects(response, reverse('accounts:login'))


class OnboardingViewTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='onboard',
            password='testpass',
            two_factor_enabled=True,
        )
        force_login_with_otp(self.client, self.user)

    def test_onboarding_links_to_manual_account_entry(self):
        response = self.client.get(reverse('accounts:onboarding'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Welcome to Emvera')
        self.assertContains(
            response,
            '<li>Step 3: Connect First Account <a href="/data/manual-account/">Start</a></li>',
            html=True,
        )

    def test_onboarding_marks_account_step_complete(self):
        Account.objects.create(user=self.user, name='Checking', type='checking')
        response = self.client.get(reverse('accounts:onboarding'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'All steps complete!')
        self.user.refresh_from_db()
        self.assertTrue(self.user.profile_complete)


class PasswordResetViewTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='resetuser',
            email='reset@example.com',
            password='OldPass123!',
        )

    def test_password_reset_sends_namespaced_confirm_link(self):
        response = self.client.post(
            reverse('accounts:password_reset'),
            {
                'email': 'reset@example.com',
            },
        )
        self.assertRedirects(response, reverse('accounts:password_reset_done'))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('/accounts/password-reset-confirm/', mail.outbox[0].body)

    def test_password_reset_confirm_updates_password(self):
        uidb64 = urlsafe_base64_encode(force_bytes(self.user.pk))
        token = default_token_generator.make_token(self.user)
        confirm_url = reverse(
            'accounts:password_reset_confirm',
            kwargs={
                'uidb64': uidb64,
                'token': token,
            },
        )
        response = self.client.get(confirm_url)
        self.assertEqual(response.status_code, 302)
        response = self.client.post(
            response['Location'],
            {
                'new_password1': 'NewSecurePass123!',
                'new_password2': 'NewSecurePass123!',
            },
        )
        self.assertRedirects(response, reverse('accounts:password_reset_complete'))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('NewSecurePass123!'))


class TwoFactorGateTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='needs2fa',
            password='testpass',
            two_factor_enabled=False,
        )
        self.client.login(username='needs2fa', password='testpass')

    def assertRequiresTwoFactorSetup(self, route_name):
        response = self.client.get(reverse(route_name))
        self.assertRedirects(response, reverse('accounts:two_factor_setup'))

    def test_onboarding_remains_available_before_two_factor_setup(self):
        response = self.client.get(reverse('accounts:onboarding'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse('accounts:two_factor_setup'))

    def test_profile_requires_two_factor_setup(self):
        self.assertRequiresTwoFactorSetup('accounts:profile')

    def test_data_entry_requires_two_factor_setup(self):
        self.assertRequiresTwoFactorSetup('data_integration:manual_account_entry')
        self.assertRequiresTwoFactorSetup('data_integration:manual_transaction_entry')
        self.assertRequiresTwoFactorSetup('data_integration:manual_debt_entry')
        self.assertRequiresTwoFactorSetup('data_integration:csv_upload')

    def test_password_change_requires_two_factor_setup(self):
        self.assertRequiresTwoFactorSetup('accounts:change_password')
        self.assertRequiresTwoFactorSetup('accounts:password_change')

    def test_investments_require_two_factor_setup(self):
        self.assertRequiresTwoFactorSetup('investments:portfolio_overview')
        self.assertRequiresTwoFactorSetup('investments:investment_growth_chart')

    def test_debt_tools_require_two_factor_setup(self):
        self.assertRequiresTwoFactorSetup('debt_management:debt_dashboard')
        self.assertRequiresTwoFactorSetup('debt_management:payoff_avalanche')
        self.assertRequiresTwoFactorSetup('debt_management:payoff_snowball')
        self.assertRequiresTwoFactorSetup('debt_management:payoff_custom')
        self.assertRequiresTwoFactorSetup('debt_management:debt_reminders')
        self.assertRequiresTwoFactorSetup('debt_management:consolidation_suggestion')
        self.assertRequiresTwoFactorSetup('debt_management:credit_score_tracking')

    def test_competition_entry_requires_two_factor_setup(self):
        self.assertRequiresTwoFactorSetup('competition:lobby')
        self.assertRequiresTwoFactorSetup('competition:create')


class TwoFactorSetupAndSettingsTest(TestCase):
    def setUp(self):
        self.enabled_user = get_user_model().objects.create_user(
            username='enabled2fa',
            password='testpass',
            two_factor_enabled=True,
        )
        self.disabled_user = get_user_model().objects.create_user(
            username='disabled2fa',
            password='testpass',
            two_factor_enabled=False,
        )

    def test_setup_confirms_the_same_device_secret_shown_in_qr(self):
        self.client.force_login(self.disabled_user)
        response = self.client.get(reverse('accounts:two_factor_setup'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('no-cache', response['Cache-Control'])
        self.assertIn('no-store', response['Cache-Control'])
        device = TOTPDevice.objects.get(user=self.disabled_user, confirmed=False)

        response = self.client.post(
            reverse('accounts:two_factor_setup'),
            {'code': current_token(device)},
        )

        self.assertRedirects(response, reverse('accounts:two_factor_settings'))
        device.refresh_from_db()
        self.disabled_user.refresh_from_db()
        self.assertTrue(device.confirmed)
        self.assertTrue(self.disabled_user.two_factor_enabled)
        self.assertEqual(self.client.get(reverse('accounts:profile')).status_code, 200)

    def test_settings_redirects_user_without_two_factor_to_setup(self):
        self.client.force_login(self.disabled_user)
        response = self.client.get(reverse('accounts:two_factor_settings'))
        self.assertRedirects(response, reverse('accounts:two_factor_setup'))

    def test_enabled_user_can_view_settings(self):
        force_login_with_otp(self.client, self.enabled_user)
        response = self.client.get(reverse('accounts:two_factor_settings'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'accounts/two_factor_settings.html')

    def test_disabling_two_factor_removes_devices_and_returns_to_setup(self):
        device = force_login_with_otp(self.client, self.enabled_user)

        response = self.client.post(reverse('accounts:two_factor_settings'), {'disable': '1'})

        self.assertRedirects(response, reverse('accounts:two_factor_setup'))
        self.enabled_user.refresh_from_db()
        self.assertFalse(self.enabled_user.two_factor_enabled)
        self.assertFalse(TOTPDevice.objects.filter(pk=device.pk).exists())
