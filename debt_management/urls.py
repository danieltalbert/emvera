from django.urls import path
from . import views

app_name = 'debt_management'

urlpatterns = [
    path('payoff/avalanche/', views.payoff_avalanche, name='payoff_avalanche'),
    path('payoff/snowball/', views.payoff_snowball, name='payoff_snowball'),
    path('payoff/custom/', views.payoff_custom, name='payoff_custom'),
    path('reminders/', views.debt_reminders, name='debt_reminders'),
    path('reminders/<int:pk>/paid/', views.mark_reminder_paid, name='mark_reminder_paid'),
    path('consolidation/', views.consolidation_suggestion, name='consolidation_suggestion'),
    path('credit-score/', views.credit_score_tracking, name='credit_score_tracking'),
    path('dashboard/', views.debt_dashboard, name='debt_dashboard'),
]
