# data_integration/urls.py
from django.urls import path
from . import views

app_name = 'data_integration'

urlpatterns = [
    path('connect-plaid/', views.connect_plaid, name='connect_plaid'),
    path('manual-account/', views.manual_account_entry, name='manual_account_entry'),
    path('manual-transaction/', views.manual_transaction_entry, name='manual_transaction_entry'),
    path('csv-upload/', views.csv_upload, name='csv_upload'),
]
