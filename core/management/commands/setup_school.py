"""Set up a FRESH school with no demo data.

Creates the school record and one Administrator (Office) login. That admin then
signs in and creates the rest (classes, subjects, staff, other user accounts)
from inside the app — so the school starts with a clean, empty system.

Usage (all on one line):
  python manage.py setup_school --school "City Grammar School" \
      --username office --password "StrongPass123" --name "Ayesha Khan"

Run without arguments to be prompted for each value.
"""
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError

from core.models import Profile, School


class Command(BaseCommand):
    help = 'Create a fresh school + one admin login (no demo data).'

    def add_arguments(self, parser):
        parser.add_argument('--school', default='', help='School name')
        parser.add_argument('--username', default='', help='Admin login username')
        parser.add_argument('--password', default='', help='Admin login password')
        parser.add_argument('--name', default='', help="Admin's full name")

    def handle(self, *args, **options):
        school_name = options['school'].strip() or input('School name: ').strip()
        username = options['username'].strip() or input('Admin username: ').strip()
        password = options['password'] or input('Admin password: ').strip()
        full_name = options['name'].strip() or input("Admin's full name: ").strip()

        if not (school_name and username and password):
            raise CommandError('School name, username and password are required.')
        if User.objects.filter(username=username).exists():
            raise CommandError('A user named "%s" already exists.' % username)

        school = School.objects.first()
        if school:
            school.name = school_name
            school.save(update_fields=['name'])
        else:
            school = School.objects.create(name=school_name)

        user = User.objects.create_user(
            username=username, password=password, first_name=full_name)
        Profile.objects.create(user=user, role='admin')

        self.stdout.write(self.style.SUCCESS(
            'School "%s" is ready.\n'
            'Admin login  -> username: %s\n'
            'Sign in, then use "Users & Roles" to add principal, teachers, '
            'parents and students, and "Classes & Subjects" to set up classes.'
            % (school.name, username)))
