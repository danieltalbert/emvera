from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from data_integration.crypto import decrypt, encrypt, has_dedicated_key
from data_integration.models import PlaidItem


class Command(BaseCommand):
    help = 'Re-encrypt every stored Plaid access token with the active dedicated key.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Verify every token can be decrypted without updating rows.',
        )

    def handle(self, *args, **options):
        if not has_dedicated_key():
            raise CommandError('Set PLAID_TOKEN_ENCRYPTION_KEY before rotating tokens.')

        rewritten = 0
        with transaction.atomic():
            # Lock and evaluate inside one transaction so a concurrent relink
            # cannot replace a token between the read and encrypted rewrite.
            items = list(
                PlaidItem.objects.select_for_update().only('pk', 'access_token').order_by('pk')
            )
            for item in items:
                raw_token = decrypt(item.access_token)
                if not raw_token:
                    raise CommandError(
                        f'Plaid Item {item.pk} has an empty or unreadable access token.'
                    )
                if not options['dry_run']:
                    item.access_token = encrypt(raw_token)
                    item.save(update_fields=['access_token'])
                    rewritten += 1

        if options['dry_run']:
            self.stdout.write(self.style.SUCCESS(f'Verified {len(items)} token(s).'))
        else:
            self.stdout.write(self.style.SUCCESS(f'Re-encrypted {rewritten} token(s).'))
