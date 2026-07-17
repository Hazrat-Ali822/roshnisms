"""Daily fee maintenance (schedule this once a day).

- Applies the school's auto late fee to any challan that is now overdue,
  unpaid, and does not already have a late fee.
- Refreshes every active student's fee_status (Paid / Pending / Overdue) so
  "Overdue" appears automatically once a due date passes.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import FeeChallan, School, Student
from core.views import _refresh_late_fee, _sync_fee_status


class Command(BaseCommand):
    help = 'Daily: auto/escalating late fee on overdue challans + refresh statuses.'

    def handle(self, *args, **options):
        today = timezone.localdate()
        school = School.objects.first()
        late = school.late_fee_amount if school else 0

        applied = 0
        if late:
            for ch in FeeChallan.objects.filter(carried_forward=False):
                if _refresh_late_fee(school, ch, today):
                    applied += 1

        synced = 0
        for s in Student.objects.filter(graduated=False, status='Active'):
            _sync_fee_status(s)
            synced += 1

        self.stdout.write(self.style.SUCCESS(
            'Daily fees: %d late fee(s) applied, %d status(es) refreshed.'
            % (applied, synced)))
