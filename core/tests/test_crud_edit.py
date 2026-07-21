"""Edit + delete added to previously add-only management pages."""
import datetime

from django.test import Client, TestCase
from django.urls import reverse

from core.models import (Book, CalendarEvent, ExamRoom, Expense, FeeHead,
                         HostelRoom, PaymentSource, Staff, Subject,
                         TransportRoute)
from core.tests.factory import build_world, PASSWORD


class EditOnlyModulesTests(TestCase):
    """Modules that already had delete but were missing edit."""
    def setUp(self):
        self.w = build_world()
        self.c = Client()
        self.c.login(username='admin1', password=PASSWORD)

    def test_fee_head_edit(self):
        h = FeeHead.objects.create(name='Admission', amount=1000, frequency='once')
        self.c.post(reverse('school_settings'), {
            'fee_action': 'edit_head', 'head_id': h.id, 'head_name': 'Admission Fee',
            'head_amount': '2500', 'head_frequency': 'monthly'})
        h.refresh_from_db()
        self.assertEqual(h.name, 'Admission Fee')
        self.assertEqual(h.amount, 2500)
        self.assertEqual(h.frequency, 'monthly')

    def test_exam_room_edit(self):
        r = ExamRoom.objects.create(name='Hall A', capacity=30)
        self.c.post(reverse('exam_rooms'), {
            'action': 'edit', 'room_id': r.id, 'name': 'Main Hall', 'capacity': '50'})
        r.refresh_from_db()
        self.assertEqual(r.name, 'Main Hall')
        self.assertEqual(r.capacity, 50)

    def test_hostel_room_edit(self):
        r = HostelRoom.objects.create(name='R1', capacity=4, warden='Kamran')
        self.c.post(reverse('hostel'), {
            'action': 'edit_room', 'room_id': r.id, 'name': 'Room 1',
            'capacity': '6', 'warden': 'Kamran Ali'})
        r.refresh_from_db()
        self.assertEqual(r.name, 'Room 1')
        self.assertEqual(r.capacity, 6)
        self.assertEqual(r.warden, 'Kamran Ali')

    def test_subject_rename(self):
        self.c.post(reverse('classes_manage'), {
            'action': 'edit_subject', 'subject_id': self.w.math9.id,
            'subject': 'Maths'})
        self.w.math9.refresh_from_db()
        self.assertEqual(self.w.math9.name, 'Maths')


class StaffCrudTests(TestCase):
    def setUp(self):
        self.w = build_world()
        self.c = Client()
        self.c.login(username='admin1', password=PASSWORD)
        self.s = Staff.objects.create(name='Sara', designation='Teacher',
                                      phone='0300-0000000', basic_salary=40000,
                                      allowances=5000)

    def test_edit_staff(self):
        self.c.post(reverse('staff_list'), {
            'action': 'edit_staff', 'id': self.s.id, 'name': 'Sara Khan',
            'designation': 'Senior Teacher', 'phone': '0301-1111111',
            'email': 'sara@x.pk', 'basic_salary': '45000', 'allowances': '6000'})
        self.s.refresh_from_db()
        self.assertEqual(self.s.name, 'Sara Khan')
        self.assertEqual(self.s.basic_salary, 45000)
        self.assertEqual(self.s.designation, 'Senior Teacher')

    def test_delete_staff(self):
        self.c.post(reverse('staff_list'), {'action': 'delete_staff', 'id': self.s.id})
        self.assertFalse(Staff.objects.filter(id=self.s.id).exists())


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


class LibraryCrudTests(TestCase):
    def setUp(self):
        self.w = build_world()
        self.c = Client()
        self.c.login(username='admin1', password=PASSWORD)
        self.b = Book.objects.create(title='Physics', author='Ali', code='LIB-0001',
                                     copies=5, available=3)   # 2 out on loan

    def test_edit_book_keeps_loans_consistent(self):
        # raise copies 5 -> 8; 2 are out, so available should become 6
        self.c.post(reverse('library'), {
            'action': 'edit_book', 'id': self.b.id, 'title': 'Physics XI',
            'author': 'Ali Khan', 'copies': '8'})
        self.b.refresh_from_db()
        self.assertEqual(self.b.title, 'Physics XI')
        self.assertEqual(self.b.copies, 8)
        self.assertEqual(self.b.available, 6)

    def test_delete_book(self):
        self.c.post(reverse('library'), {'action': 'delete_book', 'id': self.b.id})
        self.assertFalse(Book.objects.filter(id=self.b.id).exists())


class ExpensesCrudTests(TestCase):
    def setUp(self):
        self.w = build_world()
        self.c = Client()
        self.c.login(username='finance1', password=PASSWORD)
        self.src = PaymentSource.objects.create(name='Main Bank')
        self.e = Expense.objects.create(title='Electric', category='Utilities',
                                        amount=5000, date=datetime.date(2026, 6, 1),
                                        source=self.src)

    def test_edit_expense(self):
        self.c.post(reverse('expenses'), {
            'action': 'edit_expense', 'id': self.e.id, 'title': 'Electricity bill',
            'category': 'Maintenance', 'amount': '7500', 'source': self.src.id})
        self.e.refresh_from_db()
        self.assertEqual(self.e.title, 'Electricity bill')
        self.assertEqual(self.e.category, 'Maintenance')
        self.assertEqual(self.e.amount, 7500)

    def test_delete_expense(self):
        self.c.post(reverse('expenses'), {'action': 'delete_expense', 'id': self.e.id})
        self.assertFalse(Expense.objects.filter(id=self.e.id).exists())

    def test_edit_source(self):
        self.c.post(reverse('expenses'), {
            'action': 'edit_source', 'id': self.src.id, 'name': 'Meezan Bank'})
        self.src.refresh_from_db()
        self.assertEqual(self.src.name, 'Meezan Bank')

    def test_delete_source_unassigns_expense(self):
        self.c.post(reverse('expenses'), {'action': 'delete_source', 'id': self.src.id})
        self.assertFalse(PaymentSource.objects.filter(id=self.src.id).exists())
        self.e.refresh_from_db()
        self.assertIsNone(self.e.source)   # SET_NULL kept the expense
