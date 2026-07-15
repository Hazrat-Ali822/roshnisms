"""Monthly attendance register + low-attendance flag."""
import datetime

from django.test import Client, TestCase

from core.models import AttendanceRecord
from core.tests.factory import build_world


class RegisterTests(TestCase):
    def setUp(self):
        self.w = build_world()
        # Ayaan: 1 present, 3 absent in June 2026 -> 25% (below 75, flagged)
        AttendanceRecord.objects.create(student=self.w.ayaan,
                                        date=datetime.date(2026, 6, 1), status='P')
        for day in (2, 3, 4):
            AttendanceRecord.objects.create(student=self.w.ayaan,
                                            date=datetime.date(2026, 6, day), status='A')
        # Hira: all present
        for day in (1, 2, 3, 4):
            AttendanceRecord.objects.create(student=self.w.hira,
                                            date=datetime.date(2026, 6, day), status='P')

    def test_register_renders_grid(self):
        c = Client(); c.force_login(self.w.admin_u)
        html = c.get('/attendance/register/?class=%d&month=6&year=2026'
                     % self.w.c9.id).content.decode()
        self.assertIn('Ayaan', html)
        self.assertIn('Hira', html)
        self.assertIn('Print register', html)

    def test_low_attendance_flagged(self):
        c = Client(); c.force_login(self.w.admin_u)
        html = c.get('/attendance/register/?class=%d&month=6&year=2026'
                     % self.w.c9.id).content.decode()
        self.assertIn('below 75%', html)     # summary pill
        self.assertIn('25%', html)           # Ayaan's rate

    def test_high_attendance_not_flagged_alone(self):
        # Only Ayaan is low; low_count should be 1
        c = Client(); c.force_login(self.w.admin_u)
        html = c.get('/attendance/register/?class=%d&month=6&year=2026'
                     % self.w.c9.id).content.decode()
        self.assertIn('1 below 75%', html)

    def test_teacher_access_own_class(self):
        c = Client(); c.force_login(self.w.teacher_u)
        self.assertEqual(c.get('/attendance/register/').status_code, 200)

    def test_parent_blocked(self):
        c = Client(); c.force_login(self.w.parent_u)
        self.assertIn(c.get('/attendance/register/').status_code, (302, 403))
