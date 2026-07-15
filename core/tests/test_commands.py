from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from core.models import Profile, SmsMessage
from core.tests.factory import build_world
from core.views import _make_challan


class CommandTests(TestCase):
    def setUp(self):
        self.w = build_world()

    def test_seed_refuses_without_demo_flag(self):
        with self.assertRaises(CommandError):
            call_command('seed')

    def test_setup_school_creates_admin(self):
        call_command('setup_school', school='New School', username='newadmin',
                     password='StrongPass1', name='Head Office')
        u = User.objects.get(username='newadmin')
        self.assertEqual(u.profile.role, 'admin')
        self.assertFalse(u.is_superuser)

    def test_setup_school_rejects_duplicate_username(self):
        with self.assertRaises(CommandError):
            call_command('setup_school', school='X', username='admin1',
                         password='StrongPass1', name='Y')

    @override_settings(SMS_BACKEND='console')
    def test_fee_reminders_sms_defaulters(self):
        _make_challan(self.w.ayaan, 2020, 1)     # overdue, has phone
        before = SmsMessage.objects.count()
        call_command('fees_remind')
        # At least one reminder logged for the defaulter guardian
        self.assertGreater(SmsMessage.objects.count(), before)
        self.assertTrue(SmsMessage.objects.filter(msg_type='Fee Reminder').exists())
