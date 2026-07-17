"""P2 — staff performance appraisals."""
from django.test import Client, TestCase

from core.models import Appraisal, Staff
from core.tests.factory import build_world, PASSWORD


class AppraisalTests(TestCase):
    def setUp(self):
        self.w = build_world()
        self.staff = Staff.objects.create(name='Mr Ahmed', designation='Teacher',
                                          basic_salary=40000)

    def _admin(self):
        c = Client(); c.force_login(self.w.admin_u)
        return c

    def test_admin_records_appraisal(self):
        self._admin().post('/staff/appraisal/', {
            'staff_id': self.staff.id, 'period': '2025-26', 'rating': '4',
            'strengths': 'Great with students', 'improvements': 'Paperwork'})
        a = Appraisal.objects.filter(staff=self.staff).first()
        self.assertIsNotNone(a)
        self.assertEqual(a.rating, 4)
        self.assertEqual(a.period, '2025-26')
        self.assertTrue(a.reviewer)

    def test_rating_clamped(self):
        self._admin().post('/staff/appraisal/', {
            'staff_id': self.staff.id, 'period': 'X', 'rating': '99'})
        self.assertEqual(Appraisal.objects.get(staff=self.staff).rating, 5)

    def test_missing_period_rejected(self):
        self._admin().post('/staff/appraisal/', {
            'staff_id': self.staff.id, 'period': '', 'rating': '3'})
        self.assertFalse(Appraisal.objects.exists())

    def test_summary_average(self):
        Appraisal.objects.create(staff=self.staff, period='T1', rating=4)
        Appraisal.objects.create(staff=self.staff, period='T2', rating=2)
        r = self._admin().get('/staff/appraisal/')
        row = next(x for x in r.context['summary'] if x['staff'].id == self.staff.id)
        self.assertEqual(row['avg'], 3.0)
        self.assertEqual(row['count'], 2)

    def test_teacher_cannot_access(self):
        c = Client(); c.login(username='teacher1', password=PASSWORD)
        r = c.get('/staff/appraisal/')
        self.assertNotEqual(r.status_code, 200)
