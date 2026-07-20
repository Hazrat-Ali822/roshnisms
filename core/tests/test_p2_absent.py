"""P2 — Daily Absent Student List report page."""
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import AttendanceRecord
from core.tests.factory import build_world, PASSWORD


class AbsentListTests(TestCase):
    def setUp(self):
        self.w = build_world()
        self.today = timezone.localdate()
        AttendanceRecord.objects.create(student=self.w.ayaan, date=self.today,
                                        status='A')
        AttendanceRecord.objects.create(student=self.w.hira, date=self.today,
                                        status='P')   # present, must NOT appear
        self.c = Client()
        self.c.login(username='admin1', password=PASSWORD)

    def test_lists_only_absentees(self):
        r = self.c.get(reverse('absent_list'), {'date': self.today.isoformat()})
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn('Ayaan', body)
        self.assertNotIn('>Hira<', body)

    def test_csv_export(self):
        r = self.c.get(reverse('absent_list'),
                       {'date': self.today.isoformat(), 'export': 'csv'})
        self.assertEqual(r.status_code, 200)
        self.assertIn('text/csv', r['Content-Type'])
        self.assertIn('Ayaan', r.content.decode())

    def test_teacher_denied(self):
        c = Client(); c.login(username='teacher1', password=PASSWORD)
        r = c.get(reverse('absent_list'))
        self.assertIn(r.status_code, (302, 403))
