"""Edit + delete added to previously add-only management pages."""
import datetime

from django.test import Client, TestCase
from django.urls import reverse

from core.models import CalendarEvent, TransportRoute
from core.tests.factory import build_world, PASSWORD


class TransportCrudTests(TestCase):
    def setUp(self):
        self.w = build_world()
        self.c = Client()
        self.c.login(username='admin1', password=PASSWORD)
        self.r = TransportRoute.objects.create(name='Route 1', vehicle='ABC-1',
                                               driver='Kamran', fee=1000)

    def test_edit_route(self):
        self.c.post(reverse('transport'), {
            'action': 'edit', 'id': self.r.id, 'name': 'Route 1 - DHA',
            'vehicle': 'XYZ-9', 'driver': 'Kamran Ali', 'fee': '1500'})
        self.r.refresh_from_db()
        self.assertEqual(self.r.name, 'Route 1 - DHA')
        self.assertEqual(self.r.fee, 1500)
        self.assertEqual(self.r.vehicle, 'XYZ-9')

    def test_delete_route(self):
        self.c.post(reverse('transport'), {'action': 'delete', 'id': self.r.id})
        self.assertFalse(TransportRoute.objects.filter(id=self.r.id).exists())


class CalendarCrudTests(TestCase):
    def setUp(self):
        self.w = build_world()
        self.c = Client()
        self.c.login(username='admin1', password=PASSWORD)
        self.e = CalendarEvent.objects.create(
            title='Sports Day', event_type='Event', date=datetime.date(2026, 3, 1))

    def test_edit_event(self):
        self.c.post(reverse('calendar'), {
            'action': 'edit', 'id': self.e.id, 'title': 'Annual Sports Day',
            'event_type': 'Holiday', 'date': '2026-04-10'})
        self.e.refresh_from_db()
        self.assertEqual(self.e.title, 'Annual Sports Day')
        self.assertEqual(self.e.event_type, 'Holiday')
        self.assertEqual(self.e.date, datetime.date(2026, 4, 10))

    def test_delete_event(self):
        self.c.post(reverse('calendar'), {'action': 'delete', 'id': self.e.id})
        self.assertFalse(CalendarEvent.objects.filter(id=self.e.id).exists())
