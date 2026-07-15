"""Daily fee maintenance (schedule this once a day).

- Applies the school's auto late fee to any challan that is now overdue,
  unpaid, and does not already have a late fee.
- Refreshes every active student's fee_status (Paid / Pending / Overdue) so
  "Overdue" appears automatically once a due date passes.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import FeeChallan, School, Student
from core.views import _sync_fee_status


class Command(BaseCommand):
    help = 'Daily: auto late fee on overdue challans + refresh fee statuses.'

    def handle(self, *args, **options):
        today = timezone.localdate()
        school = School.objects.first()
        late = school.late_fee_amount if school else 0

        applied = 0
        if late:
            for ch in FeeChallan.objects.filter(carried_forward=False):
                if ch.balance > 0 and ch.due_date < today and ch.late_fee == 0:
                    ch.late_fee = late
                    ch.save(update_fields=['late_fee'])
                    applied += 1

        synced = 0
        for s in Student.objects.filter(graduated=False, status='Active'):
            _sync_fee_status(s)
            synced += 1

        self.stdout.write(self.style.SUCCESS(
            'Daily fees: %d late fee(s) applied, %d status(es) refreshed.'
            % (applied, synced)))
