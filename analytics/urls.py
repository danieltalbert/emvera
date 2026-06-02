from django.urls import path
from . import views

app_name = 'analytics'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('beacon/', views.beacon, name='beacon'),
    path('alerts/<int:pk>/ack/', views.acknowledge_alert, name='acknowledge_alert'),
]
