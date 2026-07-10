"""
Incrementally sync transactions for every linked PlaidItem.

Uses /transactions/sync with the cursor each Item already stores, so each run
only fetches what changed since last time. Safe to run on a schedule:

    # Daily at 02:30
    30 2 * * *  cd /srv/emvera && /srv/emvera/.venv/bin/python manage.py plaid_resync

Filter to one user with --user=<username>. Skip Items not touched recently
with --stale-hours=N (default: sync everything).
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from data_integration import plaid_client
from data_integration.models import PlaidItem
from data_integration.plaid_sync import SyncSummary, _sync_accounts, _sync_transactions


class Command(BaseCommand):
    help = 'Re-sync transactions for every linked PlaidItem via the cursor protocol.'

    def add_arguments(self, parser):
        parser.add_argument('--user', help='Limit to one username.')
        parser.add_argument(
            '--stale-hours', type=int, default=0,
            help='Only re-sync items whose last_synced_at is older than this many hours.',
        )
        parser.add_argument('--dry-run', action='store_true', help='Skip side effects, just report.')

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        if not dry_run and not plaid_client.is_configured():
            raise CommandError(
                'Plaid is not configured. Set PLAID_CLIENT_ID and PLAID_SECRET in your environment.'
            )

        qs = PlaidItem.objects.select_related('user')
        if options['user']:
            User = get_user_model()
            try:
                u = User.objects.get(username=options['user'])
            except User.DoesNotExist:
                raise CommandError(f'No user named "{options["user"]}".')
            qs = qs.filter(user=u)

        if options['stale_hours']:
            threshold = timezone.now() - timedelta(hours=options['stale_hours'])
            qs = qs.filter(last_synced_at__lt=threshold) | qs.filter(last_synced_at__isnull=True)

        total = qs.count()
        if not total:
            self.stdout.write('No items to sync.')
            return

        self.stdout.write(f'Syncing {total} item(s)...')
        for item in qs:
            self.stdout.write(f'- {item.user.username} / {item.institution_name or item.item_id}')
            if dry_run:
                continue
            summary = SyncSummary()
            try:
                _sync_accounts(item.user, item, summary)
                _sync_transactions(item.user, item, summary)
                item.last_synced_at = timezone.now()
                item.save(update_fields=['last_synced_at'])
            except plaid_client.PlaidNotConfigured as exc:
                raise CommandError(str(exc))
            except Exception as exc:
                self.stdout.write(self.style.ERROR(f'  failed: {exc}'))
                continue
            self.stdout.write(self.style.SUCCESS(
                f'  +{summary.transactions_added} added, ~{summary.transactions_modified} modified, '
                f'-{summary.transactions_removed} removed'
            ))

        self.stdout.write(self.style.SUCCESS('Done.'))
