"""First-run bootstrap: make sure the system is usable the moment it starts.

Idempotent — safe to run on every launch. Creates a School row (if none) and a
default administrator login (if the system has no users yet) so a school can log
in immediately, then change the password and fill in their own details.
"""
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from core.models import Profile, School

DEFAULT_USERNAME = 'admin'
DEFAULT_PASSWORD = 'admin123'


class Command(BaseCommand):
    help = 'Ensure a School and an administrator login exist (first-run setup).'

    def handle(self, *args, **options):
        if not School.objects.exists():
            School.objects.create()
            self.stdout.write('Created a blank School (set it up in Settings).')

        # Only create the default admin when there are no login users at all,
        # so we never touch a school that has already set things up.
        if not User.objects.filter(is_superuser=False).exists() \
                and not Profile.objects.exists():
            user = User.objects.create_user(
                username=DEFAULT_USERNAME, password=DEFAULT_PASSWORD,
                first_name='Administrator')
            Profile.objects.create(user=user, role='admin',
                                   must_change_password=True)
            self.stdout.write(self.style.SUCCESS(
                'Default admin created  ->  username: %s   password: %s'
                % (DEFAULT_USERNAME, DEFAULT_PASSWORD)))
            self.stdout.write('Please sign in and change this password.')
        else:
            self.stdout.write('Admin/login already present — nothing to do.')
