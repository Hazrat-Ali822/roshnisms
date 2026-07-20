"""Rebuild a tenant school's database CLEAN.

A tenant DB was originally created by copying the master db.sqlite3, so it
carried over every other school's users and data (a cross-tenant leak). This
command rebuilds the chosen school's ``{subdomain}.sqlite3`` from scratch:
full schema, but only that school's own School record and admin login.

WARNING: this deletes everything currently inside that tenant database. Use it
to repair a leaked/contaminated school (typically right after go-live, before
the school has entered real data).

Usage:
    python manage.py reset_tenant sca
    python manage.py reset_tenant sca --yes        # skip the confirmation
"""
import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.models import School


class Command(BaseCommand):
    help = "Rebuild a tenant's database clean (only its own school + admin)."

    def add_arguments(self, parser):
        parser.add_argument('subdomain', help='The school subdomain, e.g. sca')
        parser.add_argument('--yes', action='store_true',
                            help='Skip the confirmation prompt.')

    def handle(self, *args, **options):
        subdomain = options['subdomain'].strip()
        # The School registry lives in the master DB (this command runs there).
        school = School.objects.filter(subdomain=subdomain).first()
        if not school:
            raise CommandError('No school found with subdomain "%s" in the master '
                               'database.' % subdomain)
        if not (school.admin_username and school.admin_password):
            raise CommandError(
                'School "%s" has no admin_username/admin_password stored, so a '
                'clean admin login cannot be recreated. Set them via the SaaS '
                'portal (Edit school) first.' % subdomain)

        path = os.path.join(str(settings.BASE_DIR), '%s.sqlite3' % subdomain)
        existed = os.path.exists(path)

        if not options['yes']:
            self.stdout.write(self.style.WARNING(
                'This will DELETE all current data in %s.sqlite3 and rebuild it '
                'with only "%s" and admin "%s".'
                % (subdomain, school.name, school.admin_username)))
            confirm = input('Type the subdomain "%s" to confirm: ' % subdomain).strip()
            if confirm != subdomain:
                raise CommandError('Aborted (confirmation did not match).')

        # Import here so the helper's own imports resolve against the app.
        from core.views import _init_tenant_db
        _init_tenant_db(school, force=True)

        self.stdout.write(self.style.SUCCESS(
            '%s tenant "%s" rebuilt clean: only its school record and admin "%s".'
            % ('Rebuilt' if existed else 'Created', subdomain,
               school.admin_username)))
