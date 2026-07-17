"""P2 — annual fee card (per-student yearly fee statement)."""
from django.test import Client, TestCase
from django.utils import timezone

from core.models import FeePayment
from core.tests.factory import build_world, PASSWORD
from core.views import _make_challan


class FeeCardTests(TestCase):
    def setUp(self):
        self.w = build_world()
        self.year = timezone.localdate().year
        c = Client(); c.force_login(self.w.finance_u)
        # Jan challan, paid in full BEFORE Feb exists (so no arrears roll-forward).
        self.jan, _ = _make_challan(self.w.ayaan, self.year, 1)   # tuition 5000
        c.post('/fees/student/%d/' % self.w.ayaan.id, {
            'action': 'collect', 'challan_id': self.jan.id,
            'amount': '5000', 'mode': 'Cash'})
        # Feb challan left unpaid.
        self.feb, _ = _make_challan(self.w.ayaan, self.year, 2)

    def test_card_totals(self):
        c = Client(); c.force_login(self.w.finance_u)
        r = c.get('/fees/card/%d/?year=%d' % (self.w.ayaan.id, self.year))
        self.assertEqual(r.status_code, 200)
        ctx = r.context
        self.assertEqual(ctx['tot_billed'], 10000)   # two months @ 5000
        self.assertEqual(ctx['tot_paid'], 5000)
        self.assertEqual(ctx['tot_bal'], 5000)
        self.assertEqual(len(ctx['rows']), 12)        # all twelve months shown

    def test_parent_can_view_own_card(self):
        c = Client(); c.login(username='parent1', password=PASSWORD)
        r = c.get('/fees/card/%d/' % self.w.ayaan.id)
        self.assertEqual(r.status_code, 200)

    def test_parent_cannot_view_other_students_card(self):
        # parent1's children are Ayaan + Inaya, NOT Hira.
        c = Client(); c.login(username='parent1', password=PASSWORD)
        r = c.get('/fees/card/%d/' % self.w.hira.id)
        self.assertEqual(r.status_code, 403)

    def test_voided_payment_not_counted(self):
        p = FeePayment.objects.get(student=self.w.ayaan)
        c = Client(); c.force_login(self.w.finance_u)
        c.post('/fees/student/%d/' % self.w.ayaan.id, {
            'action': 'void_payment', 'payment_id': p.id, 'reason': 'x'})
        r = c.get('/fees/card/%d/?year=%d' % (self.w.ayaan.id, self.year))
        self.assertEqual(r.context['tot_paid'], 0)
        self.assertEqual(r.context['tot_bal'], 10000)
