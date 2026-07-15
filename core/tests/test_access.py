from django.test import Client, TestCase

from core.tests.factory import build_world


class AccessTests(TestCase):
    def setUp(self):
        self.w = build_world()
        self.c = Client()

    def test_every_role_dashboard_loads(self):
        for u in [self.w.admin_u, self.w.teacher_u, self.w.finance_u,
                  self.w.principal_u, self.w.owner_u, self.w.parent_u,
                  self.w.student_u]:
            self.c.force_login(u)
            self.assertEqual(self.c.get('/').status_code, 200,
                             '%s dashboard failed' % u.username)

    def test_login_required(self):
        # Anonymous is redirected to login (302), not served the page.
        self.assertEqual(self.c.get('/students/').status_code, 302)

    def test_teacher_blocked_from_admin_and_finance(self):
        self.c.force_login(self.w.teacher_u)
        for path in ['/students/', '/fees/collection/', '/users/',
                     '/timetable/manage/', '/admissions/']:
            self.assertEqual(self.c.get(path).status_code, 403, path)

    def test_finance_blocked_from_admin(self):
        self.c.force_login(self.w.finance_u)
        for path in ['/students/', '/users/', '/discipline/']:
            self.assertEqual(self.c.get(path).status_code, 403, path)

    def test_discipline_is_admin_only(self):
        self.c.force_login(self.w.admin_u)
        self.assertEqual(self.c.get('/discipline/').status_code, 200)
        for u in [self.w.teacher_u, self.w.parent_u, self.w.student_u,
                  self.w.finance_u]:
            self.c.force_login(u)
            self.assertEqual(self.c.get('/discipline/').status_code, 403,
                             '%s should not see discipline' % u.username)

    def test_my_discipline_url_removed(self):
        self.c.force_login(self.w.parent_u)
        self.assertEqual(self.c.get('/my-discipline/').status_code, 404)

    def test_teacher_self_service_pages(self):
        self.c.force_login(self.w.teacher_u)
        self.assertEqual(self.c.get('/teacher/timetable/').status_code, 200)
        self.assertEqual(self.c.get('/teacher/my-hr/').status_code, 200)
