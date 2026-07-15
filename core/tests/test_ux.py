"""Quick-win UX features: student search, empty states, branding on login,
and the correct school default password shown on the Users page."""
from django.test import Client, TestCase

from core.models import ClassRoom, School, Student
from core.tests.factory import build_world


class SearchTests(TestCase):
    def setUp(self):
        self.w = build_world()
        self.c = Client()
        self.c.force_login(self.w.admin_u)

    def test_search_by_name(self):
        html = self.c.get('/students/?q=Ayaan').content.decode()
        self.assertIn('Ayaan', html)
        self.assertNotIn('Hira', html)
        self.assertIn('Search results', html)

    def test_search_by_guardian_phone(self):
        # Imran is guardian of Ayaan + Inaya (shared phone)
        html = self.c.get('/students/?q=1111111').content.decode()
        self.assertIn('Ayaan', html)
        self.assertIn('Inaya', html)
        self.assertNotIn('Hira', html)

    def test_no_match_message(self):
        html = self.c.get('/students/?q=zzznobody').content.decode()
        self.assertIn('No student matches', html)

    def test_search_box_in_topbar_for_admin(self):
        html = self.c.get('/students/').content.decode()
        self.assertIn('top-search', html)

    def test_search_box_hidden_for_teacher(self):
        c = Client(); c.force_login(self.w.teacher_u)
        self.assertNotIn('top-search', c.get('/dashboard/').content.decode())


class EmptyStateTests(TestCase):
    def test_students_empty_state(self):
        # fresh school, no students at all
        School.objects.create(name='Empty School')
        c = Client()
        from core.tests.factory import make_user
        u, _ = make_user('admin_e', 'admin')
        c.force_login(u)
        html = c.get('/students/').content.decode()
        self.assertIn('No students yet', html)
        self.assertIn('Add your first student', html)


class PaginationTests(TestCase):
    def setUp(self):
        self.w = build_world()
        c = ClassRoom.objects.create(name='1', section='A', monthly_fee=1000)
        # 60 active students -> more than one page of 25
        for i in range(60):
            Student.objects.create(name='Pupil %02d' % i, classroom=c,
                                   status='Active')

    def test_students_paginated(self):
        c = Client(); c.force_login(self.w.admin_u)
        html = c.get('/students/?tab=all').content.decode()
        self.assertIn('pager', html)          # controls rendered
        self.assertIn('Next', html)
        # page 2 is reachable and preserves the tab filter
        p2 = c.get('/students/?tab=all&page=2')
        self.assertEqual(p2.status_code, 200)
        self.assertIn('tab=all&', p2.content.decode())

    def test_out_of_range_page_is_safe(self):
        c = Client(); c.force_login(self.w.admin_u)
        # get_page clamps to the last page instead of erroring
        self.assertEqual(c.get('/students/?tab=all&page=999').status_code, 200)
        self.assertEqual(c.get('/students/?tab=all&page=abc').status_code, 200)


class BrandingTests(TestCase):
    def test_login_page_shows_school_name(self):
        School.objects.create(name='Roshni Model School',
                              primary_color='#123456')
        html = Client().get('/login/').content.decode()
        self.assertIn('Roshni Model School', html)
        self.assertIn('#123456', html)


class DefaultPasswordHintTests(TestCase):
    def setUp(self):
        self.w = build_world()

    def test_users_page_shows_school_default_not_hardcoded(self):
        self.w.school.default_password = 'welcome2school'
        self.w.school.save()
        c = Client(); c.force_login(self.w.admin_u)
        html = c.get('/users/').content.decode()
        self.assertIn('welcome2school', html)
        self.assertNotIn('roshni123', html)
