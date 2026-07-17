"""P2 — parent <-> teacher messaging (per-student thread)."""
from django.test import Client, TestCase

from core.models import Message
from core.tests.factory import build_world, PASSWORD


class MessagingTests(TestCase):
    def setUp(self):
        self.w = build_world()

    def _parent(self):
        c = Client(); c.login(username='parent1', password=PASSWORD)
        return c

    def _teacher(self):
        c = Client(); c.login(username='teacher1', password=PASSWORD)
        return c

    def test_parent_sends_message(self):
        self._parent().post('/messages/', {'body': 'Is Ayaan doing okay?'})
        m = Message.objects.filter(student=self.w.ayaan).first()
        self.assertIsNotNone(m)
        self.assertEqual(m.sender_role, 'parent')
        self.assertTrue(m.seen_by_family)
        self.assertFalse(m.seen_by_staff)      # teacher hasn't read yet

    def test_teacher_sees_and_replies(self):
        self._parent().post('/messages/', {'body': 'Question about homework'})
        # teacher1 teaches 9-A where Ayaan studies -> can open + reply.
        tc = self._teacher()
        r = tc.get('/teacher/messages/?student=%d' % self.w.ayaan.id)
        self.assertEqual(r.status_code, 200)
        # Opening the thread marks the parent's message seen by staff.
        self.assertTrue(Message.objects.get(student=self.w.ayaan).seen_by_staff)
        tc.post('/teacher/messages/', {'student': self.w.ayaan.id, 'body': 'All good!'})
        reply = Message.objects.filter(student=self.w.ayaan, sender_role='teacher').first()
        self.assertIsNotNone(reply)
        self.assertFalse(reply.seen_by_family)   # parent hasn't read the reply

    def test_teacher_cannot_message_student_outside_class(self):
        # Inaya is in 10-A, not taught by teacher1.
        self._teacher().post('/teacher/messages/', {
            'student': self.w.inaya.id, 'body': 'hi'})
        self.assertFalse(Message.objects.filter(student=self.w.inaya).exists())

    def test_parent_badge_counts_unread_reply(self):
        # Teacher posts a message -> unread for family.
        Message.objects.create(student=self.w.ayaan, sender=self.w.teacher_p,
                               sender_role='teacher', sender_name='Teacher1',
                               body='Please meet me', seen_by_staff=True,
                               seen_by_family=False)
        c = self._parent()
        r = c.get('/dashboard/') if False else c.get('/')
        self.assertEqual(r.context['badge_counts'].get('parent_messages'), 1)
        # Opening the thread clears it.
        c.get('/messages/')
        r2 = c.get('/')
        self.assertIsNone(r2.context['badge_counts'].get('parent_messages'))

    def test_teacher_badge_counts_unread(self):
        self._parent().post('/messages/', {'body': 'hello teacher'})
        r = self._teacher().get('/')
        self.assertEqual(r.context['badge_counts'].get('teacher_messages'), 1)

    def test_opening_thread_marks_family_read(self):
        Message.objects.create(student=self.w.ayaan, sender=self.w.teacher_p,
                               sender_role='teacher', sender_name='Teacher1',
                               body='hi', seen_by_staff=True, seen_by_family=False)
        self._parent().get('/messages/')
        self.assertTrue(Message.objects.get(student=self.w.ayaan).seen_by_family)
