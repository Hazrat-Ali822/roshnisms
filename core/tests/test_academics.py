from django.test import Client, TestCase

from core.models import AttendanceRecord, Mark
from core.tests.factory import build_world


class MarksAndResultsTests(TestCase):
    def setUp(self):
        self.w = build_world()
        self.c = Client()

    def test_marks_entry_saves_to_selected_exam(self):
        """A3: teacher enters marks for the chosen exam, not always the first."""
        self.c.force_login(self.w.teacher_u)
        r = self.c.post('/marks/', {
            'class': self.w.c9.id, 'subject': self.w.math9.id,
            'exam': self.w.exam2.id, 'marks_%d' % self.w.ayaan.id: '55'})
        self.assertEqual(r.status_code, 302)
        saved = Mark.objects.get(student=self.w.ayaan, subject=self.w.math9,
                                 exam=self.w.exam2)
        self.assertEqual(saved.marks_obtained, 55)
        # The other exam must be untouched.
        self.assertFalse(Mark.objects.filter(
            student=self.w.ayaan, exam=self.w.exam).exists())

    def test_results_do_not_mix_exams(self):
        """A2: results page shows one exam's total, not all exams summed."""
        Mark.objects.create(student=self.w.ayaan, subject=self.w.math9,
                            exam=self.w.exam, marks_obtained=80, total_marks=100)
        Mark.objects.create(student=self.w.ayaan, subject=self.w.math9,
                            exam=self.w.exam2, marks_obtained=40, total_marks=100)
        self.c.force_login(self.w.student_u)
        html = self.c.get('/my-results/?exam=%d' % self.w.exam2.id).content.decode()
        self.assertIn('40%', html)          # Final exam percentage
        self.assertNotIn('/200', html)      # max stays 100 (one exam), not summed
        self.assertNotIn('120', html)       # obtained not summed (80 + 40)

    def test_report_card_ownership(self):
        """A parent cannot open another student's report card."""
        Mark.objects.create(student=self.w.hira, subject=self.w.math9,
                            exam=self.w.exam, marks_obtained=70, total_marks=100)
        self.c.force_login(self.w.parent_u)
        # Hira is NOT this parent's child -> forbidden
        r = self.c.get('/report-card/%d/%d/' % (self.w.hira.id, self.w.exam.id))
        self.assertEqual(r.status_code, 403)
        # Ayaan IS their child -> allowed
        r2 = self.c.get('/report-card/%d/%d/' % (self.w.ayaan.id, self.w.exam.id))
        self.assertEqual(r2.status_code, 200)


class AttendanceTests(TestCase):
    def setUp(self):
        self.w = build_world()
        self.c = Client()

    def test_teacher_marks_attendance(self):
        self.c.force_login(self.w.teacher_u)
        r = self.c.post('/attendance/', {
            'class': self.w.c9.id,
            'status_%d' % self.w.ayaan.id: 'A',
            'status_%d' % self.w.hira.id: 'P'})
        self.assertEqual(r.status_code, 302)
        rec = AttendanceRecord.objects.get(student=self.w.ayaan)
        self.assertEqual(rec.status, 'A')

    def test_teacher_cannot_mark_other_class(self):
        """Posting a student id outside the teacher's class must not create a record."""
        self.c.force_login(self.w.teacher_u)
        self.c.post('/attendance/', {
            'class': self.w.c9.id,
            'status_%d' % self.w.inaya.id: 'A'})  # Inaya is in 10-A
        self.assertFalse(AttendanceRecord.objects.filter(
            student=self.w.inaya).exists())
