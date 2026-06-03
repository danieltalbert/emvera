"""URL routing for the investments app."""

from django.urls import path
from . import views

app_name = "investments"

from . import views

urlpatterns = [
    path('', views.portfolio_overview, name='portfolio_overview'),
    path('growth-chart/', views.investment_growth_chart, name='investment_growth_chart'),
    path('projections/', views.investment_projections, name='investment_projections'),
    path('recommendations/', views.investment_recommendations, name='investment_recommendations'),
    path('comparison/', views.investment_comparison, name='investment_comparison'),
    path('performance/', views.portfolio_performance, name='portfolio_performance'),
    path('export/csv/', views.export_investments_csv, name='export_investments_csv'),
]
