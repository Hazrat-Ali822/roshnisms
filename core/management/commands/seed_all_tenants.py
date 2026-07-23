"""Back up every tenant database, then load the full demo school into each one.

DESTRUCTIVE: seeding replaces everything inside a tenant's database. This
command therefore takes a timestamped copy of every SQLite file FIRST (master
included), so any school can be put back exactly as it was.

    python manage.py seed_all_tenants --demo              # backup + seed all
    python manage.py seed_all_tenants --demo --only sca,icms
    python manage.py seed_all_tenants --demo --skip icms
    python manage.py seed_all_tenants --list              # just show the tenants

Restoring one school afterwards is a plain file copy, e.g.
    cp backups/tenants-20260722-1830/sca.sqlite3 sca.sqlite3
"""
import copy
import datetime
import os
import shutil

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connections

from core.models import School


class Command(BaseCommand):
    help = ('Back up every tenant database and load the full demo school into '
            'each. DESTRUCTIVE: requires --demo.')

    def add_arguments(self, parser):
        parser.add_argument('--demo', action='store_true',
                            help='Confirm you want to WIPE and re-seed tenants.')
        parser.add_argument('--list', action='store_true',
                            help='Only list the tenants and exit (no changes).')
        parser.add_argument('--only', default='',
                            help='Comma-separated subdomains to seed (default: all).')
        parser.add_argument('--skip', default='',
                            help='Comma-separated subdomains to leave alone.')
        parser.add_argument('--no-backup', action='store_true',
                            help='Skip the safety backup (not recommended).')
        parser.add_argument('--backup-dir', default='',
                            help='Where to put the backup copies.')

    # ---------------------------------------------------------------- helpers
    def _use_master(self):
        """Point the default connection back at the master registry DB."""
        conn = connections['default']
        conn.close()
        conn.settings_dict = copy.deepcopy(settings.DATABASES['default'])
        conn.settings_dict['NAME'] = os.path.join(str(settings.BASE_DIR),
                                                  'db.sqlite3')

    def _tenant_file(self, subdomain):
        return os.path.join(str(settings.BASE_DIR), '%s.sqlite3' % subdomain)

    # ------------------------------------------------------------------ main
    def handle(self, *args, **options):
        self._use_master()

        wanted = {s.strip() for s in options['only'].split(',') if s.strip()}
        skip = {s.strip() for s in options['skip'].split(',') if s.strip()}

        rows = []
        for school in School.objects.exclude(subdomain__isnull=True).exclude(
                subdomain='').order_by('subdomain'):
            if wanted and school.subdomain not in wanted:
                continue
            if school.subdomain in skip:
                continue
            path = self._tenant_file(school.subdomain)
            size = os.path.getsize(path) if os.path.exists(path) else 0
            rows.append((school.subdomain, school.name, path, size))

        if not rows:
            raise CommandError(
                'No tenant schools found in the master registry '
                '(db.sqlite3). Nothing to do.')

        self.stdout.write(self.style.MIGRATE_HEADING(
            'Tenants found (%d):' % len(rows)))
        for sub, name, path, size in rows:
            self.stdout.write('  %-28s %-40s %s' % (
                sub, name[:40],
                '%.1f MB' % (size / 1048576) if size else '(no file yet)'))

        if options['list']:
            return

        if not options['demo']:
            raise CommandError(
                '\nRefusing to run: this DELETES all data in every tenant above '
                'and replaces it with demo data.\n'
                'Re-run with --demo once you are sure:\n'
                '    python manage.py seed_all_tenants --demo')

        # --- 1. Safety backup ------------------------------------------------
        if not options['no_backup']:
            stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M')
            backup_dir = (options['backup_dir'] or
                          os.path.join(str(settings.BASE_DIR), 'backups',
                                       'tenants-%s' % stamp))
            os.makedirs(backup_dir, exist_ok=True)
            self.stdout.write(self.style.MIGRATE_HEADING(
                '\nBacking up to %s' % backup_dir))
            master = os.path.join(str(settings.BASE_DIR), 'db.sqlite3')
            if os.path.exists(master):
                shutil.copy2(master, os.path.join(backup_dir, 'db.sqlite3'))
                self.stdout.write('  saved db.sqlite3 (master registry)')
            for sub, _name, path, size in rows:
                if size:
                    shutil.copy2(path, os.path.join(backup_dir,
                                                    '%s.sqlite3' % sub))
                    self.stdout.write('  saved %s.sqlite3' % sub)
            self.stdout.write(self.style.SUCCESS(
                '  Backup complete — restore any school with a file copy.'))
        else:
            backup_dir = None
            self.stdout.write(self.style.WARNING(
                '\n--no-backup: skipping the safety copy.'))

        # --- 2. Seed each tenant --------------------------------------------
        done, failed = [], []
        for sub, name, _path, _size in rows:
            self.stdout.write(self.style.MIGRATE_HEADING(
                '\n=== Seeding %s (%s) ===' % (sub, name)))
            try:
                # seed switches the connection to the tenant's own file.
                call_command('seed', demo=True, tenant=sub, verbosity=0)
                done.append(sub)
                self.stdout.write(self.style.SUCCESS('  done'))
            except Exception as exc:                      # keep going
                failed.append((sub, str(exc)))
                self.stdout.write(self.style.ERROR('  FAILED: %s' % exc))
            finally:
                # Always come back to the master before reading the next row.
                self._use_master()

        # --- 3. Report -------------------------------------------------------
        self.stdout.write(self.style.MIGRATE_HEADING('\nSummary'))
        self.stdout.write(self.style.SUCCESS(
            '  seeded : %d  (%s)' % (len(done), ', '.join(done) or '-')))
        if failed:
            self.stdout.write(self.style.ERROR('  failed : %d' % len(failed)))
            for sub, err in failed:
                self.stdout.write(self.style.ERROR('    %s -> %s' % (sub, err)))
        if backup_dir:
            self.stdout.write('  backup : %s' % backup_dir)
        self.stdout.write('\n  Every seeded school uses the password: roshni123')
