# data_integration/urls.py
from django.urls import path
from . import views

app_name = 'data_integration'

urlpatterns = [
    path('connect-plaid/', views.connect_plaid, name='connect_plaid'),
    path('plaid/link-token/', views.plaid_link_token, name='plaid_link_token'),
    path('plaid/exchange/', views.plaid_exchange, name='plaid_exchange'),
    path('manual-account/', views.manual_account_entry, name='manual_account_entry'),
    path('manual-transaction/', views.manual_transaction_entry, name='manual_transaction_entry'),
    path('manual-debt/', views.manual_debt_entry, name='manual_debt_entry'),
    path('csv-upload/', views.csv_upload, name='csv_upload'),
]
