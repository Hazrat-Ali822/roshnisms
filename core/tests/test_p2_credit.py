"""P2 — advance / credit balance (deferred revenue)."""
from django.test import Client, TestCase

from core.models import FeePayment, Student
from core.tests.factory import build_world
from core.views import _make_challan


class CreditBalanceTests(TestCase):
    def setUp(self):
        self.w = build_world()
        self.c = Client(); self.c.force_login(self.w.finance_u)

    def _url(self):
        return '/fees/student/%d/' % self.w.ayaan.id

    def test_add_advance_holds_credit_not_income(self):
        self.c.post(self._url(), {'action': 'add_advance', 'amount': '3000'})
        s = Student.objects.get(pk=self.w.ayaan.pk)
        self.assertEqual(s.credit_balance, 3000)
        # An advance is NOT yet income — no FeePayment recorded.
        self.assertFalse(FeePayment.objects.filter(student=s).exists())

    def test_apply_credit_settles_challan_and_records_income(self):
        self.c.post(self._url(), {'action': 'add_advance', 'amount': '3000'})
        ch, _ = _make_challan(self.w.ayaan, 2026, 6)     # 5000 due
        self.c.post(self._url(), {'action': 'apply_credit', 'challan_id': ch.id})
        ch.refresh_from_db()
        self.assertEqual(ch.paid, 3000)                  # credit applied
        self.assertEqual(ch.balance, 2000)
        s = Student.objects.get(pk=self.w.ayaan.pk)
        self.assertEqual(s.credit_balance, 0)            # drawn down
        # Now it IS income, via a Credit-mode payment.
        p = FeePayment.objects.get(student=s)
        self.assertEqual(p.mode, 'Credit')
        self.assertEqual(p.amount, 3000)

    def test_apply_credit_capped_at_balance(self):
        self.c.post(self._url(), {'action': 'add_advance', 'amount': '9000'})
        ch, _ = _make_challan(self.w.ayaan, 2026, 6)     # 5000 due
        self.c.post(self._url(), {'action': 'apply_credit', 'challan_id': ch.id})
        ch.refresh_from_db()
        self.assertEqual(ch.balance, 0)                  # fully paid
        s = Student.objects.get(pk=self.w.ayaan.pk)
        self.assertEqual(s.credit_balance, 4000)         # 9000 - 5000 left

    def test_apply_credit_with_none_available(self):
        ch, _ = _make_challan(self.w.ayaan, 2026, 6)
        self.c.post(self._url(), {'action': 'apply_credit', 'challan_id': ch.id})
        ch.refresh_from_db()
        self.assertEqual(ch.paid, 0)                     # nothing applied
