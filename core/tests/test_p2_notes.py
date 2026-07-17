"""P2 — teacher behaviour/remark notes (teacher writes, parent/student sees)."""
from django.test import Client, TestCase

from core.models import StudentNote
from core.tests.factory import build_world, PASSWORD


class TeacherNotesTests(TestCase):
    def setUp(self):
        self.w = build_world()

    def _teacher(self):
        c = Client(); c.login(username='teacher1', password=PASSWORD)
        return c

    def test_teacher_can_add_note_for_own_class(self):
        # teacher1 teaches 9-A; Ayaan is in 9-A.
        self._teacher().post('/teacher/notes/', {
            'action': 'add', 'class': self.w.c9.id, 'student': self.w.ayaan.id,
            'kind': 'Praise', 'text': 'Excellent work today'})
        n = StudentNote.objects.filter(student=self.w.ayaan).first()
        self.assertIsNotNone(n)
        self.assertEqual(n.kind, 'Praise')
        self.assertEqual(n.teacher, self.w.teacher_p)

    def test_cannot_note_student_outside_class(self):
        # Inaya is in 10-A, which teacher1 does not teach.
        self._teacher().post('/teacher/notes/', {
            'action': 'add', 'class': self.w.c9.id, 'student': self.w.inaya.id,
            'kind': 'Note', 'text': 'x'})
        self.assertFalse(StudentNote.objects.filter(student=self.w.inaya).exists())

    def test_empty_text_rejected(self):
        self._teacher().post('/teacher/notes/', {
            'action': 'add', 'class': self.w.c9.id, 'student': self.w.ayaan.id,
            'kind': 'Note', 'text': '   '})
        self.assertFalse(StudentNote.objects.exists())

    def test_teacher_can_delete_only_own_note(self):
        mine = StudentNote.objects.create(
            student=self.w.ayaan, text='mine', teacher=self.w.teacher_p)
        other = StudentNote.objects.create(
            student=self.w.ayaan, text='other', teacher=self.w.principal_p)
        self._teacher().post('/teacher/notes/', {
            'action': 'delete', 'class': self.w.c9.id, 'note_id': mine.id})
        self.assertFalse(StudentNote.objects.filter(id=mine.id).exists())
        # Cannot delete a colleague's note.
        self._teacher().post('/teacher/notes/', {
            'action': 'delete', 'class': self.w.c9.id, 'note_id': other.id})
        self.assertTrue(StudentNote.objects.filter(id=other.id).exists())

    def test_parent_sees_note_on_profile(self):
        StudentNote.objects.create(
            student=self.w.ayaan, kind='Concern', text='Missed homework',
            teacher=self.w.teacher_p, teacher_name='Teacher1')
        c = Client(); c.login(username='parent1', password=PASSWORD)
        r = c.get('/my-profile/')
        self.assertContains(r, 'Missed homework')

    def test_parent_cannot_hit_teacher_notes(self):
        c = Client(); c.login(username='parent1', password=PASSWORD)
        r = c.get('/teacher/notes/')
        self.assertNotEqual(r.status_code, 200)
