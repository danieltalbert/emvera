"""URL routing for the analytics app."""

from django.urls import path
from . import views

app_name = 'analytics'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('beacon/', views.beacon, name='beacon'),
    path('alerts/<int:pk>/ack/', views.acknowledge_alert, name='acknowledge_alert'),
    path('export.csv', views.export_csv, name='export_csv'),
    path('export.pdf', views.export_pdf, name='export_pdf'),
    path('api/metrics/', views.api_metrics, name='api_metrics'),
    path('api/live/', views.api_live, name='api_live'),
    path('experiments/<slug:key>/', views.experiment_detail, name='experiment_detail'),
]
