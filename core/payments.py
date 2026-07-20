"""
Online fee-payment gateway abstraction for Roshni Public School.

Mirrors the shape of ``sms.py``: one small module that hides the differences
between payment providers behind a few functions. Each school configures it
from Settings; nothing here needs code changes to switch providers.

Three adapters:

  * ``bank``       -- Manual bank transfer. **Works fully offline.** The school
                      shows its account details; the parent submits the transfer
                      reference (and optional proof image); Accounts verifies it
                      and the money is recorded like a counter payment.
  * ``jazzcash``   -- JazzCash Page-Redirect (hosted checkout). Builds the signed
                      request and verifies the return hash. Needs merchant
                      credentials and a public HTTPS deployment, so it stays
                      hidden until the school enables + configures it.
  * ``easypaisa``  -- Easypaisa hosted checkout, same idea.

Design rule: a gateway is only ever offered to a parent when it is BOTH enabled
AND configured, and only when the school has switched online payments on. On a
plain LAN install everything stays off and parents simply pay at the office.
"""

import datetime
import hashlib
import hmac


# ---- What is available right now (used to decide what to show a parent) ----

def is_online_enabled(school):
    """True only if the school has switched online payments on at all."""
    return bool(school and school.online_payments_enabled)


def _bank_configured(school):
    return bool(school.pay_bank_account or school.pay_bank_iban)


def _raast_configured(school):
    # Ready once the school has provided either a scannable QR image or a
    # RAAST ID / alias a parent can pay to from any banking app.
    return bool(school.pay_raast_qr or school.pay_raast_id)


def _jazzcash_configured(school):
    return bool(school.pay_jazzcash_merchant and school.pay_jazzcash_password
                and school.pay_jazzcash_salt)


def _easypaisa_configured(school):
    return bool(school.pay_easypaisa_store and school.pay_easypaisa_hash)


def available_gateways(school):
    """List of (code, label) gateways a parent may actually use right now.

    Empty list means online payment is unavailable — the UI then tells the
    parent to pay at the office, so the system degrades gracefully offline.
    """
    if not is_online_enabled(school):
        return []
    out = []
    if school.pay_bank_enabled and _bank_configured(school):
        out.append(('bank', 'Bank transfer'))
    if school.pay_raast_enabled and _raast_configured(school):
        out.append(('raast', 'RAAST QR'))
    if school.pay_jazzcash_enabled and _jazzcash_configured(school):
        out.append(('jazzcash', 'JazzCash'))
    if school.pay_easypaisa_enabled and _easypaisa_configured(school):
        out.append(('easypaisa', 'Easypaisa'))
    return out


def gateway_available(school, code):
    return any(c == code for c, _ in available_gateways(school))


def bank_details(school):
    """The bank account shown to a parent for a manual transfer."""
    return {
        'bank': school.pay_bank_name, 'title': school.pay_bank_title,
        'account': school.pay_bank_account, 'iban': school.pay_bank_iban,
        'instructions': school.pay_bank_instructions,
    }


def raast_details(school):
    """The RAAST info shown to a parent: a scannable QR and/or a RAAST ID."""
    return {
        'id': school.pay_raast_id,
        'has_qr': bool(school.pay_raast_qr),
        'instructions': school.pay_raast_instructions,
    }


# ---- Reference generation -------------------------------------------------

def make_reference(intent_id):
    """A short, human-quotable reference for a payment attempt."""
    return 'PAY-%05d' % intent_id


# ---- Gateway request building (JazzCash / Easypaisa) ----------------------
#
# These build the signed parameters a browser auto-POSTs to the provider's
# hosted checkout page. They are only reached once the gateway is configured,
# which in practice means a public HTTPS deployment. On a LAN install they are
# never invoked, so the offline experience is unaffected.

JAZZCASH_POST_URL = ('https://sandbox.jazzcash.com.pk/CustomerPortal/'
                     'transactionmanagement/merchantform/')
EASYPAISA_POST_URL = ('https://easypay.easypaisa.com.pk/'
                      'easypay/Index.jsf')


def _jazzcash_secure_hash(fields, salt):
    """JazzCash integrity hash: HMAC-SHA256 of the salt followed by every
    non-empty field value in key order, joined by '&'."""
    ordered = [salt] + [str(fields[k]) for k in sorted(fields)
                        if k != 'pp_SecureHash' and str(fields.get(k, '')) != '']
    message = '&'.join(ordered)
    return hmac.new(salt.encode(), message.encode(),
                    hashlib.sha256).hexdigest().upper()


def build_jazzcash_request(school, intent, return_url):
    """Return (post_url, fields) for the JazzCash hosted redirect form."""
    now = datetime.datetime.now()
    txn_ref = 'T%s%05d' % (now.strftime('%Y%m%d%H%M%S'), intent.id)
    expiry = (now + datetime.timedelta(hours=1)).strftime('%Y%m%d%H%M%S')
    fields = {
        'pp_Version': '1.1',
        'pp_TxnType': 'MWALLET',
        'pp_Language': 'EN',
        'pp_MerchantID': school.pay_jazzcash_merchant,
        'pp_Password': school.pay_jazzcash_password,
        'pp_TxnRefNo': txn_ref,
        'pp_Amount': str(intent.amount * 100),   # amount is in paisa
        'pp_TxnCurrency': 'PKR',
        'pp_TxnDateTime': now.strftime('%Y%m%d%H%M%S'),
        'pp_TxnExpiryDateTime': expiry,
        'pp_BillReference': intent.ref or make_reference(intent.id),
        'pp_Description': 'School fee %s' % (intent.challan.label
                                             if intent.challan else ''),
        'pp_ReturnURL': return_url,
    }
    fields['pp_SecureHash'] = _jazzcash_secure_hash(
        fields, school.pay_jazzcash_salt)
    return JAZZCASH_POST_URL, fields


def verify_jazzcash_callback(school, data):
    """Verify a JazzCash return: recompute the hash and check success code.
    Returns (ok, txn_ref)."""
    got = (data.get('pp_SecureHash') or '').upper()
    check = {k: v for k, v in data.items() if k != 'pp_SecureHash'}
    expect = _jazzcash_secure_hash(check, school.pay_jazzcash_salt)
    ok = bool(got) and hmac.compare_digest(got, expect) \
        and str(data.get('pp_ResponseCode')) == '000'
    return ok, data.get('pp_TxnRefNo', '')


def _easypaisa_hash(fields, secret):
    ordered = '&'.join('%s=%s' % (k, fields[k]) for k in sorted(fields)
                       if str(fields.get(k, '')) != '')
    return hmac.new(secret.encode(), ordered.encode(),
                    hashlib.sha256).hexdigest().upper()


def build_easypaisa_request(school, intent, return_url):
    """Return (post_url, fields) for the Easypaisa hosted redirect form."""
    now = datetime.datetime.now()
    fields = {
        'storeId': school.pay_easypaisa_store,
        'amount': '%d.0' % intent.amount,
        'postBackURL': return_url,
        'orderRefNum': intent.ref or make_reference(intent.id),
        'expiryDate': (now + datetime.timedelta(hours=1)).strftime('%Y%m%d %H%M%S'),
        'paymentMethod': 'MA_PAYMENT_METHOD',
    }
    fields['merchantHashedReq'] = _easypaisa_hash(
        fields, school.pay_easypaisa_hash)
    return EASYPAISA_POST_URL, fields


def verify_easypaisa_callback(school, data):
    """Verify an Easypaisa return. Returns (ok, order_ref).

    The status alone is NOT trusted — the response must also carry a valid
    signature (HMAC of the response fields with our hash key), otherwise anyone
    could POST 'status=paid' and mark a payment complete without paying."""
    order_ref = data.get('orderRefNum', '')
    status_ok = str(data.get('status', '')).lower() in ('paid', 'success', '0000')
    got = (data.get('signature') or data.get('merchantHashedReq') or '').upper()
    rest = {k: v for k, v in data.items()
            if k not in ('signature', 'merchantHashedReq')}
    expect = _easypaisa_hash(rest, school.pay_easypaisa_hash)
    sig_ok = bool(got) and hmac.compare_digest(got, expect)
    return (status_ok and sig_ok), order_ref
