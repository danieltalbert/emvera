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
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.template.loader import render_to_string
from django.utils import timezone

from debt_management.models import PaymentReminder


COOLDOWN_HOURS = 24


def _build_email_body(reminder, days_until_due):
    if days_until_due < 0:
        when = f"is overdue by {abs(days_until_due)} day(s)"
    elif days_until_due == 0:
        when = "is due today"
    else:
        when = f"is due in {days_until_due} day(s) ({reminder.due_date:%b %d, %Y})"
    return (
        f"Hi {reminder.user.get_short_name() or reminder.user.username},\n\n"
        f"Your payment for {reminder.name} {when}.\n"
        f"Amount: ${reminder.amount:,.2f}\n"
        f"{('Institution: ' + reminder.institution) if reminder.institution else ''}\n\n"
        "Log in to Emvera to review or mark it paid.\n"
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
    Client(sid, token).messages.create(to=to_number, from_=from_number, body=body)
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

        candidates = PaymentReminder.objects.filter(
            is_paid=False,
        ).select_related('user', 'debt', 'debt__account')

        for r in candidates:
            window_start = r.due_date - timedelta(days=r.notify_days_before)
            if today < window_start:
                continue
            if r.last_notified_at and r.last_notified_at > cooldown:
                continue

            considered += 1
            days_until = (r.due_date - today).days
            subject = f'Payment reminder: {r.name} ({"overdue" if days_until < 0 else f"due in {days_until} day(s)"})'
            body = _build_email_body(r, days_until)

            self.stdout.write(f'- {r.user} -> {r.name} (due {r.due_date}, days_until={days_until})')

            if r.notify_via_email and r.user.email:
                if dry_run:
                    self.stdout.write(f'  [dry-run] would email {r.user.email}')
                else:
                    send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [r.user.email])
                    sent_email += 1

            if r.notify_via_sms:
                phone = getattr(r.user, 'phone_number', '')
                if not phone:
                    self.stdout.write('  SMS skipped: user has no phone number.')
                elif dry_run:
                    self.stdout.write(f'  [dry-run] would SMS {phone}')
                else:
                    if _send_sms(phone, f'{subject}\n{body}', self.stdout):
                        sent_sms += 1

            if not dry_run:
                r.last_notified_at = now
                r.save(update_fields=['last_notified_at', 'updated_at'])

        self.stdout.write(self.style.SUCCESS(
            f'Done. Considered {considered}, sent {sent_email} email(s), {sent_sms} SMS.'
        ))
