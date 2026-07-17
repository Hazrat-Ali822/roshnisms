"""P2 — teacher class analytics (read-only subject/student performance)."""
from django.test import Client, TestCase

from core.models import Mark
from core.tests.factory import build_world, PASSWORD


class TeacherAnalyticsTests(TestCase):
    def setUp(self):
        self.w = build_world()
        # Ayaan: Maths 80, English 40. Hira: Maths 60, English 20.
        Mark.objects.create(student=self.w.ayaan, subject=self.w.math9,
                            exam=self.w.exam, marks_obtained=80, total_marks=100)
        Mark.objects.create(student=self.w.ayaan, subject=self.w.eng9,
                            exam=self.w.exam, marks_obtained=40, total_marks=100)
        Mark.objects.create(student=self.w.hira, subject=self.w.math9,
                            exam=self.w.exam, marks_obtained=60, total_marks=100)
        Mark.objects.create(student=self.w.hira, subject=self.w.eng9,
                            exam=self.w.exam, marks_obtained=20, total_marks=100)

    def _teacher(self):
        c = Client(); c.login(username='teacher1', password=PASSWORD)
        return c

    def test_analytics_page_renders_with_stats(self):
        r = self._teacher().get('/teacher/analytics/?class=%s&exam=%s'
                                % (self.w.c9.id, self.w.exam.id))
        self.assertEqual(r.status_code, 200)
        ctx = r.context
        # Ayaan overall = (80+40)/200 = 60%, Hira = (60+20)/200 = 40%.
        # Class average = 50%.
        self.assertEqual(ctx['class_avg'], 50)
        self.assertEqual(ctx['graded'], 2)
        # Ranking: Ayaan (60%) above Hira (40%).
        rows = ctx['student_rows']
        self.assertEqual(rows[0]['student'], self.w.ayaan)
        self.assertEqual(rows[0]['rank'], 1)
        self.assertEqual(rows[1]['student'], self.w.hira)

    def test_subject_rows_flag_taught_subject(self):
        r = self._teacher().get('/teacher/analytics/?class=%s&exam=%s'
                                % (self.w.c9.id, self.w.exam.id))
        subj = {row['subject'].name: row for row in r.context['subj_rows']}
        # Maths average = (80+60)/2 = 70, taught by teacher1 -> mine True.
        self.assertEqual(subj['Mathematics']['avg'], 70)
        self.assertTrue(subj['Mathematics']['mine'])
        # English average = (40+20)/2 = 30, not taught by teacher1.
        self.assertEqual(subj['English']['avg'], 30)
        self.assertFalse(subj['English']['mine'])

    def test_parent_cannot_access(self):
        c = Client(); c.login(username='parent1', password=PASSWORD)
        r = c.get('/teacher/analytics/')
        self.assertNotEqual(r.status_code, 200)
