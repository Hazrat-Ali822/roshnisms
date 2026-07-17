"""Email alerts — a parallel channel to SMS/WhatsApp for guardian notices.

One entry point: ``send_email_alert(subject, body, to_email, msg_type)``. Every
attempt is recorded as an SmsMessage row (provider='email') so the Communication
page shows email alongside SMS/WhatsApp in one auditable log.

Real delivery uses Django's EMAIL_BACKEND. It defaults to the console backend
(prints, sends nothing) so everything works offline and in tests; point
EMAIL_BACKEND at SMTP on deploy to actually send. A school turns the feature on
from Settings (``School.email_alerts_enabled``).
"""
from django.conf import settings
from django.core.mail import send_mail

from .models import School, SmsMessage


def email_alerts_enabled():
    """True if the school has opted into email alerts."""
    school = School.objects.first()
    return bool(school and school.email_alerts_enabled)


def _from_address(school):
    if school and school.email_from:
        return school.email_from
    return getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@roshni.local')


def send_email_alert(subject, body, to_email='', msg_type='Email'):
    """Send (or log) one email alert and record it. Returns the status string.
    Never raises — a delivery failure is captured on the log row."""
    school = School.objects.first()
    to_email = (to_email or '').strip()
    if not to_email:
        return 'Skipped'                 # no address on file — nothing to do
    status, error = 'Queued', ''
    try:
        send_mail(subject, body, _from_address(school), [to_email],
                  fail_silently=False)
        status = 'Sent'
    except Exception as exc:  # noqa: BLE001 - record any failure, don't crash
        status, error = 'Failed', str(exc)[:200]

    SmsMessage.objects.create(
        recipients=to_email, to_phone='', body='%s: %s' % (subject, body),
        msg_type=msg_type, status=status, provider='email', error=error)
    return status
