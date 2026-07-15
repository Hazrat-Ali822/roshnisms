"""Section 6 — year-end promotion: Principal approval gate, students moved up /
graduated, arrears carried forward, session changed, and the action audited."""
import datetime

from django.test import Client, TestCase

from core.models import AuditLog, ClassRoom, FeeChallan, Student
from core.tests.factory import build_world, PASSWORD


class PromotionTests(TestCase):
    def setUp(self):
        self.w = build_world()
        self.c = Client()
        self.c.login(username='principal1', password=PASSWORD)
        # Give Ayaan (class 9) an unpaid challan so we can check arrears carry.
        FeeChallan.objects.create(student=self.w.ayaan, year=2026, month=6,
                                  tuition=5000,
                                  due_date=datetime.date(2026, 6, 10))

    def _post(self, **extra):
        data = {'action': 'promote', 'session': '2026-27'}
        data.update(extra)
        return self.c.post('/promotion/', data)

    def test_requires_principal_approval(self):
        # No approve checkbox -> nothing changes.
        self._post()
        self.w.ayaan.refresh_from_db()
        self.assertEqual(self.w.ayaan.classroom, self.w.c9)   # still in 9
        self.w.school.refresh_from_db()
        self.assertEqual(self.w.school.session, '2025-26')     # unchanged

    def test_promotes_and_changes_session(self):
        self._post(approve='1')
        self.w.ayaan.refresh_from_db()
        # Ayaan moves from 9 to a (new) class 10.
        self.assertIsNotNone(self.w.ayaan.classroom)
        self.assertEqual(self.w.ayaan.classroom.name, '10')
        self.w.school.refresh_from_db()
        self.assertEqual(self.w.school.session, '2026-27')

    def test_final_grade_graduates(self):
        # Inaya is in class 10, which is the final grade by default.
        self.w.school.final_grade = '10'
        self.w.school.save()
        self._post(approve='1')
        self.w.inaya.refresh_from_db()
        self.assertTrue(self.w.inaya.graduated)
        self.assertEqual(self.w.inaya.status, 'Graduated')
        self.assertIsNone(self.w.inaya.classroom)

    def test_detain_keeps_student(self):
        self._post(approve='1', **{'decision_%d' % self.w.hira.id: 'detain'})
        self.w.hira.refresh_from_db()
        self.assertEqual(self.w.hira.classroom, self.w.c9)     # stayed

    def test_arrears_and_audit_recorded(self):
        self._post(approve='1')
        # Ayaan's unpaid challan is untouched (dues follow the student).
        self.assertTrue(FeeChallan.objects.filter(
            student=self.w.ayaan, carried_forward=False).exists())
        log = AuditLog.objects.filter(action='Year-end promotion').first()
        self.assertIsNotNone(log)
        self.assertIn('arrears carried Rs5000', log.detail)

    def test_only_principal_can_access(self):
        c = Client(); c.login(username='finance1', password=PASSWORD)
        r = c.get('/promotion/')
        self.assertIn(r.status_code, (302, 403))
