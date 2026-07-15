"""SMS configurable from Settings: backend, credentials, alert toggles, test."""
from django.test import Client, TestCase

from core.models import SmsMessage
from core.sms import sms_enabled
from core.tests.factory import build_world


class SmsSettingsTests(TestCase):
    def setUp(self):
        self.w = build_world()
        self.c = Client(); self.c.force_login(self.w.admin_u)

    def test_save_sms_settings(self):
        self.c.post('/settings/', {
            'sms_action': 'save_sms', 'sms_backend': 'http',
            'sms_country_code': '+92',
            'sms_http_url': 'https://gw.example/send?to={to}&msg={text}',
            'sms_http_method': 'POST', 'notify_absent': 'on'})
        self.w.school.refresh_from_db()
        self.assertEqual(self.w.school.sms_backend, 'http')
        self.assertEqual(self.w.school.sms_http_method, 'POST')
        self.assertTrue(self.w.school.notify_absent)
        # unchecked boxes turn the alert off
        self.assertFalse(self.w.school.notify_payment)

    def test_invalid_backend_falls_back_to_console(self):
        self.c.post('/settings/', {'sms_action': 'save_sms',
                                   'sms_backend': 'hacker'})
        self.w.school.refresh_from_db()
        self.assertEqual(self.w.school.sms_backend, 'console')

    def test_notify_toggle_read_from_school(self):
        self.w.school.notify_payment = False
        self.w.school.save()
        self.assertFalse(sms_enabled('SMS_NOTIFY_ON_PAYMENT'))
        self.w.school.notify_payment = True
        self.w.school.save()
        self.assertTrue(sms_enabled('SMS_NOTIFY_ON_PAYMENT'))

    def test_test_message_logged_in_console_mode(self):
        before = SmsMessage.objects.count()
        self.c.post('/settings/', {'sms_action': 'test_sms',
                                   'test_phone': '0300-1234567'})
        self.assertEqual(SmsMessage.objects.count(), before + 1)
        last = SmsMessage.objects.order_by('-id').first()
        self.assertEqual(last.msg_type, 'Test')
        self.assertEqual(last.to_phone, '+923001234567')   # normalized

    def test_backend_from_school_overrides(self):
        # switch to http without a URL -> send fails and is logged as Failed
        self.w.school.sms_backend = 'http'
        self.w.school.sms_http_url = ''
        self.w.school.save()
        self.c.post('/settings/', {'sms_action': 'test_sms',
                                   'test_phone': '0300-1234567'})
        last = SmsMessage.objects.order_by('-id').first()
        self.assertEqual(last.status, 'Failed')
        self.assertEqual(last.provider, 'http')
