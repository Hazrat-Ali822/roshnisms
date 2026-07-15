"""Send an SMS fee reminder to the guardian of every student who still owes
money. Schedule weekly. Uses the configured SMS backend (console in dev, or a
real gateway once set). Every send is logged as an SmsMessage.
"""
from django.core.management.base import BaseCommand

from core.models import School, Student
from core.sms import notify


class Command(BaseCommand):
    help = 'Weekly: SMS a fee reminder to every defaulter guardian.'

    def handle(self, *args, **options):
        school = School.objects.first()
        sname = school.name if school else 'School'
        sent = no_phone = 0
        for s in (Student.objects.filter(status='Active', graduated=False)
                  .select_related('classroom').prefetch_related('challans__payments')):
            bal = sum(c.balance for c in s.challans.all())
            if bal <= 0:
                continue
            phone = (s.guardian_phone or '').strip()
            if not phone:
                no_phone += 1
                continue
            notify(
                'Dear %s, fee reminder from %s. Outstanding balance for %s is '
                'Rs %d. Kindly clear it at your earliest. Thank you.'
                % (s.guardian_name or 'Parent', sname, s.name, bal),
                to_phone=phone, recipients=s.guardian_name or s.name,
                msg_type='Fee Reminder')
            sent += 1

        self.stdout.write(self.style.SUCCESS(
            'Fee reminders: %d sent, %d defaulter(s) skipped (no phone).'
            % (sent, no_phone)))
