"""Shared test data builder — a small, predictable "world" for every test.

Ayaan (9-A) and Inaya (10-A) share one guardian (parent1) to exercise the
multi-child parent feature. teacher1 teaches only Mathematics in 9-A.
"""
from django.contrib.auth.models import User

from core.models import (ClassRoom, Exam, Profile, School, Student, Subject,
                         TeachingAssignment)

PASSWORD = 'testpass123'


def make_user(username, role, children=None, **extra):
    user = User.objects.create_user(
        username=username, password=PASSWORD, first_name=username.title())
    profile = Profile.objects.create(user=user, role=role, **extra)
    if children:
        profile.children.set(children)
    return user, profile


class World:
    """Simple attribute bag holding references to the created objects."""


def build_world():
    w = World()
    w.school = School.objects.create(name='Test School', pass_mark=40,
                                     session='2025-26')

    w.c9 = ClassRoom.objects.create(name='9', section='A', monthly_fee=5000)
    w.c10 = ClassRoom.objects.create(name='10', section='A', monthly_fee=5000)

    w.math9 = Subject.objects.create(name='Mathematics', classroom=w.c9)
    w.eng9 = Subject.objects.create(name='English', classroom=w.c9)

    w.exam = Exam.objects.create(name='Mid-Term', session='2025-26')
    w.exam2 = Exam.objects.create(name='Final', session='2025-26')

    w.ayaan = Student.objects.create(
        name='Ayaan', classroom=w.c9, roll_no='1', guardian_name='Imran',
        guardian_phone='0300-1111111', status='Active')
    w.hira = Student.objects.create(
        name='Hira', classroom=w.c9, roll_no='2', guardian_name='Aslam',
        guardian_phone='0300-2222222', status='Active')
    w.inaya = Student.objects.create(
        name='Inaya', classroom=w.c10, roll_no='1', guardian_name='Imran',
        guardian_phone='0300-1111111', status='Active')

    w.admin_u, w.admin_p = make_user('admin1', 'admin')
    w.teacher_u, w.teacher_p = make_user('teacher1', 'teacher', classroom=w.c9)
    TeachingAssignment.objects.create(
        teacher=w.teacher_p, classroom=w.c9, subject='Mathematics')
    w.finance_u, w.finance_p = make_user('finance1', 'finance')
    w.principal_u, w.principal_p = make_user('principal1', 'principal')
    w.owner_u, w.owner_p = make_user('owner1', 'owner')
    # Parent of TWO children (Ayaan + Inaya); primary = Ayaan
    w.parent_u, w.parent_p = make_user(
        'parent1', 'parent', student=w.ayaan, children=[w.ayaan, w.inaya])
    # Student account = Ayaan
    w.student_u, w.student_p = make_user('student1', 'student', student=w.ayaan)
    return w
