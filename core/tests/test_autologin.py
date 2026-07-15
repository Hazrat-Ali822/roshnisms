from django.test import Client, TestCase

from core.models import ClassRoom, Profile, School, Staff, Student
from core.tests.factory import build_world


class AutoLoginTests(TestCase):
    def setUp(self):
        self.w = build_world()
        self.default = School.objects.first().default_password  # 'school123'
        self.c = Client()
        self.c.force_login(self.w.admin_u)

    def _add_student(self, name, phone):
        self.c.post('/students/add/', {
            'name': name, 'classroom': self.w.c9.id,
            'guardian_name': 'Dad', 'guardian_phone': phone})
        return Student.objects.get(name=name)

    def test_student_add_creates_student_and_parent_logins(self):
        s = self._add_student('New KidA', '0300-5551234')
        slog = Profile.objects.filter(role='student', student=s).first()
        plog = Profile.objects.filter(role='parent', children=s).first()
        self.assertIsNotNone(slog)
        self.assertIsNotNone(plog)
        # Default password actually works for the new login
        self.assertTrue(Client().login(username=slog.user.username,
                                       password=self.default))

    def test_siblings_share_one_parent_login(self):
        a = self._add_student('Sib A', '0300-7777777')
        parents_before = Profile.objects.filter(role='parent').count()
        b = self._add_student('Sib B', '0300-7777777')   # same guardian phone
        parents_after = Profile.objects.filter(role='parent').count()
        self.assertEqual(parents_before, parents_after)   # no new parent
        plog = Profile.objects.filter(role='parent', children=a).first()
        names = set(plog.children.values_list('name', flat=True))
        self.assertEqual(names, {'Sib A', 'Sib B'})

    def test_student_detail_shows_logins_and_reset(self):
        s = self._add_student('Detail Kid', '0300-8888888')
        slog = Profile.objects.filter(role='student', student=s).first()
        html = self.c.get('/students/%d/' % s.id).content.decode()
        self.assertIn(slog.user.username, html)
        # Reset password back to default
        r = self.c.post('/students/%d/' % s.id,
                        {'action': 'reset_login', 'user_id': slog.user.id})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(Client().login(username=slog.user.username,
                                       password=self.default))

    def test_student_add_with_blank_optional_selects(self):
        """Regression: adding a student without picking a transport route (the
        select submits an empty string) must not crash with ValueError."""
        r = self.c.post('/students/add/', {
            'name': 'No Route Kid', 'classroom': self.w.c9.id,
            'route': '', 'admission_type': '', 'status': '',
            'guardian_name': 'X', 'guardian_phone': '0300-1234000'})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(Student.objects.filter(name='No Route Kid').exists())

    def test_staff_add_with_login(self):
        self.c.post('/staff/', {
            'name': 'New Teacher', 'designation': 'Teacher',
            'create_login': 'on', 'login_role': 'teacher',
            'login_class': self.w.c9.id})
        st = Staff.objects.get(name='New Teacher')
        self.assertIsNotNone(st.user_id)
        self.assertEqual(st.user.profile.role, 'teacher')
        self.assertEqual(st.user.profile.classroom_id, self.w.c9.id)

    def test_self_service_password_change(self):
        s = self._add_student('Pwd Kid', '0300-9999999')
        slog = Profile.objects.filter(role='student', student=s).first()
        sc = Client()
        self.assertTrue(sc.login(username=slog.user.username, password=self.default))
        self.assertEqual(sc.get('/account/password/').status_code, 200)
        r = sc.post('/account/password/', {
            'old_password': self.default,
            'new_password1': 'BrandNew2026', 'new_password2': 'BrandNew2026'})
        self.assertEqual(r.status_code, 302)
        # Old password no longer works; new one does
        self.assertFalse(Client().login(username=slog.user.username,
                                        password=self.default))
        self.assertTrue(Client().login(username=slog.user.username,
                                       password='BrandNew2026'))
