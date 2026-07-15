from django.test import Client, TestCase

from core.models import FeePayment, TimetableSlot
from core.tests.factory import build_world
from core.views import _make_challan


class MultiChildTests(TestCase):
    def setUp(self):
        self.w = build_world()
        self.c = Client()

    def test_parent_has_two_children(self):
        kids = {s.name for s in self.w.parent_p.child_list()}
        self.assertEqual(kids, {'Ayaan', 'Inaya'})

    def test_parent_can_switch_child(self):
        self.c.force_login(self.w.parent_u)
        # Default child (primary) is Ayaan
        h1 = self.c.get('/my-attendance/').content.decode()
        self.assertIn('Ayaan', h1)
        # Switch to Inaya
        h2 = self.c.get('/my-attendance/?child=%d' % self.w.inaya.id).content.decode()
        self.assertIn('Inaya', h2)
        # Switch persists via session on the next page (no ?child=)
        h3 = self.c.get('/my-profile/').content.decode()
        self.assertIn('Inaya', h3)

    def test_parent_cannot_view_non_child_receipt(self):
        ch, _ = _make_challan(self.w.hira, 2026, 6)
        pay = FeePayment.objects.create(
            student=self.w.hira, challan=ch, amount=5000, receipt_no='R1')
        self.c.force_login(self.w.parent_u)
        # Hira is not this parent's child
        self.assertEqual(
            self.c.get('/fees/receipt/%d/' % pay.id).status_code, 403)


class TeacherTimetableTests(TestCase):
    def setUp(self):
        self.w = build_world()
        self.c = Client()
        # 9-A grid: teacher1 teaches Mathematics; English is someone else's.
        TimetableSlot.objects.create(classroom=self.w.c9, day='Mon', period=1,
                                     start_time='08:00', subject='Mathematics',
                                     teacher='Sir A')
        TimetableSlot.objects.create(classroom=self.w.c9, day='Mon', period=2,
                                     start_time='08:45', subject='English',
                                     teacher='Ms B')

    def test_timetable_shows_only_own_periods(self):
        self.c.force_login(self.w.teacher_u)
        html = self.c.get('/teacher/timetable/').content.decode()
        self.assertIn('Mathematics', html)      # teacher's own subject
        self.assertNotIn('English', html)       # taught by someone else
