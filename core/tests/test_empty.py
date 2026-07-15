"""Robustness on a brand-new EMPTY school (setup_school path): no classes,
no students, no exams. Every page must render, not crash with 500."""
from django.contrib.auth.models import User
from django.test import Client, TestCase

from core.models import Profile, School


class EmptySchoolTests(TestCase):
    def setUp(self):
        School.objects.create(name='Fresh School')
        u = User.objects.create_user('admin1', password='x')
        Profile.objects.create(user=u, role='admin')
        self.c = Client()
        self.c.force_login(u)

    def test_admin_pages_on_empty_data(self):
        paths = ['/', '/students/', '/classes/', '/timetable/manage/',
                 '/reports/',
                 '/staff/', '/staff/payroll/', '/staff/attendance/',
                 '/exams/datesheet/', '/exams/rooms/', '/exams/seating/',
                 '/discipline/', '/admissions/', '/id-cards/', '/certificates/',
                 '/calendar/', '/inventory/', '/visitors/', '/users/',
                 '/settings/', '/communication/', '/transport/', '/library/',
                 '/hostel/']
        for p in paths:
            self.assertEqual(self.c.get(p).status_code, 200,
                             'EMPTY-DATA page crashed: %s' % p)

    def test_finance_pages_on_empty_data(self):
        u = User.objects.create_user('finance1', password='x')
        Profile.objects.create(user=u, role='finance')
        c = Client(); c.force_login(u)
        for p in ['/', '/fees/collection/', '/fees/defaulters/',
                  '/fees/receipts/', '/fees/expenses/']:
            self.assertEqual(c.get(p).status_code, 200,
                             'finance empty page crashed: %s' % p)

    def test_teacher_with_no_class(self):
        u = User.objects.create_user('teacher1', password='x')
        Profile.objects.create(user=u, role='teacher')  # no classroom
        c = Client(); c.force_login(u)
        for p in ['/', '/marks/', '/attendance/', '/teacher/timetable/',
                  '/teacher/my-hr/', '/teacher/assignments/', '/teacher/quizzes/']:
            self.assertEqual(c.get(p).status_code, 200,
                             'teacher-no-class page crashed: %s' % p)

    def test_reports_on_empty_data(self):
        for r, f in [('students', 'csv'), ('fees', 'csv'), ('attendance', 'csv'),
                     ('results', 'csv'), ('summary', 'print'),
                     ('fees_summary', 'print')]:
            resp = self.c.get('/reports/?report=%s&format=%s' % (r, f))
            self.assertEqual(resp.status_code, 200,
                             'empty report crashed: %s/%s' % (r, f))
