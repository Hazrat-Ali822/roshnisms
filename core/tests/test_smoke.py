"""Smoke / sanity tests — the fast "is anything on fire?" check.

For every role we sign in and open the pages that role uses, and assert the
server answers 200 (not a 500 crash). This catches broken templates, bad
context and import errors across the whole app in seconds, without asserting
any specific content. Deeper behaviour is covered by the feature tests.
"""
from django.test import Client, TestCase
from django.urls import reverse

from core.tests.factory import build_world


class SmokeTests(TestCase):
    def setUp(self):
        self.w = build_world()

    def _ok(self, user, url_names):
        c = Client()
        c.force_login(user)
        for name in url_names:
            url = reverse(name)
            resp = c.get(url)
            self.assertEqual(
                resp.status_code, 200,
                f'{user.username} got {resp.status_code} at {name} ({url})')

    # Every signed-in user can open their home and the help guide.
    def test_everyone_dashboard_and_help(self):
        for u in [self.w.admin_u, self.w.teacher_u, self.w.finance_u,
                  self.w.parent_u, self.w.student_u, self.w.principal_u,
                  self.w.owner_u]:
            self._ok(u, ['dashboard', 'help_guide'])

    # The Office role can open every major management screen.
    def test_office_core_pages(self):
        self._ok(self.w.admin_u, [
            'students_list', 'classes_manage', 'timetable_manage',
            'staff_list', 'fee_collection', 'admissions', 'reports',
            'school_settings',
        ])

    # Finance can open the money screens.
    def test_finance_pages(self):
        self._ok(self.w.finance_u, ['fee_collection'])
