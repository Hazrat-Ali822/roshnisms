"""P2 — finance void / refund of a recorded fee payment."""
from django.test import Client, TestCase

from core.models import FeeChallan, FeePayment
from core.tests.factory import build_world
from core.views import _make_challan


class VoidRefundTests(TestCase):
    def setUp(self):
        self.w = build_world()
        self.ch, _ = _make_challan(self.w.ayaan, 2026, 6)   # tuition 5000
        self.c = Client()
        self.c.force_login(self.w.finance_u)
        # Collect a full payment first.
        self.c.post('/fees/student/%d/' % self.w.ayaan.id, {
            'action': 'collect', 'challan_id': self.ch.id,
            'amount': '5000', 'mode': 'Cash'})
        self.payment = FeePayment.objects.get(student=self.w.ayaan)

    def test_challan_paid_after_collection(self):
        self.ch.refresh_from_db()
        self.assertEqual(self.ch.paid, 5000)
        self.assertEqual(self.ch.balance, 0)

    def test_void_reopens_balance_and_flags_payment(self):
        self.c.post('/fees/student/%d/' % self.w.ayaan.id, {
            'action': 'void_payment', 'payment_id': self.payment.id,
            'reason': 'Entered on wrong student'})
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, 'Voided')
        self.assertEqual(self.payment.reversal_reason, 'Entered on wrong student')
        self.assertTrue(self.payment.reversed_by)
        self.ch.refresh_from_db()
        self.assertEqual(self.ch.paid, 0)         # no longer counts
        self.assertEqual(self.ch.balance, 5000)   # reopened
        self.w.ayaan.refresh_from_db()
        self.assertNotEqual(self.w.ayaan.fee_status, 'Paid')

    def test_refund_reopens_balance(self):
        self.c.post('/fees/student/%d/' % self.w.ayaan.id, {
            'action': 'refund_payment', 'payment_id': self.payment.id,
            'reason': 'Parent withdrew admission'})
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, 'Refunded')
        self.ch.refresh_from_db()
        self.assertEqual(self.ch.balance, 5000)

    def test_cannot_double_reverse(self):
        # Void once...
        self.c.post('/fees/student/%d/' % self.w.ayaan.id, {
            'action': 'void_payment', 'payment_id': self.payment.id,
            'reason': 'first'})
        # ...a second refund attempt must not change it.
        self.c.post('/fees/student/%d/' % self.w.ayaan.id, {
            'action': 'refund_payment', 'payment_id': self.payment.id,
            'reason': 'second'})
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, 'Voided')
        self.assertEqual(self.payment.reversal_reason, 'first')

    def test_income_excludes_reversed(self):
        # Owner finance monthly income should drop after a void.
        owner = Client(); owner.force_login(self.w.owner_u)
        # NOTE: payment.date defaults to today; the collection above used today.
        before = owner.get('/owner/finance/').context['collected_month']
        self.assertGreaterEqual(before, 5000)
        self.c.post('/fees/student/%d/' % self.w.ayaan.id, {
            'action': 'void_payment', 'payment_id': self.payment.id,
            'reason': 'x'})
        after = owner.get('/owner/finance/').context['collected_month']
        self.assertEqual(after, before - 5000)
