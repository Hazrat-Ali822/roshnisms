"""Per-school branded Android app: assetlinks, download page, .apk upload."""
import json
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from core.models import School
from core.tests.factory import build_world, PASSWORD


class AssetLinksTests(TestCase):
    def test_empty_by_default(self):
        r = Client().get('/.well-known/assetlinks.json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(json.loads(r.content), [])

    @override_settings(TWA_ASSETLINKS=[
        {'package': 'com.roshni.schoola', 'sha256': ['AA:BB:CC']}])
    def test_lists_configured_apps(self):
        r = Client().get('/.well-known/assetlinks.json')
        data = json.loads(r.content)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['target']['package_name'], 'com.roshni.schoola')
        self.assertIn('AA:BB:CC', data[0]['target']['sha256_cert_fingerprints'])
        self.assertEqual(data[0]['relation'],
                         ['delegate_permission/common.handle_all_urls'])

    @override_settings(TWA_ASSETLINKS=[{'package': 'x'}])  # missing sha256
    def test_skips_incomplete_entries(self):
        r = Client().get('/.well-known/assetlinks.json')
        self.assertEqual(json.loads(r.content), [])


class AppDownloadPageTests(TestCase):
    def setUp(self):
        self.w = build_world()

    def test_page_loads_without_login(self):
        r = Client().get(reverse('app_download'))
        self.assertEqual(r.status_code, 200)
        self.assertIn('Install app', r.content.decode())


class ApkUploadTests(TestCase):
    def setUp(self):
        self.w = build_world()
        self.c = Client()
        self.c.login(username='admin1', password=PASSWORD)

    def test_upload_apk_saved(self):
        with tempfile.TemporaryDirectory() as media:
            with override_settings(MEDIA_ROOT=media):
                apk = SimpleUploadedFile(
                    'schoola.apk', b'PK\x03\x04 fake apk bytes',
                    content_type='application/vnd.android.package-archive')
                r = self.c.post(reverse('school_settings'), {'app_apk': apk})
                self.assertEqual(r.status_code, 302)
                self.assertTrue(School.objects.first().app_apk)

    def test_non_apk_rejected(self):
        with tempfile.TemporaryDirectory() as media:
            with override_settings(MEDIA_ROOT=media):
                bad = SimpleUploadedFile('virus.exe', b'MZ not an apk')
                self.c.post(reverse('school_settings'), {'app_apk': bad})
                self.assertFalse(School.objects.first().app_apk)
