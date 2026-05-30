"""
Order execution for the paper-trading simulator.

DESIGN: `submit_order` fetches a live price from Alpaca (when configured) and
hands off to `execute_fill`, which is PURE — no network, no price source — and
therefore directly unit-testable. If Alpaca isn't configured we record a
REJECTED order rather than invent a price, honoring the project rule that
nothing fabricates market data.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from data_integration import alpaca_client
from .models import PaperAccount, PaperPosition, PaperOrder


class OrderError(Exception):
    """A paper order that can't be filled (bad input, insufficient funds, …)."""


def submit_order(account: PaperAccount, symbol: str, side: str, quantity) -> PaperOrder:
    """Price the order from live data and apply the fill.

    Raises OrderError for bad input or an unfillable order. Returns a REJECTED
    PaperOrder (rather than raising) when Alpaca isn't configured, so the UI can
    explain that live pricing is required.
    """
    symbol = (symbol or '').upper().strip()
    side = (side or '').lower().strip()
    try:
        quantity = Decimal(str(quantity))
    except (InvalidOperation, TypeError):
        raise OrderError('Quantity must be a number.')
    if not symbol or quantity <= 0:
        raise OrderError('Enter a symbol and a positive quantity.')
    if side not in (PaperOrder.SIDE_BUY, PaperOrder.SIDE_SELL):
        raise OrderError('Side must be buy or sell.')

    if not alpaca_client.is_configured():
        return PaperOrder.objects.create(
            account=account, symbol=symbol, side=side, quantity=quantity,
            status=PaperOrder.STATUS_REJECTED,
            note='Live pricing unavailable (Alpaca not configured).',
        )

    price = alpaca_client.get_latest_prices([symbol]).get(symbol)
    if price is None:
        raise OrderError(f'No live price available for {symbol}.')
    return execute_fill(account, symbol, side, quantity, Decimal(price))


def execute_fill(account: PaperAccount, symbol: str, side: str, quantity, price) -> PaperOrder:
    """Apply a fill at `price`. PURE (no network) — unit-test this directly.

    Updates cash and positions, maintains a weighted-average cost basis on buys,
    and records a FILLED PaperOrder.
    """
    symbol = symbol.upper()
    quantity = Decimal(quantity)
    price = Decimal(price)
    cost = (quantity * price).quantize(Decimal('0.01'))

    if side == PaperOrder.SIDE_BUY:
        if cost > account.cash:
            raise OrderError('Insufficient cash for this buy.')
        position, _ = PaperPosition.objects.get_or_create(account=account, symbol=symbol)
        new_qty = position.quantity + quantity
        # Weighted-average cost basis across the prior and new shares.
        position.avg_cost = (
            ((position.quantity * position.avg_cost) + cost) / new_qty
        ).quantize(Decimal('0.0001'))
        position.quantity = new_qty
        position.save()
        account.cash = (account.cash - cost).quantize(Decimal('0.01'))
        account.save(update_fields=['cash'])

    else:  # SIDE_SELL
        try:
            position = PaperPosition.objects.get(account=account, symbol=symbol)
        except PaperPosition.DoesNotExist:
            raise OrderError(f'You hold no {symbol} to sell.')
        if quantity > position.quantity:
            raise OrderError(f'You only hold {position.quantity} {symbol}.')
        position.quantity -= quantity
        if position.quantity <= 0:
            position.delete()
        else:
            position.save()
        account.cash = (account.cash + cost).quantize(Decimal('0.01'))
        account.save(update_fields=['cash'])

    return PaperOrder.objects.create(
        account=account, symbol=symbol, side=side, quantity=quantity,
        fill_price=price, status=PaperOrder.STATUS_FILLED,
    )
