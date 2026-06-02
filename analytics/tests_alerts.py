"""Tests for anomaly alerting: detection -> persistence -> email -> acknowledge."""
from datetime import timedelta

from django.core import mail
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.utils import timezone

from .models import PageView, AnomalyAlert

User = get_user_model()


def _seed_traffic_with_spike():
    """~12 quiet days then one huge spike day, so z-score must flag it."""
    now = timezone.now()
    rows = []
    for d in range(14):
        day = now - timedelta(days=13 - d)
        count = 200 if d == 10 else 10  # day index 10 is the spike
        for _ in range(count):
            rows.append(PageView(
                user=None, session_hash='x', path='/investments/', section='Investments',
                method='GET', status_code=200, response_ms=10, is_authenticated=False,
                timestamp=day, hour=day.hour, weekday=day.weekday(),
            ))
    PageView.objects.bulk_create(rows, batch_size=1000)


class CheckAnomaliesCommandTests(TestCase):
    def setUp(self):
        _seed_traffic_with_spike()

    def test_creates_alert_for_spike(self):
        call_command('check_anomalies', '--days', '14', '--threshold', '2.0', '--no-email')
        self.assertTrue(AnomalyAlert.objects.filter(direction='spike').exists())

    def test_is_idempotent(self):
        call_command('check_anomalies', '--days', '14', '--threshold', '2.0', '--no-email')
        first = AnomalyAlert.objects.count()
        call_command('check_anomalies', '--days', '14', '--threshold', '2.0', '--no-email')
        self.assertEqual(AnomalyAlert.objects.count(), first)  # no duplicates

    def test_emails_staff_about_new_alerts(self):
        User.objects.create_user(username='boss', password='x', is_staff=True, email='boss@example.com')
        call_command('check_anomalies', '--days', '14', '--threshold', '2.0')
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('anomaly', mail.outbox[0].subject.lower())
        self.assertIn('boss@example.com', mail.outbox[0].to)

    def test_no_email_when_no_new_alerts(self):
        User.objects.create_user(username='boss', password='x', is_staff=True, email='boss@example.com')
        call_command('check_anomalies', '--days', '14', '--threshold', '2.0')  # creates + emails
        mail.outbox.clear()
        call_command('check_anomalies', '--days', '14', '--threshold', '2.0')  # nothing new
        self.assertEqual(len(mail.outbox), 0)


class AcknowledgeTests(TestCase):
    def setUp(self):
        self.alert = AnomalyAlert.objects.create(
            metric='daily_traffic', date=timezone.now().date(),
            value=200, z_score=3.1, direction='spike')
        self.staff = User.objects.create_user(username='boss', password='x', is_staff=True)

    def test_staff_can_acknowledge(self):
        self.client.force_login(self.staff)
        r = self.client.post(reverse('analytics:acknowledge_alert', args=[self.alert.pk]))
        self.assertEqual(r.status_code, 302)
        self.alert.refresh_from_db()
        self.assertTrue(self.alert.acknowledged)
        self.assertIsNotNone(self.alert.acknowledged_at)

    def test_non_staff_cannot_acknowledge(self):
        joe = User.objects.create_user(username='joe', password='x')
        self.client.force_login(joe)
        r = self.client.post(reverse('analytics:acknowledge_alert', args=[self.alert.pk]))
        self.assertEqual(r.status_code, 302)  # redirected to admin login
        self.alert.refresh_from_db()
        self.assertFalse(self.alert.acknowledged)
