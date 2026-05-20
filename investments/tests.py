from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from data_integration.models import Account

class InvestmentsViewsTest(TestCase):
	def setUp(self):
		self.user = get_user_model().objects.create_user(username='testuser', password='testpass')
		self.client.login(username='testuser', password='testpass')
		self.account = Account.objects.create(user=self.user, name='Test Investment', type='investment')

	def test_portfolio_overview_view(self):
		response = self.client.get(reverse('investments:portfolio_overview'))
		self.assertEqual(response.status_code, 200)
		self.assertTemplateUsed(response, 'investments/portfolio_overview.html')

	def test_investment_growth_chart_view(self):
		response = self.client.get(reverse('investments:investment_growth_chart'))
		self.assertEqual(response.status_code, 200)

	def test_investment_projections_view(self):
		response = self.client.get(reverse('investments:investment_projections'))
		self.assertEqual(response.status_code, 200)
		self.assertTemplateUsed(response, 'investments/investment_projections.html')

	def test_investment_recommendations_view(self):
		response = self.client.get(reverse('investments:investment_recommendations'))
		self.assertEqual(response.status_code, 200)
		self.assertTemplateUsed(response, 'investments/investment_recommendations.html')
