"""Back up the SQLite database to a timestamped file under backups/ and keep
only the most recent N (default 30). Schedule daily.

Uses SQLite's online backup API, so it is safe to run while the server is up.
"""
import os
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand


def _prune(folder, keep):
    """Keep only the most recent `keep` db_*.sqlite3 files in a folder."""
    if not keep or keep <= 0:
        return 0
    files = sorted(Path(folder).glob('db_*.sqlite3'))
    removed = 0
    for old in files[:-keep]:
        old.unlink()
        removed += 1
    return removed


class Command(BaseCommand):
    help = ('Daily: back up the SQLite database (keeps the most recent N). '
            'Also copies to ROSHNI_BACKUP_DIR (USB/network/cloud folder) if set.')

    def add_arguments(self, parser):
        parser.add_argument('--keep', type=int, default=30,
                            help='How many backups to retain (0 = keep all).')

    def handle(self, *args, **options):
        engine = settings.DATABASES['default'].get('ENGINE', '')
        if 'sqlite3' not in engine:
            self.stderr.write('backup_db only supports SQLite (this project uses %s).'
                              % engine)
            return
        db_path = Path(settings.DATABASES['default']['NAME'])
        if not db_path.exists():
            self.stderr.write('Database file not found: %s' % db_path)
            return

        backups = Path(settings.BASE_DIR) / 'backups'
        backups.mkdir(exist_ok=True)
        stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        dest = backups / ('db_%s.sqlite3' % stamp)

        src = sqlite3.connect(str(db_path))
        dst = sqlite3.connect(str(dest))
        try:
            with dst:
                src.backup(dst)
        finally:
            src.close()
            dst.close()

        keep = options['keep']
        removed = _prune(backups, keep)

        # Off-site copy — the single most important protection against a dead /
        # stolen / ransomwared PC. Point ROSHNI_BACKUP_DIR at a USB drive,
        # a mapped network drive, or a synced cloud folder (Google Drive etc.).
        offsite_msg = 'off-site: not set (ROSHNI_BACKUP_DIR)'
        off = (os.environ.get('ROSHNI_BACKUP_DIR', '') or '').strip()
        if off:
            try:
                off_dir = Path(off)
                off_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dest, off_dir / dest.name)
                off_removed = _prune(off_dir, keep)
                offsite_msg = ('off-site: copied to %s (%d old removed)'
                               % (off, off_removed))
            except Exception as exc:  # noqa: BLE001 - report, don't crash the job
                offsite_msg = 'off-site FAILED (%s): %s' % (off, exc)

        self.stdout.write(self.style.SUCCESS(
            'Backup saved: backups/%s (%d old removed). %s'
            % (dest.name, removed, offsite_msg)))
