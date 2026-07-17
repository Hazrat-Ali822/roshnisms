"""P2 — parent self-service contact editing on My Profile."""
from django.test import Client, TestCase

from core.models import Student
from core.tests.factory import build_world, PASSWORD


class ProfileEditTests(TestCase):
    def setUp(self):
        self.w = build_world()

    def test_parent_updates_contact(self):
        c = Client(); c.login(username='parent1', password=PASSWORD)
        c.post('/my-profile/', {
            'action': 'update_contact', 'guardian_name': 'Imran Khan',
            'guardian_phone': '0300-9999999', 'address': 'House 5, Lahore'})
        s = Student.objects.get(pk=self.w.ayaan.pk)
        self.assertEqual(s.guardian_name, 'Imran Khan')
        self.assertEqual(s.guardian_phone, '0300-9999999')
        self.assertEqual(s.address, 'House 5, Lahore')

    def test_student_cannot_edit(self):
        before = self.w.ayaan.guardian_phone
        c = Client(); c.login(username='student1', password=PASSWORD)
        c.post('/my-profile/', {
            'action': 'update_contact', 'guardian_phone': '0300-0000000'})
        s = Student.objects.get(pk=self.w.ayaan.pk)
        self.assertEqual(s.guardian_phone, before)   # unchanged

    def test_edit_only_touches_contact_fields(self):
        c = Client(); c.login(username='parent1', password=PASSWORD)
        c.post('/my-profile/', {
            'action': 'update_contact', 'guardian_name': 'New Name',
            'guardian_phone': '0311-1111111', 'address': 'X',
            'name': 'HACKED', 'roll_no': '999', 'admission_no': 'ZZZ'})
        s = Student.objects.get(pk=self.w.ayaan.pk)
        self.assertEqual(s.name, 'Ayaan')          # identity untouched
        self.assertEqual(s.roll_no, '1')
        self.assertEqual(s.guardian_name, 'New Name')
