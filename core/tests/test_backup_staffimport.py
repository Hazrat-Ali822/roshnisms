"""One-click DB backup download + staff bulk CSV import."""
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase

from core.models import Staff
from core.tests.factory import build_world


def csv_file(text, name='staff.csv'):
    return SimpleUploadedFile(name, text.encode('utf-8'), content_type='text/csv')


class BackupTests(TestCase):
    def setUp(self):
        self.w = build_world()

    def test_admin_downloads_backup(self):
        c = Client(); c.force_login(self.w.admin_u)
        r = c.get('/settings/backup/')
        self.assertEqual(r.status_code, 200)
        self.assertIn('attachment', r['Content-Disposition'])
        self.assertIn('.sqlite3', r['Content-Disposition'])
        # a real SQLite file starts with this magic header
        self.assertTrue(r.content.startswith(b'SQLite format 3'))

    def test_non_admin_blocked(self):
        c = Client(); c.force_login(self.w.finance_u)
        self.assertIn(c.get('/settings/backup/').status_code, (302, 403))


class StaffImportTests(TestCase):
    def setUp(self):
        self.w = build_world()
        self.c = Client(); self.c.force_login(self.w.admin_u)

    def test_page_and_template(self):
        self.assertEqual(self.c.get('/staff/import/').status_code, 200)
        r = self.c.post('/staff/import/', {'action': 'template'})
        self.assertIn('text/csv', r['Content-Type'])
        self.assertIn('Designation', r.content.decode())

    def test_import_creates_staff(self):
        before = Staff.objects.count()
        text = ('Name,Designation,Phone,Email,Basic Salary,Allowances\n'
                'Nadia Aslam,Teacher,0300-1111111,n@s.pk,40000,5000\n'
                'Bilal Khan,Clerk,0301-2222222,b@s.pk,25000,2000\n')
        self.c.post('/staff/import/', {'file': csv_file(text)})
        self.assertEqual(Staff.objects.count(), before + 2)
        nadia = Staff.objects.get(name='Nadia Aslam')
        self.assertEqual(nadia.basic_salary, 40000)
        self.assertEqual(nadia.monthly_salary, 45000)

    def test_missing_name_skipped(self):
        text = 'Name,Designation\n,Teacher\nReal Person,Teacher\n'
        self.c.post('/staff/import/', {'file': csv_file(text)})
        self.assertTrue(Staff.objects.filter(name='Real Person').exists())

    def test_bad_salary_defaults_zero(self):
        text = 'Name,Basic Salary\nOdd Salary,abc\n'
        self.c.post('/staff/import/', {'file': csv_file(text)})
        self.assertEqual(Staff.objects.get(name='Odd Salary').basic_salary, 0)

    def test_rejects_non_csv(self):
        before = Staff.objects.count()
        bad = SimpleUploadedFile('x.exe', b'no', content_type='application/x-msdownload')
        self.c.post('/staff/import/', {'file': bad})
        self.assertEqual(Staff.objects.count(), before)
