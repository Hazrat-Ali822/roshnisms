"""P2 — complaints / feedback tickets (family raises, office resolves)."""
from django.test import Client, TestCase

from core.models import Complaint
from core.tests.factory import build_world, PASSWORD


class ComplaintTests(TestCase):
    def setUp(self):
        self.w = build_world()

    def _parent(self):
        c = Client(); c.login(username='parent1', password=PASSWORD)
        return c

    def test_parent_raises_complaint(self):
        self._parent().post('/complaints/', {
            'category': 'Transport', 'subject': 'Bus late',
            'body': 'The bus was 30 min late all week.'})
        c = Complaint.objects.first()
        self.assertIsNotNone(c)
        self.assertEqual(c.category, 'Transport')
        self.assertEqual(c.status, 'Open')
        self.assertEqual(c.raised_by, self.w.parent_p)

    def test_missing_fields_rejected(self):
        self._parent().post('/complaints/', {
            'category': 'Other', 'subject': '', 'body': 'x'})
        self.assertFalse(Complaint.objects.exists())

    def test_office_responds_and_resolves(self):
        c = Complaint.objects.create(
            raised_by=self.w.parent_p, raised_by_name='Parent1',
            category='Fee', subject='Overcharged', body='Charged twice')
        admin = Client(); admin.force_login(self.w.admin_u)
        admin.post('/office/complaints/', {
            'complaint_id': c.id, 'status': 'Resolved',
            'response': 'Refund processed.'})
        c.refresh_from_db()
        self.assertEqual(c.status, 'Resolved')
        self.assertEqual(c.response, 'Refund processed.')
        self.assertTrue(c.handled_by)

    def test_admin_badge_counts_open(self):
        Complaint.objects.create(raised_by=self.w.parent_p, subject='x', body='y')
        admin = Client(); admin.force_login(self.w.admin_u)
        r = admin.get('/')
        self.assertEqual(r.context['badge_counts'].get('office_complaints'), 1)

    def test_family_only_sees_own(self):
        # A complaint by parent1...
        Complaint.objects.create(raised_by=self.w.parent_p, subject='mine', body='y')
        # ...and one by the student account.
        Complaint.objects.create(raised_by=self.w.student_p, subject='theirs', body='z')
        r = self._parent().get('/complaints/')
        subjects = [c.subject for c in r.context['complaints']]
        self.assertIn('mine', subjects)
        self.assertNotIn('theirs', subjects)

    def test_parent_cannot_access_office_view(self):
        r = self._parent().get('/office/complaints/')
        self.assertNotEqual(r.status_code, 200)
