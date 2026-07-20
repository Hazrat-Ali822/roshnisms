"""P3 — installable PWA: web manifest and service worker endpoints."""
import json

from django.test import Client, TestCase
from django.urls import reverse

from core.tests.factory import build_world


class PwaTests(TestCase):
    def setUp(self):
        self.w = build_world()
        self.c = Client()

    def test_manifest_is_valid(self):
        r = self.c.get(reverse('web_manifest'))
        self.assertEqual(r.status_code, 200)
        self.assertIn('manifest', r['Content-Type'])
        data = json.loads(r.content)
        self.assertEqual(data['display'], 'standalone')
        self.assertTrue(data['start_url'])
        # at least a 192 and a 512 icon (installability requirement)
        sizes = {i['sizes'] for i in data['icons']}
        self.assertIn('192x192', sizes)
        self.assertIn('512x512', sizes)

    def test_service_worker_served(self):
        r = self.c.get(reverse('service_worker'))
        self.assertEqual(r.status_code, 200)
        self.assertIn('javascript', r['Content-Type'])
        body = r.content.decode()
        self.assertIn('push', body)                 # push handler present
        self.assertIn('notificationclick', body)
        self.assertEqual(r['Service-Worker-Allowed'], '/')
