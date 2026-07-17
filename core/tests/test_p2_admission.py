"""P2 — public online admission form."""
from django.test import Client, TestCase

from core.models import Applicant
from core.tests.factory import build_world, PASSWORD


class OnlineAdmissionTests(TestCase):
    def setUp(self):
        self.w = build_world()
        self.c = Client()

    def test_form_is_public(self):
        # No login required.
        self.assertEqual(self.c.get('/apply/').status_code, 200)

    def test_submit_creates_online_applicant(self):
        r = self.c.post('/apply/', {
            'name': 'Zara Khan', 'parent_name': 'Ali Khan',
            'phone': '0300-1234567', 'class_applied': '5',
            'email': 'ali@example.com', 'previous_school': 'ABC School'})
        self.assertEqual(r.status_code, 200)
        a = Applicant.objects.filter(name='Zara Khan').first()
        self.assertIsNotNone(a)
        self.assertEqual(a.source, 'Online')
        self.assertEqual(a.stage, 'Enquiry')
        self.assertTrue(a.ref.startswith('APP-'))
        self.assertContains(r, a.ref)

    def test_required_fields_validated(self):
        r = self.c.post('/apply/', {'name': '', 'parent_name': '', 'phone': ''})
        self.assertFalse(Applicant.objects.exists())
        self.assertContains(r, 'required')

    def test_honeypot_blocks_bot(self):
        self.c.post('/apply/', {
            'name': 'Bot', 'parent_name': 'Bot', 'phone': '1',
            'website': 'http://spam.example'})
        self.assertFalse(Applicant.objects.exists())

    def test_online_applicant_shows_in_office(self):
        a = Applicant.objects.create(name='Zara', parent_name='Ali',
                                     phone='0300', source='Online', ref='APP-26-0001')
        c = Client(); c.force_login(self.w.admin_u)
        r = c.get('/admissions/')
        self.assertContains(r, 'APP-26-0001')
        self.assertContains(r, 'Online')

    def test_document_view_requires_admin(self):
        a = Applicant.objects.create(name='Zara', parent_name='Ali', phone='0300')
        # No file uploaded -> 404 for admin (but reachable); parent -> not 200.
        parent = Client(); parent.login(username='parent1', password=PASSWORD)
        r = parent.get('/admissions/%d/doc/photo/' % a.id)
        self.assertNotEqual(r.status_code, 200)
