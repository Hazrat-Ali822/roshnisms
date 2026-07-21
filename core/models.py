import datetime

from django.contrib.auth.models import User
from django.db import models

from core.crypto import EncryptedCharField


def grade_for(percentage):
    """Convert a percentage into a letter grade (school's grading scheme)."""
    if percentage >= 90:
        return 'A+'
    if percentage >= 80:
        return 'A'
    if percentage >= 70:
        return 'B'
    if percentage >= 60:
        return 'C'
    if percentage >= 50:
        return 'D'
    return 'F'


class School(models.Model):
    subdomain = models.SlugField(max_length=40, unique=True, null=True, blank=True)
    subscription_active = models.BooleanField(default=True)
    subscription_start = models.DateField(null=True, blank=True)
    subscription_end = models.DateField(null=True, blank=True)
    last_daily_run = models.DateField(null=True, blank=True)
    name = models.CharField(max_length=120, default='Roshni Public School')
    campus = models.CharField(max_length=120, default='Main Campus, Lahore')
    session = models.CharField(max_length=20, default='2025-26')
    
    # SaaS administrator credentials. admin_password holds a Django password
    # HASH (never plaintext); it exists only so a wiped/rebuilt tenant database
    # can recreate this school's admin login. See core.crypto.apply_stored_password.
    admin_username = models.CharField(max_length=60, blank=True)
    admin_email = models.CharField(max_length=120, blank=True)
    admin_password = models.CharField(max_length=128, blank=True)
    subscription_rate = models.PositiveIntegerField(default=5000)
    
    final_grade = models.CharField(max_length=10, default='10')
    pass_mark = models.PositiveIntegerField(default=40)
    hostel_fee = models.PositiveIntegerField(default=8000)
    # Automation: late fee auto-applied to an overdue unpaid challan by the
    # daily job. 0 = do not apply late fees automatically. The fee escalates by
    # `late_fee_per_week` for every full week a challan stays overdue, capped at
    # `late_fee_max` (0 = no cap).
    late_fee_amount = models.PositiveIntegerField(default=0)      # base, week 0
    late_fee_per_week = models.PositiveIntegerField(default=0)    # added per week overdue
    late_fee_max = models.PositiveIntegerField(default=0)         # ceiling, 0 = none
    # Email alerts (payment receipts, absence). Uses Django's EMAIL_BACKEND —
    # console by default (logged, not sent) until SMTP is configured on deploy.
    email_alerts_enabled = models.BooleanField(default=False)
    email_from = models.CharField(max_length=120, blank=True)
    # Branding — each school makes the system look like their own.
    logo = models.FileField(upload_to='school/', blank=True, null=True)
    primary_color = models.CharField(max_length=7, default='#15294D')   # headers/sidebar
    accent_color = models.CharField(max_length=7, default='#0E7C66')    # buttons/highlights
    # This school's branded Android app (.apk built with PWABuilder from the
    # school's own portal URL). When present, a "Download App" button appears on
    # the portal so parents/students can install it (no Play Store needed).
    app_apk = models.FileField(upload_to='school/apk/', blank=True, null=True)
    # Short name shown UNDER the phone app icon (the full school name is often
    # too long to fit). Blank = fall back to the school name. e.g. "Sudhum
    # Academy". Feeds the PWA manifest short_name.
    app_name = models.CharField(max_length=30, blank=True)
    # New logins (auto-created when a student/staff is added) get this password;
    # each person changes it themselves after signing in.
    default_password = models.CharField(max_length=64, default='school123')

    # --- SMS / notifications (configurable from the Settings page) ---
    # backend: 'console' (log only, default), 'http' (generic gateway / WhatsApp
    # provider) or 'twilio'. DB config here overrides settings.py.
    SMS_BACKENDS = [('console', 'Off — log only (test mode)'),
                    ('http', 'HTTP gateway (SMS / WhatsApp provider)'),
                    ('twilio', 'Twilio')]
    sms_backend = models.CharField(max_length=10, default='console',
                                   choices=SMS_BACKENDS)
    sms_country_code = models.CharField(max_length=6, default='+92')
    sms_http_url = models.CharField(max_length=300, blank=True)     # use {to} and {text}
    sms_http_method = models.CharField(max_length=4, default='GET')
    sms_twilio_sid = models.CharField(max_length=80, blank=True)
    sms_twilio_token = EncryptedCharField(max_length=255, blank=True)  # encrypted at rest
    sms_twilio_from = models.CharField(max_length=30, blank=True)
    notify_absent = models.BooleanField(default=True)
    notify_payment = models.BooleanField(default=True)
    notify_feedue = models.BooleanField(default=True)

    # --- WhatsApp notifications (extends the SMS module) ---
    # Alerts can go over SMS, WhatsApp, or both. Default 'sms' keeps existing
    # behaviour unchanged. WhatsApp is only used when it is enabled + configured.
    NOTIFY_CHANNELS = [('sms', 'SMS only'), ('whatsapp', 'WhatsApp only'),
                       ('both', 'SMS + WhatsApp')]
    WA_PROVIDERS = [('twilio', 'Twilio WhatsApp'),
                    ('meta', 'Meta WhatsApp Cloud API')]
    notify_channel = models.CharField(max_length=10, default='sms',
                                      choices=NOTIFY_CHANNELS)
    whatsapp_enabled = models.BooleanField(default=False)
    whatsapp_provider = models.CharField(max_length=10, default='twilio',
                                         choices=WA_PROVIDERS)
    whatsapp_from = models.CharField(max_length=30, blank=True)   # twilio WA sender
    whatsapp_token = EncryptedCharField(max_length=512, blank=True)  # meta access token, encrypted at rest
    whatsapp_phone_id = models.CharField(max_length=40, blank=True)  # meta phone id

    # --- Online fee payments (configurable from the Settings page) ---
    # Off by default so nothing changes for a LAN-only school. When on,
    # parents see a "Pay online" button on their fee vouchers. Each gateway
    # is only offered once it is both enabled AND configured.
    online_payments_enabled = models.BooleanField(default=False)
    pay_bank_enabled = models.BooleanField(default=True)
    pay_jazzcash_enabled = models.BooleanField(default=False)
    pay_easypaisa_enabled = models.BooleanField(default=False)
    # Bank transfer — works fully offline: the school shows its account and a
    # parent submits the transfer reference, which Accounts then verifies.
    pay_bank_name = models.CharField(max_length=80, blank=True)
    pay_bank_title = models.CharField(max_length=120, blank=True)   # account title
    pay_bank_account = models.CharField(max_length=40, blank=True)
    pay_bank_iban = models.CharField(max_length=40, blank=True)
    pay_bank_instructions = models.CharField(max_length=250, blank=True)
    # JazzCash merchant credentials (needed only for a public HTTPS deployment).
    pay_jazzcash_merchant = models.CharField(max_length=40, blank=True)
    pay_jazzcash_password = EncryptedCharField(max_length=255, blank=True)  # encrypted at rest
    pay_jazzcash_salt = EncryptedCharField(max_length=255, blank=True)   # integrity salt, encrypted at rest
    # Easypaisa merchant credentials.
    pay_easypaisa_store = models.CharField(max_length=40, blank=True)
    pay_easypaisa_hash = EncryptedCharField(max_length=300, blank=True)   # encrypted at rest
    # RAAST QR (State Bank instant payment). Static merchant QR — no API/keys:
    # the school uploads the QR image its bank/app provides; a parent scans it
    # in any banking app, pays, and submits the transaction reference for
    # Accounts to verify (the same offline-friendly flow as a bank transfer).
    pay_raast_enabled = models.BooleanField(default=False)
    pay_raast_id = models.CharField(max_length=80, blank=True)   # RAAST ID / merchant alias / IBAN
    pay_raast_qr = models.FileField(upload_to='school/', blank=True, null=True)
    pay_raast_instructions = models.CharField(max_length=250, blank=True)

    def __str__(self):
        return self.name

    def get_portal_url(self, request):
        host = request.get_host()
        sub = self.subdomain or 'default'
        if sub == 'default':
            return f"{request.scheme}://{host}/"
        return f"{request.scheme}://{host}/{sub}/"


class ClassRoom(models.Model):
    name = models.CharField(max_length=20)            # e.g. "9"
    section = models.CharField(max_length=5, default='A')
    monthly_fee = models.PositiveIntegerField(default=5500)

    class Meta:
        ordering = ['name', 'section']

    def __str__(self):
        return f"{self.name}-{self.section}"


class Student(models.Model):
    FEE_CHOICES = [('Paid', 'Paid'), ('Pending', 'Pending'), ('Overdue', 'Overdue')]

    name = models.CharField(max_length=120)
    classroom = models.ForeignKey(
        ClassRoom, on_delete=models.SET_NULL, null=True, related_name='students')
    roll_no = models.CharField(max_length=20, blank=True)
    admission_no = models.CharField(max_length=30, blank=True)
    guardian_name = models.CharField(max_length=120, blank=True)
    guardian_phone = models.CharField(max_length=20, blank=True)
    guardian_email = models.EmailField(blank=True)   # for email alerts
    fee_status = models.CharField(max_length=10, choices=FEE_CHOICES, default='Pending')
    # Advance / credit held for this student (money received ahead of a challan).
    # Held as a deposit; recognised as fee income only when applied to a challan.
    credit_balance = models.PositiveIntegerField(default=0)
    custom_fee = models.PositiveIntegerField(default=0)  # 0 = use class monthly_fee
    is_hostel = models.BooleanField(default=False)
    photo = models.FileField(upload_to='students/', blank=True, null=True)
    route = models.ForeignKey(
        'TransportRoute', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='riders')
    pickup_point = models.CharField(max_length=120, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=10, blank=True)
    blood_group = models.CharField(max_length=5, blank=True)
    address = models.CharField(max_length=200, blank=True)
    admission_date = models.DateField(null=True, blank=True)
    graduated = models.BooleanField(default=False)
    hostel_room = models.ForeignKey(
        'HostelRoom', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='residents')

    # --- Extended admission profile (Phase: full admission form) ---
    ADMISSION_TYPES = [('Fresh', 'Fresh admission'),
                       ('Transfer', 'Transfer from another school')]
    STATUS_CHOICES = [('Active', 'Active'), ('Left', 'Left'),
                      ('Graduated', 'Graduated'), ('Struck Off', 'Struck off')]

    # Identity
    b_form = models.CharField(max_length=25, blank=True)
    religion = models.CharField(max_length=30, blank=True)
    nationality = models.CharField(max_length=30, blank=True, default='Pakistani')
    # Family
    father_name = models.CharField(max_length=80, blank=True)
    mother_name = models.CharField(max_length=80, blank=True)
    father_cnic = models.CharField(max_length=20, blank=True)
    father_occupation = models.CharField(max_length=80, blank=True)
    father_phone = models.CharField(max_length=20, blank=True)
    mother_phone = models.CharField(max_length=20, blank=True)
    guardian_relation = models.CharField(max_length=40, blank=True)
    monthly_income = models.CharField(max_length=40, blank=True)
    # Contact
    permanent_address = models.CharField(max_length=200, blank=True)
    city = models.CharField(max_length=50, blank=True)
    emergency_name = models.CharField(max_length=80, blank=True)
    emergency_phone = models.CharField(max_length=20, blank=True)
    emergency_relation = models.CharField(max_length=40, blank=True)
    # Admission
    admission_type = models.CharField(
        max_length=10, choices=ADMISSION_TYPES, default='Fresh')
    previous_school = models.CharField(max_length=120, blank=True)
    previous_class = models.CharField(max_length=40, blank=True)
    leaving_reason = models.CharField(max_length=120, blank=True)
    slc_received = models.BooleanField(default=False)
    slc_number = models.CharField(max_length=40, blank=True)
    board_reg_no = models.CharField(max_length=40, blank=True)
    # Documents received (checklist)
    doc_birth = models.BooleanField(default=False)
    doc_cnic = models.BooleanField(default=False)
    doc_slc = models.BooleanField(default=False)
    doc_result = models.BooleanField(default=False)
    doc_photos = models.BooleanField(default=False)
    # Medical
    medical_notes = models.CharField(max_length=200, blank=True)
    allergies = models.CharField(max_length=120, blank=True)
    # Lifecycle
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default='Active')
    left_on = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Profile(models.Model):
    ROLE_CHOICES = [
        ('owner', 'Owner / Director'),
        ('principal', 'Principal'),
        ('admin', 'Administrator (Office)'),
        ('finance', 'Accountant / Finance'),
        ('teacher', 'Teacher'),
        ('parent', 'Parent'),
        ('student', 'Student'),
    ]
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='admin')
    school = models.ForeignKey(School, on_delete=models.SET_NULL, null=True, blank=True, related_name='profiles')
    classroom = models.ForeignKey(
        ClassRoom, on_delete=models.SET_NULL, null=True, blank=True)
    # For a student: their own record. For a parent: the primary/first child
    # (kept for backward-compat). A parent's full set of children is `children`.
    student = models.ForeignKey(
        Student, on_delete=models.SET_NULL, null=True, blank=True)
    children = models.ManyToManyField(
        Student, blank=True, related_name='guardians')
    photo = models.FileField(upload_to='avatars/', blank=True, null=True)
    # Auto-created logins start with the school default password; this forces
    # the person to set their own password the first time they sign in.
    must_change_password = models.BooleanField(default=False)

    def child_list(self):
        """All students this profile can view (parent: every child; student: self)."""
        kids = list(self.children.select_related('classroom').all())
        if self.student and self.student not in kids:
            kids.insert(0, self.student)
        return kids

    def __str__(self):
        return f"{self.user.username} ({self.role})"


class SaasTransaction(models.Model):
    TRANSACTION_TYPES = [
        ('income', 'Subscription Income'),
        ('expense', 'Platform Expense'),
    ]
    school = models.ForeignKey(School, on_delete=models.SET_NULL, null=True, blank=True, related_name='saas_transactions')
    amount = models.PositiveIntegerField()
    date = models.DateField(default=datetime.date.today)
    transaction_type = models.CharField(max_length=10, choices=TRANSACTION_TYPES, default='income')
    description = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ['-date']

    def __str__(self):
        return f"{self.transaction_type.upper()}: Rs {self.amount} ({self.date})"


class LoginAttempt(models.Model):
    """Tracks failed sign-ins per username to lock out brute-force guessing.
    One row per username, updated in place — kept tiny on purpose."""
    username = models.CharField(max_length=150, unique=True)
    fail_count = models.PositiveIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
    updated = models.DateTimeField(auto_now=True)

    def __str__(self):
        return '%s (%d fails)' % (self.username, self.fail_count)


class AuditLog(models.Model):
    """Who changed what, and when — an accountability trail for sensitive
    actions (money, grades, roles, discipline). The username is stored as text
    so the record survives even if the user account is later deleted."""
    user = models.CharField(max_length=80)
    action = models.CharField(max_length=60)
    detail = models.CharField(max_length=255, blank=True)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-id']

    def __str__(self):
        return '%s - %s' % (self.user, self.action)


class Announcement(models.Model):
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    audience = models.CharField(max_length=20, default='All')
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created']

    def __str__(self):
        return self.title


class Subject(models.Model):
    name = models.CharField(max_length=60)
    classroom = models.ForeignKey(
        ClassRoom, on_delete=models.CASCADE, related_name='subjects')

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.classroom})"


class Exam(models.Model):
    name = models.CharField(max_length=80)
    # Which academic session this exam (and all its marks) belongs to, e.g.
    # "2025-26". Stamped from School.session when the exam is created so that
    # results from different years never blend together.
    session = models.CharField(max_length=20, blank=True, default='')

    class Meta:
        ordering = ['-id']

    def __str__(self):
        return self.name


class AttendanceRecord(models.Model):
    STATUS_CHOICES = [('P', 'Present'), ('A', 'Absent'), ('L', 'Leave')]

    student = models.ForeignKey(
        Student, on_delete=models.CASCADE, related_name='attendance')
    date = models.DateField()
    status = models.CharField(max_length=1, choices=STATUS_CHOICES, default='P')
    # Academic session this record belongs to (stamped when marked). Attendance
    # is already date-scoped, but tagging the session keeps year-end reporting
    # clean when a school runs across multiple years.
    session = models.CharField(max_length=20, blank=True, default='')

    class Meta:
        unique_together = ('student', 'date')
        ordering = ['-date']

    def __str__(self):
        return f"{self.student} {self.date} {self.status}"


class StudentLeave(models.Model):
    """A leave request for a student, submitted by the parent/student and
    approved by the office/principal (mirrors the staff LeaveRequest flow)."""
    STATUS = [('Pending', 'Pending'), ('Approved', 'Approved'),
              ('Rejected', 'Rejected')]
    student = models.ForeignKey(
        Student, on_delete=models.CASCADE, related_name='leaves')
    from_date = models.DateField()
    to_date = models.DateField()
    reason = models.CharField(max_length=300)
    status = models.CharField(max_length=10, choices=STATUS, default='Pending')
    applied_by = models.CharField(max_length=80, blank=True)
    decided_by = models.CharField(max_length=80, blank=True)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created']

    def __str__(self):
        return f"{self.student} {self.from_date}→{self.to_date} ({self.status})"

    @property
    def days(self):
        return (self.to_date - self.from_date).days + 1


class StudentNote(models.Model):
    """A light behaviour/remark note a teacher writes on a student in their
    class. Unlike the confidential DisciplineRecord (office-only), these are
    meant to be shared with the parent/student — praise, a concern, or a
    general remark. Kept simple: no approval workflow."""
    KINDS = [('Praise', 'Praise'), ('Concern', 'Concern'), ('Note', 'General note')]
    student = models.ForeignKey(
        Student, on_delete=models.CASCADE, related_name='notes')
    kind = models.CharField(max_length=10, choices=KINDS, default='Note')
    text = models.CharField(max_length=400)
    teacher = models.ForeignKey(
        'Profile', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='student_notes')
    teacher_name = models.CharField(max_length=80, blank=True)
    date = models.DateField(default=datetime.date.today)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date', '-id']

    def __str__(self):
        return '%s: %s (%s)' % (self.student.name, self.kind, self.date)


class Message(models.Model):
    """One message in a per-student thread between the family (parent/student)
    and the child's teachers. A simple shared conversation scoped to the
    student — no 1:1 routing — so any teacher of the child's class and the
    parent can follow it. Unread is tracked per side for the nav badges."""
    student = models.ForeignKey(
        Student, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(
        'Profile', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='sent_messages')
    sender_name = models.CharField(max_length=80, blank=True)
    sender_role = models.CharField(max_length=20, blank=True)   # parent/student/teacher
    body = models.TextField()
    created = models.DateTimeField(auto_now_add=True)
    # Unread flags: the side that DIDN'T send starts unread.
    seen_by_family = models.BooleanField(default=False)   # parent/student has read
    seen_by_staff = models.BooleanField(default=False)    # a teacher has read

    class Meta:
        ordering = ['created', 'id']

    @property
    def from_family(self):
        return self.sender_role in ('parent', 'student')

    def __str__(self):
        return '%s -> %s: %.30s' % (self.sender_name, self.student.name, self.body)


class Complaint(models.Model):
    """A complaint / feedback a parent or student raises to the office. Routed
    to admin + principal, who respond and move it Open -> In Progress ->
    Resolved. Kept separate from the teacher message thread (which is a
    conversation) — a complaint is a tracked ticket."""
    CATEGORIES = [('Academic', 'Academic'), ('Fee', 'Fee / Finance'),
                  ('Transport', 'Transport'), ('Facility', 'Facility'),
                  ('Staff', 'Staff conduct'), ('Other', 'Other')]
    STATUS = [('Open', 'Open'), ('In Progress', 'In Progress'),
              ('Resolved', 'Resolved')]
    student = models.ForeignKey(
        Student, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='complaints')
    raised_by = models.ForeignKey(
        'Profile', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='complaints')
    raised_by_name = models.CharField(max_length=80, blank=True)
    category = models.CharField(max_length=20, choices=CATEGORIES, default='Other')
    subject = models.CharField(max_length=140)
    body = models.TextField()
    status = models.CharField(max_length=12, choices=STATUS, default='Open')
    response = models.TextField(blank=True)
    handled_by = models.CharField(max_length=80, blank=True)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created']

    def __str__(self):
        return '%s (%s) - %s' % (self.subject, self.category, self.status)


class Mark(models.Model):
    student = models.ForeignKey(
        Student, on_delete=models.CASCADE, related_name='marks')
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE)
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE)
    marks_obtained = models.PositiveIntegerField(default=0)
    total_marks = models.PositiveIntegerField(default=100)

    class Meta:
        unique_together = ('student', 'subject', 'exam')
        ordering = ['subject__name']

    @property
    def percentage(self):
        if not self.total_marks:
            return 0
        return round(self.marks_obtained / self.total_marks * 100)

    @property
    def grade(self):
        return grade_for(self.percentage)

    def __str__(self):
        return f"{self.student} {self.subject} {self.marks_obtained}"


class GradeConfig(models.Model):
    """Per-(exam, class, subject) gradebook settings: the paper's maximum marks
    (so a subject out of 75 scores correctly, not forced to /100) and a lock
    that freezes marks once finalised (moderation). One row per subject paper."""
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name='grade_configs')
    classroom = models.ForeignKey(ClassRoom, on_delete=models.CASCADE,
                                  related_name='grade_configs')
    subject = models.CharField(max_length=60)          # matches Subject.name
    max_marks = models.PositiveIntegerField(default=100)
    locked = models.BooleanField(default=False)
    locked_by = models.CharField(max_length=80, blank=True)

    class Meta:
        unique_together = ('exam', 'classroom', 'subject')

    def __str__(self):
        return '%s/%s/%s max %d%s' % (self.exam_id, self.classroom_id,
                                      self.subject, self.max_marks,
                                      ' (locked)' if self.locked else '')


class FeePayment(models.Model):
    MODE_CHOICES = [
        ('Cash', 'Cash'), ('JazzCash', 'JazzCash'), ('Easypaisa', 'Easypaisa'),
        ('RAAST', 'RAAST QR'), ('Bank', 'Bank Transfer'), ('Card', 'Card'),
        ('Cheque', 'Cheque'), ('Credit', 'Credit balance'),
    ]
    student = models.ForeignKey(
        Student, on_delete=models.CASCADE, related_name='payments')
    challan = models.ForeignKey(
        'FeeChallan', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='payments')
    month = models.CharField(max_length=20, default='June 2026')
    amount = models.PositiveIntegerField(default=0)
    late_fee = models.PositiveIntegerField(default=0)
    mode = models.CharField(max_length=20, choices=MODE_CHOICES, default='Cash')
    received_by = models.CharField(max_length=120, blank=True)
    receipt_no = models.CharField(max_length=30, blank=True)
    date = models.DateField(default=datetime.date.today)
    # A payment can be reversed: 'Voided' (recorded in error, money never truly
    # taken) or 'Refunded' (money returned to the parent). Either way it stops
    # counting toward the challan's paid total and toward income — the balance
    # reopens. Kept as a row (not deleted) so the trail survives.
    STATUS = [('Active', 'Active'), ('Voided', 'Voided'), ('Refunded', 'Refunded')]
    status = models.CharField(max_length=10, choices=STATUS, default='Active')
    reversal_reason = models.CharField(max_length=200, blank=True)
    reversed_by = models.CharField(max_length=120, blank=True)
    reversed_on = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ['-id']

    @property
    def total(self):
        return self.amount + self.late_fee

    @property
    def is_active(self):
        return self.status == 'Active'

    def __str__(self):
        return f"{self.receipt_no} - {self.student}"


class OnlinePayment(models.Model):
    """One online / bank-transfer fee payment attempt, tracked through its
    lifecycle. Bank transfers land as 'pending' for Accounts to verify;
    gateway (JazzCash/Easypaisa) callbacks reconcile automatically. On success
    the attempt is linked to the FeePayment it produced, so the money is
    recorded exactly like a counter payment (receipt, audit, notification)."""
    STATUS = [('initiated', 'Initiated'), ('pending', 'Pending verification'),
              ('paid', 'Paid'), ('failed', 'Failed'), ('rejected', 'Rejected')]
    GATEWAYS = [('bank', 'Bank transfer'), ('raast', 'RAAST QR'),
                ('jazzcash', 'JazzCash'), ('easypaisa', 'Easypaisa')]
    student = models.ForeignKey(
        Student, on_delete=models.CASCADE, related_name='online_payments')
    challan = models.ForeignKey(
        'FeeChallan', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='online_payments')
    gateway = models.CharField(max_length=20, choices=GATEWAYS)
    amount = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=20, choices=STATUS, default='initiated')
    ref = models.CharField(max_length=60, blank=True)          # our unique reference
    gateway_ref = models.CharField(max_length=80, blank=True)  # bank/gateway txn id
    proof = models.FileField(upload_to='payproof/', blank=True, null=True)
    payer_note = models.CharField(max_length=200, blank=True)
    verified_by = models.CharField(max_length=120, blank=True)
    payment = models.ForeignKey(
        FeePayment, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='online')
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-id']

    def __str__(self):
        return '%s %s Rs%d (%s)' % (self.gateway, self.ref, self.amount, self.status)


class PushSubscription(models.Model):
    """A browser's Web Push subscription for a user, so the school can send
    push notifications to installed PWAs / desktops. One row per browser."""
    user = models.ForeignKey(User, on_delete=models.CASCADE,
                             related_name='push_subs')
    endpoint = models.TextField(unique=True)
    p256dh = models.CharField(max_length=200)
    auth = models.CharField(max_length=100)
    created = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return 'push:%s' % self.user_id


class PaymentSource(models.Model):
    """Where an expense's money came from — a cash box or bank account. Lets a
    school track spending per fund and reconcile against each account."""
    name = models.CharField(max_length=80)
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Expense(models.Model):
    CATEGORY_CHOICES = [
        ('Utilities', 'Utilities'), ('Salaries', 'Salaries'),
        ('Supplies', 'Supplies'), ('Maintenance', 'Maintenance'), ('Other', 'Other'),
    ]
    title = models.CharField(max_length=150)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='Other')
    amount = models.PositiveIntegerField(default=0)
    date = models.DateField(default=datetime.date.today)
    note = models.CharField(max_length=200, blank=True)
    source = models.ForeignKey('PaymentSource', on_delete=models.SET_NULL,
                               null=True, blank=True, related_name='expenses')

    class Meta:
        ordering = ['-id']

    def __str__(self):
        return f"{self.title} - {self.amount}"


class Applicant(models.Model):
    STAGE_CHOICES = [
        ('Enquiry', 'Enquiry'), ('Test', 'Test'),
        ('Offer', 'Offer'), ('Enrolled', 'Enrolled'),
        ('Rejected', 'Rejected'),
    ]
    SOURCES = [('Office', 'Office'), ('Online', 'Online')]
    name = models.CharField(max_length=120)
    class_applied = models.CharField(max_length=40, blank=True)
    parent_name = models.CharField(max_length=120, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    stage = models.CharField(max_length=20, choices=STAGE_CHOICES, default='Enquiry')
    converted = models.BooleanField(default=False)  # a Student record was created
    # Extra details captured by the public online admission form.
    source = models.CharField(max_length=10, choices=SOURCES, default='Office')
    email = models.EmailField(blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=10, blank=True)
    address = models.CharField(max_length=255, blank=True)
    previous_school = models.CharField(max_length=140, blank=True)
    message = models.TextField(blank=True)
    photo = models.FileField(upload_to='admissions/', blank=True, null=True)
    document = models.FileField(upload_to='admissions/', blank=True, null=True)
    ref = models.CharField(max_length=20, blank=True)   # public tracking reference
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-id']

    def __str__(self):
        return f"{self.name} ({self.stage})"


class SmsMessage(models.Model):
    recipients = models.CharField(max_length=120)
    to_phone = models.CharField(max_length=30, blank=True)
    body = models.TextField()
    msg_type = models.CharField(max_length=30, default='Manual')
    status = models.CharField(max_length=20, default='Delivered')
    provider = models.CharField(max_length=20, blank=True)
    error = models.CharField(max_length=200, blank=True)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-id']

    def __str__(self):
        return f"{self.recipients}: {self.body[:30]}"


class TransportRoute(models.Model):
    name = models.CharField(max_length=80)
    vehicle = models.CharField(max_length=30, blank=True)
    driver = models.CharField(max_length=80, blank=True)
    fee = models.PositiveIntegerField(default=0)
    students = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Book(models.Model):
    title = models.CharField(max_length=150)
    author = models.CharField(max_length=120, blank=True)
    code = models.CharField(max_length=20, blank=True)
    copies = models.PositiveIntegerField(default=1)
    available = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ['title']

    def __str__(self):
        return self.title


class IssuedBook(models.Model):
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name='issues')
    student_name = models.CharField(max_length=120)
    issued_on = models.DateField(default=datetime.date.today)
    due_on = models.DateField(default=datetime.date.today)
    returned = models.BooleanField(default=False)

    class Meta:
        ordering = ['-id']

    def __str__(self):
        return f"{self.book} -> {self.student_name}"


class Staff(models.Model):
    # Optional link to a login account (Profile). Lets a teacher/staff member
    # see their own payslip and attendance, and ties HR to the login system.
    user = models.OneToOneField(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='staff_record')
    name = models.CharField(max_length=120)
    designation = models.CharField(max_length=80, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    email = models.CharField(max_length=120, blank=True)
    joined = models.DateField(default=datetime.date.today)
    basic_salary = models.PositiveIntegerField(default=0)
    allowances = models.PositiveIntegerField(default=0)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']

    @property
    def monthly_salary(self):
        return self.basic_salary + self.allowances

    def __str__(self):
        return self.name


class Certificate(models.Model):
    TYPE_CHOICES = [
        ('Leaving', 'Leaving Certificate'),
        ('Character', 'Character Certificate'),
        ('Bonafide', 'Bonafide Certificate'),
        ('Birth', 'Date of Birth Certificate'),
        ('Fee', 'Fee Certificate'),
    ]
    student = models.ForeignKey(
        Student, on_delete=models.CASCADE, related_name='certificates')
    cert_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='Leaving')
    issued_on = models.DateField(default=datetime.date.today)

    class Meta:
        ordering = ['-id']

    def __str__(self):
        return f"{self.get_cert_type_display()} - {self.student}"


class CalendarEvent(models.Model):
    TYPE_CHOICES = [
        ('Holiday', 'Holiday'), ('Exam', 'Exam'), ('PTM', 'PTM'),
        ('Event', 'Event'), ('Academic', 'Academic'),
    ]
    title = models.CharField(max_length=150)
    event_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='Event')
    date = models.DateField(default=datetime.date.today)

    class Meta:
        ordering = ['date']

    def __str__(self):
        return self.title


class InventoryItem(models.Model):
    CATEGORY_CHOICES = [
        ('Uniform', 'Uniform'), ('Stationery', 'Stationery'),
        ('Supplies', 'Supplies'), ('Books', 'Books'), ('Other', 'Other'),
    ]
    name = models.CharField(max_length=120)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='Other')
    quantity = models.PositiveIntegerField(default=0)
    reorder_level = models.PositiveIntegerField(default=0)
    unit = models.CharField(max_length=20, default='pcs')

    class Meta:
        ordering = ['name']

    @property
    def low(self):
        return self.quantity <= self.reorder_level

    def __str__(self):
        return self.name


class Visitor(models.Model):
    name = models.CharField(max_length=120)
    purpose = models.CharField(max_length=200, blank=True)
    to_meet = models.CharField(max_length=120, blank=True)
    pass_no = models.CharField(max_length=20, blank=True)
    time_in = models.DateTimeField(auto_now_add=True)
    checked_out = models.BooleanField(default=False)

    class Meta:
        ordering = ['-id']

    def __str__(self):
        return self.name


class Material(models.Model):
    TYPE_CHOICES = [
        ('Notes', 'Notes'), ('Book', 'Book'),
        ('Slides', 'Slides'), ('Past Paper', 'Past Paper'),
    ]
    subject = models.ForeignKey(
        Subject, on_delete=models.CASCADE, related_name='materials')
    title = models.CharField(max_length=160)
    mat_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='Notes')
    size = models.CharField(max_length=20, blank=True)
    file = models.FileField(upload_to='materials/', blank=True)
    uploaded_on = models.DateField(default=datetime.date.today)

    class Meta:
        ordering = ['-id']

    def __str__(self):
        return f"{self.subject.name} - {self.title}"


class TimetableSlot(models.Model):
    classroom = models.ForeignKey(
        ClassRoom, on_delete=models.CASCADE, related_name='slots')
    day = models.CharField(max_length=3)            # Mon, Tue, ...
    period = models.PositiveIntegerField()           # 1..6
    start_time = models.CharField(max_length=10)     # "08:00"
    subject = models.CharField(max_length=60)        # subject name or "Break"
    teacher = models.CharField(max_length=80, blank=True)

    class Meta:
        ordering = ['period']

    def __str__(self):
        return f"{self.classroom} {self.day} P{self.period} {self.subject}"


class Assignment(models.Model):
    classroom = models.ForeignKey(
        ClassRoom, on_delete=models.CASCADE, related_name='assignments')
    subject = models.ForeignKey(
        Subject, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='assignments')
    title = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    attachment = models.FileField(upload_to='assignments/', blank=True, null=True)
    due_date = models.DateField(default=datetime.date.today)
    created = models.DateField(auto_now_add=True)

    class Meta:
        ordering = ['-id']

    def __str__(self):
        return self.title


class Submission(models.Model):
    STATUS = [('Submitted', 'Submitted'), ('Graded', 'Graded')]
    assignment = models.ForeignKey(
        Assignment, on_delete=models.CASCADE, related_name='submissions')
    student = models.ForeignKey(
        Student, on_delete=models.CASCADE, related_name='submissions')
    answer_text = models.TextField(blank=True)
    file = models.FileField(upload_to='submissions/', blank=True, null=True)
    status = models.CharField(max_length=12, choices=STATUS, default='Submitted')
    grade = models.CharField(max_length=40, blank=True)
    submitted_on = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('assignment', 'student')
        ordering = ['-id']

    def __str__(self):
        return f"{self.student.name} - {self.assignment.title}"


class Quiz(models.Model):
    classroom = models.ForeignKey(
        ClassRoom, on_delete=models.CASCADE, related_name='quizzes')
    subject = models.ForeignKey(
        Subject, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='quizzes')
    title = models.CharField(max_length=160)
    time_limit = models.PositiveIntegerField(default=10)   # minutes
    created = models.DateField(auto_now_add=True)

    class Meta:
        ordering = ['-id']

    def __str__(self):
        return self.title


class Question(models.Model):
    CHOICES = [('A', 'A'), ('B', 'B'), ('C', 'C'), ('D', 'D')]
    quiz = models.ForeignKey(
        Quiz, on_delete=models.CASCADE, related_name='questions')
    text = models.CharField(max_length=300)
    option_a = models.CharField(max_length=160)
    option_b = models.CharField(max_length=160)
    option_c = models.CharField(max_length=160, blank=True)
    option_d = models.CharField(max_length=160, blank=True)
    correct = models.CharField(max_length=1, choices=CHOICES, default='A')
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        return self.text


class QuizAttempt(models.Model):
    quiz = models.ForeignKey(
        Quiz, on_delete=models.CASCADE, related_name='attempts')
    student = models.ForeignKey(
        Student, on_delete=models.CASCADE, related_name='quiz_attempts')
    score = models.PositiveIntegerField(default=0)
    total = models.PositiveIntegerField(default=0)
    taken_on = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('quiz', 'student')
        ordering = ['-id']

    @property
    def percentage(self):
        return round(self.score / self.total * 100) if self.total else 0

    def __str__(self):
        return f"{self.student.name} - {self.quiz.title}"


class FeeChallan(models.Model):
    MONTHS = ['', 'January', 'February', 'March', 'April', 'May', 'June',
              'July', 'August', 'September', 'October', 'November', 'December']
    student = models.ForeignKey(
        Student, on_delete=models.CASCADE, related_name='challans')
    year = models.PositiveIntegerField()
    month = models.PositiveIntegerField()            # 1-12
    tuition = models.PositiveIntegerField(default=0)
    hostel_fee = models.PositiveIntegerField(default=0)
    transport_fee = models.PositiveIntegerField(default=0)
    arrears = models.PositiveIntegerField(default=0)          # previous dues carried in
    carried_forward = models.BooleanField(default=False)      # balance rolled into a later challan
    other_charges = models.PositiveIntegerField(default=0)
    other_label = models.CharField(max_length=60, blank=True)
    discount = models.PositiveIntegerField(default=0)
    discount_reason = models.CharField(max_length=120, blank=True)
    discount_by = models.CharField(max_length=120, blank=True)
    scholarship = models.PositiveIntegerField(default=0)
    scholarship_name = models.CharField(max_length=120, blank=True)
    late_fee = models.PositiveIntegerField(default=0)
    # Set when finance edits the late fee by hand — the daily escalation then
    # leaves this challan alone (no auto-override of a manual figure/waiver).
    late_fee_locked = models.BooleanField(default=False)
    due_date = models.DateField(default=datetime.date.today)
    created = models.DateField(auto_now_add=True)

    class Meta:
        unique_together = ('student', 'year', 'month')
        ordering = ['-year', '-month']

    @property
    def label(self):
        return '%s %d' % (self.MONTHS[self.month], self.year)

    @property
    def lines_total(self):
        """Sum of extra fee heads (admission, annual, exam, security, ...)."""
        return sum(ln.amount for ln in self.lines.all())

    @property
    def gross(self):
        return (self.tuition + self.hostel_fee + self.transport_fee
                + self.other_charges + self.arrears + self.late_fee
                + self.lines_total)

    @property
    def deductions(self):
        return self.discount + self.scholarship

    @property
    def net_payable(self):
        return max(self.gross - self.deductions, 0)

    @property
    def paid(self):
        # Voided / refunded payments don't count — the balance reopens.
        return sum(p.amount for p in self.payments.all() if p.status == 'Active')

    @property
    def balance(self):
        if self.carried_forward:
            return 0
        return max(self.net_payable - self.paid, 0)

    @property
    def status(self):
        if self.carried_forward:
            return 'Carried forward'
        if self.net_payable <= 0:
            return 'Waived'
        if self.paid >= self.net_payable:
            return 'Paid'
        if self.paid > 0:
            return 'Partial'
        return 'Unpaid'

    @property
    def is_overdue(self):
        return self.balance > 0 and self.due_date < datetime.date.today()

    def __str__(self):
        return '%s - %s' % (self.student.name, self.label)


class TeachingAssignment(models.Model):
    teacher = models.ForeignKey(
        Profile, on_delete=models.CASCADE, related_name='teaching')
    classroom = models.ForeignKey(
        ClassRoom, on_delete=models.CASCADE, related_name='teachers')
    subject = models.CharField(max_length=60)

    class Meta:
        unique_together = ('teacher', 'classroom', 'subject')
        ordering = ['classroom__name', 'classroom__section', 'subject']

    def __str__(self):
        return '%s - %s (%s)' % (self.teacher.user.username, self.subject,
                                 self.classroom)


class ConcessionRequest(models.Model):
    """A fee discount or scholarship requested by Accounts that must be
    approved by the Principal before it is applied to the challan."""
    KIND_CHOICES = [('discount', 'Discount'), ('scholarship', 'Scholarship')]
    STATUS_CHOICES = [('Pending', 'Pending'), ('Approved', 'Approved'),
                      ('Rejected', 'Rejected')]
    challan = models.ForeignKey(
        'FeeChallan', on_delete=models.CASCADE, related_name='concession_requests')
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    amount = models.PositiveIntegerField(default=0)
    label = models.CharField(max_length=120, blank=True)  # reason / scholarship name
    requested_by = models.CharField(max_length=80, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='Pending')
    decided_by = models.CharField(max_length=80, blank=True)
    created = models.DateTimeField(auto_now_add=True)
    decided_on = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created']

    @property
    def student(self):
        return self.challan.student

    def __str__(self):
        return '%s Rs%d - %s' % (self.get_kind_display(), self.amount, self.status)


class StaffAttendance(models.Model):
    STATUS_CHOICES = [('P', 'Present'), ('A', 'Absent'),
                      ('L', 'Leave'), ('H', 'Half Day')]
    staff = models.ForeignKey(Staff, on_delete=models.CASCADE,
                              related_name='attendance')
    date = models.DateField(default=datetime.date.today)
    status = models.CharField(max_length=1, choices=STATUS_CHOICES, default='P')

    class Meta:
        unique_together = ('staff', 'date')
        ordering = ['-date']

    def __str__(self):
        return '%s - %s (%s)' % (self.staff.name, self.date, self.status)


class LeaveRequest(models.Model):
    STATUS_CHOICES = [('Pending', 'Pending'), ('Approved', 'Approved'),
                      ('Rejected', 'Rejected')]
    staff = models.ForeignKey(Staff, on_delete=models.CASCADE, related_name='leaves')
    from_date = models.DateField()
    to_date = models.DateField()
    reason = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='Pending')
    applied_by = models.CharField(max_length=80, blank=True)
    decided_by = models.CharField(max_length=80, blank=True)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created']

    @property
    def days(self):
        return (self.to_date - self.from_date).days + 1

    def __str__(self):
        return '%s: %s to %s (%s)' % (self.staff.name, self.from_date,
                                      self.to_date, self.status)


class Payslip(models.Model):
    staff = models.ForeignKey(Staff, on_delete=models.CASCADE, related_name='payslips')
    year = models.PositiveIntegerField()
    month = models.PositiveIntegerField()
    basic = models.PositiveIntegerField(default=0)
    allowances = models.PositiveIntegerField(default=0)
    deductions = models.PositiveIntegerField(default=0)
    generated_on = models.DateField(default=datetime.date.today)

    class Meta:
        unique_together = ('staff', 'year', 'month')
        ordering = ['-year', '-month']

    @property
    def gross(self):
        return self.basic + self.allowances

    @property
    def net(self):
        return max(self.basic + self.allowances - self.deductions, 0)

    @property
    def label(self):
        return '%s %d' % (FeeChallan.MONTHS[self.month], self.year)

    def __str__(self):
        return '%s - %s' % (self.staff.name, self.label)


class Appraisal(models.Model):
    """A periodic performance appraisal the office records for a staff member:
    an overall rating plus notes on strengths and areas to improve."""
    RATINGS = [(5, 'Outstanding'), (4, 'Exceeds expectations'),
               (3, 'Meets expectations'), (2, 'Needs improvement'),
               (1, 'Unsatisfactory')]
    staff = models.ForeignKey(Staff, on_delete=models.CASCADE,
                              related_name='appraisals')
    period = models.CharField(max_length=40)          # e.g. "2025-26" or "Term 1"
    rating = models.PositiveSmallIntegerField(choices=RATINGS, default=3)
    strengths = models.TextField(blank=True)
    improvements = models.TextField(blank=True)
    reviewer = models.CharField(max_length=80, blank=True)
    created = models.DateField(default=datetime.date.today)

    class Meta:
        ordering = ['-created', '-id']

    @property
    def rating_label(self):
        return dict(self.RATINGS).get(self.rating, '')

    def __str__(self):
        return '%s - %s (%d)' % (self.staff.name, self.period, self.rating)


class ExamRoom(models.Model):
    name = models.CharField(max_length=40)
    capacity = models.PositiveIntegerField(default=30)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class ExamSchedule(models.Model):
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name='schedule')
    classroom = models.ForeignKey(ClassRoom, on_delete=models.CASCADE,
                                  related_name='exam_schedule')
    subject = models.CharField(max_length=60)
    date = models.DateField()
    time = models.CharField(max_length=40, blank=True)  # e.g. "09:00 AM - 12:00 PM"

    class Meta:
        ordering = ['date', 'time', 'classroom__name']

    def __str__(self):
        return '%s - %s (%s)' % (self.classroom, self.subject, self.date)


class Seat(models.Model):
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name='seats')
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='seats')
    room = models.ForeignKey(ExamRoom, on_delete=models.CASCADE, related_name='seats')
    seat_no = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ('exam', 'student')
        ordering = ['room__name', 'seat_no']

    def __str__(self):
        return '%s - %s seat %d' % (self.student.name, self.room.name, self.seat_no)


class HostelRoom(models.Model):
    name = models.CharField(max_length=40)
    capacity = models.PositiveIntegerField(default=4)
    warden = models.CharField(max_length=80, blank=True)
    notes = models.CharField(max_length=120, blank=True)

    class Meta:
        ordering = ['name']

    @property
    def occupied(self):
        return self.residents.count()

    def __str__(self):
        return self.name


class DisciplineRecord(models.Model):
    CATEGORIES = [
        ('Behaviour', 'Behaviour'),
        ('Bullying', 'Bullying / Fighting'),
        ('Uniform', 'Uniform / Dress code'),
        ('Attendance', 'Attendance / Punctuality'),
        ('Homework', 'Homework / Class work'),
        ('Property', 'Property damage'),
        ('Other', 'Other'),
    ]
    SEVERITIES = [('Minor', 'Minor'), ('Major', 'Major'), ('Critical', 'Critical')]
    STATUSES = [('Open', 'Open'), ('Resolved', 'Resolved')]

    student = models.ForeignKey(
        Student, on_delete=models.CASCADE, related_name='discipline_records')
    date = models.DateField()
    category = models.CharField(max_length=20, choices=CATEGORIES, default='Behaviour')
    severity = models.CharField(max_length=10, choices=SEVERITIES, default='Minor')
    description = models.TextField()
    action_taken = models.CharField(max_length=200, blank=True)
    reported_by = models.CharField(max_length=80, blank=True)
    status = models.CharField(max_length=10, choices=STATUSES, default='Open')
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date', '-id']

    def __str__(self):
        return '%s - %s (%s)' % (self.student.name, self.category, self.date)


class FeeHead(models.Model):
    """A configurable fee, on top of monthly tuition, that the school defines
    once and the system adds to challans automatically — e.g. Admission Fee
    (one-time), Annual Charges (once a year), Exam Fee, Security Deposit."""
    FREQUENCY = [
        ('monthly', 'Every month'),
        ('one_time', 'One-time (on admission)'),
        ('annual', 'Once a year'),
    ]
    name = models.CharField(max_length=60)
    amount = models.PositiveIntegerField(default=0)
    frequency = models.CharField(max_length=10, choices=FREQUENCY, default='monthly')
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return '%s (%s)' % (self.name, self.get_frequency_display())


class ChallanLine(models.Model):
    """One itemised extra charge on a challan, created from a FeeHead so the
    voucher shows each head separately instead of one lumped figure."""
    challan = models.ForeignKey(
        FeeChallan, on_delete=models.CASCADE, related_name='lines')
    label = models.CharField(max_length=60)
    amount = models.PositiveIntegerField(default=0)

    def __str__(self):
        return '%s: %d' % (self.label, self.amount)