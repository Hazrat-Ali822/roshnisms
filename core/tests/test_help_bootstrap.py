"""In-app Help guide + first-run bootstrap (ensure_admin)."""
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import Client, TestCase

from core.models import Profile, School
from core.tests.factory import build_world


class HelpGuideTests(TestCase):
    def setUp(self):
        self.w = build_world()

    def test_help_loads_for_every_role(self):
        for u in [self.w.admin_u, self.w.teacher_u, self.w.finance_u,
                  self.w.parent_u, self.w.student_u, self.w.principal_u,
                  self.w.owner_u]:
            c = Client(); c.force_login(u)
            r = c.get('/help/')
            self.assertEqual(r.status_code, 200, 'help crashed for a role')
            self.assertIn('Getting started', r.content.decode())

    def test_each_role_sees_its_own_tailored_guide(self):
        # (user, role label that should appear, a card title only that role sees)
        cases = [
            (self.w.teacher_u, 'Teacher', 'Behaviour Notes'),
            (self.w.finance_u, 'Finance', 'Defaulters'),
            (self.w.parent_u, 'Parent', 'Message the teacher'),
            (self.w.student_u, 'Student', 'My Results'),
            (self.w.principal_u, 'Principal', 'Approvals'),
            (self.w.owner_u, 'Owner', 'Owner Dashboard'),
        ]
        for u, label, card in cases:
            c = Client(); c.force_login(u)
            html = c.get('/help/').content.decode()
            self.assertIn('Your guide', html, f'{label}: no tailored guide block')
            self.assertIn(label, html, f'{label}: role label missing')
            self.assertIn(card, html, f'{label}: expected card "{card}" missing')

    def test_non_admin_roles_do_not_see_full_office_reference(self):
        # The big "every module" office reference is for the Office role only.
        for u in [self.w.teacher_u, self.w.parent_u, self.w.student_u]:
            c = Client(); c.force_login(u)
            self.assertNotIn('Every module, explained',
                             c.get('/help/').content.decode())

    def test_admin_sees_module_reference(self):
        c = Client(); c.force_login(self.w.admin_u)
        html = c.get('/help/').content.decode()
        self.assertIn('Every module, explained', html)
        self.assertIn('Fees', html)

    def test_help_link_in_sidebar(self):
        c = Client(); c.force_login(self.w.admin_u)
        self.assertIn('/help/', c.get('/').content.decode())


class EnsureAdminTests(TestCase):
    def test_creates_admin_when_empty(self):
        # fresh DB: no users, no school
        self.assertFalse(User.objects.filter(is_superuser=False).exists())
        call_command('ensure_admin')
        self.assertTrue(School.objects.exists())
        u = User.objects.get(username='admin')
        self.assertTrue(u.check_password('admin123'))
        self.assertEqual(Profile.objects.get(user=u).role, 'admin')

    def test_idempotent_does_not_duplicate(self):
        call_command('ensure_admin')
        call_command('ensure_admin')
        self.assertEqual(User.objects.filter(username='admin').count(), 1)

    def test_skips_when_school_already_set_up(self):
        build_world()   # creates profiles + a school
        call_command('ensure_admin')
        # no default 'admin' user should be added to an existing school
        self.assertFalse(User.objects.filter(username='admin').exists())


class TestingToolsRenderTests(TestCase):
    def setUp(self):
        self.w = build_world()

    def test_settings_shows_testing_tools_and_backup(self):
        c = Client(); c.force_login(self.w.admin_u)
        html = c.get('/settings/').content.decode()
        self.assertIn('Testing tools', html)
        self.assertIn('Load demo data', html)
        self.assertIn('Start fresh', html)
        self.assertIn('Download backup now', html)
