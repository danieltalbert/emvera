from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model

class DebtManagementViewsTest(TestCase):
	def setUp(self):
		self.user = get_user_model().objects.create_user(username='testuser', password='testpass')
		self.client.login(username='testuser', password='testpass')

	def test_debt_dashboard_view(self):
		response = self.client.get(reverse('debt_management:debt_dashboard'))
		self.assertEqual(response.status_code, 200)
		self.assertTemplateUsed(response, 'debt_management/debt_dashboard.html')

	def test_credit_score_tracking_view(self):
		response = self.client.get(reverse('debt_management:credit_score_tracking'))
		self.assertEqual(response.status_code, 200)
		self.assertTemplateUsed(response, 'debt_management/credit_score_tracking.html')

	def test_consolidation_suggestion_view(self):
		response = self.client.get(reverse('debt_management:consolidation_suggestion'))
		self.assertEqual(response.status_code, 200)
		self.assertTemplateUsed(response, 'debt_management/consolidation_suggestion.html')

	def test_debt_reminders_view(self):
		response = self.client.get(reverse('debt_management:debt_reminders'))
		self.assertEqual(response.status_code, 200)
		self.assertTemplateUsed(response, 'debt_management/debt_reminders.html')

	def test_payoff_avalanche_view(self):
		response = self.client.get(reverse('debt_management:payoff_avalanche'))
		self.assertEqual(response.status_code, 200)
		self.assertTemplateUsed(response, 'debt_management/payoff_avalanche.html')

	def test_payoff_snowball_view(self):
		response = self.client.get(reverse('debt_management:payoff_snowball'))
		self.assertEqual(response.status_code, 200)
		self.assertTemplateUsed(response, 'debt_management/payoff_snowball.html')

	def test_payoff_custom_view(self):
		response = self.client.get(reverse('debt_management:payoff_custom'))
		self.assertEqual(response.status_code, 200)
		self.assertTemplateUsed(response, 'debt_management/payoff_custom.html')
