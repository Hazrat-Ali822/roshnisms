"""P2 — student/parent leave application + principal approval (new feature)."""
import datetime

from django.test import Client, TestCase

from core.models import AttendanceRecord, StudentLeave
from core.tests.factory import build_world, PASSWORD


class StudentLeaveTests(TestCase):
    def setUp(self):
        self.w = build_world()

    def _parent(self):
        c = Client(); c.login(username='parent1', password=PASSWORD)
        return c

    def test_parent_can_apply(self):
        self._parent().post('/my-leave/', {
            'from_date': '2026-06-10', 'to_date': '2026-06-12',
            'reason': 'Fever'})
        lv = StudentLeave.objects.filter(student=self.w.ayaan).first()
        self.assertIsNotNone(lv)
        self.assertEqual(lv.status, 'Pending')
        self.assertEqual(lv.days, 3)

    def test_bad_date_range_rejected(self):
        self._parent().post('/my-leave/', {
            'from_date': '2026-06-12', 'to_date': '2026-06-10', 'reason': 'x'})
        self.assertFalse(StudentLeave.objects.exists())

    def test_principal_approval_marks_attendance_leave(self):
        lv = StudentLeave.objects.create(
            student=self.w.ayaan, from_date=datetime.date(2026, 6, 10),
            to_date=datetime.date(2026, 6, 11), reason='Trip', status='Pending')
        c = Client(); c.login(username='principal1', password=PASSWORD)
        c.post('/principal/approvals/', {
            'action': 'approve_student_leave', 'leave_id': lv.id})
        lv.refresh_from_db()
        self.assertEqual(lv.status, 'Approved')
        # Both days should now be marked 'L' on the register.
        self.assertEqual(
            AttendanceRecord.objects.filter(
                student=self.w.ayaan, status='L',
                date__range=('2026-06-10', '2026-06-11')).count(), 2)

    def test_reject_leaves_attendance_untouched(self):
        lv = StudentLeave.objects.create(
            student=self.w.ayaan, from_date=datetime.date(2026, 6, 10),
            to_date=datetime.date(2026, 6, 10), reason='x', status='Pending')
        c = Client(); c.login(username='principal1', password=PASSWORD)
        c.post('/principal/approvals/', {
            'action': 'reject_student_leave', 'leave_id': lv.id})
        lv.refresh_from_db()
        self.assertEqual(lv.status, 'Rejected')
        self.assertFalse(AttendanceRecord.objects.filter(student=self.w.ayaan).exists())
