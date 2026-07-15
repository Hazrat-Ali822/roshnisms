"""Reports: CSV exports + printable HTML summaries (browser Print -> PDF)."""
from django.test import Client, TestCase

from core.models import Mark
from core.tests.factory import build_world


class ReportTests(TestCase):
    def setUp(self):
        self.w = build_world()
        Mark.objects.create(student=self.w.ayaan, subject=self.w.math9,
                            exam=self.w.exam, marks_obtained=80, total_marks=100)
        self.c = Client(); self.c.force_login(self.w.admin_u)

    def test_students_csv(self):
        r = self.c.get('/reports/?report=students&format=csv')
        self.assertEqual(r.status_code, 200)
        self.assertIn('text/csv', r['Content-Type'])
        self.assertIn('Ayaan', r.content.decode())

    def test_school_summary_is_printable_html(self):
        r = self.c.get('/reports/?report=summary&format=print')
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn('School Summary Report', html)
        self.assertIn('window.print()', html)     # print button present
        self.assertIn('Enrolment', html)

    def test_fees_summary_is_printable_html(self):
        r = self.c.get('/reports/?report=fees_summary&format=print')
        self.assertEqual(r.status_code, 200)
        self.assertIn('Fee Collection Summary', r.content.decode())

    def test_unknown_report_redirects(self):
        r = self.c.get('/reports/?report=nope&format=print')
        self.assertEqual(r.status_code, 302)
