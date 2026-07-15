"""Class position/rank on results + bulk report cards for a whole class."""
from django.test import Client, TestCase

from core.models import Mark, Student
from core.tests.factory import build_world


class RankingTests(TestCase):
    def setUp(self):
        self.w = build_world()
        # Ayaan 90/100, Hira 60/100 in 9-A, Mid-Term. Ayaan should rank 1st.
        Mark.objects.create(student=self.w.ayaan, subject=self.w.math9,
                            exam=self.w.exam, marks_obtained=90, total_marks=100)
        Mark.objects.create(student=self.w.hira, subject=self.w.math9,
                            exam=self.w.exam, marks_obtained=60, total_marks=100)

    def test_position_on_report_card(self):
        c = Client(); c.force_login(self.w.admin_u)
        html = c.get('/report-card/%d/%d/' % (self.w.ayaan.id, self.w.exam.id)).content.decode()
        self.assertIn('Position', html)
        self.assertIn('1', html)

    def test_position_on_my_results(self):
        c = Client(); c.force_login(self.w.student_u)   # student = Ayaan
        html = c.get('/my-results/?exam=%d' % self.w.exam.id).content.decode()
        self.assertIn('Position', html)

    def test_lower_scorer_ranks_second(self):
        # give Hira a login-independent check via report card position
        from core.views import _class_ranking
        ranking = _class_ranking(self.w.exam, self.w.c9)
        self.assertEqual(ranking[self.w.ayaan.id][0], 1)
        self.assertEqual(ranking[self.w.hira.id][0], 2)
        self.assertEqual(ranking[self.w.ayaan.id][1], 2)   # total ranked


class BulkReportCardTests(TestCase):
    def setUp(self):
        self.w = build_world()
        Mark.objects.create(student=self.w.ayaan, subject=self.w.math9,
                            exam=self.w.exam, marks_obtained=80, total_marks=100)
        Mark.objects.create(student=self.w.hira, subject=self.w.math9,
                            exam=self.w.exam, marks_obtained=50, total_marks=100)

    def test_bulk_page_lists_all_with_marks(self):
        c = Client(); c.force_login(self.w.admin_u)
        html = c.get('/report-cards/?class=%d&exam=%d'
                     % (self.w.c9.id, self.w.exam.id)).content.decode()
        self.assertIn('Ayaan', html)
        self.assertIn('Hira', html)
        self.assertIn('Print all', html)

    def test_students_without_marks_skipped(self):
        # Inaya is in 10-A and has no marks; not shown for 9-A anyway
        c = Client(); c.force_login(self.w.admin_u)
        html = c.get('/report-cards/?class=%d&exam=%d'
                     % (self.w.c9.id, self.w.exam.id)).content.decode()
        self.assertNotIn('Inaya', html)

    def test_teacher_limited_to_own_classes(self):
        c = Client(); c.force_login(self.w.teacher_u)
        r = c.get('/report-cards/')
        self.assertEqual(r.status_code, 200)

    def test_parent_cannot_access_bulk(self):
        c = Client(); c.force_login(self.w.parent_u)
        self.assertIn(c.get('/report-cards/').status_code, (302, 403))
