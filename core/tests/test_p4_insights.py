"""Insights — rule-based early-warning signals (offline, no external AI)."""
import datetime

from django.test import Client, TestCase
from django.urls import reverse

from core.models import AttendanceRecord, Mark
from core.tests.factory import build_world, PASSWORD


class InsightsTests(TestCase):
    def setUp(self):
        self.w = build_world()
        self.c = Client()
        self.c.login(username='admin1', password=PASSWORD)

    def _url(self):
        return reverse('insights')

    def test_result_drop_flags_student(self):
        # Ayaan: Mid-Term 80% (prev), Final 50% (latest) -> 30-pt drop flagged.
        Mark.objects.create(student=self.w.ayaan, subject=self.w.math9,
                            exam=self.w.exam, marks_obtained=80, total_marks=100)
        Mark.objects.create(student=self.w.ayaan, subject=self.w.math9,
                            exam=self.w.exam2, marks_obtained=50, total_marks=100)
        r = self.c.get(self._url())
        self.assertEqual(r.status_code, 200)
        names = [row['student'].name for row in r.context['at_risk']]
        self.assertIn('Ayaan', names)

    def test_low_attendance_flags_student(self):
        base = datetime.date(2025, 9, 1)
        AttendanceRecord.objects.create(student=self.w.hira, date=base,
                                        status='P', session='2025-26')
        for i in range(1, 4):
            AttendanceRecord.objects.create(
                student=self.w.hira, date=base + datetime.timedelta(days=i),
                status='A', session='2025-26')
        r = self.c.get(self._url())
        names = [row['student'].name for row in r.context['at_risk']]
        self.assertIn('Hira', names)   # 25% attendance < 75%

    def test_weak_subject_detected(self):
        # English class average 20% in the latest exam -> weak.
        Mark.objects.create(student=self.w.ayaan, subject=self.w.eng9,
                            exam=self.w.exam2, marks_obtained=20, total_marks=100)
        r = self.c.get(self._url())
        subjects = [w['subject'] for w in r.context['weak']]
        self.assertIn('English', subjects)

    def test_csv_export(self):
        Mark.objects.create(student=self.w.ayaan, subject=self.w.math9,
                            exam=self.w.exam, marks_obtained=90, total_marks=100)
        Mark.objects.create(student=self.w.ayaan, subject=self.w.math9,
                            exam=self.w.exam2, marks_obtained=40, total_marks=100)
        r = self.c.get(self._url() + '?export=csv')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'text/csv; charset=utf-8')
        self.assertIn('Ayaan', r.content.decode())

    def test_parent_cannot_access(self):
        self.c.logout()
        self.c.login(username='parent1', password=PASSWORD)
        r = self.c.get(self._url())
        self.assertNotEqual(r.status_code, 200)

    def test_principal_can_access(self):
        self.c.logout()
        self.c.login(username='principal1', password=PASSWORD)
        r = self.c.get(self._url())
        self.assertEqual(r.status_code, 200)
