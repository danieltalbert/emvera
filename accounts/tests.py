from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from .models import CustomUser

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

# 2FA and session security tests will be added after reviewing implementation details.
