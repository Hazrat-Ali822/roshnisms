import base64
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings

from core.models import Profile
from core.tests.factory import build_world

PNG = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==')


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class AvatarTests(TestCase):
    def setUp(self):
        self.w = build_world()

    def _png(self, name='me.png'):
        return SimpleUploadedFile(name, PNG, content_type='image/png')

    def test_account_page_loads_for_every_role(self):
        for u in [self.w.admin_u, self.w.teacher_u, self.w.parent_u,
                  self.w.student_u, self.w.finance_u]:
            c = Client(); c.force_login(u)
            self.assertEqual(c.get('/account/').status_code, 200)

    def test_upload_and_serve_avatar(self):
        c = Client(); c.force_login(self.w.teacher_u)
        c.post('/account/', {'photo': self._png()})
        prof = Profile.objects.get(user=self.w.teacher_u)
        self.assertTrue(prof.photo)
        # served + shown in topbar
        self.assertEqual(c.get('/profile-photo/%d/' % self.w.teacher_u.id).status_code, 200)
        self.assertIn('/profile-photo/%d/' % self.w.teacher_u.id,
                      c.get('/').content.decode())

    def test_bad_type_rejected(self):
        c = Client(); c.force_login(self.w.teacher_u)
        bad = SimpleUploadedFile('x.exe', b'x')
        c.post('/account/', {'photo': bad})
        self.assertFalse(Profile.objects.get(user=self.w.teacher_u).photo)

    def test_remove_avatar(self):
        c = Client(); c.force_login(self.w.teacher_u)
        c.post('/account/', {'photo': self._png()})
        c.post('/account/', {'remove_photo': '1'})
        self.assertFalse(Profile.objects.get(user=self.w.teacher_u).photo)

    def test_admin_can_manage_other_user_photo(self):
        c = Client(); c.force_login(self.w.admin_u)
        c.post('/account/?user=%d' % self.w.student_u.id,
               {'user_id': self.w.student_u.id, 'photo': self._png()})
        self.assertTrue(Profile.objects.get(user=self.w.student_u).photo)

    def test_non_admin_cannot_manage_others(self):
        # teacher tries to set student's photo -> falls back to editing self
        c = Client(); c.force_login(self.w.teacher_u)
        c.post('/account/?user=%d' % self.w.student_u.id,
               {'user_id': self.w.student_u.id, 'photo': self._png()})
        self.assertFalse(Profile.objects.get(user=self.w.student_u).photo)
        self.assertTrue(Profile.objects.get(user=self.w.teacher_u).photo)

    def test_profile_photo_404_when_none(self):
        c = Client(); c.force_login(self.w.teacher_u)
        self.assertEqual(c.get('/profile-photo/%d/' % self.w.teacher_u.id).status_code, 404)
