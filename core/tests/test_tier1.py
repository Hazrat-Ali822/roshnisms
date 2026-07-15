from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase

from core.models import Assignment, AuditLog, Submission
from core.tests.factory import build_world
from core.views import _upload_error, DOC_EXTS, IMAGE_EXTS
from core.views import _make_challan


class UploadValidationTests(TestCase):
    def test_upload_error_helper(self):
        good = SimpleUploadedFile('a.pdf', b'x', content_type='application/pdf')
        bad = SimpleUploadedFile('a.exe', b'x', content_type='application/octet-stream')
        big = SimpleUploadedFile('a.pdf', b'x' * (11 * 1024 * 1024))
        self.assertEqual(_upload_error(good, DOC_EXTS), '')
        self.assertIn('not allowed', _upload_error(bad, DOC_EXTS))
        self.assertIn('too large', _upload_error(big, DOC_EXTS))
        self.assertEqual(_upload_error(None, IMAGE_EXTS), '')   # no file = ok

    def test_bad_submission_file_blocked(self):
        w = build_world()
        a = Assignment.objects.create(classroom=w.c9, title='HW')
        c = Client(); c.force_login(w.student_u)
        bad = SimpleUploadedFile('virus.exe', b'x')
        c.post('/my-assignments/?id=%d' % a.id, {'answer_text': 'hi', 'file': bad})
        self.assertFalse(Submission.objects.filter(assignment=a).exists())
        # A valid file is accepted
        good = SimpleUploadedFile('work.pdf', b'x')
        c.post('/my-assignments/?id=%d' % a.id, {'answer_text': 'hi', 'file': good})
        self.assertTrue(Submission.objects.filter(assignment=a).exists())


class AuditLogTests(TestCase):
    def setUp(self):
        self.w = build_world()

    def test_marks_save_is_audited(self):
        c = Client(); c.force_login(self.w.teacher_u)
        c.post('/marks/', {'class': self.w.c9.id, 'subject': self.w.math9.id,
                           'exam': self.w.exam.id,
                           'marks_%d' % self.w.ayaan.id: '80'})
        self.assertTrue(AuditLog.objects.filter(action='Marks saved').exists())

    def test_fee_collection_is_audited(self):
        ch, _ = _make_challan(self.w.ayaan, 2026, 6)
        c = Client(); c.force_login(self.w.finance_u)
        c.post('/fees/student/%d/' % self.w.ayaan.id, {
            'action': 'collect', 'challan_id': ch.id, 'amount': '5000', 'mode': 'Cash'})
        self.assertTrue(AuditLog.objects.filter(action='Fee collected').exists())

    def test_role_change_is_audited(self):
        c = Client(); c.force_login(self.w.admin_u)
        c.post('/users/', {'action': 'update_role',
                           'user_id': self.w.finance_u.id, 'role': 'admin'})
        self.assertTrue(AuditLog.objects.filter(action='Role changed').exists())

    def test_audit_page_admin_only(self):
        c = Client(); c.force_login(self.w.admin_u)
        self.assertEqual(c.get('/audit/').status_code, 200)
        c2 = Client(); c2.force_login(self.w.teacher_u)
        self.assertEqual(c2.get('/audit/').status_code, 403)


class PasswordStrengthTests(TestCase):
    def setUp(self):
        self.w = build_world()
        self.c = Client(); self.c.force_login(self.w.admin_u)

    def test_weak_password_rejected(self):
        self.c.post('/users/', {'action': 'create', 'username': 'weakone',
                                'password': '123', 'role': 'admin'})
        self.assertFalse(User.objects.filter(username='weakone').exists())

    def test_strong_password_accepted(self):
        self.c.post('/users/', {'action': 'create', 'username': 'strongone',
                                'password': 'Str0ngPass!', 'role': 'admin'})
        self.assertTrue(User.objects.filter(username='strongone').exists())
