"""Bulk challan printing for a whole class."""
from django.test import Client, TestCase

from core.tests.factory import build_world
from core.views import _make_challan


class ChallanPrintTests(TestCase):
    def setUp(self):
        self.w = build_world()
        self.c = Client(); self.c.force_login(self.w.finance_u)
        # Ayaan (9-A) + Hira (9-A) get a June 2026 challan
        _make_challan(self.w.ayaan, 2026, 6)
        _make_challan(self.w.hira, 2026, 6)

    def test_lists_class_challans_for_month(self):
        html = self.c.get('/fees/challans/print/?class=%d&month=6&year=2026'
                          % self.w.c9.id).content.decode()
        self.assertIn('Ayaan', html)
        self.assertIn('Hira', html)
        self.assertIn('Print all', html)
        self.assertIn('Fee Voucher', html)

    def test_other_class_not_included(self):
        html = self.c.get('/fees/challans/print/?class=%d&month=6&year=2026'
                          % self.w.c9.id).content.decode()
        self.assertNotIn('Inaya', html)   # Inaya is in 10-A

    def test_empty_month_shows_guidance(self):
        html = self.c.get('/fees/challans/print/?class=%d&month=3&year=2026'
                          % self.w.c9.id).content.decode()
        self.assertIn('No challans found', html)

    def test_admin_can_access_finance_page(self):
        c = Client(); c.force_login(self.w.admin_u)
        self.assertEqual(c.get('/fees/challans/print/').status_code, 200)
