"""
Send notifications for upcoming PaymentReminders.

Picks up every open reminder whose `due_date` falls inside its
`notify_days_before` window (or is already overdue) and hasn't been notified
in the last 24 hours, then sends an email and/or SMS based on the per-reminder
toggles.

Run this on a schedule — once a day is plenty:

    # Linux/macOS cron
    0 8 * * *  cd /srv/emvera && /srv/emvera/.venv/bin/python manage.py send_due_reminders

    # Windows Task Scheduler
    schtasks /Create /SC DAILY /TN "Emvera reminders" /TR ^
      "python C:\\path\\to\\emvera\\manage.py send_due_reminders" /ST 08:00

SMS is delivered through Twilio if TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, and
TWILIO_FROM_NUMBER are set; otherwise the command logs that SMS is skipped.
"""

import logging
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from debt_management.models import PaymentReminder

COOLDOWN_HOURS = 24
logger = logging.getLogger(__name__)


def _build_email_body(reminder, days_until_due):
    if days_until_due < 0:
        when = f'is overdue by {abs(days_until_due)} day(s)'
    elif days_until_due == 0:
        when = 'is due today'
    else:
        when = f'is due in {days_until_due} day(s) ({reminder.due_date:%b %d, %Y})'
    return (
        f'Hi {reminder.user.get_short_name() or reminder.user.username},\n\n'
        f'Your payment for {reminder.name} {when}.\n'
        f'Amount: ${reminder.amount:,.2f}\n'
        f'{("Institution: " + reminder.institution) if reminder.institution else ""}\n\n'
        'Log in to Emvera to review or mark it paid.\n'
    )


def _send_sms(to_number, body, stdout):
    sid = getattr(settings, 'TWILIO_ACCOUNT_SID', '')
    token = getattr(settings, 'TWILIO_AUTH_TOKEN', '')
    from_number = getattr(settings, 'TWILIO_FROM_NUMBER', '')
    if not (sid and token and from_number):
        stdout.write('  SMS skipped: Twilio credentials not configured.')
        return False
    try:
        from twilio.rest import Client  # type: ignore
    except ImportError:
        stdout.write('  SMS skipped: install `twilio` to enable.')
        return False
    try:
        Client(sid, token).messages.create(to=to_number, from_=from_number, body=body)
    except Exception as exc:
        logger.error('Twilio reminder delivery failed (%s).', type(exc).__name__)
        stdout.write('  SMS delivery failed.')
        return False
    return True


class Command(BaseCommand):
    help = 'Send email/SMS notifications for upcoming PaymentReminders.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be sent without actually sending.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        now = timezone.now()
        today = now.date()
        cooldown = now - timedelta(hours=COOLDOWN_HOURS)

        sent_email = 0
        sent_sms = 0
        considered = 0

        candidate_ids = PaymentReminder.objects.filter(is_paid=False).values_list('pk', flat=True)

        for reminder_id in candidate_ids.iterator():
            # Claim due channels under a row lock. Provider calls happen after
            # commit so an SMTP/Twilio timeout does not hold a DB transaction.
            with transaction.atomic():
                r = (
                    PaymentReminder.objects.select_for_update()
                    .select_related('user', 'debt', 'debt__account')
                    .get(pk=reminder_id)
                )
                window_start = r.due_date - timedelta(days=r.notify_days_before)
                if r.is_paid or today < window_start:
                    continue

                email_due = r.notify_via_email and (
                    r.email_last_notified_at is None or r.email_last_notified_at <= cooldown
                )
                sms_due = r.notify_via_sms and (
                    r.sms_last_notified_at is None or r.sms_last_notified_at <= cooldown
                )
                if not email_due and not sms_due:
                    continue

                previous_email_at = r.email_last_notified_at
                previous_sms_at = r.sms_last_notified_at
                previous_last_at = r.last_notified_at
                if not dry_run:
                    update_fields = ['last_notified_at', 'updated_at']
                    r.last_notified_at = now
                    if email_due:
                        r.email_last_notified_at = now
                        update_fields.append('email_last_notified_at')
                    if sms_due:
                        r.sms_last_notified_at = now
                        update_fields.append('sms_last_notified_at')
                    r.save(update_fields=update_fields)

            considered += 1
            days_until = (r.due_date - today).days
            subject = f'Payment reminder: {r.name} ({"overdue" if days_until < 0 else f"due in {days_until} day(s)"})'
            body = _build_email_body(r, days_until)
            email_succeeded = False
            sms_succeeded = False
            email_failed = False
            sms_failed = False

            self.stdout.write(f'- processing reminder {r.pk} (days_until={days_until})')

            if email_due:
                if not r.user.email:
                    email_failed = True
                    self.stdout.write('  Email skipped: user has no email address.')
                elif dry_run:
                    self.stdout.write('  [dry-run] would send email.')
                else:
                    try:
                        delivered = send_mail(
                            subject,
                            body,
                            settings.DEFAULT_FROM_EMAIL,
                            [r.user.email],
                        )
                        if delivered == 1:
                            sent_email += 1
                            email_succeeded = True
                        else:
                            email_failed = True
                            self.stdout.write(self.style.ERROR('  Email was not accepted.'))
                    except Exception as exc:
                        email_failed = True
                        logger.error(
                            'Email delivery failed for reminder %s (%s).',
                            r.pk,
                            type(exc).__name__,
                        )
                        self.stdout.write(self.style.ERROR('  Email delivery failed.'))

            if sms_due:
                phone = getattr(r.user, 'phone_number', '')
                if not phone:
                    sms_failed = True
                    self.stdout.write('  SMS skipped: user has no phone number.')
                elif dry_run:
                    self.stdout.write('  [dry-run] would send SMS.')
                else:
                    if _send_sms(phone, f'{subject}\n{body}', self.stdout):
                        sent_sms += 1
                        sms_succeeded = True
                    else:
                        sms_failed = True

            if not dry_run and (email_failed or sms_failed):
                # Release only failed channel claims. A successful email is
                # therefore not duplicated merely because SMS needs a retry.
                with transaction.atomic():
                    current = PaymentReminder.objects.select_for_update().get(pk=r.pk)
                    update_fields = ['updated_at']
                    if email_failed and current.email_last_notified_at == now:
                        current.email_last_notified_at = previous_email_at
                        update_fields.append('email_last_notified_at')
                    if sms_failed and current.sms_last_notified_at == now:
                        current.sms_last_notified_at = previous_sms_at
                        update_fields.append('sms_last_notified_at')
                    if (
                        not email_succeeded
                        and not sms_succeeded
                        and current.last_notified_at == now
                    ):
                        current.last_notified_at = previous_last_at
                        update_fields.append('last_notified_at')
                    current.save(update_fields=update_fields)

        self.stdout.write(
            self.style.SUCCESS(
                f'Done. Considered {considered}, sent {sent_email} email(s), {sent_sms} SMS.'
            )
        )
