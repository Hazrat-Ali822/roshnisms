"""Section 7 — multi-user safety. Two accountants must never double-collect the
same challan, and two teachers must not silently overwrite each other's marks."""
import datetime

from django.test import Client, TestCase

from core.models import (Exam, FeeChallan, FeePayment, Mark, Student, Subject)
from core.tests.factory import build_world, PASSWORD
from core.views import _marks_signature


class FeeConcurrencyTests(TestCase):
    def setUp(self):
        self.w = build_world()
        self.challan = FeeChallan.objects.create(
            student=self.w.ayaan, year=2026, month=6, tuition=5000,
            due_date=datetime.date(2026, 6, 10))

    def _finance(self):
        c = Client(); c.login(username='finance1', password=PASSWORD)
        return c

    def test_second_collection_with_stale_page_is_blocked(self):
        # Both accountants opened the page when paid == 0.
        a = self._finance()
        b = self._finance()
        # Accountant A collects the full balance.
        a.post('/fees/student/%d/' % self.w.ayaan.id, {
            'action': 'collect', 'challan_id': self.challan.id,
            'known_paid': '0', 'amount': '5000', 'mode': 'Cash'})
        self.assertEqual(FeePayment.objects.filter(challan=self.challan).count(), 1)
        # Accountant B submits the same stale page (known_paid still 0).
        b.post('/fees/student/%d/' % self.w.ayaan.id, {
            'action': 'collect', 'challan_id': self.challan.id,
            'known_paid': '0', 'amount': '5000', 'mode': 'Cash'})
        # No second payment recorded — double collection prevented.
        self.assertEqual(FeePayment.objects.filter(challan=self.challan).count(), 1)

    def test_overpayment_is_refused(self):
        c = self._finance()
        c.post('/fees/student/%d/' % self.w.ayaan.id, {
            'action': 'collect', 'challan_id': self.challan.id,
            'known_paid': '0', 'amount': '9000', 'mode': 'Cash'})
        self.assertFalse(FeePayment.objects.filter(challan=self.challan).exists())

    def test_partial_then_remainder_still_works(self):
        c = self._finance()
        c.post('/fees/student/%d/' % self.w.ayaan.id, {
            'action': 'collect', 'challan_id': self.challan.id,
            'known_paid': '0', 'amount': '2000', 'mode': 'Cash'})
        self.challan.refresh_from_db()
        # Second, legitimate payment uses the updated known_paid (2000).
        c.post('/fees/student/%d/' % self.w.ayaan.id, {
            'action': 'collect', 'challan_id': self.challan.id,
            'known_paid': '2000', 'amount': '3000', 'mode': 'Cash'})
        self.assertEqual(FeePayment.objects.filter(challan=self.challan).count(), 2)
        self.challan.refresh_from_db()
        self.assertEqual(self.challan.balance, 0)


class MarksConcurrencyTests(TestCase):
    def setUp(self):
        self.w = build_world()
        self.c = Client(); self.c.login(username='teacher1', password=PASSWORD)

    def _sig(self):
        students = list(Student.objects.filter(classroom=self.w.c9))
        return _marks_signature([s.id for s in students], self.w.math9, self.w.exam)

    def test_stale_marks_save_is_rejected(self):
        # Teacher opens the page: signature is empty (no marks yet).
        stale_sig = self._sig()
        # Meanwhile someone else saves a mark for Ayaan.
        Mark.objects.create(student=self.w.ayaan, subject=self.w.math9,
                            exam=self.w.exam, marks_obtained=80, total_marks=100)
        # The first teacher now submits with the stale signature.
        self.c.post('/marks/', {
            'class': self.w.c9.id, 'subject': self.w.math9.id,
            'exam': self.w.exam.id, 'known_sig': stale_sig,
            'marks_%d' % self.w.ayaan.id: '30'})
        # The other teacher's 80 must NOT be overwritten by the stale 30.
        m = Mark.objects.get(student=self.w.ayaan, subject=self.w.math9,
                             exam=self.w.exam)
        self.assertEqual(m.marks_obtained, 80)

    def test_fresh_marks_save_succeeds(self):
        sig = self._sig()   # current (empty) signature
        self.c.post('/marks/', {
            'class': self.w.c9.id, 'subject': self.w.math9.id,
            'exam': self.w.exam.id, 'known_sig': sig,
            'marks_%d' % self.w.ayaan.id: '75'})
        m = Mark.objects.get(student=self.w.ayaan, subject=self.w.math9,
                             exam=self.w.exam)
        self.assertEqual(m.marks_obtained, 75)
