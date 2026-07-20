"""Section 3 — online fee payments: gateway availability, the offline-safe
bank-transfer flow (submit -> Accounts verify -> recorded), and the gateway
hash/verify helpers."""
import datetime

from django.test import Client, TestCase

from core import payments
from core.models import FeeChallan, FeePayment, OnlinePayment
from core.tests.factory import build_world, PASSWORD


def _challan(student, balance=5000):
    """A simple unpaid challan with the given payable amount."""
    return FeeChallan.objects.create(
        student=student, year=2026, month=6, tuition=balance,
        due_date=datetime.date(2026, 6, 10))


class GatewayAvailabilityTests(TestCase):
    def setUp(self):
        self.w = build_world()
        self.s = self.w.school

    def test_nothing_offered_when_off(self):
        self.s.online_payments_enabled = False
        self.s.save()
        self.assertEqual(payments.available_gateways(self.s), [])

    def test_bank_needs_account_details(self):
        self.s.online_payments_enabled = True
        self.s.pay_bank_enabled = True
        self.s.save()
        # No account number/IBAN yet -> not offered.
        self.assertEqual(payments.available_gateways(self.s), [])
        self.s.pay_bank_account = '1234567890'
        self.s.save()
        self.assertEqual(payments.available_gateways(self.s), [('bank', 'Bank transfer')])

    def test_jazzcash_needs_credentials(self):
        self.s.online_payments_enabled = True
        self.s.pay_jazzcash_enabled = True
        self.s.pay_jazzcash_merchant = 'M1'
        self.s.pay_jazzcash_password = 'P1'
        self.s.pay_jazzcash_salt = 'SALT'
        self.s.save()
        codes = [c for c, _ in payments.available_gateways(self.s)]
        self.assertIn('jazzcash', codes)


class BankTransferFlowTests(TestCase):
    def setUp(self):
        self.w = build_world()
        self.s = self.w.school
        self.s.online_payments_enabled = True
        self.s.pay_bank_enabled = True
        self.s.pay_bank_account = '1234567890'
        self.s.pay_bank_name = 'Test Bank'
        self.s.save()
        self.challan = _challan(self.w.ayaan, 5000)

    def _parent(self):
        c = Client()
        c.login(username='parent1', password=PASSWORD)
        return c

    def test_parent_submits_bank_transfer_creates_pending(self):
        c = self._parent()
        r = c.post('/my-fees/pay/%d/' % self.challan.id,
                   {'gateway': 'bank', 'amount': '5000',
                    'bank_ref': 'TID-999', 'note': 'paid today'})
        self.assertEqual(r.status_code, 302)
        intent = OnlinePayment.objects.get(challan=self.challan)
        self.assertEqual(intent.status, 'pending')
        self.assertEqual(intent.amount, 5000)
        self.assertEqual(intent.gateway_ref, 'TID-999')
        # Not recorded as money yet — Accounts must verify first.
        self.assertFalse(FeePayment.objects.filter(student=self.w.ayaan).exists())

    def test_accounts_verify_records_payment(self):
        c = self._parent()
        c.post('/my-fees/pay/%d/' % self.challan.id,
               {'gateway': 'bank', 'amount': '5000', 'bank_ref': 'TID-1'})
        intent = OnlinePayment.objects.get(challan=self.challan)

        fin = Client(); fin.login(username='finance1', password=PASSWORD)
        r = fin.post('/fees/online/',
                     {'intent_id': intent.id, 'action': 'approve'})
        self.assertEqual(r.status_code, 302)
        intent.refresh_from_db()
        self.assertEqual(intent.status, 'paid')
        self.assertIsNotNone(intent.payment)
        pay = intent.payment
        self.assertEqual(pay.amount, 5000)
        self.assertEqual(pay.mode, 'Bank')
        self.assertTrue(pay.receipt_no)
        # Challan is now settled.
        self.challan.refresh_from_db()
        self.assertEqual(self.challan.balance, 0)

    def test_accounts_reject_does_not_record(self):
        c = self._parent()
        c.post('/my-fees/pay/%d/' % self.challan.id,
               {'gateway': 'bank', 'amount': '5000', 'bank_ref': 'TID-2'})
        intent = OnlinePayment.objects.get(challan=self.challan)
        fin = Client(); fin.login(username='finance1', password=PASSWORD)
        fin.post('/fees/online/', {'intent_id': intent.id, 'action': 'reject'})
        intent.refresh_from_db()
        self.assertEqual(intent.status, 'rejected')
        self.assertFalse(FeePayment.objects.filter(student=self.w.ayaan).exists())

    def test_amount_cannot_exceed_balance(self):
        c = self._parent()
        c.post('/my-fees/pay/%d/' % self.challan.id,
               {'gateway': 'bank', 'amount': '999999', 'bank_ref': 'X'})
        intent = OnlinePayment.objects.get(challan=self.challan)
        self.assertEqual(intent.amount, 5000)   # clamped to balance

    def test_parent_cannot_pay_another_familys_challan(self):
        other = _challan(self.w.hira, 3000)     # Hira is not parent1's child
        c = self._parent()
        r = c.post('/my-fees/pay/%d/' % other.id,
                   {'gateway': 'bank', 'amount': '3000', 'bank_ref': 'Z'})
        self.assertEqual(r.status_code, 403)
        self.assertFalse(OnlinePayment.objects.filter(challan=other).exists())

    def test_pay_button_absent_when_online_off(self):
        self.s.online_payments_enabled = False
        self.s.save()
        c = self._parent()
        r = c.get('/my-fees/pay/%d/' % self.challan.id)
        # Redirected away because no gateway is available.
        self.assertEqual(r.status_code, 302)


class RaastFlowTests(TestCase):
    """RAAST QR (static merchant QR): offered when configured, and paid through
    the same offline submit -> Accounts verify -> recorded flow as a bank
    transfer, with no payment API."""
    def setUp(self):
        self.w = build_world()
        self.s = self.w.school
        self.s.online_payments_enabled = True
        self.s.pay_raast_enabled = True
        self.s.pay_raast_id = '03001234567'   # RAAST alias — enough to configure
        self.s.save()
        self.challan = _challan(self.w.ayaan, 5000)

    def _parent(self):
        c = Client()
        c.login(username='parent1', password=PASSWORD)
        return c

    def test_raast_needs_qr_or_id(self):
        self.s.pay_raast_id = ''
        self.s.save()
        self.assertNotIn('raast', [c for c, _ in payments.available_gateways(self.s)])
        self.s.pay_raast_id = '03001234567'
        self.s.save()
        self.assertIn('raast', [c for c, _ in payments.available_gateways(self.s)])

    def test_raast_off_when_disabled(self):
        self.s.pay_raast_enabled = False
        self.s.save()
        self.assertNotIn('raast', [c for c, _ in payments.available_gateways(self.s)])

    def test_parent_submits_raast_creates_pending(self):
        c = self._parent()
        r = c.post('/my-fees/pay/%d/' % self.challan.id,
                   {'gateway': 'raast', 'amount': '5000', 'raast_ref': 'RST-777'})
        self.assertEqual(r.status_code, 302)
        intent = OnlinePayment.objects.get(challan=self.challan)
        self.assertEqual(intent.gateway, 'raast')
        self.assertEqual(intent.status, 'pending')
        self.assertEqual(intent.gateway_ref, 'RST-777')
        self.assertFalse(FeePayment.objects.filter(student=self.w.ayaan).exists())

    def test_accounts_verify_records_raast_payment(self):
        c = self._parent()
        c.post('/my-fees/pay/%d/' % self.challan.id,
               {'gateway': 'raast', 'amount': '5000', 'raast_ref': 'RST-1'})
        intent = OnlinePayment.objects.get(challan=self.challan)
        fin = Client(); fin.login(username='finance1', password=PASSWORD)
        fin.post('/fees/online/', {'intent_id': intent.id, 'action': 'approve'})
        intent.refresh_from_db()
        self.assertEqual(intent.status, 'paid')
        self.assertEqual(intent.payment.mode, 'RAAST')
        self.challan.refresh_from_db()
        self.assertEqual(self.challan.balance, 0)


class GatewayHashTests(TestCase):
    def setUp(self):
        self.w = build_world()
        self.s = self.w.school
        self.s.pay_jazzcash_merchant = 'M1'
        self.s.pay_jazzcash_password = 'P1'
        self.s.pay_jazzcash_salt = 'INTEGRITYSALT'
        self.s.save()
        self.challan = _challan(self.w.ayaan, 5000)
        self.intent = OnlinePayment.objects.create(
            student=self.w.ayaan, challan=self.challan, gateway='jazzcash',
            amount=5000, ref='PAY-00001')

    def test_jazzcash_request_is_signed(self):
        url, fields = payments.build_jazzcash_request(
            self.s, self.intent, 'https://x/return')
        self.assertTrue(url.startswith('https://'))
        self.assertIn('pp_SecureHash', fields)
        self.assertEqual(fields['pp_Amount'], '500000')   # paisa

    def test_jazzcash_callback_verifies_valid_hash(self):
        data = {
            'pp_MerchantID': 'M1', 'pp_Amount': '500000',
            'pp_BillReference': 'PAY-00001', 'pp_ResponseCode': '000',
            'pp_TxnRefNo': 'T123',
        }
        data['pp_SecureHash'] = payments._jazzcash_secure_hash(
            data, self.s.pay_jazzcash_salt)
        ok, ref = payments.verify_jazzcash_callback(self.s, data)
        self.assertTrue(ok)

    def test_jazzcash_callback_rejects_tampered_hash(self):
        data = {'pp_ResponseCode': '000', 'pp_BillReference': 'PAY-00001',
                'pp_SecureHash': 'DEADBEEF'}
        ok, _ = payments.verify_jazzcash_callback(self.s, data)
        self.assertFalse(ok)

    def test_easypaisa_callback_rejects_unsigned_status(self):
        # Just claiming status=paid must NOT be accepted without a signature.
        self.s.pay_easypaisa_hash = 'EPHASHKEY'
        self.s.save()
        ok, _ = payments.verify_easypaisa_callback(
            self.s, {'status': 'paid', 'orderRefNum': 'PAY-00001'})
        self.assertFalse(ok)

    def test_easypaisa_callback_accepts_signed(self):
        self.s.pay_easypaisa_hash = 'EPHASHKEY'
        self.s.save()
        data = {'status': 'paid', 'orderRefNum': 'PAY-00001'}
        data['signature'] = payments._easypaisa_hash(data, 'EPHASHKEY')
        ok, ref = payments.verify_easypaisa_callback(self.s, data)
        self.assertTrue(ok)
        self.assertEqual(ref, 'PAY-00001')


class ProofAccessTests(TestCase):
    def setUp(self):
        self.w = build_world()
        s = self.w.school
        s.online_payments_enabled = True
        s.pay_bank_enabled = True
        s.pay_bank_account = '123'
        s.save()
        self.challan = _challan(self.w.ayaan, 5000)
        from django.core.files.uploadedfile import SimpleUploadedFile
        c = Client(); c.login(username='parent1', password=PASSWORD)
        c.post('/my-fees/pay/%d/' % self.challan.id, {
            'gateway': 'bank', 'amount': '5000', 'bank_ref': 'T1',
            'proof': SimpleUploadedFile('p.png', b'\x89PNG\r\n\x1a\nx',
                                        content_type='image/png')})
        self.intent = OnlinePayment.objects.get(challan=self.challan)

    def test_finance_can_view_proof(self):
        c = Client(); c.login(username='finance1', password=PASSWORD)
        r = c.get('/fees/online/proof/%d/' % self.intent.id)
        self.assertEqual(r.status_code, 200)

    def test_parent_cannot_view_proof(self):
        c = Client(); c.login(username='parent1', password=PASSWORD)
        r = c.get('/fees/online/proof/%d/' % self.intent.id)
        self.assertIn(r.status_code, (302, 403))
