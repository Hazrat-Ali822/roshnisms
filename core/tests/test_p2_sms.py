"""P2 — one-click Result via SMS, and Parent password via SMS."""
from django.test import Client, TestCase
from django.urls import reverse

from core.models import Mark, SmsMessage
from core.tests.factory import build_world, PASSWORD


class ResultSmsTests(TestCase):
    def setUp(self):
        self.w = build_world()
        # Ayaan: 80/100 Maths + 50/100 English -> 130/200 = 65% (Grade C).
        Mark.objects.create(student=self.w.ayaan, subject=self.w.math9,
                            exam=self.w.exam, marks_obtained=80, total_marks=100)
        Mark.objects.create(student=self.w.ayaan, subject=self.w.eng9,
                            exam=self.w.exam, marks_obtained=50, total_marks=100)
        self.c = Client()
        self.c.login(username='admin1', password=PASSWORD)

    def test_result_blast_messages_guardian(self):
        r = self.c.post(reverse('communication'),
                        {'action': 'result_sms', 'exam': self.w.exam.id})
        self.assertEqual(r.status_code, 302)
        msg = SmsMessage.objects.filter(msg_type='Result').first()
        self.assertIsNotNone(msg)
        self.assertIn('65', msg.body)          # 130/200 = 65%
        self.assertIn('Ayaan', msg.body)

    def test_result_blast_needs_exam(self):
        r = self.c.post(reverse('communication'), {'action': 'result_sms'})
        self.assertEqual(r.status_code, 302)
        self.assertFalse(SmsMessage.objects.filter(msg_type='Result').exists())


class ParentPasswordSmsTests(TestCase):
    def setUp(self):
        self.w = build_world()
        self.c = Client()
        self.c.login(username='admin1', password=PASSWORD)

    def test_reset_and_sms_sends_login(self):
        old = self.w.student_u.password
        r = self.c.post(reverse('users_list'),
                        {'action': 'reset_password_sms',
                         'user_id': self.w.student_u.id})
        self.assertEqual(r.status_code, 302)
        self.w.student_u.refresh_from_db()
        self.assertNotEqual(self.w.student_u.password, old)   # password changed
        msg = SmsMessage.objects.filter(msg_type='Login').first()
        self.assertIsNotNone(msg)
        self.assertIn('student1', msg.body)                   # username in the SMS

    def test_no_phone_no_sms(self):
        # Strip Ayaan's guardian phone → the login cannot be texted.
        self.w.ayaan.guardian_phone = ''
        self.w.ayaan.save()
        self.c.post(reverse('users_list'),
                    {'action': 'reset_password_sms',
                     'user_id': self.w.student_u.id})
        self.assertFalse(SmsMessage.objects.filter(msg_type='Login').exists())
