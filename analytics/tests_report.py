"""Tests for the CSV/PDF report export (PDF is gated on reportlab)."""
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.utils import timezone

from .models import PageView
from . import reporting

User = get_user_model()


class ReportContentTests(TestCase):
    def setUp(self):
        now = timezone.now()
        PageView.objects.bulk_create([
            PageView(user=None, session_hash='s1', path='/investments/', section='Investments',
                     method='GET', status_code=200, response_ms=15, is_authenticated=False,
                     timestamp=now - timedelta(days=1), hour=10, weekday=2)
            for _ in range(5)
        ])

    def test_report_sections_present(self):
        titles = [s['title'] for s in reporting.report_sections(30)]
        self.assertIn('Overview', titles)
        self.assertIn('Sessions', titles)
        self.assertIn('Top pages', titles)

    def test_csv_has_header_and_values(self):
        csv_text = reporting.report_csv(30)
        self.assertTrue(csv_text.startswith('Section,Metric,Value'))
        self.assertIn('Total page views', csv_text)


class ExportViewTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(username='boss', password='x', is_staff=True)
        self.client.force_login(self.staff)

    def test_csv_download(self):
        r = self.client.get(reverse('analytics:export_csv') + '?days=30')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'text/csv')
        self.assertIn('attachment', r['Content-Disposition'])
        self.assertIn('Section,Metric,Value', r.content.decode())

    def test_pdf_gated_when_reportlab_absent(self):
        # reportlab isn't installed in this env -> graceful redirect with a note,
        # never a 500. (If it IS installed, we should get a real PDF instead.)
        r = self.client.get(reverse('analytics:export_pdf') + '?days=30')
        if reporting.pdf_available():
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r['Content-Type'], 'application/pdf')
        else:
            self.assertEqual(r.status_code, 302)

    def test_export_requires_staff(self):
        joe = User.objects.create_user(username='joe', password='x')
        self.client.force_login(joe)
        r = self.client.get(reverse('analytics:export_csv'))
        self.assertEqual(r.status_code, 302)  # bounced to admin login
