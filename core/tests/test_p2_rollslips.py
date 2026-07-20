"""P2 — printable roll-number slips for an exam."""
import datetime

from django.test import Client, TestCase
from django.urls import reverse

from core.models import ExamSchedule
from core.tests.factory import build_world, PASSWORD


class RollSlipTests(TestCase):
    def setUp(self):
        self.w = build_world()
        ExamSchedule.objects.create(
            exam=self.w.exam, classroom=self.w.c9, subject='Mathematics',
            date=datetime.date(2026, 6, 10), time='09:00 AM')
        self.c = Client()
        self.c.login(username='admin1', password=PASSWORD)

    def test_slip_lists_class_students_and_papers(self):
        r = self.c.get(reverse('roll_slips'), {'exam': self.w.exam.id})
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn('Ayaan', body)          # student in 9-A (has a datesheet)
        self.assertIn('Mathematics', body)    # the scheduled paper
        self.assertNotIn('Inaya', body)       # 10-A has no datesheet for this exam

    def test_no_datesheet_shows_hint(self):
        ExamSchedule.objects.all().delete()
        r = self.c.get(reverse('roll_slips'), {'exam': self.w.exam.id})
        self.assertEqual(r.status_code, 200)
        self.assertIn('No datesheet', r.content.decode())
