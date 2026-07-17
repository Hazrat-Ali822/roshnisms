"""P2 — email alerts (parallel channel to SMS)."""
from django.core import mail
from django.test import Client, TestCase, override_settings

from core.emailer import send_email_alert
from core.models import FeePayment, SmsMessage
from core.tests.factory import build_world
from core.views import _make_challan


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class EmailAlertTests(TestCase):
    def setUp(self):
        self.w = build_world()
        self.w.school.email_alerts_enabled = True
        self.w.school.save()

    def test_send_email_alert_logs_and_sends(self):
        status = send_email_alert('Hi', 'Body text', 'p@example.com')
        self.assertEqual(status, 'Sent')
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['p@example.com'])
        # Logged in the unified communication history.
        self.assertTrue(SmsMessage.objects.filter(provider='email').exists())

    def test_no_address_skips(self):
        status = send_email_alert('Hi', 'Body', '')
        self.assertEqual(status, 'Skipped')
        self.assertEqual(len(mail.outbox), 0)

    def test_payment_emails_guardian_when_enabled(self):
        self.w.ayaan.guardian_email = 'guardian@example.com'
        self.w.ayaan.save()
        ch, _ = _make_challan(self.w.ayaan, 2026, 6)
        c = Client(); c.force_login(self.w.finance_u)
        c.post('/fees/student/%d/' % self.w.ayaan.id, {
            'action': 'collect', 'challan_id': ch.id, 'amount': '5000', 'mode': 'Cash'})
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('guardian@example.com', mail.outbox[0].to)
        self.assertIn('Receipt', mail.outbox[0].body)

    def test_no_email_sent_when_disabled(self):
        self.w.school.email_alerts_enabled = False
        self.w.school.save()
        self.w.ayaan.guardian_email = 'guardian@example.com'
        self.w.ayaan.save()
        ch, _ = _make_challan(self.w.ayaan, 2026, 6)
        c = Client(); c.force_login(self.w.finance_u)
        c.post('/fees/student/%d/' % self.w.ayaan.id, {
            'action': 'collect', 'challan_id': ch.id, 'amount': '5000', 'mode': 'Cash'})
        self.assertEqual(len(mail.outbox), 0)

    def test_parent_can_set_guardian_email(self):
        from core.tests.factory import PASSWORD
        from core.models import Student
        c = Client(); c.login(username='parent1', password=PASSWORD)
        c.post('/my-profile/', {
            'action': 'update_contact', 'guardian_email': 'new@example.com'})
        self.assertEqual(Student.objects.get(pk=self.w.ayaan.pk).guardian_email,
                         'new@example.com')
