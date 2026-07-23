"""Every printed document must carry the school's own logo and name.

Certificates, ID cards, receipts, payslips and report cards leave the building —
a parent, a board or another school reads them. If one of them shows a blank
crest, a hardcoded "Roshni Public School", or no name at all (which is exactly
what happened to the Leaving Certificate), the document is worthless.

These tests render each document for a school that HAS uploaded a logo and
assert its real name and logo appear.
"""
import io

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse

from core.models import (Certificate, Exam, FeePayment, Mark, Payslip, School,
                         Staff, Subject)
from core.tests.factory import build_world

# No ampersand: Django escapes '&' to '&amp;' in the HTML, which would make a
# plain assertIn on the raw name fail for the wrong reason.
SCHOOL_NAME = 'Sudhum Children Academy Rustam Mardan'


def _logo_png():
    from PIL import Image
    img = Image.new('RGB', (48, 48), (12, 90, 74))
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()


class DocumentBrandingTests(TestCase):
    def setUp(self):
        self.w = build_world()
        school = School.objects.first()
        school.name = SCHOOL_NAME
        school.campus = 'Main Campus'
        school.address = '12-A College Road, Mardan'
        school.phone = '0937-123456'
        school.principal_name = 'Asad Mehmood'
        school.logo = SimpleUploadedFile('logo.png', _logo_png(),
                                         content_type='image/png')
        school.save()
        self.school = school
        self.c = Client()
        self.c.force_login(self.w.admin_u)

    def _assert_branded(self, url, label):
        resp = self.c.get(url)
        self.assertEqual(resp.status_code, 200, '%s did not render' % label)
        html = resp.content.decode()
        self.assertIn(SCHOOL_NAME, html,
                      "%s does not show the school's name" % label)
        self.assertIn(reverse('school_logo'), html,
                      "%s does not show the school's logo" % label)
        self.assertNotIn('Roshni Public School', html,
                         '%s has a hardcoded school name' % label)
        return html

    def test_certificate_shows_logo_name_and_principal(self):
        cert = Certificate.objects.create(student=self.w.ayaan,
                                          cert_type='Leaving')
        html = self._assert_branded(
            reverse('certificate_view', args=[cert.id]), 'Certificate')
        # The principal must come from Settings, not be baked into the template.
        self.assertIn('Asad Mehmood', html)
        self.assertIn(self.school.address, html)

    def test_id_cards_show_logo_and_name(self):
        self._assert_branded(reverse('id_cards'), 'ID cards')

    def test_receipt_shows_logo_and_name(self):
        payment = FeePayment.objects.create(
            student=self.w.ayaan, month='June 2026', amount=5000,
            mode='Cash', received_by='Office', receipt_no='RCPT-1')
        self._assert_branded(reverse('receipt_view', args=[payment.id]),
                             'Fee receipt')

    def test_payslip_shows_logo_and_name(self):
        staff = Staff.objects.create(name='Bilal Hussain', designation='Teacher',
                                     basic_salary=50000, allowances=5000)
        slip = Payslip.objects.create(staff=staff, year=2026, month=6,
                                      basic=50000, allowances=5000)
        self._assert_branded(reverse('payslip_pdf', args=[slip.id]), 'Payslip')

    def test_report_card_shows_logo_and_name(self):
        exam = Exam.objects.create(name='Mid-Term', session='2025-26')
        subject = Subject.objects.filter(classroom=self.w.c9).first()
        Mark.objects.create(student=self.w.ayaan, subject=subject, exam=exam,
                            marks_obtained=80, total_marks=100)
        self._assert_branded(
            reverse('report_card', args=[self.w.ayaan.id, exam.id]),
            'Report card')

    def test_no_document_template_hardcodes_a_school_name(self):
        """Guards the whole templates folder, not just the pages above."""
        import glob
        import os
        offenders = []
        for path in glob.glob('core/templates/*.html'):
            if os.path.basename(path) == 'app_download.html':
                continue          # standalone page with its own fixed styling
            with open(path, encoding='utf-8') as fh:
                body = fh.read()
            if 'Roshni Public School' in body or 'Main Campus, Lahore' in body:
                offenders.append(os.path.basename(path))
        self.assertFalse(
            offenders,
            'these templates hardcode a school name instead of using '
            'brand_name: %s' % offenders)
