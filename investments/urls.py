from django.urls import path
from . import views

app_name = "investments"

urlpatterns = [
    path('', views.portfolio_overview, name='portfolio_overview'),
    path('growth-chart/', views.investment_growth_chart, name='investment_growth_chart'),
    path('projections/', views.investment_projections, name='investment_projections'),
    path('recommendations/', views.investment_recommendations, name='investment_recommendations'),
    path(
        'recommendations/<int:pk>/reviewed/',
        views.mark_recommendation_reviewed,
        name='mark_recommendation_reviewed',
    ),
    path('comparison/', views.investment_comparison, name='investment_comparison'),
    path('performance/', views.portfolio_performance, name='portfolio_performance'),
    path('export/csv/', views.export_investments_csv, name='export_investments_csv'),
]
