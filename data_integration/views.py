# data_integration/views.py
"""
Views for user data integration:
"""

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render

from accounts.require_2fa import require_2fa

from .csv_import import import_transactions
from .forms import CSVUploadForm, ManualAccountForm, ManualDebtForm, ManualTransactionForm

logger = logging.getLogger(__name__)


@login_required
@require_2fa
def connect_plaid(request):
    from .plaid_client import is_configured

    return render(
        request,
        'data_integration/connect_plaid.html',
        {
            'plaid_configured': is_configured(),
            'linked_items': request.user.plaid_items.all(),
        },
    )


@login_required
@require_2fa
def plaid_link_token(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required.'}, status=405)
    from .plaid_client import PlaidNotConfigured, create_link_token

    try:
        token = create_link_token(request.user)
    except PlaidNotConfigured as exc:
        return JsonResponse({'error': str(exc)}, status=503)
    except Exception as exc:
        logger.error('Failed to create Plaid link token (%s).', type(exc).__name__)
        return JsonResponse({'error': 'Plaid is temporarily unavailable.'}, status=502)
    return JsonResponse({'link_token': token})


@login_required
@require_2fa
def plaid_exchange(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required.'}, status=405)
    public_token = request.POST.get('public_token')
    if not public_token:
        return JsonResponse({'error': 'public_token is required.'}, status=400)

    from .plaid_client import PlaidNotConfigured
    from .plaid_sync import PlaidItemOwnershipError, link_and_sync

    try:
        item, summary = link_and_sync(request.user, public_token)
    except PlaidItemOwnershipError:
        logger.warning('Rejected a cross-user Plaid Item link attempt.')
        return JsonResponse(
            {'error': 'This bank connection is already linked to another account.'},
            status=409,
        )
    except PlaidNotConfigured as exc:
        return JsonResponse({'error': str(exc)}, status=503)
    except Exception as exc:
        logger.error('Failed to exchange Plaid public token (%s).', type(exc).__name__)
        return JsonResponse({'error': 'Plaid sync is temporarily unavailable.'}, status=502)

    messages.success(
        request,
        f'Linked {item.institution_name or "your bank"} — '
        f'{summary.accounts_created} new account(s), {summary.transactions_added} transaction(s).',
    )
    return JsonResponse(
        {
            'item_id': item.item_id,
            'institution': item.institution_name,
            'accounts_created': summary.accounts_created,
            'transactions_added': summary.transactions_added,
        }
    )


@login_required
@require_2fa
def manual_account_entry(request):
    if request.method == 'POST':
        form = ManualAccountForm(request.POST)
        if form.is_valid():
            account = form.save(commit=False)
            account.user = request.user
            account.save()
            if request.user.profile_complete:
                return redirect('investments:portfolio_overview')
            return redirect('accounts:onboarding')
    else:
        form = ManualAccountForm()
    return render(request, 'data_integration/manual_account_entry.html', {'form': form})


@login_required
@require_2fa
def manual_transaction_entry(request):
    if request.method == 'POST':
        form = ManualTransactionForm(request.POST, user=request.user)
        if form.is_valid():
            transaction = form.save(commit=False)
            transaction.source = 'manual'
            transaction.save()
            return redirect('investments:portfolio_overview')
    else:
        form = ManualTransactionForm(user=request.user)
    return render(request, 'data_integration/manual_transaction_entry.html', {'form': form})


@login_required
@require_2fa
def manual_debt_entry(request):
    if request.method == 'POST':
        form = ManualDebtForm(request.POST, user=request.user)
        if form.is_valid():
            form.save()
            return redirect('debt_management:debt_dashboard')
    else:
        form = ManualDebtForm(user=request.user)
    return render(request, 'data_integration/manual_debt_entry.html', {'form': form})


@login_required
@require_2fa
def csv_upload(request):
    import_result = None
    if request.method == 'POST':
        form = CSVUploadForm(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            import_result = import_transactions(
                form.cleaned_data['file'],
                form.cleaned_data['account'],
            )
            if import_result.created:
                messages.success(
                    request,
                    f'Imported {import_result.created} transaction(s).'
                    + (f' Skipped {import_result.skipped}.' if import_result.skipped else ''),
                )
            elif import_result.row_errors:
                messages.error(request, 'No transactions imported — see issues below.')
            else:
                messages.warning(request, 'File contained no rows.')
    else:
        form = CSVUploadForm(user=request.user)
    return render(
        request,
        'data_integration/csv_upload.html',
        {
            'form': form,
            'import_result': import_result,
        },
    )
