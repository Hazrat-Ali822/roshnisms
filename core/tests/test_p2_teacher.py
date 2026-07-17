"""P2 — teachers can now EDIT and DELETE assignments, quizzes and questions
(previously create-only, so mistakes were permanent)."""
import datetime

from django.test import Client, TestCase

from core.models import Assignment, Question, Quiz
from core.tests.factory import build_world, PASSWORD


class TeacherEditDeleteTests(TestCase):
    def setUp(self):
        self.w = build_world()
        self.c = Client()
        self.c.login(username='teacher1', password=PASSWORD)
        self.assignment = Assignment.objects.create(
            classroom=self.w.c9, subject=self.w.math9, title='Old title',
            due_date=datetime.date(2026, 6, 10))
        self.quiz = Quiz.objects.create(
            classroom=self.w.c9, subject=self.w.math9, title='Old quiz', time_limit=10)
        self.q = Question.objects.create(
            quiz=self.quiz, text='2+2?', option_a='4', option_b='5', correct='A', order=1)

    def test_delete_assignment(self):
        self.c.post('/teacher/assignments/', {
            'action': 'delete', 'assignment_id': self.assignment.id,
            'class': self.w.c9.id})
        self.assertFalse(Assignment.objects.filter(pk=self.assignment.id).exists())

    def test_edit_assignment(self):
        self.c.post('/teacher/assignments/?id=%d&class=%d'
                    % (self.assignment.id, self.w.c9.id), {
                        'action': 'edit', 'class': self.w.c9.id,
                        'title': 'New title', 'subject': self.w.math9.id,
                        'due_date': '2026-07-01', 'description': 'do it'})
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.title, 'New title')

    def test_delete_quiz(self):
        self.c.post('/teacher/quizzes/', {
            'action': 'delete', 'quiz_id': self.quiz.id, 'class': self.w.c9.id})
        self.assertFalse(Quiz.objects.filter(pk=self.quiz.id).exists())

    def test_delete_question(self):
        self.c.post('/teacher/quizzes/?id=%d&class=%d' % (self.quiz.id, self.w.c9.id),
                    {'action': 'del_q', 'question_id': self.q.id})
        self.assertFalse(Question.objects.filter(pk=self.q.id).exists())

    def test_edit_quiz(self):
        self.c.post('/teacher/quizzes/?id=%d&class=%d' % (self.quiz.id, self.w.c9.id),
                    {'action': 'edit', 'class': self.w.c9.id,
                     'title': 'Renamed quiz', 'time_limit': '15'})
        self.quiz.refresh_from_db()
        self.assertEqual(self.quiz.title, 'Renamed quiz')

    def test_cannot_delete_other_class_assignment(self):
        """A teacher must not delete an assignment in a class they don't teach."""
        other = Assignment.objects.create(
            classroom=self.w.c10, title='Other', due_date=datetime.date(2026, 6, 10))
        self.c.post('/teacher/assignments/', {
            'action': 'delete', 'assignment_id': other.id, 'class': self.w.c10.id})
        self.assertTrue(Assignment.objects.filter(pk=other.id).exists())
