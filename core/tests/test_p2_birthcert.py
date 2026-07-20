"""P2 — Date of Birth certificate in the certificate module."""
import datetime

from django.test import Client, TestCase
from django.urls import reverse

from core.models import Certificate
from core.tests.factory import build_world, PASSWORD


class BirthCertificateTests(TestCase):
    def setUp(self):
        self.w = build_world()
        self.w.ayaan.date_of_birth = datetime.date(2012, 3, 5)
        self.w.ayaan.father_name = 'Imran Khan'
        self.w.ayaan.save()
        self.c = Client()
        self.c.login(username='admin1', password=PASSWORD)

    def test_generate_birth_certificate(self):
        r = self.c.post(reverse('certificates'),
                        {'student': self.w.ayaan.id, 'cert_type': 'Birth'})
        self.assertEqual(r.status_code, 302)
        cert = Certificate.objects.filter(student=self.w.ayaan,
                                          cert_type='Birth').first()
        self.assertIsNotNone(cert)

    def test_birth_certificate_shows_dob(self):
        cert = Certificate.objects.create(student=self.w.ayaan, cert_type='Birth')
        r = self.c.get(reverse('certificate_view', args=[cert.id]))
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn('05 March 2012', body)     # formatted DOB
        self.assertIn('Imran Khan', body)         # father name
        self.assertIn('Date of Birth Certificate', body)
