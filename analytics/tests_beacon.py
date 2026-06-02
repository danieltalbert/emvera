"""Tests for the time-on-page beacon: token minting, ingestion, and clamping."""
import json

from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model

from .models import PageView

User = get_user_model()


class BeaconTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='surf', password='x')
        self.client.login(username='surf', password='x')

    def test_pageview_gets_a_view_token(self):
        self.client.get(reverse('competition:lobby'))
        pv = PageView.objects.latest('timestamp')
        self.assertEqual(len(pv.view_token), 32)
        self.assertEqual(pv.dwell_ms, 0)

    def test_beacon_attaches_dwell(self):
        self.client.get(reverse('competition:lobby'))
        pv = PageView.objects.latest('timestamp')
        r = self.client.post(reverse('analytics:beacon'),
                             data=json.dumps({'token': pv.view_token, 'dwell_ms': 4200}),
                             content_type='application/json')
        self.assertEqual(r.status_code, 204)
        pv.refresh_from_db()
        self.assertEqual(pv.dwell_ms, 4200)

    def test_beacon_clamps_absurd_values(self):
        self.client.get(reverse('competition:lobby'))
        pv = PageView.objects.latest('timestamp')
        # 10 hours -> rejected (over the 30-min cap), dwell stays 0.
        self.client.post(reverse('analytics:beacon'),
                         data=json.dumps({'token': pv.view_token, 'dwell_ms': 36000000}),
                         content_type='application/json')
        pv.refresh_from_db()
        self.assertEqual(pv.dwell_ms, 0)

    def test_beacon_unknown_token_is_noop(self):
        r = self.client.post(reverse('analytics:beacon'),
                             data=json.dumps({'token': 'deadbeef' * 4, 'dwell_ms': 1000}),
                             content_type='application/json')
        self.assertEqual(r.status_code, 204)  # accepted, matched nothing

    def test_beacon_bad_payload_is_rejected(self):
        r = self.client.post(reverse('analytics:beacon'), data='not json',
                             content_type='application/json')
        self.assertEqual(r.status_code, 400)

    def test_beacon_is_csrf_exempt(self):
        # A CSRF-enforcing client must still be accepted (sendBeacon can't send tokens).
        from django.test import Client
        c = Client(enforce_csrf_checks=True)
        c.login(username='surf', password='x')
        c.get(reverse('competition:lobby'))
        pv = PageView.objects.latest('timestamp')
        r = c.post(reverse('analytics:beacon'),
                   data=json.dumps({'token': pv.view_token, 'dwell_ms': 1500}),
                   content_type='application/json')
        self.assertEqual(r.status_code, 204)
