"""Section 5 — guided backup restore: file validation, preview, and the typed
confirmation gate. We drive the two-step upload flow with an in-memory file."""
import io
import sqlite3
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase

from core.tests.factory import build_world, PASSWORD
from core.views import _validate_backup


def _make_valid_backup_bytes():
    """A minimal SQLite file that passes validation (has the required tables)."""
    tmp = tempfile.NamedTemporaryFile(suffix='.sqlite3', delete=False)
    tmp.close()
    con = sqlite3.connect(tmp.name)
    cur = con.cursor()
    cur.execute('CREATE TABLE django_migrations (id INTEGER PRIMARY KEY)')
    cur.execute('CREATE TABLE auth_user (id INTEGER PRIMARY KEY)')
    cur.execute('CREATE TABLE core_student (id INTEGER PRIMARY KEY)')
    cur.execute('CREATE TABLE core_staff (id INTEGER PRIMARY KEY)')
    cur.execute('CREATE TABLE core_feepayment (id INTEGER PRIMARY KEY)')
    cur.execute('CREATE TABLE core_school (id INTEGER PRIMARY KEY, name TEXT, '
                'session TEXT)')
    cur.execute("INSERT INTO core_school (name, session) VALUES "
                "('Backup School', '2024-25')")
    cur.execute('INSERT INTO core_student (id) VALUES (1), (2), (3)')
    con.commit()
    con.close()
    with open(tmp.name, 'rb') as fh:
        return fh.read()


class ValidateBackupTests(TestCase):
    def test_rejects_non_sqlite(self):
        tmp = tempfile.NamedTemporaryFile(delete=False)
        tmp.write(b'this is not a database')
        tmp.close()
        ok, err, _ = _validate_backup(tmp.name)
        self.assertFalse(ok)
        self.assertIn('not a valid backup', err)

    def test_accepts_valid_backup_and_previews(self):
        tmp = tempfile.NamedTemporaryFile(suffix='.sqlite3', delete=False)
        tmp.write(_make_valid_backup_bytes())
        tmp.close()
        ok, err, preview = _validate_backup(tmp.name)
        self.assertTrue(ok, err)
        self.assertEqual(preview['students'], 3)
        self.assertEqual(preview['school_name'], 'Backup School')
        self.assertEqual(preview['session'], '2024-25')


class RestoreFlowTests(TestCase):
    def setUp(self):
        self.w = build_world()
        self.c = Client()
        self.c.login(username='admin1', password=PASSWORD)

    def test_upload_step_shows_preview(self):
        up = SimpleUploadedFile('backup.sqlite3', _make_valid_backup_bytes(),
                                content_type='application/x-sqlite3')
        r = self.c.post('/settings/restore/', {'step': 'upload', 'backup': up})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Backup School')
        self.assertContains(r, 'Type RESTORE')

    def test_bad_file_is_rejected(self):
        up = SimpleUploadedFile('notes.txt', b'hello there',
                                content_type='text/plain')
        r = self.c.post('/settings/restore/', {'step': 'upload', 'backup': up},
                        follow=True)
        self.assertContains(r, 'not a valid backup')

    def test_confirm_requires_exact_word(self):
        up = SimpleUploadedFile('backup.sqlite3', _make_valid_backup_bytes(),
                                content_type='application/x-sqlite3')
        self.c.post('/settings/restore/', {'step': 'upload', 'backup': up})
        # Wrong confirmation text -> nothing happens, still on the page.
        r = self.c.post('/settings/restore/',
                        {'step': 'confirm', 'confirm_text': 'yes please'})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Type RESTORE')

    def test_confirm_without_upload_redirects(self):
        r = self.c.post('/settings/restore/',
                        {'step': 'confirm', 'confirm_text': 'RESTORE'})
        self.assertEqual(r.status_code, 302)

    def test_non_admin_cannot_restore(self):
        c = Client(); c.login(username='finance1', password=PASSWORD)
        r = c.get('/settings/restore/')
        self.assertIn(r.status_code, (302, 403))
