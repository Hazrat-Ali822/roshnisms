"""Section 1 — security hardening: forced first-login password change,
brute-force lockout, and idle session timeout."""
import time

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import Client, TestCase

from core.backends import EmailOrUsernameBackend
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
        from django.conf import settings
        c = Client(); c.force_login(self.w.admin_u)
        c.get('/')                                   # stamps last_activity
        s = c.session
        s['last_activity'] = int(time.time()) - 3600  # an hour ago (> 30 min)
        s.save()
        c.cookies[settings.SESSION_COOKIE_NAME] = s.session_key
        r = c.get('/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('timeout=1', r['Location'])

    def test_active_session_stays(self):
        c = Client(); c.force_login(self.w.admin_u)
        c.get('/')
        self.assertEqual(c.get('/').status_code, 200)


class EmailOrUsernameBackendTests(TestCase):
    def setUp(self):
        self.w = build_world()
        self.backend = EmailOrUsernameBackend()
        
        # Create users with duplicate emails
        self.u1 = User.objects.create_user(username='dupuser1', password='pass1', email='dup@roshni.edu.pk')
        self.u2 = User.objects.create_user(username='dupuser2', password='pass2', email='dup@roshni.edu.pk')
        
        # Create users with blank emails
        self.u_blank1 = User.objects.create_user(username='blankuser1', password='pass1', email='')
        self.u_blank2 = User.objects.create_user(username='blankuser2', password='pass2', email='')

    def test_auth_by_username(self):
        user = self.backend.authenticate(None, username='dupuser1', password='pass1')
        self.assertEqual(user, self.u1)

    def test_auth_by_email_first_user(self):
        user = self.backend.authenticate(None, username='dup@roshni.edu.pk', password='pass1')
        self.assertEqual(user, self.u1)

    def test_auth_by_email_second_user(self):
        user = self.backend.authenticate(None, username='dup@roshni.edu.pk', password='pass2')
        self.assertEqual(user, self.u2)

    def test_auth_by_email_wrong_password(self):
        user = self.backend.authenticate(None, username='dup@roshni.edu.pk', password='wrong')
        self.assertIsNone(user)

    def test_auth_with_blank_username(self):
        # Blank username lookup should return None, rather than matching users with blank emails
        user = self.backend.authenticate(None, username='', password='pass1')
        self.assertIsNone(user)
        user_space = self.backend.authenticate(None, username='   ', password='pass1')
        self.assertIsNone(user_space)


# =====================================================================
# Priority 0 — at-rest credential protection (field encryption + hashing)
# =====================================================================
from django.contrib.auth.hashers import identify_hasher   # noqa: E402
from django.db import connection                            # noqa: E402

from core.crypto import (encrypt, decrypt, hash_password, is_hashed,   # noqa: E402
                         apply_stored_password)
from core.models import School                              # noqa: E402


class FieldEncryptionTests(TestCase):
    def test_encrypt_roundtrip_and_tolerance(self):
        token = encrypt('super-secret')
        self.assertNotEqual(token, 'super-secret')
        self.assertTrue(token.startswith('enc::'))
        self.assertEqual(decrypt(token), 'super-secret')
        # Legacy plaintext (no prefix) passes through untouched.
        self.assertEqual(decrypt('legacy-plain'), 'legacy-plain')
        # Empty stays empty.
        self.assertEqual(encrypt(''), '')
        self.assertEqual(decrypt(''), '')

    def test_secret_field_stored_encrypted_read_plaintext(self):
        s = School.objects.create(
            name='Enc School', subdomain='encschool',
            pay_jazzcash_password='jc-pass-123', pay_jazzcash_salt='salt-xyz',
            whatsapp_token='wa-token-abc', sms_twilio_token='tw-token-999')
        # Read back via the ORM → decrypted plaintext (what payments/sms use).
        got = School.objects.get(pk=s.pk)
        self.assertEqual(got.pay_jazzcash_password, 'jc-pass-123')
        self.assertEqual(got.pay_jazzcash_salt, 'salt-xyz')
        self.assertEqual(got.whatsapp_token, 'wa-token-abc')
        self.assertEqual(got.sms_twilio_token, 'tw-token-999')
        # The raw database column must NOT contain the plaintext.
        with connection.cursor() as cur:
            cur.execute(
                'SELECT pay_jazzcash_password, whatsapp_token '
                'FROM core_school WHERE id=%s', [s.pk])
            raw_jc, raw_wa = cur.fetchone()
        self.assertNotIn('jc-pass-123', raw_jc or '')
        self.assertTrue((raw_jc or '').startswith('enc::'))
        self.assertNotIn('wa-token-abc', raw_wa or '')
        self.assertTrue((raw_wa or '').startswith('enc::'))

    def test_blank_secret_stays_blank(self):
        s = School.objects.create(name='Blank', subdomain='blanksec')
        got = School.objects.get(pk=s.pk)
        self.assertEqual(got.pay_jazzcash_password, '')


class AdminPasswordHashTests(TestCase):
    def test_hash_password_and_detection(self):
        h = hash_password('MyPass123')
        self.assertTrue(is_hashed(h))
        self.assertNotEqual(h, 'MyPass123')
        identify_hasher(h)  # must be a recognised Django hash
        self.assertFalse(is_hashed('plaintextpw'))
        self.assertEqual(hash_password(''), '')

    def test_apply_stored_password_from_hash(self):
        """A stored hash assigned to a User authenticates with the original
        plaintext (exactly what the tenant rebuild does)."""
        stored = hash_password('SchoolAdmin1')
        u = User(username='rebuilt_admin')
        apply_stored_password(u, stored)
        u.save()
        self.assertTrue(u.check_password('SchoolAdmin1'))

    def test_apply_stored_password_from_legacy_plaintext(self):
        u = User(username='legacy_admin')
        apply_stored_password(u, 'legacyPlain9')   # not a hash
        u.save()
        self.assertTrue(u.check_password('legacyPlain9'))

    def test_provisioning_stores_hash_not_plaintext(self):
        """saas_school_add must never persist the admin password in plaintext."""
        from django.urls import reverse
        su = User.objects.create_superuser('root', 'root@x.com', 'rootpw123')
        c = Client()
        c.force_login(su)
        # No admin_username → the school is created but no tenant DB is built,
        # keeping this a pure unit test of the hashing behaviour.
        c.post(reverse('saas_school_add'), {
            'name': 'Hash School', 'subdomain': 'hashschool',
            'subscription_rate': '5000', 'admin_password': 'PlainSecret1'})
        s = School.objects.filter(subdomain='hashschool').first()
        self.assertIsNotNone(s)
        self.assertNotEqual(s.admin_password, 'PlainSecret1')
        self.assertTrue(is_hashed(s.admin_password))

