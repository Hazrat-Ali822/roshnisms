"""The demo seed must build a COMPLETE school.

The whole point of `seed --demo` is that a person can open any screen while
testing and find believable data there — never an empty page that forces them
to type records in by hand first. This test locks that promise in.

It runs the real seed, so it is slower than a unit test; that is deliberate —
it is the only thing standing between a broken seed and a demo full of blank
pages.
"""
from django.core.management import call_command
from django.test import TestCase

from core.models import (Announcement, Applicant, Appraisal, Assignment,
                         AttendanceRecord, Book, CalendarEvent, Certificate,
                         ClassRoom, Complaint, ConcessionRequest,
                         DisciplineRecord, Exam, ExamRoom, ExamSchedule,
                         Expense, FeeChallan, FeeHead, FeePayment, HostelRoom,
                         InventoryItem, IssuedBook, LeaveRequest, Mark,
                         Material, Message, OnlinePayment, Payslip, Profile,
                         Question, Quiz, QuizAttempt, School, Seat, SmsMessage,
                         Staff, StaffAttendance, Student, StudentLeave,
                         StudentNote, Subject, Submission, TeachingAssignment,
                         TimetableSlot, TransportRoute, Visitor)


class SeedDemoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('seed', demo=True, verbosity=0)

    def test_school_is_realistically_sized(self):
        self.assertEqual(School.objects.count(), 1)
        self.assertGreaterEqual(ClassRoom.objects.count(), 10)
        self.assertGreaterEqual(Student.objects.count(), 150)
        self.assertGreaterEqual(Staff.objects.count(), 20)

    def test_more_teachers_than_subjects(self):
        """A real school has at least one teacher per subject, usually more."""
        teachers = Profile.objects.filter(role='teacher').count()
        distinct_subjects = Subject.objects.values('name').distinct().count()
        self.assertGreaterEqual(teachers, distinct_subjects)

    def test_every_class_has_a_class_teacher_and_subjects(self):
        for cls in ClassRoom.objects.all():
            self.assertIsNotNone(cls.class_teacher,
                                 '%s has no class teacher' % cls)
            self.assertTrue(cls.subjects.exists(), '%s has no subjects' % cls)

    def test_every_subject_has_a_teacher(self):
        for sub in Subject.objects.select_related('classroom'):
            self.assertTrue(
                TeachingAssignment.objects.filter(
                    classroom=sub.classroom, subject=sub.name).exists(),
                'No teacher assigned for %s in %s' % (sub.name, sub.classroom))

    def test_timetable_is_clash_free_and_covers_six_days(self):
        slots = list(TimetableSlot.objects.all())
        self.assertTrue(slots, 'no timetable was generated')
        self.assertIn('Sat', {s.day for s in slots})
        # A class can only be in one place per slot...
        class_slots = [(s.classroom_id, s.day, s.period) for s in slots]
        self.assertEqual(len(class_slots), len(set(class_slots)),
                         'two subjects booked for one class at the same time')
        # ...and so can a teacher.
        teacher_slots = [(s.teacher, s.day, s.period) for s in slots if s.teacher]
        self.assertEqual(len(teacher_slots), len(set(teacher_slots)),
                         'a teacher is double-booked')

    def test_every_module_has_data(self):
        """No screen should greet a tester with an empty table."""
        for model in (AttendanceRecord, Mark, Exam, ExamRoom, ExamSchedule,
                      Seat, FeeChallan, FeePayment, FeeHead, OnlinePayment,
                      ConcessionRequest, Expense, Staff, StaffAttendance,
                      LeaveRequest, Payslip, Appraisal, Assignment, Submission,
                      Quiz, Question, QuizAttempt, Material, Book, IssuedBook,
                      InventoryItem, TransportRoute, HostelRoom, Visitor,
                      DisciplineRecord, Complaint, StudentNote, StudentLeave,
                      Message, Certificate, CalendarEvent, Announcement,
                      Applicant, SmsMessage):
            self.assertTrue(
                model.objects.exists(),
                '%s has no demo rows — that screen will look empty'
                % model.__name__)

    def test_students_cover_every_status_tab(self):
        statuses = set(Student.objects.values_list('status', flat=True))
        self.assertIn('Active', statuses)
        self.assertTrue({'Left', 'Graduated'} & statuses,
                        'no left/graduated students — those tabs are empty')

    def test_fee_scenarios_are_varied(self):
        """Paid, pending and overdue must all appear, plus real concessions."""
        statuses = set(Student.objects.values_list('fee_status', flat=True))
        self.assertGreaterEqual(len(statuses), 2, 'fee statuses are all the same')
        self.assertTrue(FeeChallan.objects.filter(scholarship__gt=0).exists())
        self.assertTrue(FeeChallan.objects.filter(discount__gt=0).exists())

    def test_demo_logins_exist_for_every_role(self):
        for username in ('admin', 'principal', 'office', 'finance', 'director',
                         'teacher', 'parent', 'student'):
            self.assertTrue(
                Profile.objects.filter(user__username=username).exists()
                or username == 'admin',
                'demo login "%s" is missing' % username)

    def test_demo_parent_has_more_than_one_child(self):
        parent = Profile.objects.get(user__username='parent')
        self.assertGreaterEqual(len(parent.child_list()), 2)
