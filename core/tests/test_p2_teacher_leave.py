"""P2 — teacher self-service leave (files own LeaveRequest → principal approves)."""
import datetime

from django.test import Client, TestCase

from core.models import LeaveRequest, Staff, StaffAttendance
from core.tests.factory import build_world, PASSWORD


class TeacherSelfLeaveTests(TestCase):
    def setUp(self):
        self.w = build_world()
        # Link teacher1's login to a Staff record so HR self-service works.
        self.staff = Staff.objects.create(
            user=self.w.teacher_u, name='Teacher1', designation='Teacher',
            basic_salary=40000)

    def _teacher(self):
        c = Client(); c.login(username='teacher1', password=PASSWORD)
        return c

    def test_teacher_can_file_own_leave(self):
        self._teacher().post('/teacher/my-hr/', {
            'from_date': '2026-06-10', 'to_date': '2026-06-12', 'reason': 'Medical'})
        lv = LeaveRequest.objects.filter(staff=self.staff).first()
        self.assertIsNotNone(lv)
        self.assertEqual(lv.status, 'Pending')
        self.assertEqual(lv.days, 3)

    def test_bad_range_rejected(self):
        self._teacher().post('/teacher/my-hr/', {
            'from_date': '2026-06-12', 'to_date': '2026-06-10', 'reason': 'x'})
        self.assertFalse(LeaveRequest.objects.exists())

    def test_no_reason_rejected(self):
        self._teacher().post('/teacher/my-hr/', {
            'from_date': '2026-06-10', 'to_date': '2026-06-10', 'reason': '  '})
        self.assertFalse(LeaveRequest.objects.exists())

    def test_principal_approval_marks_staff_leave(self):
        lv = LeaveRequest.objects.create(
            staff=self.staff, from_date=datetime.date(2026, 6, 10),
            to_date=datetime.date(2026, 6, 11), reason='Trip', status='Pending')
        c = Client(); c.login(username='principal1', password=PASSWORD)
        c.post('/principal/approvals/', {'action': 'approve_leave', 'leave_id': lv.id})
        lv.refresh_from_db()
        self.assertEqual(lv.status, 'Approved')
        self.assertEqual(
            StaffAttendance.objects.filter(
                staff=self.staff, status='L',
                date__range=('2026-06-10', '2026-06-11')).count(), 2)
