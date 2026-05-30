"""
Sync real brokerage holdings (via SnapTrade) into Emvera's own models.

WHY: this bridges the aggregator to the rest of the app. Connected brokerage
accounts become `Account` rows (type='investment') and their positions become
`Investment` rows, so the existing portfolio views, projections, comparisons —
and, later, competitions — work on real data with no further changes.

DESIGN: the only network calls live in `sync_link` (through snaptrade_client).
The actual upsert mapping is in `_sync_account_holdings`, which takes plain
dicts and touches only the ORM, so it is unit-testable without any SnapTrade
credentials (see tests).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.utils import timezone

from . import snaptrade_client
from .models import Account, Investment, BrokerageLink


def sync_link(link: BrokerageLink) -> dict:
    """Pull every account + its holdings for one BrokerageLink and upsert them.

    Requires SnapTrade to be configured; returns a small summary dict.
    """
    secret = link.get_user_secret()
    accounts = snaptrade_client.list_accounts(link.user, secret)
    positions = 0
    for acct in accounts:
        holdings = snaptrade_client.list_holdings(link.user, secret, acct['account_id'])
        positions += _sync_account_holdings(link, acct, holdings)
    link.last_synced_at = timezone.now()
    link.save(update_fields=['last_synced_at'])
    return {'accounts': len(accounts), 'positions': positions}


def _sync_account_holdings(link: BrokerageLink, acct: dict, holdings: list[dict]) -> int:
    """Upsert one brokerage account and its positions. No network — testable.

    The brokerage account is keyed by a namespaced external_id so re-syncing
    updates the same rows instead of duplicating them.
    """
    account, _ = Account.objects.update_or_create(
        user=link.user,
        external_id=f"snaptrade:{acct['account_id']}",
        defaults={
            'name': acct.get('name') or 'Brokerage',
            'type': 'investment',
            'institution': acct.get('institution', ''),
        },
    )
    count = 0
    for holding in holdings:
        symbol = (holding.get('symbol') or '').upper()
        if not symbol:
            continue
        quantity = Decimal(str(holding.get('quantity') or 0))
        price = Decimal(str(holding.get('price') or 0))
        Investment.objects.update_or_create(
            account=account,
            symbol=symbol,
            defaults={
                'name': symbol,
                'type': 'brokerage',
                'quantity': quantity,
                'value': (quantity * price).quantize(Decimal('0.01')),
                'as_of': date.today(),
            },
        )
        count += 1
    return count
