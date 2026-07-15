"""Bulk student import from CSV."""
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase

from core.models import Profile, Student
from core.tests.factory import build_world


def csv_file(text, name='students.csv'):
    return SimpleUploadedFile(name, text.encode('utf-8'), content_type='text/csv')


class ImportTests(TestCase):
    def setUp(self):
        self.w = build_world()
        self.c = Client()
        self.c.force_login(self.w.admin_u)

    def test_page_loads(self):
        self.assertEqual(self.c.get('/students/import/').status_code, 200)

    def test_template_download(self):
        r = self.c.post('/students/import/', {'action': 'template'})
        self.assertEqual(r.status_code, 200)
        self.assertIn('text/csv', r['Content-Type'])
        self.assertIn('Name', r.content.decode())

    def test_import_creates_students_and_logins(self):
        before = Student.objects.count()
        text = ('Name,Class,Roll No,Admission No,Gender,Date of Birth,'
                'Guardian Name,Guardian Phone,Address\n'
                'Bilal Ahmed,9-A,5,,Male,2011-03-02,Ahmed,0300-9999999,Lahore\n'
                'Sara Khan,9-A,6,,Female,,Khan,0301-8888888,Lahore\n')
        self.c.post('/students/import/', {'file': csv_file(text)})
        self.assertEqual(Student.objects.count(), before + 2)
        bilal = Student.objects.get(name='Bilal Ahmed')
        self.assertEqual(bilal.classroom, self.w.c9)
        self.assertEqual(str(bilal.date_of_birth), '2011-03-02')
        # login auto-created for the student
        self.assertTrue(Profile.objects.filter(role='student',
                                               student=bilal).exists())

    def test_missing_name_is_skipped_not_fatal(self):
        text = ('Name,Class\n'
                ',9-A\n'
                'Real Kid,9-A\n')
        self.c.post('/students/import/', {'file': csv_file(text)})
        self.assertTrue(Student.objects.filter(name='Real Kid').exists())
        self.assertFalse(Student.objects.filter(name='').exists())

    def test_bad_date_still_imports_student(self):
        text = 'Name,Date of Birth\nOdd Date,not-a-date\n'
        self.c.post('/students/import/', {'file': csv_file(text)})
        s = Student.objects.get(name='Odd Date')
        self.assertIsNone(s.date_of_birth)

    def test_auto_admission_number_when_blank(self):
        text = 'Name\nNo Adm Kid\n'
        self.c.post('/students/import/', {'file': csv_file(text)})
        s = Student.objects.get(name='No Adm Kid')
        self.assertTrue(s.admission_no)

    def test_non_admin_blocked(self):
        c = Client(); c.force_login(self.w.teacher_u)
        self.assertIn(c.get('/students/import/').status_code, (302, 403))

    def test_rejects_non_csv(self):
        before = Student.objects.count()
        bad = SimpleUploadedFile('x.exe', b'nope', content_type='application/x-msdownload')
        self.c.post('/students/import/', {'file': bad})
        self.assertEqual(Student.objects.count(), before)
