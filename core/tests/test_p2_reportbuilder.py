"""P2 — custom student report builder."""
from django.test import Client, TestCase

from core.tests.factory import build_world, PASSWORD


class ReportBuilderTests(TestCase):
    def setUp(self):
        self.w = build_world()
        self.c = Client(); self.c.force_login(self.w.admin_u)

    def test_builder_page_renders(self):
        r = self.c.get('/reports/builder/')
        self.assertEqual(r.status_code, 200)
        self.assertIn('name', r.context['selected'])

    def test_export_csv_selected_columns(self):
        r = self.c.get('/reports/builder/?col=name&col=guardian_phone&export=csv')
        self.assertEqual(r['Content-Type'].split(';')[0], 'text/csv')
        body = r.content.decode()
        self.assertIn('Name,Guardian Phone', body)
        self.assertIn('Ayaan', body)
        # A column not selected must not appear.
        self.assertNotIn('Admission No', body)

    def test_class_filter(self):
        # Only class 9-A students (Ayaan, Hira), not Inaya (10-A).
        r = self.c.get('/reports/builder/?col=name&class=%d&export=csv' % self.w.c9.id)
        body = r.content.decode()
        self.assertIn('Ayaan', body)
        self.assertIn('Hira', body)
        self.assertNotIn('Inaya', body)

    def test_preview_limited_and_counts(self):
        r = self.c.get('/reports/builder/?col=name')
        self.assertEqual(r.context['total'], 3)      # ayaan, hira, inaya active
        self.assertLessEqual(len(r.context['preview_rows']), 50)

    def test_teacher_cannot_access(self):
        c = Client(); c.login(username='teacher1', password=PASSWORD)
        r = c.get('/reports/builder/')
        self.assertNotEqual(r.status_code, 200)
