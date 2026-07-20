"""Tenant database provisioning.

Each school lives in its own ``{subdomain}.sqlite3`` file. These files must be
created from the master's SCHEMA only — never its DATA — otherwise every school
inherits the master's users, students and staff (a cross-tenant leak).

``build_clean_tenant_db`` is the single, shared way to create a tenant DB
cleanly. It is used by SaaS provisioning (views), the routing middleware's
first-touch fallback, and the ``reset_tenant`` management command, so there is
exactly one code path and it can never drift back to a raw copy.
"""
import copy as _copy
import os
import shutil

from django.conf import settings


def tenant_db_path(subdomain):
    return os.path.join(str(settings.BASE_DIR), '%s.sqlite3' % (subdomain or 'default'))


def build_clean_tenant_db(school, *, force=False):
    """Create a CLEAN database file for a tenant school: the full schema (copied
    from the master) but NONE of the master's data — only this school's own
    School record and admin login.

    No-op if the tenant file already exists, unless force=True (rebuild from
    scratch — used to repair a contaminated tenant). Returns True if it
    (re)built the file. Always restores the default connection to the master.
    """
    from django.core.management import call_command
    from django.db import connections
    from django.contrib.auth.models import User
    from core.models import Profile, School as TenantSchool

    subdomain = school.subdomain or 'default'
    master_db = os.path.join(str(settings.BASE_DIR), 'db.sqlite3')
    path = tenant_db_path(subdomain)

    if os.path.exists(path):
        if not force:
            return False
        os.remove(path)

    shutil.copyfile(master_db, path)   # schema carrier; data is flushed next

    conn = connections['default']
    conn.close()
    conn.settings_dict = _copy.deepcopy(conn.settings_dict)
    conn.settings_dict['NAME'] = path
    try:
        call_command('flush', verbosity=0, interactive=False)
        ts = TenantSchool.objects.create(
            name=school.name, subdomain=subdomain,
            subscription_start=school.subscription_start,
            subscription_end=school.subscription_end,
            subscription_active=True,
            admin_username=school.admin_username or '',
            admin_email=school.admin_email or '',
            admin_password=school.admin_password or '',
            subscription_rate=school.subscription_rate or 5000)
        if school.admin_username and school.admin_password:
            user = User.objects.create_user(
                username=school.admin_username, email=school.admin_email or '',
                password=school.admin_password, first_name=school.name)
            Profile.objects.create(user=user, role='admin', school=ts,
                                   must_change_password=False)
    finally:
        conn.close()
        conn.settings_dict = _copy.deepcopy(settings.DATABASES['default'])
        conn.settings_dict['NAME'] = master_db
    return True
