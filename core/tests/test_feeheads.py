"""Configurable fee heads: extra charges auto-added to challans by frequency."""
from django.test import Client, TestCase

from core.models import ChallanLine, FeeHead
from core.tests.factory import build_world
from core.views import _make_challan


class FeeHeadModelTests(TestCase):
    def setUp(self):
        self.w = build_world()

    def test_monthly_head_on_every_challan(self):
        FeeHead.objects.create(name='Computer Fee', amount=500, frequency='monthly')
        c1, _ = _make_challan(self.w.ayaan, 2026, 6)
        c2, _ = _make_challan(self.w.ayaan, 2026, 7)
        self.assertEqual(c1.lines.count(), 1)
        self.assertEqual(c2.lines.count(), 1)
        # gross includes the head: tuition 5000 + 500
        self.assertEqual(c1.gross, 5500)

    def test_one_time_head_only_on_first_challan(self):
        FeeHead.objects.create(name='Admission Fee', amount=5000, frequency='one_time')
        c1, _ = _make_challan(self.w.ayaan, 2026, 6)
        c2, _ = _make_challan(self.w.ayaan, 2026, 7)
        self.assertTrue(c1.lines.filter(label='Admission Fee').exists())
        self.assertFalse(c2.lines.filter(label='Admission Fee').exists())

    def test_annual_head_once_per_year(self):
        FeeHead.objects.create(name='Annual Charges', amount=3000, frequency='annual')
        c1, _ = _make_challan(self.w.ayaan, 2026, 6)
        c2, _ = _make_challan(self.w.ayaan, 2026, 7)
        c3, _ = _make_challan(self.w.ayaan, 2027, 1)   # new year
        self.assertTrue(c1.lines.filter(label='Annual Charges').exists())
        self.assertFalse(c2.lines.filter(label='Annual Charges').exists())
        self.assertTrue(c3.lines.filter(label='Annual Charges').exists())

    def test_inactive_head_not_applied(self):
        FeeHead.objects.create(name='Old Fee', amount=100, frequency='monthly',
                               active=False)
        c1, _ = _make_challan(self.w.ayaan, 2026, 6)
        self.assertEqual(c1.lines.count(), 0)

    def test_balance_includes_heads(self):
        FeeHead.objects.create(name='Lab Fee', amount=1000, frequency='monthly')
        c1, _ = _make_challan(self.w.ayaan, 2026, 6)
        # tuition 5000 + lab 1000, nothing paid
        self.assertEqual(c1.balance, 6000)


class FeeHeadSettingsTests(TestCase):
    def setUp(self):
        self.w = build_world()
        self.c = Client(); self.c.force_login(self.w.admin_u)

    def test_add_head_via_settings(self):
        self.c.post('/settings/', {'fee_action': 'add_head',
                                   'head_name': 'Security Deposit',
                                   'head_amount': '2000',
                                   'head_frequency': 'one_time'})
        h = FeeHead.objects.get(name='Security Deposit')
        self.assertEqual(h.amount, 2000)
        self.assertEqual(h.frequency, 'one_time')

    def test_toggle_and_delete_head(self):
        h = FeeHead.objects.create(name='Temp', amount=100, frequency='monthly')
        self.c.post('/settings/', {'fee_action': 'toggle_head', 'head_id': h.id})
        self.assertFalse(FeeHead.objects.get(pk=h.id).active)
        self.c.post('/settings/', {'fee_action': 'delete_head', 'head_id': h.id})
        self.assertFalse(FeeHead.objects.filter(pk=h.id).exists())

    def test_head_shows_on_voucher(self):
        FeeHead.objects.create(name='Sports Fee', amount=700, frequency='monthly')
        challan, _ = _make_challan(self.w.ayaan, 2026, 6)
        # finance collect page lists the itemised line
        fc = Client(); fc.force_login(self.w.finance_u)
        html = fc.get('/fees/student/%d/' % self.w.ayaan.id).content.decode()
        self.assertIn('Sports Fee', html)
