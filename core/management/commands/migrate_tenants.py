"""Apply migrations to the master DB and every tenant SQLite file.

Because each school lives in its own ``{subdomain}.sqlite3`` file (copied from
the master when the school is provisioned), a normal ``migrate`` only updates
the master. After deploying code with new migrations, run this so every tenant
database gets the same schema change too.

Usage:
    python manage.py migrate_tenants
    python manage.py migrate_tenants --list        # just show what would run
"""
import copy
import glob
import os

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import connections

# Files that are NOT tenant databases and must be skipped.
_SKIP = {'db.sqlite3', 'restore_staging.sqlite3'}


def _tenant_db_files():
    base = str(settings.BASE_DIR)
    files = []
    for path in sorted(glob.glob(os.path.join(base, '*.sqlite3'))):
        name = os.path.basename(path)
        if name in _SKIP or '_backup_' in name or name.startswith('backup'):
            continue
        files.append(path)
    return files


class Command(BaseCommand):
    help = 'Run migrate on the master DB and every tenant .sqlite3 file.'

    def add_arguments(self, parser):
        parser.add_argument('--list', action='store_true',
                            help='List tenant DB files without migrating.')

    def handle(self, *args, **options):
        tenant_files = _tenant_db_files()

        if options['list']:
            self.stdout.write('Master: db.sqlite3')
            for f in tenant_files:
                self.stdout.write('Tenant: %s' % os.path.basename(f))
            self.stdout.write(self.style.SUCCESS(
                '%d tenant database(s) found.' % len(tenant_files)))
            return

        # 1. Master database first.
        master = os.path.join(str(settings.BASE_DIR), 'db.sqlite3')
        self.stdout.write(self.style.MIGRATE_HEADING('Migrating master (db.sqlite3)'))
        self._migrate_file(master)

        # 2. Each tenant file.
        for path in tenant_files:
            self.stdout.write(self.style.MIGRATE_HEADING(
                'Migrating tenant (%s)' % os.path.basename(path)))
            self._migrate_file(path)

        # 3. Always leave the connection pointed back at the master.
        self._point_at(master)
        self.stdout.write(self.style.SUCCESS(
            'Done: master + %d tenant database(s) migrated.' % len(tenant_files)))

    def _point_at(self, db_path):
        conn = connections['default']
        conn.close()
        conn.settings_dict = copy.deepcopy(settings.DATABASES['default'])
        conn.settings_dict['NAME'] = db_path

    def _migrate_file(self, db_path):
        self._point_at(db_path)
        call_command('migrate', verbosity=1, interactive=False)
