# data_integration/views.py
"""
Views for user data integration:
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from accounts.require_2fa import require_2fa

from .csv_import import import_transactions
from .forms import CSVUploadForm, ManualAccountForm, ManualDebtForm, ManualTransactionForm
from .models import Account, Transaction

SUPPORTED_PLAID_INSTITUTIONS = [
    'Chase', 'Bank of America', 'Wells Fargo', 'Citibank', 'US Bank',
    'Vanguard', 'Fidelity', 'Charles Schwab', 'Ally Bank', 'Capital One',
]


@login_required
@require_2fa
def connect_plaid(request):
    from .plaid_client import is_configured
    return render(request, 'data_integration/connect_plaid.html', {
        'plaid_configured': is_configured(),
        'linked_items': request.user.plaid_items.all(),
        'supported_institutions': SUPPORTED_PLAID_INSTITUTIONS,
    })


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
    except Exception as exc:  # network/credential issues, surface to client
        return JsonResponse({'error': f'Plaid error: {exc}'}, status=502)
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
    from .plaid_sync import link_and_sync
    try:
        item, summary = link_and_sync(request.user, public_token)
    except PlaidNotConfigured as exc:
        return JsonResponse({'error': str(exc)}, status=503)
    except Exception as exc:
        return JsonResponse({'error': f'Plaid sync failed: {exc}'}, status=502)

    messages.success(
        request,
        f'Linked {item.institution_name or "your bank"} — '
        f'{summary.accounts_created} new account(s), {summary.transactions_added} transaction(s).',
    )
    return JsonResponse({
        'item_id': item.item_id,
        'institution': item.institution_name,
        'accounts_created': summary.accounts_created,
        'transactions_added': summary.transactions_added,
    })

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
    return render(request, 'data_integration/csv_upload.html', {
        'form': form,
        'import_result': import_result,
    })


# ---------------------------------------------------------------------------
# Real brokerage linking (SnapTrade) + live pricing (Alpaca).
#
# These are the two future-optional "live investing" integrations. They are
# fully wired but gated: with no keys, the pages render an explainer and the
# actions no-op gracefully (mirroring how connect_plaid behaves without Plaid).
# See data_integration/snaptrade_client.py and alpaca_client.py for the why.
# ---------------------------------------------------------------------------

@login_required
@require_2fa
def connect_brokerage(request):
    """SnapTrade entry point: link a brokerage the user ALREADY has.

    When configured we ensure a BrokerageLink (registering the user with
    SnapTrade on first use) and hand back a connection-portal URL. When not
    configured we just render the "needs keys" explainer.
    """
    from . import snaptrade_client
    from .models import BrokerageLink

    configured = snaptrade_client.is_configured()
    portal_url = None
    if configured:
        link, _ = BrokerageLink.objects.get_or_create(
            user=request.user, provider=BrokerageLink.PROVIDER_SNAPTRADE,
        )
        if not link.get_user_secret():
            registration = snaptrade_client.register_user(request.user)
            link.provider_user_id = registration['user_id']
            link.set_user_secret(registration['user_secret'])
            link.save()
        portal_url = snaptrade_client.build_connection_portal_url(
            request.user, link.get_user_secret()
        )

    return render(request, 'data_integration/connect_brokerage.html', {
        'snaptrade_configured': configured,
        'portal_url': portal_url,
        'links': request.user.brokerage_links.all(),
    })


@login_required
@require_2fa
@require_POST
def sync_brokerage(request):
    """Pull the latest holdings from linked brokerages into Investments."""
    from . import snaptrade_client, brokerage_sync

    if not snaptrade_client.is_configured():
        messages.info(request, 'Brokerage linking isn’t configured yet (SnapTrade keys missing).')
        return redirect('data_integration:connect_brokerage')

    accounts = positions = 0
    for link in request.user.brokerage_links.all():
        try:
            summary = brokerage_sync.sync_link(link)
            accounts += summary['accounts']
            positions += summary['positions']
        except snaptrade_client.SnapTradeNotConfigured:
            pass
    messages.success(request, f'Synced {positions} position(s) from {accounts} account(s).')
    return redirect('data_integration:connect_brokerage')


@login_required
@require_2fa
@require_POST
def refresh_prices(request):
    """Update holding values from live Alpaca market data (data_integration/pricing.py)."""
    from . import alpaca_client, pricing

    if not alpaca_client.is_configured():
        messages.info(request, 'Live pricing isn’t configured yet (Alpaca keys missing).')
        return redirect('investments:portfolio_overview')
    try:
        result = pricing.refresh_user_investment_values(request.user)
        messages.success(request, f"Updated {result['updated']} holding value(s) from live prices.")
    except alpaca_client.AlpacaNotConfigured:
        messages.info(request, 'Live pricing isn’t configured yet.')
    return redirect('investments:portfolio_overview')
