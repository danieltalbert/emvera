"""
Refresh Investment values from live market prices (Alpaca).

WHY: this is the "live time" piece. It recomputes each holding's stored `value`
as quantity * latest_price so portfolios — and, later, competition standings —
reflect the current market. It works for holdings from any source (manual,
Plaid, or a linked brokerage) as long as the Investment has a ticker `symbol`.

DESIGN: only `refresh_user_investment_values` touches the network (via
alpaca_client). `_apply_prices` is pure ORM and is unit-testable by passing in
a {symbol: price} map (see tests).
"""
from __future__ import annotations

from decimal import Decimal

from . import alpaca_client
from .models import Investment


def refresh_user_investment_values(user) -> dict:
    """Update every priced holding for `user` from live Alpaca quotes.

    Requires Alpaca to be configured; raises AlpacaNotConfigured otherwise.
    """
    investments = list(Investment.objects.filter(account__user=user).exclude(symbol=''))
    symbols = {inv.symbol.upper() for inv in investments}
    prices = alpaca_client.get_latest_prices(symbols)
    return _apply_prices(investments, prices)


def _apply_prices(investments, prices: dict) -> dict:
    """Apply a {symbol: price} map to Investment rows. No network — testable."""
    updated = 0
    for inv in investments:
        price = prices.get(inv.symbol.upper())
        if price is None:
            continue
        inv.value = (Decimal(inv.quantity) * Decimal(price)).quantize(Decimal('0.01'))
        inv.save(update_fields=['value'])
        updated += 1
    return {'priced': len(prices), 'updated': updated}
