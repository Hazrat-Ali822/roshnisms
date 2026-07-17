"""P2 — real gradebook: per-subject max marks + marks lock/moderation."""
from django.test import Client, TestCase

from core.models import GradeConfig, Mark
from core.tests.factory import build_world, PASSWORD


class GradebookTests(TestCase):
    def setUp(self):
        self.w = build_world()

    def _teacher(self):
        c = Client(); c.login(username='teacher1', password=PASSWORD)
        return c

    def _q(self):
        return 'class=%d&subject=%d&exam=%d' % (
            self.w.c9.id, self.w.math9.id, self.w.exam.id)

    def _set_max(self, client, mx):
        client.post('/marks/', {
            'action': 'set_max', 'class': self.w.c9.id,
            'subject': self.w.math9.id, 'exam': self.w.exam.id, 'max_marks': mx})

    def test_set_max_marks_used_on_save(self):
        c = self._teacher()
        self._set_max(c, 75)
        cfg = GradeConfig.objects.get(exam=self.w.exam, classroom=self.w.c9,
                                      subject='Mathematics')
        self.assertEqual(cfg.max_marks, 75)
        # Save marks; total_marks should follow the configured max.
        c.post('/marks/', {
            'action': 'save_marks', 'class': self.w.c9.id,
            'subject': self.w.math9.id, 'exam': self.w.exam.id,
            'known_sig': '', 'marks_%d' % self.w.ayaan.id: '60'})
        m = Mark.objects.get(student=self.w.ayaan, subject=self.w.math9)
        self.assertEqual(m.total_marks, 75)
        self.assertEqual(m.marks_obtained, 60)
        self.assertEqual(m.percentage, 80)     # 60/75

    def test_marks_clamped_to_max(self):
        c = self._teacher()
        self._set_max(c, 50)
        c.post('/marks/', {
            'action': 'save_marks', 'class': self.w.c9.id,
            'subject': self.w.math9.id, 'exam': self.w.exam.id,
            'known_sig': '', 'marks_%d' % self.w.ayaan.id: '999'})
        m = Mark.objects.get(student=self.w.ayaan, subject=self.w.math9)
        self.assertEqual(m.marks_obtained, 50)    # clamped

    def test_lock_blocks_further_edits(self):
        c = self._teacher()
        c.post('/marks/', {
            'action': 'save_marks', 'class': self.w.c9.id,
            'subject': self.w.math9.id, 'exam': self.w.exam.id,
            'known_sig': '', 'marks_%d' % self.w.ayaan.id: '40'})
        # Lock.
        c.post('/marks/', {'action': 'lock', 'class': self.w.c9.id,
                           'subject': self.w.math9.id, 'exam': self.w.exam.id})
        self.assertTrue(GradeConfig.objects.get(
            exam=self.w.exam, classroom=self.w.c9, subject='Mathematics').locked)
        # Attempt to change a mark -> ignored.
        c.post('/marks/', {
            'action': 'save_marks', 'class': self.w.c9.id,
            'subject': self.w.math9.id, 'exam': self.w.exam.id,
            'known_sig': '', 'marks_%d' % self.w.ayaan.id: '99'})
        m = Mark.objects.get(student=self.w.ayaan, subject=self.w.math9)
        self.assertEqual(m.marks_obtained, 40)    # unchanged

    def test_teacher_cannot_unlock_only_office(self):
        c = self._teacher()
        GradeConfig.objects.create(exam=self.w.exam, classroom=self.w.c9,
                                   subject='Mathematics', locked=True)
        c.post('/marks/', {'action': 'unlock', 'class': self.w.c9.id,
                           'subject': self.w.math9.id, 'exam': self.w.exam.id})
        self.assertTrue(GradeConfig.objects.get(
            exam=self.w.exam, classroom=self.w.c9, subject='Mathematics').locked)
        # Admin can unlock.
        a = Client(); a.force_login(self.w.admin_u)
        a.post('/marks/', {'action': 'unlock', 'class': self.w.c9.id,
                           'subject': self.w.math9.id, 'exam': self.w.exam.id})
        self.assertFalse(GradeConfig.objects.get(
            exam=self.w.exam, classroom=self.w.c9, subject='Mathematics').locked)
