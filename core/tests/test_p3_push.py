"""P3 — Web Push: subscription capture and guardian resolution."""
import json

from django.test import Client, TestCase
from django.urls import reverse

from core import push
from core.models import PushSubscription
from core.tests.factory import build_world, PASSWORD


class PushSubscribeTests(TestCase):
    def setUp(self):
        self.w = build_world()
        self.c = Client()
        self.c.login(username='parent1', password=PASSWORD)

    def test_subscribe_saves_subscription(self):
        payload = {'endpoint': 'https://push.example/abc',
                   'keys': {'p256dh': 'KEY123', 'auth': 'AUTH123'}}
        r = self.c.post(reverse('push_subscribe'), data=json.dumps(payload),
                        content_type='application/json')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['ok'])
        sub = PushSubscription.objects.get(endpoint='https://push.example/abc')
        self.assertEqual(sub.user, self.w.parent_u)
        self.assertEqual(sub.auth, 'AUTH123')

    def test_subscribe_rejects_incomplete(self):
        r = self.c.post(reverse('push_subscribe'),
                        data=json.dumps({'endpoint': 'x'}),
                        content_type='application/json')
        self.assertEqual(r.status_code, 400)

    def test_resubscribe_updates_in_place(self):
        payload = {'endpoint': 'https://push.example/same',
                   'keys': {'p256dh': 'K1', 'auth': 'A1'}}
        self.c.post(reverse('push_subscribe'), data=json.dumps(payload),
                    content_type='application/json')
        payload['keys'] = {'p256dh': 'K2', 'auth': 'A2'}
        self.c.post(reverse('push_subscribe'), data=json.dumps(payload),
                    content_type='application/json')
        self.assertEqual(
            PushSubscription.objects.filter(endpoint='https://push.example/same').count(), 1)
        self.assertEqual(
            PushSubscription.objects.get(endpoint='https://push.example/same').auth, 'A2')


class GuardianResolveTests(TestCase):
    def setUp(self):
        self.w = build_world()

    def test_guardian_users_includes_parent_and_student(self):
        users = push.guardian_users(self.w.ayaan)
        self.assertIn(self.w.parent_u, users)   # parent of Ayaan
        self.assertIn(self.w.student_u, users)   # Ayaan's own login

    def test_send_web_push_no_users_is_zero(self):
        self.assertEqual(push.send_web_push([], 'x', 'y'), 0)
