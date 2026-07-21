import datetime

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core.models import (Announcement, Applicant, Assignment, AttendanceRecord,
                         Book, CalendarEvent, Certificate, ClassRoom, ConcessionRequest,
                         DisciplineRecord,
                         Exam, ExamRoom, ExamSchedule,
                         Expense, FeeChallan, FeeHead, FeePayment, HostelRoom, InventoryItem, IssuedBook,
                         LeaveRequest, Mark, Material, Payslip,
                         Profile, Question, Quiz, QuizAttempt, School, Seat,
                         SmsMessage, Staff, StaffAttendance, Student, Subject, Submission,
                         TeachingAssignment, TimetableSlot, TransportRoute, Visitor)

# One simple password for every demo account, so testing is easy.
PASSWORD = 'roshni123'


class Command(BaseCommand):
    help = ('Load DEMO data and login accounts for every role. '
            'DESTRUCTIVE: wipes existing data. Requires --demo to run.')

    def add_arguments(self, parser):
        parser.add_argument(
            '--demo', action='store_true',
            help='Confirm you want to WIPE all data and load demo data.')
        parser.add_argument(
            '--tenant', default='',
            help="Subdomain of a tenant school to seed into ITS OWN database "
                 "(e.g. --tenant sca). Omit to seed the master db.sqlite3.")

    def handle(self, *args, **options):
        if not options['demo']:
            raise CommandError(
                'Refusing to run: `seed` DELETES all data and loads demo data.\n'
                'If this is a real school, do NOT run this.\n'
                'To load the demo anyway, run:  python manage.py seed --demo\n'
                'To start a blank school instead, run:  python manage.py setup_school')

        # --tenant: point the connection at that school's own SQLite file before
        # touching any data, so the demo lands in the tenant DB (not the master).
        # We grab the school's real name from the master registry first, then
        # (after switching) stamp the subdomain onto the seeded School row — the
        # routing middleware deletes any School whose subdomain != the tenant.
        self._tenant = (options.get('tenant') or '').strip()
        self._tenant_name = ''
        if self._tenant:
            import os
            import copy
            from django.conf import settings
            from django.db import connections
            from django.core.management import call_command
            reg = School.objects.filter(subdomain=self._tenant).first()
            self._tenant_name = reg.name if reg else self._tenant.title()
            db_path = os.path.join(str(settings.BASE_DIR),
                                   '%s.sqlite3' % self._tenant)
            conn = connections['default']
            conn.close()
            conn.settings_dict = copy.deepcopy(settings.DATABASES['default'])
            conn.settings_dict['NAME'] = db_path
            self.stdout.write(self.style.MIGRATE_HEADING(
                'Seeding tenant "%s"  ->  %s' % (self._tenant,
                                                 os.path.basename(db_path))))
            # Ensure the tenant DB exists and has the current schema before we
            # start deleting/inserting (creates the file if it's the first time).
            call_command('migrate', interactive=False, verbosity=0)

        self.stdout.write('Clearing old demo data...')
        Visitor.objects.all().delete()
        InventoryItem.objects.all().delete()
        CalendarEvent.objects.all().delete()
        Certificate.objects.all().delete()
        Staff.objects.all().delete()
        StaffAttendance.objects.all().delete()
        LeaveRequest.objects.all().delete()
        Payslip.objects.all().delete()
        Applicant.objects.all().delete()
        SmsMessage.objects.all().delete()
        TransportRoute.objects.all().delete()
        IssuedBook.objects.all().delete()
        Book.objects.all().delete()
        FeePayment.objects.all().delete()
        ConcessionRequest.objects.all().delete()
        FeeChallan.objects.all().delete()
        Expense.objects.all().delete()
        Mark.objects.all().delete()
        DisciplineRecord.objects.all().delete()
        AttendanceRecord.objects.all().delete()
        Material.objects.all().delete()
        TimetableSlot.objects.all().delete()
        Submission.objects.all().delete()
        QuizAttempt.objects.all().delete()
        Question.objects.all().delete()
        Assignment.objects.all().delete()
        Quiz.objects.all().delete()
        Subject.objects.all().delete()
        TeachingAssignment.objects.all().delete()
        Seat.objects.all().delete()
        ExamSchedule.objects.all().delete()
        ExamRoom.objects.all().delete()
        Exam.objects.all().delete()
        Profile.objects.all().delete()
        HostelRoom.objects.all().delete()
        Student.objects.all().delete()
        ClassRoom.objects.all().delete()
        Announcement.objects.all().delete()
        School.objects.all().delete()
        User.objects.filter(is_superuser=False).delete()

        self.stdout.write('Creating school and classes...')
        school_obj = School.objects.create(default_password=PASSWORD)
        if self._tenant:
            # Keep this row alive under the tenant routing middleware, and carry
            # the school's real name over from the master registry.
            school_obj.subdomain = self._tenant
            if self._tenant_name:
                school_obj.name = self._tenant_name
            school_obj.save()
        c9 = ClassRoom.objects.create(name='9', section='A', monthly_fee=5500)
        c10 = ClassRoom.objects.create(name='10', section='A', monthly_fee=5500)
        c5 = ClassRoom.objects.create(name='5', section='B', monthly_fee=4500)

        self.stdout.write('Creating students...')
        rows = [
            ('Ayaan Khan', c9, '09-A-04', 'RPS-2024-0188', 'Imran Khan', '0301-2345671', 'Pending'),
            ('Hira Aslam', c9, '09-A-07', 'RPS-2024-0191', 'Aslam Pervaiz', '0300-1112233', 'Paid'),
            ('Bilal Ahmed', c9, '09-A-01', 'RPS-2024-0185', 'Naeem Ahmed', '0302-2223344', 'Overdue'),
            ('Mahnoor Fatima', c9, '09-A-11', 'RPS-2024-0199', 'Tariq Mehmood', '0303-3334455', 'Paid'),
            ('Areeba Malik', c10, '10-A-03', 'RPS-2023-0150', 'Malik Riaz', '0304-4445566', 'Paid'),
            ('Saad Iqbal', c10, '10-A-08', 'RPS-2023-0162', 'Iqbal Hussain', '0305-5556677', 'Pending'),
            ('Inaya Khan', c5, '05-B-09', 'RPS-2025-0312', 'Imran Khan', '0301-2345671', 'Paid'),
        ]
        students = {}
        for name, cls, roll, adm, guardian, phone, fee in rows:
            students[name] = Student.objects.create(
                name=name, classroom=cls, roll_no=roll, admission_no=adm,
                guardian_name=guardian, guardian_phone=phone, fee_status=fee)

        self.stdout.write('Creating subjects and exam...')
        subject_names = ['English', 'Urdu', 'Mathematics', 'Science',
                         'Islamiyat', 'Pak Studies', 'Computer']
        subjects = {n: Subject.objects.create(name=n, classroom=c9)
                    for n in subject_names}
        for _cls in (c10, c5):
            for _n in subject_names:
                Subject.objects.create(name=_n, classroom=_cls)
        _school = School.objects.first()
        exam = Exam.objects.create(
            name='Mid-Term 2026',
            session=(_school.session if _school else '2025-26'))

        self.stdout.write('Entering Mid-Term marks for Ayaan Khan...')
        ayaan = students['Ayaan Khan']
        ayaan_marks = {
            'English': 82, 'Urdu': 88, 'Mathematics': 91, 'Science': 85,
            'Islamiyat': 90, 'Pak Studies': 86, 'Computer': 89,
        }  # total 611 / 700 = 87% (Grade A)
        for sub_name, val in ayaan_marks.items():
            Mark.objects.create(student=ayaan, subject=subjects[sub_name],
                                exam=exam, marks_obtained=val, total_marks=100)

        # A failing student (suggested for "Detain") and a mid-range passing one
        bilal_ahmed = students['Bilal Ahmed']
        for sub_name, val in {'English': 32, 'Urdu': 41, 'Mathematics': 28,
                              'Science': 35, 'Islamiyat': 45, 'Pak Studies': 30,
                              'Computer': 38}.items():   # ~36% -> Fail
            Mark.objects.create(student=bilal_ahmed, subject=subjects[sub_name],
                                exam=exam, marks_obtained=val, total_marks=100)
        hira = students['Hira Aslam']
        for sub_name, val in {'English': 64, 'Urdu': 70, 'Mathematics': 58,
                              'Science': 66, 'Islamiyat': 72, 'Pak Studies': 60,
                              'Computer': 63}.items():   # ~65% -> Pass
            Mark.objects.create(student=hira, subject=subjects[sub_name],
                                exam=exam, marks_obtained=val, total_marks=100)

        self.stdout.write('Adding subject materials...')
        materials = {
            'Mathematics': [
                ('Notes', 'Chapter 5 - Algebraic Expressions', '1.2 MB'),
                ('Past Paper', 'Mid-Term 2025 (with solution)', '780 KB'),
                ('Slides', 'Quadratic Equations - lecture', '3.4 MB'),
                ('Book', 'Mathematics Textbook - Class 9', '12.1 MB'),
            ],
            'English': [
                ('Notes', 'Grammar - Tenses summary', '640 KB'),
                ('Notes', 'Essay writing - guidelines', '410 KB'),
                ('Book', 'English Reader - Class 9', '9.8 MB'),
            ],
            'Science': [
                ('Slides', 'Photosynthesis - diagrams', '2.6 MB'),
                ('Past Paper', 'First Term 2025', '820 KB'),
                ('Book', 'General Science - Class 9', '14.3 MB'),
            ],
            'Urdu': [
                ('Notes', 'Nazm tashreeh - Chapter 3', '720 KB'),
                ('Book', 'Urdu Textbook - Class 9', '8.1 MB'),
            ],
            'Islamiyat': [
                ('Notes', 'Seerat-un-Nabi - key points', '560 KB'),
                ('Book', 'Islamiyat - Class 9', '6.4 MB'),
            ],
            'Pak Studies': [
                ('Notes', 'Ideology of Pakistan - notes', '690 KB'),
                ('Book', 'Pakistan Studies - Class 9', '7.2 MB'),
            ],
            'Computer': [
                ('Slides', 'Introduction to MS Word', '4.1 MB'),
                ('Notes', 'Hardware vs Software', '380 KB'),
                ('Book', 'Computer Science - Class 9', '10.5 MB'),
            ],
        }
        for sub_name, items in materials.items():
            subj = subjects.get(sub_name)
            if not subj:
                continue
            for mtype, title, size in items:
                Material.objects.create(subject=subj, mat_type=mtype,
                                        title=title, size=size)

        self.stdout.write('Building class 9-A timetable...')
        period_times = ['08:00', '08:45', '09:30', '10:15', '11:00', '11:45']
        timetable = {
            'Mon': [('Mathematics', 'Sir Bilal'), ('English', 'Ms Sana'),
                    ('Science', 'Sir Kamran'), ('Urdu', 'Ms Rabia'),
                    ('Break', ''), ('Computer', 'Ms Nida')],
            'Tue': [('English', 'Ms Sana'), ('Mathematics', 'Sir Bilal'),
                    ('Islamiyat', 'Ms Rabia'), ('Science', 'Sir Kamran'),
                    ('Break', ''), ('Pak Studies', 'Sir Kamran')],
            'Wed': [('Science', 'Sir Kamran'), ('Urdu', 'Ms Rabia'),
                    ('Mathematics', 'Sir Bilal'), ('English', 'Ms Sana'),
                    ('Break', ''), ('Library', '')],
            'Thu': [('Mathematics', 'Sir Bilal'), ('Computer', 'Ms Nida'),
                    ('English', 'Ms Sana'), ('Islamiyat', 'Ms Rabia'),
                    ('Break', ''), ('Science', 'Sir Kamran')],
            'Fri': [('Pak Studies', 'Sir Kamran'), ('Mathematics', 'Sir Bilal'),
                    ('Urdu', 'Ms Rabia'), ('Computer', 'Ms Nida'),
                    ('Break', ''), ('Games', '')],
        }
        for day, slots in timetable.items():
            for i, (subj_name, teacher) in enumerate(slots):
                TimetableSlot.objects.create(
                    classroom=c9, day=day, period=i + 1,
                    start_time=period_times[i], subject=subj_name,
                    teacher=teacher)

        self.stdout.write('Recording attendance for class 9-A (full month)...')
        today = timezone.localdate()
        c9_students = [s for s in students.values() if s.classroom_id == c9.id]
        school_days = []
        d = today.replace(day=1)
        while d <= today:
            if d.weekday() != 6:          # skip Sunday (holiday)
                school_days.append(d)
            d += datetime.timedelta(days=1)
        # A few non-present days so the data is realistic (counted from the end):
        status_map = {}

        def mark_day(name, idx_from_end, st):
            if len(school_days) >= idx_from_end:
                status_map[(name, school_days[-idx_from_end])] = st

        mark_day('Ayaan Khan', 4, 'L')
        mark_day('Ayaan Khan', 9, 'A')
        mark_day('Bilal Ahmed', 3, 'A')
        mark_day('Bilal Ahmed', 7, 'A')
        mark_day('Hira Aslam', 5, 'A')
        for day in school_days:
            for s in c9_students:
                status = status_map.get((s.name, day), 'P')
                AttendanceRecord.objects.create(student=s, date=day, status=status)

        self.stdout.write('Creating assignments and quizzes...')
        a1 = Assignment.objects.create(
            classroom=c9, subject=subjects.get('Mathematics'),
            title='Exercise 5.2 - Q1 to Q10',
            description='Solve all questions from Exercise 5.2 and show your full working.',
            due_date=today + datetime.timedelta(days=3))
        Assignment.objects.create(
            classroom=c9, subject=subjects.get('English'),
            title='Essay: My Country (300 words)',
            description='Write a 300-word essay on the topic "My Country".',
            due_date=today + datetime.timedelta(days=5))
        Assignment.objects.create(
            classroom=c9, subject=subjects.get('Science'),
            title='Lab report - Photosynthesis',
            description='Write a short lab report on the photosynthesis experiment done in class.',
            due_date=today + datetime.timedelta(days=6))
        # One example submission (not Ayaan, so the demo student can submit while testing)
        hira = students.get('Hira Aslam')
        if hira:
            Submission.objects.create(
                assignment=a1, student=hira,
                answer_text='Completed all 10 questions in my notebook.',
                status='Submitted')

        quizzes_data = [
            ('Algebra Basics', 'Mathematics', 15, [
                ('What is the value of x if 2x = 10?', '3', '5', '10', '20', 'B'),
                ('Simplify: 3x + 2x', '5x', '6x', 'x', '5', 'A'),
                ('What is 7 squared?', '14', '49', '21', '77', 'B'),
                ('Solve: x - 4 = 6', '2', '10', '24', '-2', 'B'),
            ]),
            ('MS Word Fundamentals', 'Computer', 10, [
                ('Which shortcut saves a document?', 'Ctrl + S', 'Ctrl + P', 'Ctrl + Z', 'Ctrl + V', 'A'),
                ('Which shortcut makes text bold?', 'Ctrl + B', 'Ctrl + I', 'Ctrl + U', 'Ctrl + L', 'A'),
                ('Where is the Print option found?', 'File menu', 'Edit menu', 'View menu', 'Insert menu', 'A'),
            ]),
            ('Cell Structure', 'Science', 10, [
                ('What is the powerhouse of the cell?', 'Nucleus', 'Mitochondria', 'Ribosome', 'Cell wall', 'B'),
                ('Which part controls the activities of a cell?', 'Nucleus', 'Cytoplasm', 'Membrane', 'Vacuole', 'A'),
                ('Plant cells have a cell ___?', 'Wall', 'Mouth', 'Bone', 'Skin', 'A'),
            ]),
        ]
        for q_title, subj_name, tl, qs in quizzes_data:
            quiz = Quiz.objects.create(
                classroom=c9, subject=subjects.get(subj_name),
                title=q_title, time_limit=tl)
            for i, (text, oa, ob, oc, od, correct) in enumerate(qs):
                Question.objects.create(
                    quiz=quiz, text=text, option_a=oa, option_b=ob,
                    option_c=oc, option_d=od, correct=correct, order=i + 1)

        FeeHead.objects.create(name='Admission Fee', amount=5000,
                               frequency='one_time')
        FeeHead.objects.create(name='Annual Charges', amount=3000,
                               frequency='annual')
        FeeHead.objects.create(name='Exam Fee', amount=800, frequency='annual')

        self.stdout.write('Generating fee challans (with real scenarios)...')

        def ym(off):
            y, m = today.year, today.month - off
            while m <= 0:
                m += 12
                y -= 1
            return y, m

        def challan(student, off, **extra):
            y, m = ym(off)
            cls = student.classroom
            return FeeChallan.objects.create(
                student=student, year=y, month=m,
                tuition=cls.monthly_fee if cls else 0,
                hostel_fee=8000 if student.is_hostel else 0,
                due_date=datetime.date(y, m, 10), **extra)

        def pay(ch, amount, mode='Cash'):
            p = FeePayment.objects.create(
                student=ch.student, challan=ch, month=ch.label,
                amount=amount, mode=mode, received_by='Adeel Anwar', date=today)
            p.receipt_no = 'RCPT-26-%04d' % p.id
            p.save()

        # Mahnoor is a hostel resident
        mahnoor = students['Mahnoor Fatima']
        mahnoor.is_hostel = True
        mahnoor.save(update_fields=['is_hostel'])
        # Saad is also a hostel resident (set before his fee challans so hostel fee applies)
        students['Saad Iqbal'].is_hostel = True
        students['Saad Iqbal'].save(update_fields=['is_hostel'])

        # Areeba (10-A): all three months fully paid (clean)
        areeba = students['Areeba Malik']
        for off in (2, 1, 0):
            pay(challan(areeba, off), areeba.classroom.monthly_fee)

        # Ayaan (9-A): 2 months ago paid; last month HALF (partial);
        # this month unpaid with a sibling discount approved by the Principal
        pay(challan(ayaan, 2), ayaan.classroom.monthly_fee)
        pay(challan(ayaan, 1), ayaan.classroom.monthly_fee // 2)
        challan(ayaan, 0, discount=1000,
                discount_reason='Sibling discount (2 children)',
                discount_by='Asad Mehmood (Principal)')

        # Inaya (5-B, Ayaan's sibling): older months paid, this month unpaid + sibling discount
        inaya = students['Inaya Khan']
        pay(challan(inaya, 2), inaya.classroom.monthly_fee)
        pay(challan(inaya, 1), inaya.classroom.monthly_fee)
        challan(inaya, 0, discount=800,
                discount_reason='Sibling discount (2 children)',
                discount_by='Asad Mehmood (Principal)')

        # Bilal Ahmed (9-A): THREE months pending (arrears, nothing paid)
        for off in (2, 1, 0):
            challan(students['Bilal Ahmed'], off)

        # Hira (9-A): merit scholarship every month, then paid
        hira = students['Hira Aslam']
        for off in (2, 1, 0):
            pay(challan(hira, off, scholarship=2500,
                        scholarship_name='Merit Scholarship'),
                hira.classroom.monthly_fee - 2500)

        # Mahnoor (9-A, hostel): older months paid, this month unpaid (hostel shows)
        pay(challan(mahnoor, 2), mahnoor.classroom.monthly_fee + 8000)
        pay(challan(mahnoor, 1), mahnoor.classroom.monthly_fee + 8000)
        challan(mahnoor, 0)

        # Saad (10-A): older months paid, this month unpaid + a late fee
        saad = students['Saad Iqbal']
        pay(challan(saad, 2), saad.classroom.monthly_fee)
        pay(challan(saad, 1), saad.classroom.monthly_fee)
        challan(saad, 0, late_fee=300)

        # Keep each student's quick status flag in sync with their challans
        for s in students.values():
            chs = list(s.challans.all())
            outstanding = sum(c.balance for c in chs)
            overdue = any(c.is_overdue for c in chs)
            s.fee_status = ('Paid' if outstanding <= 0
                            else ('Overdue' if overdue else 'Pending'))
            s.save(update_fields=['fee_status'])

        # Pending fee concessions awaiting the Principal's approval (Phase 2 demo)
        def pending_concession(student_name, kind, amount, label):
            st = students.get(student_name)
            ch = st.challans.order_by('-year', '-month').first() if st else None
            if ch:
                ConcessionRequest.objects.create(
                    challan=ch, kind=kind, amount=amount, label=label,
                    requested_by='Adeel Anwar (Accounts)', status='Pending')

        pending_concession('Saad Iqbal', 'discount', 1500, 'Financial hardship')
        pending_concession('Bilal Ahmed', 'scholarship', 2000, 'Need-based aid')

        Expense.objects.create(title='Electricity bill', category='Utilities',
                               amount=14000, date=today)
        Expense.objects.create(title='Staff salaries (advance)', category='Salaries',
                               amount=180000, date=today)
        Expense.objects.create(title='Stationery and supplies', category='Supplies',
                               amount=8500, date=today)

        self.stdout.write('Creating operations data (admissions, SMS, transport, library)...')
        applicants = [
            ('Ahmad Raza', 'Class 1', 'Raza Khan', '0300-1112233', 'Enquiry'),
            ('Fatima Noor', 'Class 6', 'Noor Ahmed', '0301-2223344', 'Enquiry'),
            ('Hassan Ali', 'Class 3', 'Ali Akbar', '0302-3334455', 'Test'),
            ('Mariam Shah', 'Class 9', 'Shah Jahan', '0303-4445566', 'Test'),
            ('Bilal Tariq', 'Class 4', 'Tariq Mahmood', '0304-5556677', 'Offer'),
            ('Zainab Malik', 'Class 7', 'Malik Riaz', '0306-7778899', 'Offer'),
            ('Ayesha Khan', 'Class 2', 'Khan Sahib', '0305-6667788', 'Enrolled'),
        ]
        for n, c, p, ph, st in applicants:
            Applicant.objects.create(name=n, class_applied=c, parent_name=p,
                                     phone=ph, stage=st)

        SmsMessage.objects.create(recipients='All Parents - Class 9',
                                  body='Mid-Term exams begin 8 July.', msg_type='Announcement')
        SmsMessage.objects.create(recipients='Imran Khan (Ayaan)',
                                  body='June fee Rs 5,500 is due by the 10th.', msg_type='Fee Reminder')
        SmsMessage.objects.create(recipients='All Parents',
                                  body='PTM this Saturday at 9:00 AM.', msg_type='Announcement')

        route1 = TransportRoute.objects.create(name='Route 1 - Model Town', vehicle='LEB-1234',
                                               driver='Rashid Ali', fee=2500, students=24)
        route2 = TransportRoute.objects.create(name='Route 2 - Johar Town', vehicle='LEB-5678',
                                               driver='Akram Khan', fee=2800, students=31)
        route3 = TransportRoute.objects.create(name='Route 3 - Gulberg', vehicle='LEB-9012',
                                               driver='Saleem Butt', fee=3000, students=18)

        self.stdout.write('Filling rich profiles (personal + transport)...')

        ayaan.date_of_birth = datetime.date(2010, 4, 18)
        ayaan.gender = 'Male'
        ayaan.blood_group = 'B+'
        ayaan.address = 'House 14, Block C, Model Town, Lahore'
        ayaan.admission_date = datetime.date(2024, 4, 1)
        ayaan.route = route1
        ayaan.pickup_point = 'Model Town, Block C Stop'
        ayaan.save()

        inaya = students['Inaya Khan']
        inaya.date_of_birth = datetime.date(2014, 9, 6)
        inaya.gender = 'Female'
        inaya.blood_group = 'B+'
        inaya.address = 'House 14, Block C, Model Town, Lahore'
        inaya.admission_date = datetime.date(2025, 4, 1)
        inaya.route = route1
        inaya.pickup_point = 'Model Town, Block C Stop'
        inaya.save()

        hira = students['Hira Aslam']
        hira.date_of_birth = datetime.date(2010, 1, 22)
        hira.gender = 'Female'
        hira.blood_group = 'O+'
        hira.address = 'House 8, Johar Town, Lahore'
        hira.admission_date = datetime.date(2024, 4, 1)
        hira.route = route2
        hira.pickup_point = 'Johar Town G-1 Market'
        hira.save()

        saad = students['Saad Iqbal']
        saad.date_of_birth = datetime.date(2009, 11, 3)
        saad.gender = 'Male'
        saad.blood_group = 'A+'
        saad.address = 'House 20, Gulberg III, Lahore'
        saad.admission_date = datetime.date(2023, 4, 1)
        saad.route = route3
        saad.pickup_point = 'Gulberg Main Boulevard'
        saad.save()

        # Mahnoor is a hostel resident (lives on campus, no transport)
        mahnoor.date_of_birth = datetime.date(2010, 7, 14)
        mahnoor.gender = 'Female'
        mahnoor.blood_group = 'AB+'
        mahnoor.address = 'School Hostel, Main Campus, Lahore'
        mahnoor.admission_date = datetime.date(2024, 4, 1)
        mahnoor.save()

        b1 = Book.objects.create(title='Oxford English Dictionary', author='Oxford Press',
                                 code='LIB-0451', copies=6, available=5)
        b2 = Book.objects.create(title='A Brief History of Time', author='Stephen Hawking',
                                 code='LIB-0782', copies=3, available=2)
        Book.objects.create(title='Pakistan Studies Reference', author='Ferozsons',
                            code='LIB-1033', copies=10, available=8)
        Book.objects.create(title='Mathematics Olympiad Guide', author='NMS',
                            code='LIB-1190', copies=4, available=4)
        IssuedBook.objects.create(book=b1, student_name='Hira Aslam (9-A)',
                                  issued_on=today, due_on=today - datetime.timedelta(days=1))
        IssuedBook.objects.create(book=b2, student_name='Ayaan Khan (9-A)',
                                  issued_on=today, due_on=today + datetime.timedelta(days=3))

        self.stdout.write('Creating staff, calendar, inventory, visitors...')
        st_bilal = Staff.objects.create(name='Bilal Hussain', designation='Senior Teacher',
                                        phone='0301-1111111', basic_salary=55000, allowances=8000)
        st_sana = Staff.objects.create(name='Sana Riaz', designation='Teacher',
                                       phone='0302-2222222', basic_salary=42000, allowances=5000)
        st_adeel = Staff.objects.create(name='Adeel Anwar', designation='Accountant',
                                        phone='0303-3333333', basic_salary=48000, allowances=6000)
        st_nida = Staff.objects.create(name='Nida Farooq', designation='Admin Clerk',
                                       phone='0304-4444444', basic_salary=35000, allowances=4000)

        # Today's staff attendance + pending leave requests (Phase 3 demo)
        for _s, _st in [(st_bilal, 'P'), (st_sana, 'P'), (st_adeel, 'P'), (st_nida, 'A')]:
            StaffAttendance.objects.create(staff=_s, date=today, status=_st)
        LeaveRequest.objects.create(
            staff=st_sana, from_date=today + datetime.timedelta(days=2),
            to_date=today + datetime.timedelta(days=4), reason='Family event',
            applied_by='Nadia Farooq (Office)', status='Pending')
        LeaveRequest.objects.create(
            staff=st_adeel, from_date=today + datetime.timedelta(days=5),
            to_date=today + datetime.timedelta(days=5), reason='Medical appointment',
            applied_by='Nadia Farooq (Office)', status='Pending')

        # Exam rooms, datesheet and generated seating for Mid-Term (Phase 4 demo)
        ExamRoom.objects.create(name='Hall A', capacity=6)
        ExamRoom.objects.create(name='Hall B', capacity=30)
        ExamRoom.objects.create(name='Room 1', capacity=20)
        datesheet = [
            (c9, 'Mathematics', 2, '09:00 AM - 12:00 PM'),
            (c9, 'English', 4, '09:00 AM - 12:00 PM'),
            (c9, 'Science', 6, '09:00 AM - 11:30 AM'),
            (c10, 'Mathematics', 2, '09:00 AM - 12:00 PM'),
            (c10, 'English', 4, '09:00 AM - 12:00 PM'),
            (c10, 'Computer', 6, '09:00 AM - 11:00 AM'),
            (c5, 'English', 3, '09:30 AM - 11:30 AM'),
            (c5, 'Mathematics', 5, '09:30 AM - 11:30 AM'),
        ]
        for _cls, _subj, _off, _time in datesheet:
            ExamSchedule.objects.create(
                exam=exam, classroom=_cls, subject=_subj,
                date=today + datetime.timedelta(days=_off), time=_time)
        _rooms = list(ExamRoom.objects.all().order_by('name'))
        _ri, _seat = 0, 1
        for _s in Student.objects.select_related('classroom').order_by(
                'classroom__name', 'classroom__section', 'roll_no'):
            while _ri < len(_rooms) and _seat > _rooms[_ri].capacity:
                _ri += 1
                _seat = 1
            if _ri >= len(_rooms):
                break
            Seat.objects.create(exam=exam, student=_s, room=_rooms[_ri], seat_no=_seat)
            _seat += 1

        # Hostel rooms and allocation (Phase 5 demo).
        # Mahnoor is allocated; Saad is left unassigned to demo the allocation workflow.
        hr1 = HostelRoom.objects.create(name='Block A - Room 1', capacity=4, warden='Mr. Kareem')
        HostelRoom.objects.create(name='Block A - Room 2', capacity=4, warden='Mr. Kareem')
        HostelRoom.objects.create(name='Block B - Room 1', capacity=6, warden='Ms. Shabana')
        mahnoor.hostel_room = hr1
        mahnoor.save(update_fields=['hostel_room'])

        # Discipline / complaint records (Phase 5 demo).
        _disc = [
            ('Bilal Ahmed', 'Behaviour', 'Major',
             'Repeatedly disrupting class and talking back to the teacher.',
             'Parent informed; verbal warning issued.', 'Bilal Hussain', 'Open', 4),
            ('Ayaan Khan', 'Uniform', 'Minor',
             'Arrived without the school ID card.',
             'Verbal warning.', 'Nadia Farooq', 'Resolved', 9),
            ('Ayaan Khan', 'Homework', 'Minor',
             'Mathematics homework not submitted on time.',
             '', 'Bilal Hussain', 'Open', 2),
            ('Saad Iqbal', 'Attendance', 'Minor',
             'Late to morning assembly (third instance this month).',
             'Counselled by class teacher.', 'Nadia Farooq', 'Resolved', 6),
            ('Hira Aslam', 'Property', 'Major',
             'Damaged a classroom chair during break.',
             'Parent informed; repair cost to be recovered.', 'Nadia Farooq', 'Open', 1),
        ]
        for _nm, _cat, _sev, _desc, _act, _by, _st, _ago in _disc:
            _stu = students.get(_nm)
            if _stu:
                DisciplineRecord.objects.create(
                    student=_stu, date=today - datetime.timedelta(days=_ago),
                    category=_cat, severity=_sev, description=_desc,
                    action_taken=_act, reported_by=_by, status=_st)

        # SMS log (Phase 7 demo). Console = logged in dev; one Failed shows the UI.
        SmsMessage.objects.create(
            recipients='All Parents', to_phone='', msg_type='Announcement',
            status='Console', provider='console',
            body='Dear Parent, the Mid-Term result has been published in the '
                 'parent portal. - Roshni Public School')
        SmsMessage.objects.create(
            recipients='Tariq Ahmed', to_phone='+923217654321',
            msg_type='Fee Reminder', status='Console', provider='console',
            body='Dear Tariq Ahmed, fee reminder from Roshni Public School: '
                 'outstanding Rs 5500 for Bilal Ahmed. Please clear it soon.')
        SmsMessage.objects.create(
            recipients='Imran Khan', to_phone='+923001234567',
            msg_type='Fee Receipt', status='Console', provider='console',
            body='Roshni Public School: received Rs 5500 for Ayaan Khan '
                 '(April 2026). Receipt RCPT-26-0007. Thank you.')
        SmsMessage.objects.create(
            recipients='Fatima Noor', to_phone='+923451112233',
            msg_type='Fee Reminder', status='Failed', provider='twilio',
            error='Twilio is not configured (SID / token / from-number).',
            body='Dear Fatima Noor, fee reminder from Roshni Public School.')

        CalendarEvent.objects.create(title='Summer vacation begins', event_type='Holiday',
                                     date=today + datetime.timedelta(days=6))
        CalendarEvent.objects.create(title='Mid-Term examinations begin', event_type='Exam',
                                     date=today + datetime.timedelta(days=9))
        CalendarEvent.objects.create(title='Parent-Teacher Meeting (9 & 10)', event_type='PTM',
                                     date=today + datetime.timedelta(days=13))
        CalendarEvent.objects.create(title='Independence Day celebration', event_type='Event',
                                     date=today + datetime.timedelta(days=46))

        InventoryItem.objects.create(name='School Uniform (Shirt)', category='Uniform',
                                     quantity=120, reorder_level=50, unit='pcs')
        InventoryItem.objects.create(name='Notebooks (200 pg)', category='Stationery',
                                     quantity=340, reorder_level=100, unit='pcs')
        InventoryItem.objects.create(name='Whiteboard Markers', category='Supplies',
                                     quantity=28, reorder_level=40, unit='pcs')
        InventoryItem.objects.create(name='Textbook Set - Class 9', category='Books',
                                     quantity=62, reorder_level=30, unit='sets')

        Visitor.objects.create(name='Mr. Imran Khan', purpose='Meet class teacher (9-A)',
                               to_meet='Ms Rabia', pass_no='V-239')
        Visitor.objects.create(name='Ferozsons Sales Rep', purpose='Book supply',
                               to_meet='Admin Office', pass_no='V-240', checked_out=True)

        self.stdout.write('Creating announcements...')
        Announcement.objects.create(
            title='Mid-Term Exams begin 8 July',
            body='The full examination schedule has been published.', audience='All')
        Announcement.objects.create(
            title='Parent-Teacher Meeting this Saturday',
            body='PTM for Class 9 and 10 at 9:00 AM.', audience='All')

        self.stdout.write('Creating login accounts...')

        def make_user(username, role, first_name, children=None, **profile_extra):
            user = User.objects.create_user(
                username=username, password=PASSWORD, first_name=first_name)
            prof = Profile.objects.create(user=user, role=role, **profile_extra)
            if children:
                prof.children.set(children)
            return user

        make_user('principal', 'principal', 'Asad')
        make_user('office', 'admin', 'Nadia')
        teacher_user = make_user('teacher', 'teacher', 'Bilal', classroom=c9)
        # Link the teacher's login to their HR/staff record (payslip + attendance).
        st_bilal.user = teacher_user
        st_bilal.save(update_fields=['user'])
        teacher_profile = Profile.objects.get(user__username='teacher')
        for _cls, _subj in [(c9, 'Mathematics'), (c9, 'Computer'), (c10, 'Mathematics')]:
            TeachingAssignment.objects.create(
                teacher=teacher_profile, classroom=_cls, subject=_subj)
        # Imran Khan is guardian of BOTH Ayaan (9-A) and Inaya (5-B) — multi-child.
        make_user('parent', 'parent', 'Imran',
                  student=students['Ayaan Khan'],
                  children=[students['Ayaan Khan'], students['Inaya Khan']])
        make_user('student', 'student', 'Ayaan', student=students['Ayaan Khan'])
        finance_user = make_user('finance', 'finance', 'Adeel')
        st_adeel.user = finance_user
        st_adeel.save(update_fields=['user'])
        make_user('director', 'owner', 'Yusuf')

        superuser, _ = User.objects.get_or_create(
            username='admin', defaults={'email': ''})
        superuser.is_staff = True
        superuser.is_superuser = True
        superuser.set_password(PASSWORD)
        superuser.save()
        Profile.objects.get_or_create(user=superuser, defaults={'role': 'admin'})

        self.stdout.write(self.style.SUCCESS(
            'Seed complete. All accounts use the password: ' + PASSWORD))