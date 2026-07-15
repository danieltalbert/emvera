
from django.db import models
from data_integration.models import Investment
from django.conf import settings

class InvestmentRecommendation(models.Model):
	investment = models.ForeignKey(Investment, on_delete=models.CASCADE, related_name='recommendations')
	user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
	recommendation_type = models.CharField(max_length=50)  # e.g., 'rebalance', 'increase_contribution'
	message = models.TextField()
	created_at = models.DateTimeField(auto_now_add=True)
	reviewed = models.BooleanField(default=False)

	def __str__(self):
		return f"{self.recommendation_type} for {self.investment}"

class InvestmentProjection(models.Model):
	investment = models.ForeignKey(Investment, on_delete=models.CASCADE, related_name='projections')
	user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
	projection_date = models.DateField()
	projected_value = models.DecimalField(max_digits=16, decimal_places=2)
	growth_rate = models.FloatField(help_text="Annualized growth rate used for projection")
	created_at = models.DateTimeField(auto_now_add=True)

	def __str__(self):
		return f"Projection for {self.investment} on {self.projection_date}"

	def annualized_return(self):
		"""CAGR between the underlying investment's as_of date and this projection's date."""
		current = float(self.investment.value or 0)
		projected = float(self.projected_value or 0)
		if current <= 0 or projected <= 0:
			return None
		days = (self.projection_date - self.investment.as_of).days
		if days <= 0:
			return None
		years = days / 365.25
		return ((projected / current) ** (1 / years) - 1) * 100

# Visualization utilities will be implemented as Python modules, not models.
