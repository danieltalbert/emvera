# data_integration/views.py
"""
Views for user data integration:
"""
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from accounts.require_2fa import require_2fa
from django.http import JsonResponse, HttpResponse
from .models import Account, Transaction
from .forms import ManualAccountForm, ManualTransactionForm, CSVUploadForm

@login_required
@require_2fa
def connect_plaid(request):
    # Placeholder: Implement Plaid Link and token exchange
    return render(request, 'data_integration/connect_plaid.html')

@login_required
@require_2fa
def manual_account_entry(request):
    if request.method == 'POST':
        form = ManualAccountForm(request.POST)
        if form.is_valid():
            account = form.save(commit=False)
            account.user = request.user
            account.save()
            return redirect('accounts:list')
    else:
        form = ManualAccountForm()
    return render(request, 'data_integration/manual_account_entry.html', {'form': form})

@login_required
@require_2fa
def manual_transaction_entry(request):
    if request.method == 'POST':
        form = ManualTransactionForm(request.POST)
        if form.is_valid():
            transaction = form.save()
            return redirect('accounts:detail', pk=transaction.account.pk)
    else:
        form = ManualTransactionForm()
    return render(request, 'data_integration/manual_transaction_entry.html', {'form': form})

@login_required
@require_2fa
def csv_upload(request):
    if request.method == 'POST':
        form = CSVUploadForm(request.POST, request.FILES)
        if form.is_valid():
            # Placeholder: Parse CSV and create Transaction objects
            return HttpResponse('CSV uploaded and processed.')
    else:
        form = CSVUploadForm()
    return render(request, 'data_integration/csv_upload.html', {'form': form})
