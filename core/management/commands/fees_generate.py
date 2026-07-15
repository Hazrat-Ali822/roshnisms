"""Generate this month's fee challans for all active students.

Schedule this once a month (e.g. on the 1st). It is idempotent: a student who
already has a challan for that month is skipped, so running it twice is safe.
Previous unpaid balances are carried forward automatically (existing logic).
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import Student
from core.views import _make_challan, _sync_fee_status


class Command(BaseCommand):
    help = "Monthly: create this month's challans for active students (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument('--month', type=int, default=0, help='1-12 (default: current)')
        parser.add_argument('--year', type=int, default=0, help='e.g. 2026 (default: current)')

    def handle(self, *args, **options):
        today = timezone.localdate()
        month = options['month'] or today.month
        year = options['year'] or today.year

        created = 0
        students = (Student.objects.filter(status='Active', graduated=False)
                    .select_related('classroom', 'route'))
        for s in students:
            _, made = _make_challan(s, year, month)
            if made:
                created += 1
                _sync_fee_status(s)

        self.stdout.write(self.style.SUCCESS(
            'Challans for %02d/%d: %d created (existing skipped).'
            % (month, year, created)))
