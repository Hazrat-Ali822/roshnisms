from django.test import Client, TestCase

from core.models import School
from core.tests.factory import build_world


class BrandingTests(TestCase):
    def setUp(self):
        self.w = build_world()
        self.c = Client()
        self.c.force_login(self.w.admin_u)

    def test_settings_saves_name_and_colours(self):
        self.c.post('/settings/', {
            'name': 'Green Valley School', 'campus': 'Lahore',
            'session': '2025-26', 'final_grade': '10', 'pass_mark': '40',
            'hostel_fee': '8000', 'late_fee_amount': '0',
            'primary_color': '#7A1F2B', 'accent_color': '#1F6F3B'})
        s = School.objects.first()
        self.assertEqual(s.name, 'Green Valley School')
        self.assertEqual(s.primary_color, '#7A1F2B')
        self.assertEqual(s.accent_color, '#1F6F3B')

    def test_colours_and_name_applied_app_wide(self):
        School.objects.filter(pk=self.w.school.pk).update(
            name='Green Valley School', accent_color='#1F6F3B')
        html = self.c.get('/').content.decode()
        self.assertIn('#1F6F3B', html)                 # colour injected
        self.assertIn('Green Valley School', html)     # brand name in sidebar
        self.assertNotIn('Roshni School</b>', html)    # no hardcoded name

    def test_login_page_is_branded(self):
        School.objects.filter(pk=self.w.school.pk).update(name='Green Valley School')
        html = Client().get('/login/').content.decode()
        self.assertIn('Green Valley School', html)
        self.assertNotIn('roshni123', html)            # demo hint removed

    def test_bad_colour_ignored(self):
        self.c.post('/settings/', {
            'name': 'X', 'primary_color': 'not-a-colour',
            'accent_color': '#123456'})
        s = School.objects.first()
        self.assertEqual(s.primary_color, '#15294D')   # unchanged (invalid)
        self.assertEqual(s.accent_color, '#123456')    # valid applied

    def test_logo_404_when_none(self):
        self.assertEqual(Client().get('/school-logo/').status_code, 404)
