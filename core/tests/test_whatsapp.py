"""Section 4 — WhatsApp notifications: the channel dispatcher, WhatsApp logging,
and the Settings screen. Backward compatibility: default channel 'sms' behaves
exactly like before."""
from django.test import Client, TestCase

from core.models import SmsMessage
from core import sms
from core.tests.factory import build_world


class ChannelDispatchTests(TestCase):
    def setUp(self):
        self.w = build_world()
        self.s = self.w.school

    def test_default_channel_is_sms_only(self):
        before = SmsMessage.objects.count()
        results = sms.notify('hi', to_phone='0300-1234567', recipients='X',
                             msg_type='Test')
        self.assertEqual(len(results), 1)              # only SMS
        rows = SmsMessage.objects.all()[:1]
        self.assertEqual(rows[0].provider, 'console')  # SMS console backend
        self.assertEqual(SmsMessage.objects.count(), before + 1)

    def test_both_channel_logs_two_messages(self):
        self.s.notify_channel = 'both'
        self.s.whatsapp_enabled = True
        self.s.save()
        results = sms.notify('hi', to_phone='0300-1234567', recipients='X')
        self.assertEqual(len(results), 2)              # SMS + WhatsApp
        providers = set(SmsMessage.objects.values_list('provider', flat=True))
        self.assertIn('console', providers)
        self.assertTrue(any(p.startswith('whatsapp:') for p in providers))

    def test_whatsapp_only_channel(self):
        self.s.notify_channel = 'whatsapp'
        self.s.whatsapp_enabled = True
        self.s.save()
        results = sms.notify('hi', to_phone='0300-1234567')
        self.assertEqual(len(results), 1)
        last = SmsMessage.objects.order_by('-id').first()
        self.assertTrue(last.provider.startswith('whatsapp:'))

    def test_whatsapp_channel_falls_back_to_sms_when_not_ready(self):
        # Channel says WhatsApp, but it's not enabled -> alert must still go out.
        self.s.notify_channel = 'whatsapp'
        self.s.whatsapp_enabled = False
        self.s.save()
        results = sms.notify('hi', to_phone='0300-1234567')
        self.assertEqual(len(results), 1)
        last = SmsMessage.objects.order_by('-id').first()
        self.assertEqual(last.provider, 'console')     # fell back to SMS

    def test_whatsapp_test_mode_logs_console(self):
        self.s.whatsapp_enabled = False
        self.s.save()
        status = sms.send_whatsapp('hi', to_phone='0300-1234567', msg_type='Test')
        self.assertEqual(status, 'Console')
        last = SmsMessage.objects.order_by('-id').first()
        self.assertEqual(last.to_phone, '+923001234567')
        self.assertTrue(last.provider.startswith('whatsapp:'))


class WhatsAppSettingsTests(TestCase):
    def setUp(self):
        self.w = build_world()
        self.c = Client(); self.c.force_login(self.w.admin_u)

    def test_save_whatsapp_settings(self):
        self.c.post('/settings/', {
            'wa_action': 'save_whatsapp', 'notify_channel': 'both',
            'whatsapp_provider': 'meta', 'whatsapp_enabled': 'on',
            'whatsapp_token': 'TOK', 'whatsapp_phone_id': '12345'})
        self.w.school.refresh_from_db()
        self.assertEqual(self.w.school.notify_channel, 'both')
        self.assertEqual(self.w.school.whatsapp_provider, 'meta')
        self.assertTrue(self.w.school.whatsapp_enabled)
        self.assertEqual(self.w.school.whatsapp_phone_id, '12345')

    def test_invalid_channel_falls_back(self):
        self.c.post('/settings/', {'wa_action': 'save_whatsapp',
                                   'notify_channel': 'telepathy'})
        self.w.school.refresh_from_db()
        self.assertEqual(self.w.school.notify_channel, 'sms')

    def test_whatsapp_test_message_logged(self):
        before = SmsMessage.objects.count()
        self.c.post('/settings/', {'wa_action': 'test_whatsapp',
                                   'test_phone': '0300-1234567'})
        self.assertEqual(SmsMessage.objects.count(), before + 1)
        last = SmsMessage.objects.order_by('-id').first()
        self.assertEqual(last.msg_type, 'Test')
        self.assertTrue(last.provider.startswith('whatsapp:'))
