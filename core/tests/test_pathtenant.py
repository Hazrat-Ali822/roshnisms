"""Path-based multi-tenant routing (the only option on hosts without wildcard
subdomains, e.g. PythonAnywhere).

A tenant is reached at /<subdomain>/... The middleware strips the prefix for URL
resolution but sets SCRIPT_NAME so every URL Django builds keeps the prefix — so
a tenant NEVER leaks back to the master login/dashboard.
"""
from django.test import Client, TestCase

from core.models import School


class PathTenantRoutingTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name='Sudhum Children Academy',
                                             subdomain='sca')

    def test_tenant_root_redirects_to_tenant_login_not_master(self):
        """GET /sca/ while logged out must redirect to /sca/login/, never the
        master /login/ (that was the 'open a school, the main one opens' bug)."""
        resp = Client().get('/sca/')
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(
            resp['Location'].startswith('/sca/login/'),
            "expected redirect to /sca/login/, got %r" % resp['Location'])

    def test_tenant_login_page_shows_tenant_brand(self):
        """The /sca/login/ page must render with the school's own brand, proving
        the request resolved to the tenant and not the neutral master."""
        resp = Client().get('/sca/login/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Sudhum Children Academy')

    def test_master_login_is_still_neutral(self):
        """The bare /login/ (master) must stay neutral, not adopt a tenant."""
        resp = Client().get('/login/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Roshni SMS')
