"""Load a COMPLETE, realistic demo school.

Sized like a real mid-size Pakistani private school so that every screen in the
system has believable data and nothing looks empty while testing:

  * 14 classes (Nursery -> Class 10, with sections) and ~280 students
  * 30 staff — 22 teachers (more teachers than subjects) + 8 support staff
  * A class teacher for every class and a subject teacher for every subject
  * A clash-free Mon–Sat timetable built by the app's own generator
  * Two exams with marks for every student, datesheet, rooms and seating
  * Three months of fee challans covering every real scenario
  * HR (attendance, leave, payroll, appraisals), library, transport, hostel,
    inventory, visitors, discipline, complaints, messages, certificates...

Deterministic: the same command always produces the same school.
"""
import datetime
import random

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core.models import (Announcement, Applicant, Appraisal, Assignment,
                         AttendanceRecord, AuditLog, Book, CalendarEvent,
                         Certificate, ChallanLine, ClassRoom, Complaint,
                         ConcessionRequest, DisciplineRecord, Exam, ExamRoom,
                         ExamSchedule, Expense, FeeChallan, FeeHead, FeePayment,
                         GradeConfig, HostelRoom, InventoryItem, IssuedBook,
                         LeaveRequest, Mark, Material, Message, OnlinePayment,
                         PaymentSource, Payslip, Profile, Question, Quiz,
                         QuizAttempt, School, Seat, SmsMessage, Staff,
                         StaffAttendance, Student, StudentLeave, StudentNote,
                         Subject, Submission, TeachingAssignment, TimetableSlot,
                         TransportRoute, Visitor)

# One simple password for every demo account, so testing is easy.
PASSWORD = 'roshni123'

# ---------------------------------------------------------------- name pools
BOYS = ['Ayaan', 'Bilal', 'Saad', 'Hamza', 'Usman', 'Ali', 'Ahmed', 'Hassan',
        'Zain', 'Umar', 'Talha', 'Faizan', 'Danish', 'Arsalan', 'Shahzaib',
        'Rehan', 'Fahad', 'Noman', 'Waleed', 'Ibrahim', 'Yasir', 'Owais',
        'Junaid', 'Salman', 'Asad', 'Haris', 'Musa', 'Taha', 'Zohaib',
        'Sufyan', 'Abdullah', 'Huzaifa', 'Shayan', 'Anas', 'Moiz']
GIRLS = ['Ayesha', 'Fatima', 'Hira', 'Mahnoor', 'Areeba', 'Inaya', 'Zainab',
         'Maryam', 'Sana', 'Rabia', 'Nida', 'Amna', 'Iqra', 'Sadia', 'Hina',
         'Komal', 'Laiba', 'Anum', 'Bushra', 'Saba', 'Noor', 'Eman', 'Alishba',
         'Warda', 'Mehwish', 'Sidra', 'Kinza', 'Tayyaba', 'Rimsha', 'Aqsa',
         'Hafsa', 'Zoya', 'Areesha', 'Minahil', 'Dua']
FAMILY = ['Khan', 'Ahmed', 'Malik', 'Iqbal', 'Hussain', 'Raza', 'Shah', 'Butt',
          'Chaudhry', 'Farooq', 'Siddiqui', 'Qureshi', 'Aslam', 'Javed',
          'Rashid', 'Nawaz', 'Tariq', 'Mehmood', 'Akram', 'Sharif', 'Bhatti',
          'Dar', 'Gill', 'Sheikh', 'Ansari', 'Abbasi', 'Niazi', 'Sial']
FATHERS = ['Imran', 'Aslam', 'Naeem', 'Tariq', 'Riaz', 'Iqbal', 'Nadeem',
           'Shahid', 'Javed', 'Kashif', 'Rizwan', 'Waseem', 'Arif', 'Sajid',
           'Pervaiz', 'Amjad', 'Zafar', 'Mansoor', 'Akhtar', 'Rauf']
BLOOD = ['A+', 'B+', 'O+', 'AB+', 'A-', 'O-']
CITIES = ['Lahore', 'Rawalpindi', 'Mardan', 'Peshawar', 'Multan']
AREAS = ['Model Town', 'Johar Town', 'Gulberg III', 'Cantt', 'Satellite Town',
         'DHA Phase 4', 'Township', 'Faisal Colony', 'Garden Town']

# ------------------------------------------------------- curriculum by level
# (subject name, periods per week). Total stays under 6 days x 7 usable periods.
PRE_PRIMARY = [('English', 6), ('Urdu', 6), ('Mathematics', 6),
               ('Drawing', 3), ('Islamiyat', 3)]
PRIMARY = [('English', 6), ('Urdu', 5), ('Mathematics', 6),
           ('General Science', 4), ('Islamiyat', 3), ('Social Studies', 3),
           ('Computer', 2)]
MIDDLE = [('English', 6), ('Urdu', 5), ('Mathematics', 6), ('Science', 5),
          ('Islamiyat', 3), ('Pak Studies', 3), ('Computer', 3)]
SECONDARY = [('English', 5), ('Urdu', 4), ('Mathematics', 6), ('Physics', 4),
             ('Chemistry', 4), ('Biology', 4), ('Islamiyat', 2),
             ('Pak Studies', 2), ('Computer', 3)]

# (class name, section, monthly fee, curriculum, roughly how many students)
CLASS_PLAN = [
    ('Nursery', 'A', 3500, PRE_PRIMARY, 18),
    ('KG', 'A', 4000, PRE_PRIMARY, 20),
    ('1', 'A', 4500, PRIMARY, 22),
    ('2', 'A', 4500, PRIMARY, 21),
    ('3', 'A', 5000, PRIMARY, 20),
    ('4', 'A', 5000, PRIMARY, 22),
    ('5', 'A', 5500, PRIMARY, 21),
    ('6', 'A', 5500, MIDDLE, 20),
    ('7', 'A', 6000, MIDDLE, 19),
    ('8', 'A', 6000, MIDDLE, 20),
    ('9', 'A', 6500, SECONDARY, 22),
    ('9', 'B', 6500, SECONDARY, 19),
    ('10', 'A', 7500, SECONDARY, 21),
    ('10', 'B', 7500, SECONDARY, 18),
]

# 22 teachers — more than the 13 distinct subjects, as a real school has.
# (name, designation, subjects they teach, basic salary)
TEACHERS = [
    ('Bilal Hussain', 'Senior Teacher', ['Mathematics'], 62000),
    ('Kamran Aslam', 'Teacher', ['Mathematics'], 48000),
    ('Nasir Mehmood', 'Teacher', ['Mathematics'], 46000),
    ('Sana Riaz', 'Senior Teacher', ['English'], 58000),
    ('Ayesha Siddiqui', 'Teacher', ['English'], 47000),
    ('Farhan Javed', 'Teacher', ['English'], 45000),
    ('Rabia Noor', 'Senior Teacher', ['Urdu'], 52000),
    ('Shazia Parveen', 'Teacher', ['Urdu'], 44000),
    ('Qari Abdul Rehman', 'Senior Teacher', ['Islamiyat'], 50000),
    ('Hafiz Usman Ali', 'Teacher', ['Islamiyat'], 43000),
    ('Nida Farooq', 'Teacher', ['Computer'], 46000),
    ('Adeel Sarwar', 'Teacher', ['Physics'], 54000),
    ('Sadia Malik', 'Teacher', ['Chemistry'], 54000),
    ('Uzma Khalid', 'Teacher', ['Biology'], 53000),
    ('Tahir Nadeem', 'Teacher', ['Science'], 47000),
    ('Saima Iqbal', 'Teacher', ['General Science'], 45000),
    ('Imtiaz Hussain', 'Teacher', ['Pak Studies'], 44000),
    ('Rukhsana Bibi', 'Teacher', ['Social Studies'], 42000),
    ('Naveed Anwar', 'Teacher', ['Drawing'], 38000),
    ('Mehreen Zafar', 'Teacher', ['English', 'Social Studies'], 44000),
    ('Zeeshan Haider', 'Teacher', ['Mathematics', 'Computer'], 46000),
    ('Hina Shabbir', 'Teacher', ['Urdu', 'Islamiyat'], 43000),
]

SUPPORT_STAFF = [
    ('Adeel Anwar', 'Accountant', 48000),
    ('Nadia Farooq', 'Admin Officer', 45000),
    ('Asad Mehmood', 'Principal', 95000),
    ('Yusuf Karim', 'Director', 0),
    ('Kareem Bakhsh', 'Hostel Warden', 32000),
    ('Rashid Ali', 'Driver', 28000),
    ('Shabana Yasmin', 'Librarian', 34000),
    ('Ghulam Abbas', 'Security Guard', 26000),
]


class Command(BaseCommand):
    help = ('Load a COMPLETE demo school (14 classes, ~280 students, 30 staff, '
            'and data in every module). DESTRUCTIVE: wipes existing data.')

    def add_arguments(self, parser):
        parser.add_argument(
            '--demo', action='store_true',
            help='Confirm you want to WIPE all data and load demo data.')
        parser.add_argument(
            '--tenant', default='',
            help="Subdomain of a tenant school to seed into ITS OWN database "
                 "(e.g. --tenant sca). Omit to seed the master db.sqlite3.")

    # ------------------------------------------------------------------ main
    def handle(self, *args, **options):
        if not options['demo']:
            raise CommandError(
                'Refusing to run: `seed` DELETES all data and loads demo data.\n'
                'If this is a real school, do NOT run this.\n'
                'To load the demo anyway, run:  python manage.py seed --demo\n'
                'To start a blank school instead, run:  python manage.py setup_school')

        self.rnd = random.Random(20260722)   # deterministic demo data
        self.today = timezone.localdate()

        self._switch_tenant(options)
        self._wipe()
        self._school_and_classes()
        self._staff_and_logins()
        self._subjects_and_teachers()
        self._students()
        self._timetable()
        self._attendance()
        self._exams_and_marks()
        self._fees()
        self._hr()
        self._classwork()
        self._operations()
        self._family_logins()

        self.stdout.write(self.style.SUCCESS(
            '\nDemo school ready:  %d classes  |  %d students  |  %d staff  |  '
            '%d teachers\nAll accounts use the password: %s'
            % (ClassRoom.objects.count(), Student.objects.count(),
               Staff.objects.count(),
               Profile.objects.filter(role='teacher').count(), PASSWORD)))

    # -------------------------------------------------------------- tenant
    def _switch_tenant(self, options):
        """Point the connection at a tenant's own SQLite file, if asked."""
        self._tenant = (options.get('tenant') or '').strip()
        self._tenant_name = ''
        if not self._tenant:
            return
        import copy
        import os
        from django.conf import settings
        from django.core.management import call_command
        from django.db import connections
        reg = School.objects.filter(subdomain=self._tenant).first()
        self._tenant_name = reg.name if reg else self._tenant.title()
        db_path = os.path.join(str(settings.BASE_DIR), '%s.sqlite3' % self._tenant)
        conn = connections['default']
        conn.close()
        conn.settings_dict = copy.deepcopy(settings.DATABASES['default'])
        conn.settings_dict['NAME'] = db_path
        self.stdout.write(self.style.MIGRATE_HEADING(
            'Seeding tenant "%s"  ->  %s' % (self._tenant,
                                             os.path.basename(db_path))))
        call_command('migrate', interactive=False, verbosity=0)

    # ---------------------------------------------------------------- wipe
    def _wipe(self):
        self.stdout.write('Clearing old data...')
        for model in (Seat, ExamSchedule, ExamRoom, GradeConfig, Mark,
                      QuizAttempt, Question, Quiz, Submission, Assignment,
                      Material, TimetableSlot, AttendanceRecord, StudentLeave,
                      StudentNote, Message, Complaint, DisciplineRecord,
                      Certificate, ChallanLine, OnlinePayment, FeePayment,
                      ConcessionRequest, FeeChallan, FeeHead, Expense,
                      PaymentSource, IssuedBook, Book, Payslip, Appraisal,
                      LeaveRequest, StaffAttendance, Staff, Applicant,
                      SmsMessage, Visitor, InventoryItem, CalendarEvent,
                      Announcement, AuditLog, TeachingAssignment, Subject,
                      Exam, Profile, Student, HostelRoom, TransportRoute,
                      ClassRoom, School):
            model.objects.all().delete()
        User.objects.filter(is_superuser=False).delete()

    # ------------------------------------------------------ school + classes
    def _school_and_classes(self):
        self.stdout.write('Creating school and classes...')
        school = School.objects.create(
            default_password=PASSWORD, session='2025-26', pass_mark=40,
            campus='Main Campus', address='12-A, College Road, Model Town',
            phone='042-3577 1234', contact_email='info@roshni.edu.pk',
            website='www.roshni.edu.pk', principal_name='Asad Mehmood',
            motto='Knowledge, Character, Service', established='1998',
            receipt_footer='This is a computer-generated receipt. '
                           'Please keep it for your record.',
            login_headline='Everything your school runs on — in one place.',
            login_tagline='Attendance, fees, exams and results, managed from '
                          'one secure portal.',
            tt_days='Mon,Tue,Wed,Thu,Fri,Sat', tt_periods_per_day=8,
            tt_break_period=5, hostel_fee=8000,
            late_fee_amount=200, late_fee_per_week=100, late_fee_max=1000)
        if self._tenant:
            school.subdomain = self._tenant
            if self._tenant_name:
                school.name = self._tenant_name
            school.save()
        self.school = school

        self.classes = []
        self.curriculum = {}      # classroom -> [(subject, periods)]
        for name, section, fee, curriculum, strength in CLASS_PLAN:
            cls = ClassRoom.objects.create(name=name, section=section,
                                           monthly_fee=fee)
            self.classes.append((cls, strength))
            self.curriculum[cls.id] = curriculum

    # ------------------------------------------------------ staff + logins
    def _staff_and_logins(self):
        self.stdout.write('Creating staff and login accounts...')
        self.teacher_profiles = {}     # name -> Profile
        self.subject_pool = {}         # subject name -> [Profile, ...]

        def make_login(username, role, first_name, last_name='', **extra):
            user = User.objects.create_user(
                username=username, password=PASSWORD,
                first_name=first_name, last_name=last_name)
            return user, Profile.objects.create(
                user=user, role=role, school=self.school, **extra)

        # --- teachers (each also gets an HR/staff record) ---
        for i, (name, designation, subjects, salary) in enumerate(TEACHERS, 1):
            first, last = name.split(' ', 1) if ' ' in name else (name, '')
            user, prof = make_login('teacher%02d' % i, 'teacher', first, last)
            Staff.objects.create(
                user=user, name=name, designation=designation,
                phone='03%02d-%07d' % (self.rnd.randint(0, 49),
                                       self.rnd.randint(1000000, 9999999)),
                email='%s@roshni.edu.pk' % ('teacher%02d' % i),
                joined=datetime.date(self.rnd.randint(2015, 2024),
                                     self.rnd.randint(1, 12), 1),
                basic_salary=salary, allowances=int(salary * 0.12))
            self.teacher_profiles[name] = prof
            for subj in subjects:
                self.subject_pool.setdefault(subj, []).append(prof)

        # --- support staff ---
        for name, designation, salary in SUPPORT_STAFF:
            Staff.objects.create(
                name=name, designation=designation,
                phone='03%02d-%07d' % (self.rnd.randint(0, 49),
                                       self.rnd.randint(1000000, 9999999)),
                joined=datetime.date(self.rnd.randint(2012, 2023),
                                     self.rnd.randint(1, 12), 1),
                basic_salary=salary, allowances=int(salary * 0.1))

        # --- office / leadership logins, linked to their staff records ---
        make_login('principal', 'principal', 'Asad', 'Mehmood')
        make_login('office', 'admin', 'Nadia', 'Farooq')
        make_login('director', 'owner', 'Yusuf', 'Karim')
        fin_user, _ = make_login('finance', 'finance', 'Adeel', 'Anwar')
        Staff.objects.filter(name='Adeel Anwar').update(user=fin_user)

        # A friendly 'teacher' alias login pointing at the first teacher.
        alias, alias_prof = make_login('teacher', 'teacher', 'Bilal', 'Hussain')
        self.alias_teacher = alias_prof

        superuser, _ = User.objects.get_or_create(
            username='admin', defaults={'email': ''})
        superuser.is_staff = superuser.is_superuser = True
        superuser.set_password(PASSWORD)
        superuser.save()
        Profile.objects.get_or_create(user=superuser, defaults={'role': 'admin'})

    # ------------------------------------------- subjects + subject teachers
    def _subjects_and_teachers(self):
        self.stdout.write('Assigning subjects and subject teachers...')
        load = {p.id: 0 for p in self.teacher_profiles.values()}
        all_teachers = list(self.teacher_profiles.values())

        for cls, _strength in self.classes:
            class_teachers = []
            for subj_name, periods in self.curriculum[cls.id]:
                Subject.objects.create(name=subj_name, classroom=cls,
                                       periods_per_week=periods)
                pool = self.subject_pool.get(subj_name) or all_teachers
                # Give the lesson to whoever currently teaches the fewest
                # periods, so no teacher is overloaded and the timetable fits.
                teacher = min(pool, key=lambda p: load[p.id])
                load[teacher.id] += periods
                TeachingAssignment.objects.get_or_create(
                    teacher=teacher, classroom=cls, subject=subj_name)
                class_teachers.append(teacher)
            # The class teacher is one of the people who actually teach it.
            cls.class_teacher = class_teachers[0]
            cls.save(update_fields=['class_teacher'])

        # The alias 'teacher' login shares 9-A so that demo account sees data.
        c9a = ClassRoom.objects.get(name='9', section='A')
        self.alias_teacher.classroom = c9a
        self.alias_teacher.save(update_fields=['classroom'])
        for subj in ('Mathematics', 'Computer'):
            TeachingAssignment.objects.get_or_create(
                teacher=self.alias_teacher, classroom=c9a, subject=subj)

    # ------------------------------------------------------------- students
    def _students(self):
        self.stdout.write('Creating students...')
        used = set()
        self.students = []
        adm_counter = 100

        def unique_name(pool):
            for _ in range(200):
                nm = '%s %s' % (self.rnd.choice(pool), self.rnd.choice(FAMILY))
                if nm not in used:
                    used.add(nm)
                    return nm
            nm = '%s %s %d' % (self.rnd.choice(pool), self.rnd.choice(FAMILY),
                               len(used))
            used.add(nm)
            return nm

        # Rough age for each class, so dates of birth look right.
        age_for = {'Nursery': 4, 'KG': 5}
        for n in range(1, 11):
            age_for[str(n)] = 5 + n

        for cls, strength in self.classes:
            for roll in range(1, strength + 1):
                male = self.rnd.random() < 0.52
                name = unique_name(BOYS if male else GIRLS)
                family = name.split(' ')[-1]
                father = '%s %s' % (self.rnd.choice(FATHERS), family)
                adm_counter += 1
                age = age_for.get(cls.name, 10)
                phone = '03%02d-%07d' % (self.rnd.randint(0, 49),
                                         self.rnd.randint(1000000, 9999999))
                city = self.rnd.choice(CITIES)
                # A handful of leavers/alumni so every Students tab has rows.
                status, graduated, left_on = 'Active', False, None
                r = self.rnd.random()
                if cls.name == '10' and r < 0.10:
                    status, graduated = 'Graduated', True
                    left_on = self.today - datetime.timedelta(days=self.rnd.randint(30, 200))
                elif r < 0.03:
                    status = 'Left'
                    left_on = self.today - datetime.timedelta(days=self.rnd.randint(20, 150))

                st = Student.objects.create(
                    name=name, classroom=cls,
                    roll_no='%s-%s-%02d' % (cls.name, cls.section, roll),
                    admission_no='RPS-2024-%04d' % adm_counter,
                    guardian_name=father, guardian_phone=phone,
                    guardian_email='%s@example.com' % father.split(' ')[0].lower(),
                    father_name=father,
                    mother_name='%s %s' % (self.rnd.choice(GIRLS), family),
                    father_phone=phone, guardian_relation='Father',
                    father_occupation=self.rnd.choice(
                        ['Businessman', 'Government Servant', 'Shopkeeper',
                         'Doctor', 'Farmer', 'Engineer', 'Teacher']),
                    date_of_birth=datetime.date(
                        self.today.year - age, self.rnd.randint(1, 12),
                        self.rnd.randint(1, 28)),
                    gender='Male' if male else 'Female',
                    blood_group=self.rnd.choice(BLOOD),
                    address='House %d, %s, %s' % (self.rnd.randint(1, 400),
                                                  self.rnd.choice(AREAS), city),
                    city=city, religion='Islam', nationality='Pakistani',
                    admission_date=datetime.date(
                        self.today.year - min(age - 4, 5),
                        self.rnd.randint(3, 8), 1),
                    emergency_name=father, emergency_phone=phone,
                    emergency_relation='Father',
                    doc_birth=True, doc_photos=True,
                    doc_cnic=self.rnd.random() < 0.8,
                    status=status, graduated=graduated, left_on=left_on)
                self.students.append(st)
        self.stdout.write('  %d students created' % len(self.students))

    # ------------------------------------------------------------ timetable
    def _timetable(self):
        self.stdout.write('Generating a clash-free Mon-Sat timetable...')
        from core.views import _generate_timetable
        unplaced = _generate_timetable()
        made = TimetableSlot.objects.count()
        if unplaced:
            self.stdout.write('  %d slots (%d lessons could not be placed)'
                              % (made, len(unplaced)))
        else:
            self.stdout.write('  %d slots, no clashes' % made)

    # ----------------------------------------------------------- attendance
    def _attendance(self):
        self.stdout.write('Recording attendance (last 24 school days)...')
        days, d = [], self.today
        while len(days) < 24:
            if d.weekday() != 6:          # Sunday is a holiday
                days.append(d)
            d -= datetime.timedelta(days=1)

        rows = []
        active = [s for s in self.students if s.status == 'Active']
        for s in active:
            # Each student has their own reliability, so percentages differ.
            attend_rate = self.rnd.uniform(0.80, 0.99)
            for day in days:
                r = self.rnd.random()
                if r < attend_rate:
                    status = 'P'
                elif r < attend_rate + 0.6 * (1 - attend_rate):
                    status = 'A'
                else:
                    status = 'L'
                rows.append(AttendanceRecord(student=s, date=day, status=status,
                                             session=self.school.session))
        AttendanceRecord.objects.bulk_create(rows, batch_size=2000)
        self.stdout.write('  %d attendance records' % len(rows))

    # ------------------------------------------------------- exams + marks
    def _exams_and_marks(self):
        self.stdout.write('Creating exams, marks, datesheet and seating...')
        session = self.school.session
        first = Exam.objects.create(name='First Term 2025', session=session)
        mid = Exam.objects.create(name='Mid-Term 2026', session=session)
        self.exam = mid

        subjects_by_class = {}
        for sub in Subject.objects.select_related('classroom'):
            subjects_by_class.setdefault(sub.classroom_id, []).append(sub)

        marks = []
        active = [s for s in self.students if s.status != 'Left']
        for s in active:
            ability = self.rnd.gauss(66, 14)        # this student's usual level
            for exam, drift in ((first, 0), (mid, self.rnd.uniform(-6, 8))):
                for sub in subjects_by_class.get(s.classroom_id, []):
                    score = ability + drift + self.rnd.gauss(0, 8)
                    score = int(max(12, min(99, score)))
                    marks.append(Mark(student=s, subject=sub, exam=exam,
                                      marks_obtained=score, total_marks=100))
        Mark.objects.bulk_create(marks, batch_size=2000)
        self.stdout.write('  %d marks entered' % len(marks))

        # Lock a couple of papers so the gradebook lock UI has real examples.
        c9a = ClassRoom.objects.get(name='9', section='A')
        for subj, mx, locked in (('Mathematics', 100, True),
                                 ('English', 100, False),
                                 ('Physics', 75, False)):
            GradeConfig.objects.create(exam=mid, classroom=c9a, subject=subj,
                                       max_marks=mx, locked=locked,
                                       locked_by='Asad Mehmood' if locked else '')

        # Exam rooms, datesheet and seating for the Mid-Term.
        rooms = [ExamRoom.objects.create(name=n, capacity=c) for n, c in
                 (('Hall A', 120), ('Hall B', 100), ('Room 1', 40),
                  ('Room 2', 40), ('Room 3', 40))]
        offset = 2
        for cls, _s in self.classes:
            for i, (subj_name, _p) in enumerate(self.curriculum[cls.id][:5]):
                ExamSchedule.objects.create(
                    exam=mid, classroom=cls, subject=subj_name,
                    date=self.today + datetime.timedelta(days=offset + i * 2),
                    time='09:00 AM - 12:00 PM')

        seats, ri, no = [], 0, 1
        for s in Student.objects.filter(status='Active').order_by(
                'classroom__name', 'classroom__section', 'roll_no'):
            while ri < len(rooms) and no > rooms[ri].capacity:
                ri += 1
                no = 1
            if ri >= len(rooms):
                break
            seats.append(Seat(exam=mid, student=s, room=rooms[ri], seat_no=no))
            no += 1
        Seat.objects.bulk_create(seats, batch_size=1000)

    # ----------------------------------------------------------------- fees
    def _fees(self):
        self.stdout.write('Generating fee challans, payments and expenses...')
        FeeHead.objects.create(name='Admission Fee', amount=5000, frequency='one_time')
        FeeHead.objects.create(name='Annual Charges', amount=3000, frequency='annual')
        FeeHead.objects.create(name='Exam Fee', amount=800, frequency='annual')
        FeeHead.objects.create(name='Security Deposit', amount=2000, frequency='one_time')

        def ym(offset):
            y, m = self.today.year, self.today.month - offset
            while m <= 0:
                m += 12
                y -= 1
            return y, m

        active = [s for s in self.students if s.status == 'Active']
        # Give some students hostel places and transport before billing them.
        hostel_rooms = [HostelRoom.objects.create(
            name=n, capacity=c, warden=w) for n, c, w in
            (('Block A - Room 1', 4, 'Kareem Bakhsh'),
             ('Block A - Room 2', 4, 'Kareem Bakhsh'),
             ('Block B - Room 1', 6, 'Shabana Yasmin'),
             ('Block B - Room 2', 6, 'Shabana Yasmin'),
             ('Block C - Room 1', 8, 'Kareem Bakhsh'))]
        routes = [TransportRoute.objects.create(
            name=n, vehicle=v, driver=d, fee=f) for n, v, d, f in
            (('Route 1 - Model Town', 'LEB-1234', 'Rashid Ali', 2500),
             ('Route 2 - Johar Town', 'LEB-5678', 'Akram Khan', 2800),
             ('Route 3 - Gulberg', 'LEB-9012', 'Saleem Butt', 3000),
             ('Route 4 - Cantt', 'LEB-3456', 'Nazir Ahmed', 2600),
             ('Route 5 - Township', 'LEB-7890', 'Shafiq Masih', 2400))]

        boarders = self.rnd.sample(active, min(18, len(active)))
        for i, s in enumerate(boarders):
            room = hostel_rooms[i % len(hostel_rooms)]
            if room.residents.count() < room.capacity:
                s.is_hostel = True
                s.hostel_room = room
                s.save(update_fields=['is_hostel', 'hostel_room'])
        riders = [s for s in active if not s.is_hostel]
        for s in self.rnd.sample(riders, min(90, len(riders))):
            route = self.rnd.choice(routes)
            s.route = route
            s.pickup_point = '%s Stop' % self.rnd.choice(AREAS)
            s.save(update_fields=['route', 'pickup_point'])
        for r in routes:
            r.students = r.riders.count()
            r.save(update_fields=['students'])

        receipt_no = 0
        for s in active:
            # Every student falls into a realistic paying profile.
            roll = self.rnd.random()
            if roll < 0.55:
                profile = 'good'          # pays on time
            elif roll < 0.70:
                profile = 'partial'       # pays part of the latest month
            elif roll < 0.82:
                profile = 'defaulter'     # months of arrears
            elif roll < 0.92:
                profile = 'scholarship'
            else:
                profile = 'discount'

            for offset in (2, 1, 0):
                y, m = ym(offset)
                extra = {}
                if profile == 'scholarship':
                    extra = {'scholarship': 2500,
                             'scholarship_name': 'Merit Scholarship'}
                elif profile == 'discount' and offset == 0:
                    extra = {'discount': 1000,
                             'discount_reason': 'Sibling discount',
                             'discount_by': 'Asad Mehmood (Principal)'}
                ch = FeeChallan.objects.create(
                    student=s, year=y, month=m,
                    tuition=s.classroom.monthly_fee if s.classroom else 0,
                    hostel_fee=self.school.hostel_fee if s.is_hostel else 0,
                    transport_fee=s.route.fee if s.route else 0,
                    due_date=datetime.date(y, m, 10),
                    late_fee=300 if (profile == 'defaulter' and offset > 0) else 0,
                    **extra)
                # Annual heads land on the oldest challan, like a real year start.
                if offset == 2:
                    ChallanLine.objects.create(challan=ch, label='Annual Charges',
                                               amount=3000)
                    ChallanLine.objects.create(challan=ch, label='Exam Fee',
                                               amount=800)

                should_pay = (profile in ('good', 'scholarship', 'discount')
                              or (profile == 'partial' and offset > 0))
                part = (profile == 'partial' and offset == 0)
                if should_pay or part:
                    amount = ch.net_payable // 2 if part else ch.net_payable
                    if amount > 0:
                        receipt_no += 1
                        FeePayment.objects.create(
                            student=s, challan=ch, month=ch.label, amount=amount,
                            mode=self.rnd.choice(
                                ['Cash', 'Cash', 'Bank', 'JazzCash', 'Easypaisa']),
                            received_by='Adeel Anwar',
                            receipt_no='RCPT-26-%05d' % receipt_no,
                            date=datetime.date(y, m, self.rnd.randint(3, 15)))

        # Keep each student's quick status flag in step with their challans.
        for s in Student.objects.prefetch_related('challans__payments'):
            chs = list(s.challans.all())
            outstanding = sum(c.balance for c in chs)
            overdue = any(c.is_overdue for c in chs)
            s.fee_status = ('Paid' if outstanding <= 0
                            else ('Overdue' if overdue else 'Pending'))
            s.save(update_fields=['fee_status'])

        # Concessions waiting for the Principal, so Approvals is never empty.
        for s in self.rnd.sample(active, 5):
            ch = s.challans.order_by('-year', '-month').first()
            if ch:
                ConcessionRequest.objects.create(
                    challan=ch, kind=self.rnd.choice(['discount', 'scholarship']),
                    amount=self.rnd.choice([1000, 1500, 2000, 2500]),
                    label=self.rnd.choice(['Financial hardship', 'Need-based aid',
                                           'Sibling discount', 'Merit award']),
                    requested_by='Adeel Anwar (Accounts)', status='Pending')

        # Online / bank payments in every state for the verification screen.
        unpaid = list(Student.objects.filter(status='Active')
                      .exclude(fee_status='Paid')[:14])
        for i, s in enumerate(unpaid):
            ch = s.challans.order_by('-year', '-month').first()
            if not ch:
                continue
            status = ['pending', 'pending', 'paid', 'rejected', 'failed'][i % 5]
            OnlinePayment.objects.create(
                student=s, challan=ch,
                gateway=self.rnd.choice(['bank', 'raast', 'jazzcash', 'easypaisa']),
                amount=ch.net_payable, status=status,
                ref='OP-2026-%04d' % (i + 1),
                gateway_ref='TXN%08d' % self.rnd.randint(1, 99999999),
                payer_note='Transferred from %s account' % s.guardian_name,
                verified_by='Adeel Anwar' if status == 'paid' else '')

        # Expenses across categories and months, from real funds.
        cash = PaymentSource.objects.create(name='Main Cash Box',
                                            note='Daily office cash')
        bank = PaymentSource.objects.create(name='HBL Current Account',
                                            note='School operating account')
        expense_rows = [
            ('Electricity bill', 'Utilities', 82000, bank),
            ('Gas bill', 'Utilities', 14500, bank),
            ('Internet & phone', 'Utilities', 9800, bank),
            ('Teaching staff salaries', 'Salaries', 1180000, bank),
            ('Support staff salaries', 'Salaries', 240000, bank),
            ('Stationery and supplies', 'Supplies', 38500, cash),
            ('Whiteboard markers & dusters', 'Supplies', 7200, cash),
            ('Generator maintenance', 'Maintenance', 26000, cash),
            ('Classroom furniture repair', 'Maintenance', 31000, bank),
            ('Bus fuel and servicing', 'Maintenance', 96000, bank),
            ('Library book purchase', 'Supplies', 45000, bank),
            ('Annual function arrangements', 'Other', 68000, cash),
        ]
        for m_off in (2, 1, 0):
            y, m = ym(m_off)
            for title, cat, amount, src in expense_rows:
                Expense.objects.create(
                    title=title, category=cat,
                    amount=int(amount * self.rnd.uniform(0.9, 1.1)),
                    date=datetime.date(y, m, self.rnd.randint(2, 26)),
                    source=src)

    # ------------------------------------------------------------------- HR
    def _hr(self):
        self.stdout.write('Creating HR records (attendance, leave, payroll)...')
        staff = list(Staff.objects.all())
        days, d = [], self.today
        while len(days) < 20:
            if d.weekday() != 6:
                days.append(d)
            d -= datetime.timedelta(days=1)
        rows = []
        for s in staff:
            for day in days:
                r = self.rnd.random()
                status = 'P' if r < 0.93 else ('L' if r < 0.97 else
                                               ('A' if r < 0.99 else 'H'))
                rows.append(StaffAttendance(staff=s, date=day, status=status))
        StaffAttendance.objects.bulk_create(rows, batch_size=1000)

        reasons = ['Family event', 'Medical appointment', 'Personal work',
                   'Wedding in family', 'Out of city']
        for s in self.rnd.sample(staff, 8):
            start = self.today + datetime.timedelta(days=self.rnd.randint(1, 12))
            LeaveRequest.objects.create(
                staff=s, from_date=start,
                to_date=start + datetime.timedelta(days=self.rnd.randint(0, 3)),
                reason=self.rnd.choice(reasons),
                applied_by='Nadia Farooq (Office)', status='Pending')
        for s in self.rnd.sample(staff, 6):
            start = self.today - datetime.timedelta(days=self.rnd.randint(10, 60))
            LeaveRequest.objects.create(
                staff=s, from_date=start,
                to_date=start + datetime.timedelta(days=1),
                reason=self.rnd.choice(reasons), applied_by='Nadia Farooq (Office)',
                status=self.rnd.choice(['Approved', 'Approved', 'Rejected']),
                decided_by='Asad Mehmood (Principal)')

        for offset in (2, 1):
            y, m = self.today.year, self.today.month - offset
            while m <= 0:
                m += 12
                y -= 1
            for s in staff:
                if not s.basic_salary:
                    continue
                Payslip.objects.create(
                    staff=s, year=y, month=m, basic=s.basic_salary,
                    allowances=s.allowances,
                    deductions=self.rnd.choice([0, 0, 0, 500, 1200]),
                    generated_on=datetime.date(y, m, 28))

        for s in self.rnd.sample(staff, 12):
            rating = self.rnd.choice([5, 4, 4, 3, 3, 2])
            Appraisal.objects.create(
                staff=s, period='2025-26', rating=rating,
                strengths=self.rnd.choice([
                    'Excellent classroom control and lesson planning.',
                    'Very punctual and cooperative with colleagues.',
                    'Strong subject knowledge; students score well.',
                    'Handles parents professionally and patiently.']),
                improvements=self.rnd.choice([
                    'Could use more visual teaching aids.',
                    'Submit monthly result sheets on time.',
                    'Encourage weaker students to participate more.',
                    'Attend the upcoming teacher training workshop.']),
                reviewer='Asad Mehmood (Principal)')

    # ----------------------------------- assignments, quizzes and materials
    def _classwork(self):
        self.stdout.write('Creating assignments, quizzes and materials...')
        senior = [c for c, _s in self.classes
                  if c.name in ('5', '6', '7', '8', '9', '10')]
        subjects_by_class = {}
        for sub in Subject.objects.select_related('classroom'):
            subjects_by_class.setdefault(sub.classroom_id, []).append(sub)

        titles = {
            'Mathematics': ('Exercise 5.2 — Q1 to Q10',
                            'Solve every question and show your full working.'),
            'English': ('Essay: My Country (300 words)',
                        'Write a 300-word essay. Watch your paragraphing.'),
            'Urdu': ('Nazm ki tashreeh — Chapter 3',
                     'Explain the poem in your own words.'),
            'Science': ('Lab report — Photosynthesis',
                        'Write up the experiment we did in class.'),
            'Physics': ('Numericals — Motion and Force',
                        'Attempt all numericals from the chapter review.'),
            'Chemistry': ('Worksheet — Periodic Table',
                          'Complete the worksheet handed out in class.'),
            'Biology': ('Diagram — The human heart',
                        'Draw and label the human heart neatly.'),
            'Computer': ('Practical — Format a document in MS Word',
                         'Format the given text and submit a printout.'),
            'Pak Studies': ('Notes — Ideology of Pakistan',
                            'Prepare short notes for the coming test.'),
            'Islamiyat': ('Seerat-un-Nabi — key events',
                          'List and briefly describe five key events.'),
        }
        made = 0
        for cls in senior:
            for sub in subjects_by_class.get(cls.id, [])[:4]:
                title, desc = titles.get(sub.name,
                                         ('Revision worksheet',
                                          'Complete the worksheet given in class.'))
                a = Assignment.objects.create(
                    classroom=cls, subject=sub, title=title, description=desc,
                    due_date=self.today + datetime.timedelta(
                        days=self.rnd.randint(2, 10)))
                made += 1
                # Some of the class has already submitted; some are graded.
                roster = [s for s in self.students
                          if s.classroom_id == cls.id and s.status == 'Active']
                for s in self.rnd.sample(roster, max(1, len(roster) // 3)):
                    graded = self.rnd.random() < 0.5
                    Submission.objects.create(
                        assignment=a, student=s,
                        answer_text='Completed the work in my notebook.',
                        status='Graded' if graded else 'Submitted',
                        grade=self.rnd.choice(['A', 'B+', 'B', 'A-'])
                        if graded else '')

        quiz_bank = [
            ('Algebra Basics', 'Mathematics', 15, [
                ('What is x if 2x = 10?', '3', '5', '10', '20', 'B'),
                ('Simplify: 3x + 2x', '5x', '6x', 'x', '5', 'A'),
                ('What is 7 squared?', '14', '49', '21', '77', 'B'),
                ('Solve: x - 4 = 6', '2', '10', '24', '-2', 'B'),
            ]),
            ('MS Word Fundamentals', 'Computer', 10, [
                ('Which shortcut saves a document?', 'Ctrl + S', 'Ctrl + P',
                 'Ctrl + Z', 'Ctrl + V', 'A'),
                ('Which shortcut makes text bold?', 'Ctrl + B', 'Ctrl + I',
                 'Ctrl + U', 'Ctrl + L', 'A'),
                ('Where is the Print option?', 'File menu', 'Edit menu',
                 'View menu', 'Insert menu', 'A'),
            ]),
            ('Cell Structure', 'Science', 10, [
                ('Powerhouse of the cell?', 'Nucleus', 'Mitochondria',
                 'Ribosome', 'Cell wall', 'B'),
                ('Which part controls the cell?', 'Nucleus', 'Cytoplasm',
                 'Membrane', 'Vacuole', 'A'),
                ('Plant cells have a cell ___?', 'Wall', 'Mouth', 'Bone',
                 'Skin', 'A'),
            ]),
            ('Tenses Check', 'English', 10, [
                ('He ___ to school every day.', 'go', 'goes', 'going', 'gone', 'B'),
                ('They ___ playing now.', 'is', 'am', 'are', 'be', 'C'),
                ('I ___ my homework yesterday.', 'do', 'did', 'does', 'done', 'B'),
            ]),
        ]
        for cls in senior:
            names = {s.name for s in subjects_by_class.get(cls.id, [])}
            for title, subj_name, limit, questions in quiz_bank:
                if subj_name not in names:
                    continue
                sub = next(s for s in subjects_by_class[cls.id]
                           if s.name == subj_name)
                quiz = Quiz.objects.create(classroom=cls, subject=sub,
                                           title=title, time_limit=limit)
                for i, (text, a, b, c, d, correct) in enumerate(questions, 1):
                    Question.objects.create(
                        quiz=quiz, text=text, option_a=a, option_b=b,
                        option_c=c, option_d=d, correct=correct, order=i)
                roster = [s for s in self.students
                          if s.classroom_id == cls.id and s.status == 'Active']
                for s in self.rnd.sample(roster, max(1, len(roster) // 2)):
                    total = len(questions)
                    QuizAttempt.objects.create(
                        quiz=quiz, student=s, total=total,
                        score=self.rnd.randint(max(1, total - 3), total))

        material_kinds = [('Notes', 'Chapter notes', '620 KB'),
                          ('Book', 'Textbook (PDF)', '10.4 MB'),
                          ('Past Paper', 'Last year paper with solution', '780 KB'),
                          ('Slides', 'Lecture slides', '3.1 MB')]
        for cls in senior:
            for sub in subjects_by_class.get(cls.id, []):
                for mtype, title, size in material_kinds:
                    Material.objects.create(
                        subject=sub, mat_type=mtype,
                        title='%s — %s' % (sub.name, title), size=size)
        self.stdout.write('  %d assignments, %d quizzes, %d materials'
                          % (made, Quiz.objects.count(), Material.objects.count()))

    # ------------------------------------------------------------ operations
    def _operations(self):
        self.stdout.write('Creating library, inventory, discipline, messages...')
        active = [s for s in self.students if s.status == 'Active']

        books = [
            ('Oxford English Dictionary', 'Oxford Press', 'LIB-0451', 6),
            ('A Brief History of Time', 'Stephen Hawking', 'LIB-0782', 3),
            ('Pakistan Studies Reference', 'Ferozsons', 'LIB-1033', 10),
            ('Mathematics Olympiad Guide', 'NMS', 'LIB-1190', 4),
            ('Urdu Adab ka Safar', 'Dr. Jameel Jalibi', 'LIB-1240', 5),
            ('The Story of Pakistan', 'Ahmed Rashid', 'LIB-1305', 6),
            ('Encyclopedia of Science', 'Dorling Kindersley', 'LIB-1402', 2),
            ('Seerat-un-Nabi (SAW)', 'Shibli Nomani', 'LIB-1455', 8),
            ('Physics for Beginners', 'Cambridge', 'LIB-1500', 5),
            ('Chemistry Lab Manual', 'Punjab Board', 'LIB-1533', 7),
            ('Biology Illustrated', 'Macmillan', 'LIB-1580', 4),
            ('Computer Science Basics', 'Sams', 'LIB-1610', 6),
        ]
        book_objs = []
        for title, author, code, copies in books:
            issued = self.rnd.randint(0, min(3, copies))
            book_objs.append(Book.objects.create(
                title=title, author=author, code=code, copies=copies,
                available=copies - issued))
        for b in book_objs:
            out = b.copies - b.available
            for _ in range(out):
                s = self.rnd.choice(active)
                issued_on = self.today - datetime.timedelta(days=self.rnd.randint(1, 25))
                IssuedBook.objects.create(
                    book=b, student_name='%s (%s)' % (s.name, s.classroom),
                    issued_on=issued_on,
                    due_on=issued_on + datetime.timedelta(days=14))

        inventory = [
            ('School Uniform (Shirt)', 'Uniform', 120, 50, 'pcs'),
            ('School Uniform (Trouser)', 'Uniform', 96, 50, 'pcs'),
            ('School Tie', 'Uniform', 40, 45, 'pcs'),
            ('Notebooks (200 pg)', 'Stationery', 340, 100, 'pcs'),
            ('Register (Attendance)', 'Stationery', 25, 30, 'pcs'),
            ('Ball Pens (box)', 'Stationery', 60, 20, 'box'),
            ('Whiteboard Markers', 'Supplies', 28, 40, 'pcs'),
            ('Chalk (box)', 'Supplies', 55, 20, 'box'),
            ('A4 Paper (ream)', 'Supplies', 34, 15, 'ream'),
            ('Printer Toner', 'Supplies', 3, 5, 'pcs'),
            ('Textbook Set - Class 9', 'Books', 62, 30, 'sets'),
            ('Textbook Set - Class 10', 'Books', 48, 30, 'sets'),
            ('First Aid Kit', 'Other', 6, 4, 'pcs'),
            ('Sports Equipment Set', 'Other', 9, 5, 'sets'),
        ]
        for name, cat, qty, reorder, unit in inventory:
            InventoryItem.objects.create(name=name, category=cat, quantity=qty,
                                         reorder_level=reorder, unit=unit)

        visitor_rows = [
            ('Mr. Imran Khan', 'Meet class teacher (9-A)', 'Rabia Noor', False),
            ('Ferozsons Sales Rep', 'Book supply', 'Admin Office', True),
            ('Mrs. Shazia Bibi', 'Fee enquiry', 'Accounts', True),
            ('Mr. Tariq Mehmood', 'Admission enquiry', 'Admin Office', False),
            ('School Board Inspector', 'Annual inspection', 'Principal', True),
            ('Water Supplier', 'Monthly delivery', 'Support Staff', True),
            ('Mrs. Naila Akhtar', 'Discuss result', 'Sana Riaz', False),
        ]
        for name, purpose, meet, out in visitor_rows:
            Visitor.objects.create(name=name, purpose=purpose, to_meet=meet,
                                   pass_no='V-%03d' % self.rnd.randint(200, 399),
                                   checked_out=out)

        disc_rows = [
            ('Behaviour', 'Major', 'Disrupting class repeatedly.',
             'Parent informed; verbal warning issued.', 'Open'),
            ('Uniform', 'Minor', 'Arrived without the school ID card.',
             'Verbal warning.', 'Resolved'),
            ('Homework', 'Minor', 'Homework not submitted on time (third time).',
             '', 'Open'),
            ('Attendance', 'Minor', 'Late to morning assembly.',
             'Counselled by class teacher.', 'Resolved'),
            ('Property', 'Major', 'Damaged a classroom chair during break.',
             'Parent informed; repair cost recovered.', 'Resolved'),
            ('Bullying', 'Critical', 'Fighting with a classmate in the corridor.',
             'Both parents called; two-day suspension.', 'Open'),
        ]
        for s in self.rnd.sample(active, 14):
            cat, sev, desc, action, status = self.rnd.choice(disc_rows)
            DisciplineRecord.objects.create(
                student=s,
                date=self.today - datetime.timedelta(days=self.rnd.randint(1, 40)),
                category=cat, severity=sev, description=desc,
                action_taken=action, reported_by=self.rnd.choice(
                    ['Bilal Hussain', 'Nadia Farooq', 'Sana Riaz']),
                status=status)

        note_rows = [
            ('Praise', 'Excellent participation in class discussion today.'),
            ('Praise', 'Scored full marks in the surprise test — well done!'),
            ('Concern', 'Not completing homework regularly this week.'),
            ('Concern', 'Seems distracted in class; please check at home.'),
            ('Note', 'Represented the class in the debate competition.'),
            ('Note', 'Handwriting has improved a lot this term.'),
        ]
        for s in self.rnd.sample(active, 20):
            kind, text = self.rnd.choice(note_rows)
            teacher = s.classroom.class_teacher if s.classroom else None
            StudentNote.objects.create(
                student=s, kind=kind, text=text, teacher=teacher,
                teacher_name=(teacher.user.get_full_name() if teacher else ''),
                date=self.today - datetime.timedelta(days=self.rnd.randint(0, 25)))

        for s in self.rnd.sample(active, 10):
            start = self.today + datetime.timedelta(days=self.rnd.randint(-10, 10))
            StudentLeave.objects.create(
                student=s, from_date=start,
                to_date=start + datetime.timedelta(days=self.rnd.randint(0, 2)),
                reason=self.rnd.choice(['Fever', 'Family wedding',
                                        'Out of city', 'Doctor appointment']),
                status=self.rnd.choice(['Pending', 'Pending', 'Approved',
                                        'Rejected']),
                applied_by='Parent')

        complaint_rows = [
            ('Transport', 'Van arrives late every morning',
             'The van has been 20 minutes late for the past week.'),
            ('Fee', 'Fee challan shows wrong amount',
             'Transport fee is charged although we do not use the van.'),
            ('Academic', 'Maths syllabus is behind schedule',
             'The class seems behind compared to the term plan.'),
            ('Facility', 'Classroom fan not working',
             'The fan in 8-A has been out of order for days.'),
            ('Staff', 'Request to change section',
             'We would like our child moved to the morning section.'),
            ('Other', 'Canteen food quality',
             'Please look into the quality of food at the canteen.'),
        ]
        for i, (cat, subject, body) in enumerate(complaint_rows):
            s = self.rnd.choice(active)
            status = ['Open', 'In Progress', 'Resolved'][i % 3]
            Complaint.objects.create(
                student=s, raised_by_name=s.guardian_name, category=cat,
                subject=subject, body=body, status=status,
                response='Noted — we are looking into this.'
                if status != 'Open' else '',
                handled_by='Nadia Farooq' if status != 'Open' else '')

        # Parent <-> teacher message threads (some unread on each side).
        for s in self.rnd.sample(active, 8):
            teacher = s.classroom.class_teacher if s.classroom else None
            tname = teacher.user.get_full_name() if teacher else 'Class Teacher'
            Message.objects.create(
                student=s, sender_name=s.guardian_name, sender_role='parent',
                body='Assalam-o-Alaikum. How is %s doing in class this term?'
                     % s.name.split(' ')[0],
                seen_by_staff=True, seen_by_family=True)
            Message.objects.create(
                student=s, sender=teacher, sender_name=tname,
                sender_role='teacher',
                body='Walaikum Assalam. %s is doing well overall; just needs '
                     'to be more regular with homework.' % s.name.split(' ')[0],
                seen_by_staff=True, seen_by_family=False)
        for s in self.rnd.sample(active, 4):
            Message.objects.create(
                student=s, sender_name=s.guardian_name, sender_role='parent',
                body='Please share the date sheet for the coming exams.',
                seen_by_staff=False, seen_by_family=True)

        for s in self.rnd.sample(self.students, 10):
            Certificate.objects.create(
                student=s,
                cert_type=self.rnd.choice(['Leaving', 'Character', 'Bonafide',
                                           'Birth', 'Fee']),
                issued_on=self.today - datetime.timedelta(
                    days=self.rnd.randint(1, 120)))

        applicants = [
            ('Ahmad Raza', 'Class 1', 'Raza Khan', 'Enquiry'),
            ('Fatima Noor', 'Class 6', 'Noor Ahmed', 'Enquiry'),
            ('Hassan Ali', 'Class 3', 'Ali Akbar', 'Test'),
            ('Mariam Shah', 'Class 9', 'Shah Jahan', 'Test'),
            ('Bilal Tariq', 'Class 4', 'Tariq Mahmood', 'Offer'),
            ('Zainab Malik', 'Class 7', 'Malik Riaz', 'Offer'),
            ('Ayesha Khan', 'Class 2', 'Khan Sahib', 'Enrolled'),
            ('Umar Farooq', 'Nursery', 'Farooq Ahmed', 'Enquiry'),
            ('Hania Sheikh', 'Class 5', 'Sheikh Imran', 'Test'),
            ('Rehan Butt', 'Class 8', 'Butt Sahib', 'Rejected'),
        ]
        for i, (name, cls_applied, parent, stage) in enumerate(applicants, 1):
            Applicant.objects.create(
                name=name, class_applied=cls_applied, parent_name=parent,
                phone='03%02d-%07d' % (self.rnd.randint(0, 49),
                                       self.rnd.randint(1000000, 9999999)),
                stage=stage, source='Online' if i % 3 == 0 else 'Office',
                ref='ADM-%04d' % (1000 + i))

        sms_rows = [
            ('All Parents', 'Announcement', 'Console',
             'Mid-Term exams begin next week. The date sheet is in the portal.'),
            ('All Parents - Class 9', 'Announcement', 'Console',
             'Parent-Teacher Meeting this Saturday at 9:00 AM.'),
            ('Imran Khan', 'Fee Reminder', 'Console',
             'Fee reminder: outstanding amount is due by the 10th.'),
            ('Aslam Pervaiz', 'Fee Receipt', 'Console',
             'Received Rs 6,500. Receipt RCPT-26-00042. Thank you.'),
            ('Naeem Ahmed', 'Absent Alert', 'Console',
             'Your child was marked absent today.'),
            ('Fatima Noor', 'Fee Reminder', 'Failed',
             'Dear parent, fee reminder from Roshni Public School.'),
        ]
        for recipients, mtype, status, body in sms_rows:
            SmsMessage.objects.create(
                recipients=recipients, msg_type=mtype, status=status,
                provider='console' if status == 'Console' else 'twilio',
                error='Twilio is not configured.' if status == 'Failed' else '',
                body=body)

        events = [
            ('Summer vacation begins', 'Holiday', 6),
            ('Mid-Term examinations begin', 'Exam', 9),
            ('Parent-Teacher Meeting', 'PTM', 13),
            ('Independence Day celebration', 'Event', 24),
            ('Annual Sports Day', 'Event', 38),
            ('Eid holidays', 'Holiday', 52),
            ('Result day — Mid-Term', 'Academic', 30),
            ('Science exhibition', 'Event', 45),
        ]
        for title, etype, offset in events:
            CalendarEvent.objects.create(
                title=title, event_type=etype,
                date=self.today + datetime.timedelta(days=offset))

        announcements = [
            ('Mid-Term Exams begin next week',
             'The full examination schedule has been published in the portal.',
             'All'),
            ('Parent-Teacher Meeting this Saturday',
             'PTM for all classes from 9:00 AM to 1:00 PM.', 'Parents'),
            ('School closed on Friday',
             'The school will remain closed for a public holiday.', 'All'),
            ('Staff meeting on Monday',
             'All teaching staff to attend the meeting at 2:00 PM.', 'Staff'),
            ('Winter uniform from next month',
             'Students should switch to the winter uniform from the 1st.', 'All'),
        ]
        for title, body, audience in announcements:
            Announcement.objects.create(title=title, body=body, audience=audience)

        audits = [
            ('office', 'Student added', 'Created a new student record'),
            ('finance', 'Payment recorded', 'Fee payment of Rs 6,500 received'),
            ('principal', 'Concession approved', 'Approved a merit scholarship'),
            ('teacher01', 'Marks entered', 'Mid-Term marks saved for 9-A Maths'),
            ('office', 'Role changed', 'Changed a user role to Teacher'),
            ('finance', 'Payment voided', 'Voided a duplicate receipt'),
        ]
        for user, action, detail in audits:
            AuditLog.objects.create(user=user, action=action, detail=detail)

    # ---------------------------------------------- parent / student logins
    def _family_logins(self):
        """Give a slice of the school real family logins, plus the friendly
        'parent' / 'student' demo accounts everyone signs in with."""
        self.stdout.write('Creating parent and student logins...')
        c9a = ClassRoom.objects.get(name='9', section='A')
        roster = [s for s in self.students
                  if s.classroom_id == c9a.id and s.status == 'Active']

        # The headline demo family: one parent with TWO children in the school.
        elder = roster[0]
        younger = next((s for s in self.students
                        if s.classroom and s.classroom.name == '5'
                        and s.status == 'Active'), roster[1])
        # Make them a real family — same guardian details.
        younger.guardian_name = elder.guardian_name
        younger.father_name = elder.father_name
        younger.guardian_phone = elder.guardian_phone
        younger.save(update_fields=['guardian_name', 'father_name',
                                    'guardian_phone'])

        parent_user = User.objects.create_user(
            username='parent', password=PASSWORD,
            first_name=elder.guardian_name.split(' ')[0])
        parent_profile = Profile.objects.create(
            user=parent_user, role='parent', school=self.school, student=elder)
        parent_profile.children.set([elder, younger])

        student_user = User.objects.create_user(
            username='student', password=PASSWORD,
            first_name=elder.name.split(' ')[0])
        Profile.objects.create(user=student_user, role='student',
                               school=self.school, student=elder)

        # A few more real family logins so the lists aren't a single row.
        for i, s in enumerate(roster[1:9], 1):
            su = User.objects.create_user(
                username='student%02d' % i, password=PASSWORD,
                first_name=s.name.split(' ')[0])
            Profile.objects.create(user=su, role='student', school=self.school,
                                   student=s)
            pu = User.objects.create_user(
                username='parent%02d' % i, password=PASSWORD,
                first_name=s.guardian_name.split(' ')[0])
            pp = Profile.objects.create(user=pu, role='parent',
                                        school=self.school, student=s)
            pp.children.set([s])
