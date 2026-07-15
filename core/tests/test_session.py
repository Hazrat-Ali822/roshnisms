"""Academic-session tagging: exams/marks from different years must not blend."""
from django.test import Client, TestCase

from core.models import Exam, Mark, Subject
from core.tests.factory import build_world


class SessionTests(TestCase):
    def setUp(self):
        self.w = build_world()
        # A prior-year exam with a result for Ayaan, tagged 2024-25.
        self.old_exam = Exam.objects.create(name='Mid-Term', session='2024-25')
        Mark.objects.create(student=self.w.ayaan, subject=self.w.math9,
                            exam=self.old_exam, marks_obtained=30, total_marks=100)
        # A current-session result (school session = 2025-26).
        Mark.objects.create(student=self.w.ayaan, subject=self.w.math9,
                            exam=self.w.exam, marks_obtained=90, total_marks=100)

    def test_new_exam_stamped_with_current_session(self):
        c = Client(); c.force_login(self.w.admin_u)
        c.post('/exams/datesheet/', {'action': 'add_exam',
                                     'name': 'Final Term 2026'})
        e = Exam.objects.get(name='Final Term 2026')
        self.assertEqual(e.session, '2025-26')

    def test_results_default_to_current_session_only(self):
        c = Client(); c.force_login(self.w.student_u)
        html = c.get('/my-results/').content.decode()
        # current session result (90%) shown, not the prior-year one (30%)
        self.assertIn('90%', html)
        self.assertNotIn('30%', html)

    def test_switch_to_past_session(self):
        c = Client(); c.force_login(self.w.student_u)
        html = c.get('/my-results/?session=2024-25').content.decode()
        self.assertIn('30%', html)  # old result becomes visible
        self.assertNotIn('90%', html)

    def test_attendance_marked_with_session(self):
        c = Client(); c.force_login(self.w.teacher_u)
        c.post('/attendance/', {'class': self.w.c9.id, 'date': '2026-06-10',
                                'status_%d' % self.w.ayaan.id: 'A'})
        from core.models import AttendanceRecord
        rec = AttendanceRecord.objects.get(student=self.w.ayaan, date='2026-06-10')
        self.assertEqual(rec.session, '2025-26')

    def test_topbar_shows_current_session(self):
        c = Client(); c.force_login(self.w.admin_u)
        self.assertIn('2025-26', c.get('/').content.decode())
