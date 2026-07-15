from django.core.management import call_command
from django.test import Client, TestCase

from core.models import FeeChallan, FeePayment
from core.tests.factory import build_world
from core.views import _make_challan


class FeeTests(TestCase):
    def setUp(self):
        self.w = build_world()
        self.c = Client()

    def test_challan_generation_idempotent(self):
        ch1, made1 = _make_challan(self.w.ayaan, 2026, 6)
        ch2, made2 = _make_challan(self.w.ayaan, 2026, 6)
        self.assertTrue(made1)
        self.assertFalse(made2)          # second call must not duplicate
        self.assertEqual(ch1.id, ch2.id)
        self.assertEqual(ch1.tuition, 5000)

    def test_finance_collects_payment(self):
        ch, _ = _make_challan(self.w.ayaan, 2026, 6)
        self.c.force_login(self.w.finance_u)
        r = self.c.post('/fees/student/%d/' % self.w.ayaan.id, {
            'action': 'collect', 'challan_id': ch.id,
            'amount': '5000', 'mode': 'Cash'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(FeePayment.objects.filter(student=self.w.ayaan).count(), 1)
        ch.refresh_from_db()
        self.assertEqual(ch.balance, 0)
        self.w.ayaan.refresh_from_db()
        self.assertEqual(self.w.ayaan.fee_status, 'Paid')

    def test_daily_job_marks_overdue_and_late_fee(self):
        """fees_daily: overdue status + auto late fee once due date passes."""
        _make_challan(self.w.ayaan, 2020, 1)         # due 2020-01-10 (past)
        self.w.school.late_fee_amount = 100
        self.w.school.save()
        call_command('fees_daily')
        self.w.ayaan.refresh_from_db()
        self.assertEqual(self.w.ayaan.fee_status, 'Overdue')
        ch = FeeChallan.objects.get(student=self.w.ayaan, year=2020, month=1)
        self.assertEqual(ch.late_fee, 100)

    def test_defaulters_list_shows_unpaid(self):
        _make_challan(self.w.ayaan, 2020, 1)         # unpaid, overdue
        self.c.force_login(self.w.finance_u)
        html = self.c.get('/fees/defaulters/').content.decode()
        self.assertIn('Ayaan', html)

    def test_generate_command_creates_current_month(self):
        call_command('fees_generate', '--month', '6', '--year', '2026')
        self.assertTrue(FeeChallan.objects.filter(
            student=self.w.ayaan, year=2026, month=6).exists())
