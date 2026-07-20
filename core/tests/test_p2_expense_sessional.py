"""P2 — Payment Sources in Expenses, and the Sessional attendance report."""
import datetime

from django.test import Client, TestCase
from django.urls import reverse

from core.models import AttendanceRecord, Expense, PaymentSource
from core.tests.factory import build_world, PASSWORD


class PaymentSourceTests(TestCase):
    def setUp(self):
        self.w = build_world()
        self.c = Client()
        self.c.login(username='finance1', password=PASSWORD)

    def test_add_source_then_expense_tracks_it(self):
        self.c.post(reverse('expenses'),
                    {'action': 'add_source', 'name': 'Main Bank'})
        src = PaymentSource.objects.get(name='Main Bank')
        self.c.post(reverse('expenses'),
                    {'title': 'Electricity', 'category': 'Utilities',
                     'amount': '3000', 'source': src.id})
        e = Expense.objects.get(title='Electricity')
        self.assertEqual(e.source_id, src.id)
        # Per-source total appears on the page.
        r = self.c.get(reverse('expenses'))
        self.assertContains(r, 'Main Bank')

    def test_expense_without_source_is_unassigned(self):
        self.c.post(reverse('expenses'),
                    {'title': 'Chalk', 'category': 'Supplies', 'amount': '500'})
        e = Expense.objects.get(title='Chalk')
        self.assertIsNone(e.source_id)


class SessionalAttendanceTests(TestCase):
    def setUp(self):
        self.w = build_world()
        # Ayaan (9-A): 3 present, 1 absent in session 2025-26 -> 75%.
        for day, st in [(1, 'P'), (2, 'P'), (3, 'P'), (4, 'A')]:
            AttendanceRecord.objects.create(
                student=self.w.ayaan, date=datetime.date(2025, 9, day),
                status=st, session='2025-26')
        self.c = Client()
        self.c.login(username='admin1', password=PASSWORD)

    def test_sessional_summary(self):
        r = self.c.get(reverse('attendance_sessional'),
                       {'class': self.w.c9.id, 'session': '2025-26'})
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn('Ayaan', body)
        self.assertIn('75%', body)      # 3 of 4 present

    def test_sessional_csv(self):
        r = self.c.get(reverse('attendance_sessional'),
                       {'class': self.w.c9.id, 'session': '2025-26',
                        'export': 'csv'})
        self.assertEqual(r.status_code, 200)
        self.assertIn('text/csv', r['Content-Type'])
        self.assertIn('Ayaan', r.content.decode())
