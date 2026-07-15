"""
SMS gateway for Roshni Public School SMS.

One entry point: ``send_sms(text, to_phone=..., recipients=..., msg_type=...)``.
Every send is recorded as an SmsMessage row (with status and any error), so the
Communication page shows a full, auditable log regardless of backend.

Backends (configured in settings.SMS_BACKEND):
  * 'console' (default) -- prints to the server terminal and logs the message.
                           No network needed. Use this in development.
  * 'twilio'            -- Twilio REST API (needs SID, token and a from-number).
  * 'http'              -- a generic HTTP SMS gateway (set a URL with {to}/{text}).

Because real delivery needs your own provider account and outbound network
access, switch SMS_BACKEND to 'twilio' or 'http' and add your credentials on the
machine where you deploy. Until then, 'console' keeps everything working and
logged without sending anything.
"""

import base64
import json
import urllib.parse
import urllib.request

from django.conf import settings

from .models import School, SmsMessage

# Settings-name -> School-field, so a school can configure SMS from the UI and
# the DB value wins over settings.py (which stays as a fallback / default).
_SCHOOL_FIELDS = {
    'SMS_BACKEND': 'sms_backend',
    'SMS_COUNTRY_CODE': 'sms_country_code',
    'SMS_HTTP_URL': 'sms_http_url',
    'SMS_HTTP_METHOD': 'sms_http_method',
    'SMS_TWILIO_SID': 'sms_twilio_sid',
    'SMS_TWILIO_TOKEN': 'sms_twilio_token',
    'SMS_TWILIO_FROM': 'sms_twilio_from',
}
_NOTIFY_FIELDS = {
    'SMS_NOTIFY_ON_ABSENT': 'notify_absent',
    'SMS_NOTIFY_ON_PAYMENT': 'notify_payment',
    'SMS_NOTIFY_ON_FEE_DUE': 'notify_feedue',
}


def _cfg(name, default=''):
    """Read an SMS setting, preferring the School row (UI-editable) over
    settings.py so schools don't have to touch code to enable SMS."""
    field = _SCHOOL_FIELDS.get(name)
    if field:
        school = School.objects.first()
        val = getattr(school, field, '') if school else ''
        if val:
            return val
    return getattr(settings, name, default)


def normalize_phone(raw):
    """Turn a stored number like '0300-1234567' into '+923001234567'."""
    if not raw:
        return ''
    digits = ''.join(ch for ch in raw if ch.isdigit() or ch == '+')
    cc = _cfg('SMS_COUNTRY_CODE', '+92')
    if digits.startswith('+'):
        return digits
    if digits.startswith('00'):
        return '+' + digits[2:]
    if digits.startswith('0'):
        return cc + digits[1:]
    if cc and not digits.startswith(cc.lstrip('+')):
        return cc + digits
    return digits


def _send_twilio(to_e164, text):
    sid = _cfg('SMS_TWILIO_SID')
    token = _cfg('SMS_TWILIO_TOKEN')
    from_no = _cfg('SMS_TWILIO_FROM')
    if not (sid and token and from_no):
        raise ValueError('Twilio is not configured (SID / token / from-number).')
    url = 'https://api.twilio.com/2010-04-01/Accounts/%s/Messages.json' % sid
    data = urllib.parse.urlencode(
        {'From': from_no, 'To': to_e164, 'Body': text}).encode()
    req = urllib.request.Request(url, data=data, method='POST')
    auth = base64.b64encode(('%s:%s' % (sid, token)).encode()).decode()
    req.add_header('Authorization', 'Basic %s' % auth)
    with urllib.request.urlopen(req, timeout=15) as resp:
        resp.read()


def _send_http(to_e164, text):
    url_tmpl = _cfg('SMS_HTTP_URL')
    if not url_tmpl:
        raise ValueError('SMS_HTTP_URL is not configured.')
    url = url_tmpl.replace('{to}', urllib.parse.quote(to_e164)).replace(
        '{text}', urllib.parse.quote(text))
    method = (_cfg('SMS_HTTP_METHOD', 'GET') or 'GET').upper()
    if method == 'POST':
        req = urllib.request.Request(url, data=b'', method='POST')
    else:
        req = urllib.request.Request(url, method='GET')
    with urllib.request.urlopen(req, timeout=15) as resp:
        resp.read()


def send_sms(text, to_phone='', recipients='', msg_type='Manual'):
    """Send (or log) one SMS and record it. Returns the resulting status string."""
    backend = (_cfg('SMS_BACKEND', 'console') or 'console').lower()
    to_e164 = normalize_phone(to_phone)
    label = recipients or to_e164 or to_phone or 'Unknown'
    status, error = 'Queued', ''

    if backend == 'console':
        print('[SMS][console] to=%s :: %s' % (to_e164 or recipients, text))
        status = 'Console'
    elif backend == 'twilio':
        try:
            _send_twilio(to_e164, text)
            status = 'Sent'
        except Exception as exc:  # noqa: BLE001 - record any failure
            status, error = 'Failed', str(exc)[:200]
    elif backend == 'http':
        try:
            _send_http(to_e164, text)
            status = 'Sent'
        except Exception as exc:  # noqa: BLE001
            status, error = 'Failed', str(exc)[:200]
    else:
        status, error = 'Failed', 'Unknown SMS_BACKEND: %s' % backend

    SmsMessage.objects.create(
        recipients=label, to_phone=to_e164, body=text, msg_type=msg_type,
        status=status, provider=backend, error=error)
    return status


def sms_enabled(flag_name, default=True):
    """Helper for notification toggles (e.g. SMS_NOTIFY_ON_PAYMENT). Reads the
    School row first so each school controls its own alerts from Settings."""
    field = _NOTIFY_FIELDS.get(flag_name)
    if field:
        school = School.objects.first()
        if school:
            return bool(getattr(school, field))
    return bool(getattr(settings, flag_name, default))


# =====================================================================
# WhatsApp — same idea as SMS, a different channel. Every message is still
# logged as an SmsMessage row (provider='whatsapp:...') so the Communication
# page shows one unified, auditable history. Two providers are supported:
#   * twilio -- Twilio WhatsApp (reuses the Twilio SID/token; needs a WA sender)
#   * meta   -- Meta WhatsApp Business Cloud API (Graph API token + phone id)
# =====================================================================


def _send_whatsapp_twilio(school, to_e164, text):
    sid = _cfg('SMS_TWILIO_SID') or school.sms_twilio_sid
    token = _cfg('SMS_TWILIO_TOKEN') or school.sms_twilio_token
    sender = school.whatsapp_from
    if not (sid and token and sender):
        raise ValueError('Twilio WhatsApp is not configured (SID / token / sender).')
    url = 'https://api.twilio.com/2010-04-01/Accounts/%s/Messages.json' % sid
    data = urllib.parse.urlencode({
        'From': 'whatsapp:%s' % sender, 'To': 'whatsapp:%s' % to_e164,
        'Body': text}).encode()
    req = urllib.request.Request(url, data=data, method='POST')
    auth = base64.b64encode(('%s:%s' % (sid, token)).encode()).decode()
    req.add_header('Authorization', 'Basic %s' % auth)
    with urllib.request.urlopen(req, timeout=15) as resp:
        resp.read()


def _send_whatsapp_meta(school, to_e164, text):
    token = school.whatsapp_token
    phone_id = school.whatsapp_phone_id
    if not (token and phone_id):
        raise ValueError('Meta WhatsApp is not configured (token / phone id).')
    url = 'https://graph.facebook.com/v19.0/%s/messages' % phone_id
    body = json.dumps({
        'messaging_product': 'whatsapp',
        'to': to_e164.lstrip('+'),
        'type': 'text', 'text': {'body': text}}).encode()
    req = urllib.request.Request(url, data=body, method='POST')
    req.add_header('Authorization', 'Bearer %s' % token)
    req.add_header('Content-Type', 'application/json')
    with urllib.request.urlopen(req, timeout=15) as resp:
        resp.read()


def send_whatsapp(text, to_phone='', recipients='', msg_type='Manual'):
    """Send (or log) one WhatsApp message and record it. Returns the status."""
    school = School.objects.first()
    to_e164 = normalize_phone(to_phone)
    label = recipients or to_e164 or to_phone or 'Unknown'
    provider = (getattr(school, 'whatsapp_provider', 'twilio') or 'twilio')
    status, error = 'Queued', ''

    if not (school and school.whatsapp_enabled):
        # Test mode: nothing sent, but still logged so schools can see it work.
        print('[WhatsApp][console] to=%s :: %s' % (to_e164 or recipients, text))
        status = 'Console'
    else:
        try:
            if provider == 'meta':
                _send_whatsapp_meta(school, to_e164, text)
            else:
                _send_whatsapp_twilio(school, to_e164, text)
            status = 'Sent'
        except Exception as exc:  # noqa: BLE001 - record any failure
            status, error = 'Failed', str(exc)[:200]

    SmsMessage.objects.create(
        recipients=label, to_phone=to_e164, body=text, msg_type=msg_type,
        status=status, provider='whatsapp:%s' % provider, error=error)
    return status


def notify(text, to_phone='', recipients='', msg_type='Manual'):
    """Send a guardian alert over the school's chosen channel(s): SMS, WhatsApp
    or both. Each channel is logged separately. Returns a list of statuses.

    Default channel is 'sms', so callers that used to call send_sms behave
    identically until a school opts into WhatsApp from Settings.
    """
    school = School.objects.first()
    channel = getattr(school, 'notify_channel', 'sms') if school else 'sms'
    results = []
    if channel in ('sms', 'both'):
        results.append(send_sms(text, to_phone, recipients, msg_type))
    if channel in ('whatsapp', 'both') and school and school.whatsapp_enabled:
        results.append(send_whatsapp(text, to_phone, recipients, msg_type))
    if not results:
        # Channel is 'whatsapp' but WhatsApp isn't ready — fall back to SMS so
        # the alert is never silently dropped.
        results.append(send_sms(text, to_phone, recipients, msg_type))
    return results