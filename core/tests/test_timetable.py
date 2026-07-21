"""Auto timetable generator (clash-free) + class-teacher selection."""
from django.test import Client, TestCase
from django.urls import reverse

from core.models import (ClassRoom, Subject, TeachingAssignment, TimetableSlot)
from core.tests.factory import build_world, PASSWORD


class TimetableGeneratorTests(TestCase):
    def setUp(self):
        self.w = build_world()
        self.c = Client()
        self.c.login(username='admin1', password=PASSWORD)
        # Give every subject a small, feasible weekly load.
        Subject.objects.all().update(periods_per_week=3)
        # Make teacher1 ALSO teach a subject in class 10 so we can prove the
        # generator never double-books one teacher across two classes.
        Subject.objects.create(name='Mathematics', classroom=self.w.c10,
                               periods_per_week=3)
        TeachingAssignment.objects.create(
            teacher=self.w.teacher_p, classroom=self.w.c10, subject='Mathematics')

    def _generate(self):
        return self.c.post(reverse('timetable_manage'),
                           {'action': 'generate', 'class_id': self.w.c9.id})

    def test_generates_slots(self):
        self._generate()
        self.assertTrue(TimetableSlot.objects.exists())

    def test_no_class_or_teacher_clash(self):
        self._generate()
        class_seen, teacher_seen = set(), set()
        for s in TimetableSlot.objects.all():
            ckey = (s.classroom_id, s.day, s.period)
            self.assertNotIn(ckey, class_seen, 'two subjects in one class slot')
            class_seen.add(ckey)
            if s.teacher:
                tkey = (s.teacher, s.day, s.period)
                self.assertNotIn(tkey, teacher_seen,
                                 'teacher %s double-booked' % s.teacher)
                teacher_seen.add(tkey)

    def test_respects_periods_per_week(self):
        Subject.objects.filter(classroom=self.w.c9, name='Mathematics').update(
            periods_per_week=4)
        self._generate()
        n = TimetableSlot.objects.filter(
            classroom=self.w.c9, subject='Mathematics').count()
        self.assertEqual(n, 4)

    def test_teacher_name_filled_from_assignment(self):
        self._generate()
        math = TimetableSlot.objects.filter(
            classroom=self.w.c9, subject='Mathematics').first()
        self.assertTrue(math.teacher)   # teacher1's name was placed

    def test_save_periods(self):
        self.c.post(reverse('timetable_manage'), {
            'action': 'save_periods', 'class_id': self.w.c9.id,
            'ppw_%d' % self.w.math9.id: '6'})
        self.w.math9.refresh_from_db()
        self.assertEqual(self.w.math9.periods_per_week, 6)

    def test_save_structure(self):
        self.c.post(reverse('timetable_manage'), {
            'action': 'save_structure', 'class_id': self.w.c9.id,
            'tt_day': ['Mon', 'Tue', 'Wed'], 'tt_periods_per_day': '6',
            'tt_break_period': '4'})
        self.w.school.refresh_from_db()
        self.assertEqual(self.w.school.tt_days, 'Mon,Tue,Wed')
        self.assertEqual(self.w.school.tt_periods_per_day, 6)
        self.assertEqual(self.w.school.tt_break_period, 4)

    def test_break_period_left_empty(self):
        self.w.school.tt_break_period = 4
        self.w.school.save()
        self._generate()
        self.assertFalse(
            TimetableSlot.objects.filter(period=4).exists())   # no lessons at break


class ClassTeacherTests(TestCase):
    def setUp(self):
        self.w = build_world()
        self.c = Client()
        self.c.login(username='admin1', password=PASSWORD)

    def test_set_class_teacher(self):
        self.c.post(reverse('classes_manage'), {
            'action': 'set_class_teacher', 'class_id': self.w.c9.id,
            'teacher_id': self.w.teacher_p.id})
        self.w.c9.refresh_from_db()
        self.assertEqual(self.w.c9.class_teacher_id, self.w.teacher_p.id)

    def test_clear_class_teacher(self):
        self.w.c9.class_teacher = self.w.teacher_p
        self.w.c9.save()
        self.c.post(reverse('classes_manage'), {
            'action': 'set_class_teacher', 'class_id': self.w.c9.id,
            'teacher_id': ''})
        self.w.c9.refresh_from_db()
        self.assertIsNone(self.w.c9.class_teacher_id)


class SubjectTeacherTests(TestCase):
    def setUp(self):
        self.w = build_world()
        self.c = Client()
        self.c.login(username='admin1', password=PASSWORD)
        # A second teacher to reassign to.
        from django.contrib.auth.models import User
        from core.models import Profile
        u = User.objects.create_user('teacher2', password=PASSWORD,
                                     first_name='Sana')
        self.t2 = Profile.objects.create(user=u, role='teacher')

    def test_assign_subject_teacher(self):
        # English in 9-A has no teacher in the factory; assign one.
        self.c.post(reverse('classes_manage'), {
            'action': 'assign_subject_teacher', 'class_id': self.w.c9.id,
            'subject_name': 'English', 'teacher_id': self.t2.id})
        self.assertTrue(TeachingAssignment.objects.filter(
            classroom=self.w.c9, subject='English', teacher=self.t2).exists())

    def test_reassign_replaces_teacher(self):
        for tid in (self.w.teacher_p.id, self.t2.id):
            self.c.post(reverse('classes_manage'), {
                'action': 'assign_subject_teacher', 'class_id': self.w.c9.id,
                'subject_name': 'English', 'teacher_id': tid})
        qs = TeachingAssignment.objects.filter(classroom=self.w.c9, subject='English')
        self.assertEqual(qs.count(), 1)                 # not duplicated
        self.assertEqual(qs.first().teacher_id, self.t2.id)

    def test_clear_subject_teacher(self):
        TeachingAssignment.objects.create(
            teacher=self.t2, classroom=self.w.c9, subject='English')
        self.c.post(reverse('classes_manage'), {
            'action': 'assign_subject_teacher', 'class_id': self.w.c9.id,
            'subject_name': 'English', 'teacher_id': ''})
        self.assertFalse(TeachingAssignment.objects.filter(
            classroom=self.w.c9, subject='English').exists())

    def test_rename_subject_keeps_teacher(self):
        self.c.post(reverse('classes_manage'), {
            'action': 'edit_subject', 'subject_id': self.w.math9.id,
            'subject': 'Maths'})
        # the factory's Mathematics teacher assignment follows the rename
        self.assertTrue(TeachingAssignment.objects.filter(
            classroom=self.w.c9, subject='Maths').exists())
        self.assertFalse(TeachingAssignment.objects.filter(
            classroom=self.w.c9, subject='Mathematics').exists())

    def test_new_school_defaults_to_six_days(self):
        from core.models import School
        s = School.objects.create(name='Fresh School')
        self.assertIn('Sat', s.tt_days)
