from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django_otp.plugins.otp_totp.models import TOTPDevice

from data_integration.models import Account

class RegistrationViewTest(TestCase):
	def test_register_page_loads(self):
		response = self.client.get(reverse('accounts:register'))
		self.assertEqual(response.status_code, 200)
		self.assertTemplateUsed(response, 'registration/register.html')

	def test_register_creates_user(self):
		response = self.client.post(reverse('accounts:register'), {
			'username': 'newuser',
			'password1': 'StrongPass123!',
			'password2': 'StrongPass123!'
		})
		self.assertEqual(response.status_code, 302)  # Redirect
		self.assertTrue(get_user_model().objects.filter(username='newuser').exists())

class LoginViewTest(TestCase):
	def setUp(self):
		self.user = get_user_model().objects.create_user(username='testuser', password='testpass')

	def test_login_page_loads(self):
		response = self.client.get(reverse('accounts:login'))
		self.assertEqual(response.status_code, 200)
		self.assertTemplateUsed(response, 'registration/login.html')

	def test_login_success(self):
		response = self.client.post(reverse('accounts:login'), {
			'username': 'testuser',
			'password': 'testpass'
		})
		self.assertEqual(response.status_code, 302)

class ProfileViewTest(TestCase):
	def setUp(self):
		self.user = get_user_model().objects.create_user(
			username='testuser', password='testpass', two_factor_enabled=True,
		)

	def test_profile_requires_login(self):
		response = self.client.get(reverse('accounts:profile'))
		self.assertEqual(response.status_code, 302)  # Redirect to login

	def test_profile_page_loads_for_logged_in_user(self):
		self.client.login(username='testuser', password='testpass')
		response = self.client.get(reverse('accounts:profile'))
		self.assertEqual(response.status_code, 200)
		self.assertTemplateUsed(response, 'accounts/profile.html')

	def test_profile_links_to_custom_change_password_route(self):
		self.client.login(username='testuser', password='testpass')
		response = self.client.get(reverse('accounts:profile'))
		self.assertContains(response, f'href="{reverse("accounts:change_password")}"')

	def test_logout_uses_post(self):
		self.client.login(username='testuser', password='testpass')
		response = self.client.post(reverse('accounts:logout'))
		self.assertRedirects(response, reverse('accounts:login'))


class OnboardingViewTest(TestCase):
	def setUp(self):
		self.user = get_user_model().objects.create_user(
			username='onboard', password='testpass', two_factor_enabled=True,
		)
		self.client.login(username='onboard', password='testpass')

	def test_onboarding_links_to_manual_account_entry(self):
		response = self.client.get(reverse('accounts:onboarding'))
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'Welcome to Ridge &amp; River Financial Onboarding', html=True)
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
			username='resetuser', email='reset@example.com', password='OldPass123!',
		)

	def test_password_reset_sends_namespaced_confirm_link(self):
		response = self.client.post(reverse('accounts:password_reset'), {
			'email': 'reset@example.com',
		})
		self.assertRedirects(response, reverse('accounts:password_reset_done'))
		self.assertEqual(len(mail.outbox), 1)
		self.assertIn('/accounts/password-reset-confirm/', mail.outbox[0].body)

	def test_password_reset_confirm_updates_password(self):
		uidb64 = urlsafe_base64_encode(force_bytes(self.user.pk))
		token = default_token_generator.make_token(self.user)
		confirm_url = reverse('accounts:password_reset_confirm', kwargs={
			'uidb64': uidb64,
			'token': token,
		})
		response = self.client.get(confirm_url)
		self.assertEqual(response.status_code, 302)
		response = self.client.post(response['Location'], {
			'new_password1': 'NewPass123!',
			'new_password2': 'NewPass123!',
		})
		self.assertRedirects(response, reverse('accounts:password_reset_complete'))
		self.user.refresh_from_db()
		self.assertTrue(self.user.check_password('NewPass123!'))


class TwoFactorGateTest(TestCase):
	def setUp(self):
		self.user = get_user_model().objects.create_user(
			username='needs2fa', password='testpass', two_factor_enabled=False,
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


class TwoFactorSettingsTest(TestCase):
	def setUp(self):
		self.enabled_user = get_user_model().objects.create_user(
			username='enabled2fa', password='testpass', two_factor_enabled=True,
		)
		self.disabled_user = get_user_model().objects.create_user(
			username='disabled2fa', password='testpass', two_factor_enabled=False,
		)

	def test_settings_redirects_user_without_two_factor_to_setup(self):
		self.client.force_login(self.disabled_user)
		response = self.client.get(reverse('accounts:two_factor_settings'))
		self.assertRedirects(response, reverse('accounts:two_factor_setup'))

	def test_enabled_user_can_view_settings(self):
		self.client.force_login(self.enabled_user)
		response = self.client.get(reverse('accounts:two_factor_settings'))
		self.assertEqual(response.status_code, 200)
		self.assertTemplateUsed(response, 'accounts/two_factor_settings.html')

	def test_disabling_two_factor_removes_devices_and_returns_to_setup(self):
		device = TOTPDevice.objects.create(
			user=self.enabled_user,
			name='Authenticator App',
			confirmed=True,
		)
		self.client.force_login(self.enabled_user)

		response = self.client.post(reverse('accounts:two_factor_settings'), {'disable': '1'})

		self.assertRedirects(response, reverse('accounts:two_factor_setup'))
		self.enabled_user.refresh_from_db()
		self.assertFalse(self.enabled_user.two_factor_enabled)
		self.assertFalse(TOTPDevice.objects.filter(pk=device.pk).exists())
