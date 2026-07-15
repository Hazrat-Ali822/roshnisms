"""Section 1 — security hardening: forced first-login password change,
brute-force lockout, and idle session timeout."""
import time

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import Client, TestCase

from core.models import LoginAttempt, Profile, Student
from core.tests.factory import build_world


class ForcePasswordChangeTests(TestCase):
    def setUp(self):
        self.w = build_world()

    def test_flagged_user_is_redirected_to_change_password(self):
        self.w.admin_p.must_change_password = True
        self.w.admin_p.save()
        c = Client(); c.force_login(self.w.admin_u)
        r = c.get('/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/account/password/', r['Location'])

    def test_change_password_page_itself_is_reachable(self):
        self.w.admin_p.must_change_password = True
        self.w.admin_p.save()
        c = Client(); c.force_login(self.w.admin_u)
        self.assertEqual(c.get('/account/password/').status_code, 200)

    def test_changing_password_clears_the_flag(self):
        self.w.admin_p.must_change_password = True
        self.w.admin_p.save()
        c = Client(); c.force_login(self.w.admin_u)
        c.post('/account/password/', {
            'old_password': 'testpass123',
            'new_password1': 'FreshPass2026', 'new_password2': 'FreshPass2026'})
        self.w.admin_p.refresh_from_db()
        self.assertFalse(self.w.admin_p.must_change_password)
        self.assertEqual(c.get('/').status_code, 200)   # no longer forced

    def test_normal_user_not_forced(self):
        c = Client(); c.force_login(self.w.admin_u)
        self.assertEqual(c.get('/').status_code, 200)

    def test_auto_created_student_login_is_flagged(self):
        from core.views import _provision_student_login
        s = Student.objects.create(name='New Kid', classroom=self.w.c9)
        _provision_student_login(s)
        prof = Profile.objects.get(role='student', student=s)
        self.assertTrue(prof.must_change_password)

    def test_default_admin_is_flagged(self):
        call_command('ensure_admin')
        u = User.objects.filter(username='admin').first()
        if u:   # only created on a truly empty system
            self.assertTrue(u.profile.must_change_password)


class LockoutTests(TestCase):
    def setUp(self):
        self.w = build_world()
        self.username = self.w.admin_u.username

    def test_locks_after_five_failures(self):
        c = Client()
        for _ in range(5):
            c.post('/login/', {'username': self.username, 'password': 'wrong'})
        rec = LoginAttempt.objects.get(username=self.username)
        self.assertIsNotNone(rec.locked_until)
        # even the CORRECT password is refused while locked
        r = c.post('/login/', {'username': self.username, 'password': 'testpass123'})
        self.assertIn('Too many failed attempts', r.content.decode())
        self.assertNotIn('_auth_user_id', c.session)

    def test_successful_login_resets_counter(self):
        c = Client()
        c.post('/login/', {'username': self.username, 'password': 'wrong'})
        c.post('/login/', {'username': self.username, 'password': 'wrong'})
        r = c.post('/login/', {'username': self.username, 'password': 'testpass123'})
        self.assertEqual(r.status_code, 302)                 # logged in
        self.assertFalse(LoginAttempt.objects.filter(username=self.username).exists())


class IdleTimeoutTests(TestCase):
    def setUp(self):
        self.w = build_world()

    def test_idle_session_is_signed_out(self):
        c = Client(); c.force_login(self.w.admin_u)
        c.get('/')                                   # stamps last_activity
        s = c.session
        s['last_activity'] = int(time.time()) - 3600  # an hour ago (> 30 min)
        s.save()
        r = c.get('/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('timeout=1', r['Location'])

    def test_active_session_stays(self):
        c = Client(); c.force_login(self.w.admin_u)
        c.get('/')
        self.assertEqual(c.get('/').status_code, 200)
