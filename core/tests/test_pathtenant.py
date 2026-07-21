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

    def test_tenant_manifest_is_reachable(self):
        """File-like tenant URLs (manifest.webmanifest) must NOT get a forced
        trailing slash — that turned every PWA asset into a 404 under path
        tenancy and broke install/packaging (no manifest found)."""
        resp = Client().get('/sca/manifest.webmanifest')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('manifest', resp['Content-Type'])

    def test_tenant_service_worker_is_reachable(self):
        resp = Client().get('/sca/sw.js')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('javascript', resp['Content-Type'])

    def test_tenant_page_still_gets_trailing_slash(self):
        """Normal (non-file) tenant pages keep Django's trailing-slash behaviour
        — /sca/login (no slash) still resolves to the tenant login."""
        resp = Client().get('/sca/login/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Sudhum Children Academy')
