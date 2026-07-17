"""Regression tests for the P0 critical-bug fixes (July 2026 audit)."""
from django.test import Client, TestCase

from core.models import FeeChallan, FeePayment, Mark, OnlinePayment, Student
from core.tests.factory import build_world, PASSWORD
from core.views import _next_admission_no


class MarksIdorTests(TestCase):
    """A teacher must not be able to enter marks for a subject they don't teach."""

    def setUp(self):
        self.w = build_world()
        self.c = Client()
        self.c.login(username='teacher1', password=PASSWORD)

    def test_teacher_cannot_mark_untaught_subject(self):
        # teacher1 teaches Mathematics (math9) in 9-A, NOT English (eng9).
        self.c.post('/marks/', {
            'class': self.w.c9.id, 'subject': self.w.eng9.id,
            'exam': self.w.exam.id, 'known_sig': '',
            'marks_%d' % self.w.ayaan.id: '90'})
        self.assertEqual(
            Mark.objects.filter(subject=self.w.eng9).count(), 0,
            "teacher wrote marks for a subject they do not teach (IDOR)")

    def test_teacher_can_mark_own_subject(self):
        self.c.post('/marks/', {
            'class': self.w.c9.id, 'subject': self.w.math9.id,
            'exam': self.w.exam.id, 'known_sig': '',
            'marks_%d' % self.w.ayaan.id: '90'})
        m = Mark.objects.get(student=self.w.ayaan, subject=self.w.math9,
                             exam=self.w.exam)
        self.assertEqual(m.marks_obtained, 90)


class AdmissionNumberTests(TestCase):
    def setUp(self):
        self.w = build_world()

    def test_next_admission_no_uses_max_not_count(self):
        """After a deletion, the next number must not repeat an existing one."""
        year = __import__('datetime').date.today().year
        Student.objects.create(name='X', admission_no='RPS-%d-0009' % year,
                               status='Active')
        # count() is small, but max is 9 -> next must be 10, never a repeat.
        self.assertEqual(_next_admission_no(), 'RPS-%d-0010' % year)

    def test_no_duplicate_after_delete(self):
        year = __import__('datetime').date.today().year
        a = _next_admission_no()
        Student.objects.create(name='A', admission_no=a, status='Active')
        b = _next_admission_no()
        self.assertNotEqual(a, b)


class DestructiveActionGateTests(TestCase):
    """load_demo / reset_blank must be superuser-only, never a plain admin."""

    def setUp(self):
        self.w = build_world()
        self.c = Client()
        self.c.login(username='admin1', password=PASSWORD)  # admin, NOT superuser

    def test_non_superuser_admin_cannot_wipe(self):
        before = Student.objects.count()
        resp = self.c.post('/settings/', {'data_action': 'reset_blank'})
        self.assertEqual(resp.status_code, 302)
        # Data must be untouched — the destructive action was refused.
        self.assertEqual(Student.objects.count(), before)


class OnlinePaymentCapTests(TestCase):
    """Approving/recording an online payment must not overpay a challan."""

    def setUp(self):
        self.w = build_world()
        self.challan = FeeChallan.objects.create(
            student=self.w.ayaan, year=2026, month=6, tuition=5000)
        self.intent = OnlinePayment.objects.create(
            student=self.w.ayaan, challan=self.challan, gateway='bank',
            amount=9000, status='pending', ref='PAY-00001')

    def test_approve_caps_to_balance(self):
        c = Client()
        c.login(username='finance1', password=PASSWORD)
        c.post('/fees/online/', {'action': 'approve', 'intent_id': self.intent.id})
        pay = FeePayment.objects.filter(challan=self.challan).first()
        self.assertIsNotNone(pay)
        self.assertEqual(pay.amount, 5000, "online payment overpaid the challan")
