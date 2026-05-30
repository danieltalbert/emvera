"""Views for the paper-trading simulator (see models.py for the why)."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from accounts.require_2fa import require_2fa
from data_integration import alpaca_client
from .execution import submit_order, OrderError
from .models import PaperAccount


def _get_practice_account(user) -> PaperAccount:
    """Each user gets one stand-alone practice account, created on first visit."""
    account, _ = PaperAccount.objects.get_or_create(user=user, competition=None)
    return account


@login_required
@require_2fa
def dashboard(request):
    account = _get_practice_account(request.user)
    positions = list(account.positions.all())

    # Price holdings live when Alpaca is configured; otherwise fall back to cost
    # basis and let the template show a "connect Alpaca for live prices" notice.
    prices = {}
    if alpaca_client.is_configured() and positions:
        try:
            prices = alpaca_client.get_latest_prices([p.symbol for p in positions])
        except alpaca_client.AlpacaNotConfigured:
            prices = {}

    rows = []
    for p in positions:
        price = prices.get(p.symbol.upper())
        rows.append({
            'symbol': p.symbol,
            'quantity': p.quantity,
            'avg_cost': p.avg_cost,
            'price': price,
            'market_value': (p.quantity * price) if price is not None else None,
        })

    return render(request, 'paper_trading/dashboard.html', {
        'account': account,
        'rows': rows,
        'equity': account.equity(prices),
        'alpaca_configured': alpaca_client.is_configured(),
        'recent_orders': account.orders.all()[:10],
    })


@login_required
@require_2fa
@require_POST
def place_order(request):
    account = _get_practice_account(request.user)
    try:
        order = submit_order(
            account,
            symbol=request.POST.get('symbol', ''),
            side=request.POST.get('side', 'buy'),
            quantity=request.POST.get('quantity', '0'),
        )
    except OrderError as exc:
        messages.error(request, str(exc))
    else:
        if order.status == order.STATUS_FILLED:
            messages.success(
                request,
                f'{order.side.title()} {order.quantity} {order.symbol} @ ${order.fill_price}.',
            )
        else:
            messages.warning(request, order.note or 'Order could not be filled.')
    return redirect('paper_trading:dashboard')
