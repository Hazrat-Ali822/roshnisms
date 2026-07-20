"""Web Push delivery (browser / installed-PWA notifications).

A thin wrapper over pywebpush + the VAPID keys in settings. Best-effort: if
push isn't configured, or a browser subscription has expired, we degrade
silently (SMS/WhatsApp/email remain the primary channels). Dead subscriptions
(404/410) are pruned automatically.
"""
import json

from django.conf import settings


def push_enabled():
    return bool(getattr(settings, 'VAPID_PRIVATE_KEY', ''))


def guardian_users(student):
    """Users who should hear about this student: the student's own login and any
    parent whose primary child or child-list includes them."""
    from django.contrib.auth.models import User
    from core.models import Profile
    ids = set(Profile.objects.filter(student=student)
              .values_list('user_id', flat=True))
    ids |= set(Profile.objects.filter(children=student)
               .values_list('user_id', flat=True))
    return list(User.objects.filter(id__in=ids))


def send_web_push(users, title, body, url='/'):
    """Push a notification to every browser subscription of the given users.
    Returns the number of successful sends (0 if push is off)."""
    if not push_enabled() or not users:
        return 0
    from pywebpush import webpush, WebPushException
    from core.models import PushSubscription

    payload = json.dumps({'title': title, 'body': body, 'url': url})
    sent = 0
    subs = PushSubscription.objects.filter(user__in=users)
    for s in subs:
        try:
            webpush(
                subscription_info={'endpoint': s.endpoint,
                                   'keys': {'p256dh': s.p256dh, 'auth': s.auth}},
                data=payload,
                vapid_private_key=settings.VAPID_PRIVATE_KEY,
                vapid_claims={'sub': settings.VAPID_CLAIM_EMAIL})
            sent += 1
        except WebPushException as ex:      # noqa: BLE001
            resp = getattr(ex, 'response', None)
            if resp is not None and resp.status_code in (404, 410):
                s.delete()                  # subscription gone — prune it
        except Exception:                   # noqa: BLE001 - never break a request
            pass
    return sent


def push_student_guardians(student, title, body, url='/'):
    """Convenience: web-push everyone linked to a student."""
    return send_web_push(guardian_users(student), title, body, url)
