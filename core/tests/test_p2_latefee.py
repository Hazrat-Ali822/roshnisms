"""P2 — escalating / slab late fees with a manual lock."""
import datetime

from django.core.management import call_command
from django.test import Client, TestCase

from core.models import FeeChallan
from core.tests.factory import build_world, PASSWORD
from core.views import _escalating_late_fee, _make_challan


class EscalatingLateFeeTests(TestCase):
    def setUp(self):
        self.w = build_world()
        self.today = datetime.date(2026, 3, 1)

    def _overdue_challan(self, due):
        ch, _ = _make_challan(self.w.ayaan, 2026, 1)
        ch.due_date = due
        ch.save(update_fields=['due_date'])
        return ch

    def test_escalation_math(self):
        self.w.school.late_fee_amount = 100
        self.w.school.late_fee_per_week = 50
        self.w.school.late_fee_max = 0
        self.w.school.save()
        # Due 3 weeks + a few days before today -> 3 full weeks.
        ch = self._overdue_challan(self.today - datetime.timedelta(days=24))
        self.assertEqual(_escalating_late_fee(self.w.school, ch, self.today),
                         100 + 50 * 3)

    def test_cap_applied(self):
        self.w.school.late_fee_amount = 100
        self.w.school.late_fee_per_week = 50
        self.w.school.late_fee_max = 180
        self.w.school.save()
        ch = self._overdue_challan(self.today - datetime.timedelta(days=70))  # 10 wks
        self.assertEqual(_escalating_late_fee(self.w.school, ch, self.today), 180)

    def test_not_overdue_is_zero(self):
        self.w.school.late_fee_amount = 100
        self.w.school.save()
        ch = self._overdue_challan(self.today + datetime.timedelta(days=5))
        self.assertEqual(_escalating_late_fee(self.w.school, ch, self.today), 0)

    def test_daily_job_escalates(self):
        self.w.school.late_fee_amount = 100
        self.w.school.late_fee_per_week = 50
        self.w.school.save()
        # Two weeks overdue relative to *real* today so the command (which uses
        # timezone.localdate) sees it as overdue.
        import django.utils.timezone as tz
        real_today = tz.localdate()
        ch, _ = _make_challan(self.w.ayaan, 2020, 1)
        ch.due_date = real_today - datetime.timedelta(days=14)
        ch.save(update_fields=['due_date'])
        call_command('fees_daily')
        ch.refresh_from_db()
        self.assertEqual(ch.late_fee, 100 + 50 * 2)

    def test_manual_late_fee_locks_against_escalation(self):
        self.w.school.late_fee_amount = 100
        self.w.school.late_fee_per_week = 50
        self.w.school.save()
        import django.utils.timezone as tz
        real_today = tz.localdate()
        ch, _ = _make_challan(self.w.ayaan, 2020, 1)
        ch.due_date = real_today - datetime.timedelta(days=21)
        ch.save(update_fields=['due_date'])
        # Finance sets a late fee by hand -> locked.
        c = Client(); c.force_login(self.w.finance_u)
        c.post('/fees/student/%d/' % self.w.ayaan.id, {
            'action': 'late_fee', 'challan_id': ch.id, 'late_fee': '250'})
        ch.refresh_from_db()
        self.assertTrue(ch.late_fee_locked)
        self.assertEqual(ch.late_fee, 250)
        # Daily job must not touch a locked challan.
        call_command('fees_daily')
        ch.refresh_from_db()
        self.assertEqual(ch.late_fee, 250)

    def test_escalation_never_lowers(self):
        self.w.school.late_fee_amount = 100
        self.w.school.late_fee_per_week = 0
        self.w.school.save()
        import django.utils.timezone as tz
        real_today = tz.localdate()
        ch, _ = _make_challan(self.w.ayaan, 2020, 1)
        ch.due_date = real_today - datetime.timedelta(days=10)
        ch.late_fee = 500          # already higher than base, not locked
        ch.save(update_fields=['due_date', 'late_fee'])
        call_command('fees_daily')
        ch.refresh_from_db()
        self.assertEqual(ch.late_fee, 500)   # unchanged (never lowered)
