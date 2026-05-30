from django.urls import path
from . import views

app_name = 'paper_trading'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('order/', views.place_order, name='place_order'),
]
