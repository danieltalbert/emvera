"""
Map Plaid responses onto our local Account / Transaction / PlaidItem rows.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db import IntegrityError, transaction
from django.utils import timezone

from . import plaid_client
from .models import Account, PlaidItem

PLAID_TYPE_MAP = {
    'depository': 'checking',
    'credit': 'credit',
    'investment': 'investment',
    'loan': 'debt',
}


@dataclass
class SyncSummary:
    accounts_created: int = 0
    accounts_existing: int = 0
    transactions_added: int = 0
    transactions_modified: int = 0
    transactions_removed: int = 0


class PlaidItemOwnershipError(RuntimeError):
    """Raised when a Plaid Item is already linked to a different user."""


def _local_account_type(plaid_type: str, subtype: str) -> str:
    t = (plaid_type or '').lower()
    sub = (subtype or '').lower()
    if t == 'depository' and 'savings' in sub:
        return 'savings'
    return PLAID_TYPE_MAP.get(t, 'checking')


def link_and_sync(user, public_token: str) -> tuple[PlaidItem, SyncSummary]:
    """Exchange a public_token, persist the Item, sync accounts + transactions."""
    exchange = plaid_client.exchange_public_token(public_token)
    institution = ''
    try:
        institution = plaid_client.get_institution_name(exchange['access_token'])
    except Exception:
        # Institution lookup is best-effort; we already have the access token.
        pass

    # The Item lock remains held through provider synchronization so a web
    # relink and scheduled resync cannot advance the same cursor concurrently.
    # This deliberately trades a longer transaction for deterministic writes;
    # the demo's low sync volume makes that safer than cursor corruption.
    with transaction.atomic():
        item = PlaidItem.objects.select_for_update().filter(item_id=exchange['item_id']).first()
        if item is None:
            try:
                with transaction.atomic():
                    item = PlaidItem.objects.create(
                        item_id=exchange['item_id'],
                        user=user,
                        institution_name=institution,
                    )
            except IntegrityError:
                item = PlaidItem.objects.select_for_update().get(item_id=exchange['item_id'])

        if item.user_id != user.pk:
            raise PlaidItemOwnershipError(
                'This bank connection is already linked to another account.'
            )

        item.institution_name = institution
        item.set_access_token(exchange['access_token'])
        item.save()

        summary = SyncSummary()
        _sync_accounts(user, item, summary)
        _sync_transactions(user, item, summary)
        item.last_synced_at = timezone.now()
        item.save(update_fields=['last_synced_at'])
    return item, summary


def _sync_accounts(user, item: PlaidItem, summary: SyncSummary) -> dict[str, Account]:
    accounts = plaid_client.fetch_accounts(item.get_access_token())
    by_external_id: dict[str, Account] = {}
    for p in accounts:
        account, created = Account.objects.update_or_create(
            user=user,
            external_id=p['account_id'],
            defaults={
                'name': p['official_name'] or p['name'],
                'type': _local_account_type(p['type'], p['subtype']),
                'institution': item.institution_name,
            },
        )
        by_external_id[p['account_id']] = account
        if created:
            summary.accounts_created += 1
        else:
            summary.accounts_existing += 1
    return by_external_id


def _sync_transactions(user, item: PlaidItem, summary: SyncSummary):
    """Use Plaid's /transactions/sync cursor protocol so re-runs are idempotent."""
    try:
        from plaid.model.transactions_sync_request import TransactionsSyncRequest
    except ImportError as exc:
        raise plaid_client.PlaidNotConfigured('plaid-python not installed.') from exc

    client = plaid_client._client()
    cursor = item.cursor or ''
    accounts_by_id = {a.external_id: a for a in Account.objects.filter(user=user) if a.external_id}
    access_token = item.get_access_token()

    has_more = True
    while has_more:
        resp = client.transactions_sync(
            TransactionsSyncRequest(access_token=access_token, cursor=cursor)
        )
        from .models import Transaction

        for t in resp.added:
            account = accounts_by_id.get(t.account_id)
            if not account:
                continue
            _, created = Transaction.objects.update_or_create(
                account=account,
                external_id=t.transaction_id,
                defaults={
                    'date': t.date,
                    'amount': -t.amount,  # Plaid: positive = outflow; we use signed.
                    'category': (t.category or [''])[0] if t.category else '',
                    'description': t.name or '',
                    'source': 'api',
                },
            )
            if created:
                summary.transactions_added += 1
        for t in resp.modified:
            updated = Transaction.objects.filter(
                account__user=user,
                external_id=t.transaction_id,
            ).update(
                date=t.date,
                amount=-t.amount,
                category=(t.category or [''])[0] if t.category else '',
                description=t.name or '',
            )
            summary.transactions_modified += updated
        for t in resp.removed:
            count, _ = Transaction.objects.filter(
                account__user=user,
                external_id=t.transaction_id,
            ).delete()
            summary.transactions_removed += count

        cursor = resp.next_cursor
        has_more = resp.has_more

    item.cursor = cursor
    item.save(update_fields=['cursor'])
