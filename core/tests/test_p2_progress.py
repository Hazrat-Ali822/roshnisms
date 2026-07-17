"""P2 — family progress trends across exams."""
from django.test import Client, TestCase

from core.models import Mark
from core.tests.factory import build_world, PASSWORD


class ProgressTests(TestCase):
    def setUp(self):
        self.w = build_world()
        # Two exams same session. Ayaan Maths: 50 in Mid-Term, 80 in Final.
        Mark.objects.create(student=self.w.ayaan, subject=self.w.math9,
                            exam=self.w.exam, marks_obtained=50, total_marks=100)
        Mark.objects.create(student=self.w.ayaan, subject=self.w.math9,
                            exam=self.w.exam2, marks_obtained=80, total_marks=100)

    def _parent(self):
        c = Client(); c.login(username='parent1', password=PASSWORD)
        return c

    def test_progress_page_trend(self):
        r = self._parent().get('/my-progress/')
        self.assertEqual(r.status_code, 200)
        ctx = r.context
        # exam (Mid-Term, id lower) first, exam2 (Final) second -> chronological.
        overall = ctx['overall']
        self.assertEqual(overall[0]['pct'], 50)
        self.assertEqual(overall[1]['pct'], 80)
        self.assertEqual(ctx['latest'], 80)
        self.assertEqual(ctx['best'], 80)
        self.assertEqual(ctx['delta'], 30)          # 80 - 50

    def test_subject_trend_row(self):
        r = self._parent().get('/my-progress/')
        rows = {row['subject']: row for row in r.context['subject_rows']}
        maths = rows['Mathematics']
        self.assertEqual(maths['cells'], [50, 80])
        self.assertEqual(maths['trend'], 30)        # last - first
        self.assertEqual(maths['avg'], 65)

    def test_no_marks_is_graceful(self):
        c = Client(); c.login(username='parent1', password=PASSWORD)
        # Switch active child to Inaya (no marks) via query.
        r = c.get('/my-progress/?child=%d' % self.w.inaya.id)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['overall'], [])

    def test_student_cannot_be_denied(self):
        c = Client(); c.login(username='student1', password=PASSWORD)
        r = c.get('/my-progress/')
        self.assertEqual(r.status_code, 200)
