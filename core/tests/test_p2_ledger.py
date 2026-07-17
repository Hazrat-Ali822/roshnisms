"""P2 — finance income-vs-expense (P&L) ledger."""
from django.test import Client, TestCase
from django.utils import timezone

from core.models import Expense, FeePayment, Payslip, Staff
from core.tests.factory import build_world
from core.views import _make_challan


class LedgerTests(TestCase):
    def setUp(self):
        self.w = build_world()
        self.year = timezone.localdate().year
        self.c = Client()
        self.c.force_login(self.w.finance_u)
        # Income: collect Rs 5000.
        ch, _ = _make_challan(self.w.ayaan, self.year, 6)
        self.c.post('/fees/student/%d/' % self.w.ayaan.id, {
            'action': 'collect', 'challan_id': ch.id, 'amount': '5000', 'mode': 'Cash'})
        self.payment = FeePayment.objects.get(student=self.w.ayaan)
        # Expense: Rs 1200 utilities.
        Expense.objects.create(title='Electricity', category='Utilities',
                               amount=1200, date=timezone.localdate())
        # Payroll: one payslip, net = 40000.
        staff = Staff.objects.create(name='Teacher1', basic_salary=40000)
        Payslip.objects.create(staff=staff, year=self.year, month=6,
                               basic=40000, allowances=0, deductions=0)

    def test_ledger_totals(self):
        r = self.c.get('/fees/ledger/?year=%d' % self.year)
        self.assertEqual(r.status_code, 200)
        ctx = r.context
        self.assertEqual(ctx['total_income'], 5000)
        self.assertEqual(ctx['total_expense'], 1200 + 40000)   # expense + payroll
        self.assertEqual(ctx['net'], 5000 - 41200)             # deficit

    def test_payroll_in_breakdown(self):
        r = self.c.get('/fees/ledger/?year=%d' % self.year)
        cats = dict(r.context['cat_rows'])
        self.assertEqual(cats['Payroll (payslips)'], 40000)
        self.assertEqual(cats['Utilities'], 1200)

    def test_voided_payment_excluded(self):
        self.c.post('/fees/student/%d/' % self.w.ayaan.id, {
            'action': 'void_payment', 'payment_id': self.payment.id, 'reason': 'x'})
        r = self.c.get('/fees/ledger/?year=%d' % self.year)
        self.assertEqual(r.context['total_income'], 0)

    def test_other_year_empty(self):
        r = self.c.get('/fees/ledger/?year=%d' % (self.year - 1))
        self.assertEqual(r.context['total_income'], 0)
        self.assertEqual(r.context['total_expense'], 0)

    def test_teacher_cannot_access(self):
        c = Client(); c.force_login(self.w.teacher_u)
        r = c.get('/fees/ledger/')
        self.assertNotEqual(r.status_code, 200)
