import io

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase

from core.models import School
from core.tests.factory import build_world


def _logo_bytes(color):
    """A tiny PNG: a block of `color` plus a dark corner (logo outline)."""
    from PIL import Image
    img = Image.new('RGB', (60, 40), (255, 255, 255))
    for x in range(4, 40):
        for y in range(4, 36):
            img.putpixel((x, y), color)
    for x in range(44, 56):
        for y in range(8, 32):
            img.putpixel((x, y), (18, 18, 26))
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()


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
        # Branding only shows in an explicit tenant context (a school's own
        # subdomain) — never on the bare SaaS/main host. Resolve the tenant via
        # its subdomain so the branding context processor kicks in.
        School.objects.filter(pk=self.w.school.pk).update(
            name='Green Valley School', accent_color='#1F6F3B',
            subdomain='greenvalley')
        html = self.c.get('/', HTTP_HOST='greenvalley.example.com').content.decode()
        self.assertIn('#1F6F3B', html)                 # colour injected
        self.assertIn('Green Valley School', html)     # brand name in sidebar
        self.assertNotIn('Roshni School</b>', html)    # no hardcoded name

    def test_login_page_is_branded(self):
        School.objects.filter(pk=self.w.school.pk).update(
            name='Green Valley School', subdomain='greenvalley')
        html = Client().get(
            '/login/', HTTP_HOST='greenvalley.example.com').content.decode()
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

    def test_match_colours_to_logo(self):
        s = School.objects.first()
        s.logo = SimpleUploadedFile('logo.png', _logo_bytes((245, 212, 0)),
                                    content_type='image/png')
        s.primary_color, s.accent_color = '#111111', '#222222'
        s.save()
        self.c.post('/settings/', {'action': 'logo_colors'})
        s.refresh_from_db()
        # Yellow logo -> a yellow-ish accent and a dark sidebar primary.
        self.assertNotEqual(s.accent_color, '#222222')
        r, g, b = (int(s.accent_color[i:i + 2], 16) for i in (1, 3, 5))
        self.assertTrue(r > 180 and g > 150 and b < 90)      # accent is yellow
        pr = sum(int(s.primary_color[i:i + 2], 16) for i in (1, 3, 5))
        self.assertLess(pr, 200)                             # primary is dark

    def test_auto_theme_checkbox_overrides_pickers(self):
        s = School.objects.first()
        s.logo = SimpleUploadedFile('logo.png', _logo_bytes((30, 90, 200)),
                                    content_type='image/png')
        s.save()
        # Admin picks red but also ticks "match to logo" -> logo (blue) wins.
        self.c.post('/settings/', {
            'name': 'X', 'primary_color': '#AA0000', 'accent_color': '#AA0000',
            'auto_theme': 'on'})
        s.refresh_from_db()
        rb, gb, bb = (int(s.accent_color[i:i + 2], 16) for i in (1, 3, 5))
        self.assertTrue(bb > rb)                             # accent is blue-ish

    def test_logo_served_with_cache_header(self):
        School.objects.filter(pk=self.w.school.pk).update(subdomain='greenvalley')
        s = School.objects.first()
        s.logo = SimpleUploadedFile('logo.png', _logo_bytes((14, 124, 102)),
                                    content_type='image/png')
        s.save()
        r = self.c.get('/school-logo/', HTTP_HOST='greenvalley.example.com')
        self.assertEqual(r.status_code, 200)
        self.assertIn('max-age', r['Cache-Control'])
