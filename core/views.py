import calendar as pycal
import csv
import datetime
import io
import json

from django.contrib import messages
from django.conf import settings
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode
from django.views.decorators.csrf import csrf_exempt

from .decorators import role_required
from .emailer import email_alerts_enabled, send_email_alert
from .sms import notify, send_sms, sms_enabled
from . import payments
from .models import (Announcement, Applicant, Assignment, AttendanceRecord, AuditLog,
                     Book, CalendarEvent, Certificate, ChallanLine, ClassRoom,
                     ConcessionRequest,
                     Appraisal, Complaint, DisciplineRecord,
                     Exam, ExamRoom, ExamSchedule, Expense,
                     FeeChallan, FeeHead, FeePayment, GradeConfig, HostelRoom, InventoryItem, IssuedBook, LeaveRequest,
                     LoginAttempt,
                     Mark, Material, Message, OnlinePayment, Payslip,
                     Profile, Question, Quiz, QuizAttempt, School, Seat, SmsMessage, Staff, StaffAttendance,
                     Student, StudentLeave, StudentNote, Subject, Submission, TeachingAssignment,
                     TimetableSlot, TransportRoute,
                     Visitor, grade_for)


def _teacher_classes(profile):
    """All classrooms a teacher is linked to: home class + taught classes."""
    classes = {}
    if profile and profile.classroom_id:
        classes[profile.classroom_id] = profile.classroom
    if profile:
        for ta in profile.teaching.select_related('classroom'):
            classes[ta.classroom_id] = ta.classroom
    return list(classes.values())


def _active_child(request):
    """The child a parent/student is currently viewing.

    A parent may have several children and switch between them with ?child=
    (remembered in the session). A student always resolves to their own record.
    Returns (child_or_None, list_of_all_children).
    """
    profile = getattr(request.user, 'profile', None)
    children = profile.child_list() if profile else []
    if not children:
        return None, []
    cid = request.GET.get('child') or request.session.get('child_id')
    child = next((c for c in children if str(c.id) == str(cid)), None)
    if child is None:
        child = children[0]
    request.session['child_id'] = child.id
    return child, children


def _owns_student(profile, student_id):
    """True if this profile (parent/student) is allowed to see the student."""
    if not profile:
        return False
    return any(c.id == student_id for c in profile.child_list())


def _pk(value):
    """Safely clean a primary-key value from a form field. Returns the value
    only if it looks like a valid id, else None — so `filter(pk=_pk(...))`
    never crashes when a dropdown is left on its blank option."""
    v = (value or '').strip()
    return v if v.isdigit() else None


# ---- File upload validation (size + type) ----
IMAGE_EXTS = {'png', 'jpg', 'jpeg', 'webp', 'gif'}
DOC_EXTS = {'pdf', 'doc', 'docx', 'ppt', 'pptx', 'xls', 'xlsx', 'txt', 'csv',
            'png', 'jpg', 'jpeg', 'zip'}
MAX_UPLOAD_MB = 10


def _upload_error(f, allowed_exts, max_mb=MAX_UPLOAD_MB):
    """Return an error message if the upload is the wrong type or too big,
    else '' (empty). Safe to call with f=None."""
    if not f:
        return ''
    ext = f.name.rsplit('.', 1)[-1].lower() if '.' in f.name else ''
    if ext not in allowed_exts:
        return 'File type ".%s" is not allowed (allowed: %s).' % (
            ext or '?', ', '.join(sorted(allowed_exts)))
    if f.size > max_mb * 1024 * 1024:
        return 'File is too large — max %d MB.' % max_mb
    return ''


def _audit(request, action, detail=''):
    """Record a sensitive action in the audit trail."""
    who = getattr(getattr(request, 'user', None), 'username', '') or 'system'
    AuditLog.objects.create(user=who, action=action, detail=str(detail)[:255])


def _school_default_password():
    s = School.objects.first()
    return (s.default_password if s and s.default_password else 'school123')


def _current_session():
    """The school's active academic session, e.g. '2025-26'. New exams and
    attendance are stamped with this so different years never blend."""
    s = School.objects.first()
    return (s.session if s and s.session else '2025-26')


def _force_change(user):
    """Mark a login so the person must set a new password on next sign-in."""
    prof = getattr(user, 'profile', None)
    if prof is not None:
        prof.must_change_password = True
        prof.save(update_fields=['must_change_password'])


# --- Brute-force protection: lock a username after too many failed logins ---
LOGIN_MAX_FAILS = 5
LOGIN_LOCK_MINUTES = 15
LOGIN_FAIL_WINDOW_MINUTES = 15


def _login_lock_remaining(username):
    """Minutes left if this username is currently locked out, else 0."""
    if not username:
        return 0
    rec = LoginAttempt.objects.filter(username=username).first()
    if rec and rec.locked_until and rec.locked_until > timezone.now():
        return int((rec.locked_until - timezone.now()).total_seconds() // 60) + 1
    return 0


def _record_login_fail(username):
    if not username:
        return
    now = timezone.now()
    rec, created = LoginAttempt.objects.get_or_create(username=username)
    # Forget old failures once the window has passed.
    if not created and rec.updated and \
            (now - rec.updated).total_seconds() > LOGIN_FAIL_WINDOW_MINUTES * 60:
        rec.fail_count = 0
    rec.fail_count += 1
    if rec.fail_count >= LOGIN_MAX_FAILS:
        rec.locked_until = now + datetime.timedelta(minutes=LOGIN_LOCK_MINUTES)
        rec.fail_count = 0
    rec.save()


def _reset_login_fails(username):
    LoginAttempt.objects.filter(username=username).delete()


class LockoutLoginView(auth_views.LoginView):
    """Login that blocks a username after repeated failures, and resets the
    counter on a successful sign-in."""
    template_name = 'registration/login.html'

    def post(self, request, *args, **kwargs):
        username = (request.POST.get('username') or '').strip()
        mins = _login_lock_remaining(username)
        if mins > 0:
            form = AuthenticationForm(request=request)   # unbound: no error shown
            return self.render_to_response(
                self.get_context_data(form=form, locked_minutes=mins))
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        _reset_login_fails(form.get_user().username)
        return super().form_valid(form)

    def form_invalid(self, form):
        _record_login_fail((self.request.POST.get('username') or '').strip())
        return super().form_invalid(form)

    def get_success_url(self):
        """
        After a successful login, redirect based on WHERE the login happened:
        - School login page (/unicom/login/) → always go to that school's dashboard (/{sub}/)
          The middleware will handle evicting true superusers from school pages.
        - Root login page (/login/) with no school context:
            * Superuser → /saas-admin/
            * Regular user → Django's default LOGIN_REDIRECT_URL
        """
        # If login happened via a school URL, request.tenant is set by TenantMiddleware.
        # Always send the user to that school's dashboard — school context wins.
        school = getattr(self.request, 'tenant', None)
        if school:
            sub = school.subdomain or 'default'
            return f'/{sub}/'

        # No school context = root login. Send superusers to SaaS admin.
        if self.request.user.is_superuser:
            return '/saas-admin/'

        return super().get_success_url()


class ForcedPasswordChangeView(auth_views.PasswordChangeView):
    """After a successful change, clear the must-change flag."""
    template_name = 'password_change.html'

    def form_valid(self, form):
        resp = super().form_valid(form)
        prof = getattr(self.request.user, 'profile', None)
        if prof is not None and prof.must_change_password:
            prof.must_change_password = False
            prof.save(update_fields=['must_change_password'])
        return resp


def _paginate(request, qs, per_page=25, keep=()):
    """Return (page, qs_prefix). `page` is a Django Page (iterable like a list)
    so templates keep working; `qs_prefix` preserves filters like tab/q/session
    on the Prev/Next links (e.g. 'tab=active&'). Big lists no longer render
    every row at once, which keeps pages fast as schools grow."""
    page = Paginator(qs, per_page).get_page(request.GET.get('page'))
    kept = {k: request.GET[k] for k in keep if request.GET.get(k)}
    prefix = (urlencode(kept) + '&') if kept else ''
    return page, prefix


def _unique_username(base):
    """A username starting from `base`, with a numeric suffix if taken."""
    name = base
    i = 1
    while User.objects.filter(username=name).exists():
        i += 1
        name = '%s-%d' % (base, i)
    return name


def _provision_student_login(student):
    """Auto-create the student's own login. Returns the username (or None if
    one already exists)."""
    if Profile.objects.filter(role='student', student=student).exists():
        return None
    username = _unique_username('std%04d' % student.id)
    first = (student.name or '').split()[0] if student.name else ''
    user = User.objects.create_user(
        username=username, password=_school_default_password(), first_name=first)
    Profile.objects.create(user=user, role='student', student=student,
                           must_change_password=True)
    return username


def _provision_parent_login(student):
    """Attach the student to their guardian's existing parent login (siblings
    share the same guardian phone) or create a new one.
    Returns (username, created_new)."""
    phone = (student.guardian_phone or '').strip()
    existing = None
    if phone:
        existing = (Profile.objects.filter(
            role='parent', children__guardian_phone=phone).distinct().first())
    if existing:
        existing.children.add(student)
        return existing.user.username, False
    username = _unique_username('par%04d' % student.id)
    first = (student.guardian_name or 'Parent').split()[0]
    user = User.objects.create_user(
        username=username, password=_school_default_password(), first_name=first)
    prof = Profile.objects.create(user=user, role='parent', student=student,
                                  must_change_password=True)
    prof.children.add(student)
    return username, True


def _provision_staff_login(staff, role, classroom=None):
    """Auto-create a login for a staff member and link it to the HR record.
    Returns the username (or None if the staff already has a login)."""
    if staff.user_id:
        return None
    prefix = {'teacher': 'tch', 'finance': 'acc', 'admin': 'off',
              'principal': 'prin', 'owner': 'dir'}.get(role, 'stf')
    username = _unique_username('%s%04d' % (prefix, staff.id))
    first = (staff.name or '').split()[0] if staff.name else ''
    user = User.objects.create_user(
        username=username, password=_school_default_password(), first_name=first)
    extra = {'classroom': classroom} if role == 'teacher' and classroom else {}
    Profile.objects.create(user=user, role=role, must_change_password=True,
                           **extra)
    staff.user = user
    staff.save(update_fields=['user'])
    return username


def _donut_gradient(segments):
    """Build a CSS conic-gradient + legend from (label, value, color) tuples."""
    total = sum(v for _, v, _ in segments)
    legend = []
    if total <= 0:
        for label, _, color in segments:
            legend.append({'label': label, 'value': 0, 'pct': 0, 'color': color})
        return 'conic-gradient(#E3E8EF 0 100%)', legend, 0
    stops = []
    acc = 0.0
    for label, value, color in segments:
        pct = value / total * 100
        stops.append('%s %.3f%% %.3f%%' % (color, acc, acc + pct))
        legend.append({'label': label, 'value': value,
                       'pct': round(pct), 'color': color})
        acc += pct
    return 'conic-gradient(%s)' % ', '.join(stops), legend, int(total)


@login_required
def dashboard(request):
    if request.user.is_superuser:
        return redirect('saas_admin_dashboard')
        
    profile = getattr(request.user, 'profile', None)
    role = profile.role if profile else 'admin'

    context = {
        'role': role,
        'active': 'dashboard',
        'profile': profile,
        'announcements': Announcement.objects.all()[:5],
    }

    if role == 'admin':
        # Administrator (Office) — operational, data-entry console
        stages = ['Enquiry', 'Test', 'Offer', 'Enrolled']
        pipeline = [{'stage': st, 'count': Applicant.objects.filter(stage=st).count()}
                    for st in stages]
        to_process = list(Applicant.objects.exclude(stage='Enrolled').order_by('-id')[:6])
        teacher_by_class = {}
        for p in Profile.objects.filter(role='teacher').select_related('user'):
            if p.classroom_id and p.classroom_id not in teacher_by_class:
                teacher_by_class[p.classroom_id] = (
                    p.user.get_full_name() or p.user.username)
        classes_overview = [{
            'room': c,
            'count': Student.objects.filter(classroom=c).count(),
            'teacher': teacher_by_class.get(c.id, '—'),
        } for c in ClassRoom.objects.all()]
        a_paid = Student.objects.filter(fee_status='Paid').count()
        a_pending = Student.objects.filter(fee_status='Pending').count()
        a_overdue = Student.objects.filter(fee_status='Overdue').count()
        a_fee_grad, a_fee_legend, a_fee_total = _donut_gradient([
            ('Paid', a_paid, '#0E7C66'),
            ('Pending', a_pending, '#B07D17'),
            ('Overdue', a_overdue, '#C0432F')])
        context.update({
            'student_count': Student.objects.count(),
            'class_count': ClassRoom.objects.count(),
            'staff_count': Profile.objects.filter(role='teacher').count(),
            'admissions_inprogress': Applicant.objects.exclude(stage='Enrolled').count(),
            'pipeline': pipeline,
            'to_process': to_process,
            'classes_overview': classes_overview,
            'fee_donut': a_fee_grad, 'fee_legend': a_fee_legend,
            'fee_donut_total': a_fee_total,
            'recent_students': list(
                Student.objects.select_related('classroom').order_by('-id')[:6]),
        })

    elif role == 'principal':
        # Principal — academic oversight + items awaiting approval
        today = timezone.localdate()
        today_att = list(AttendanceRecord.objects.filter(date=today))
        p_present = sum(1 for r in today_att if r.status == 'P')
        p_absent = sum(1 for r in today_att if r.status == 'A')
        p_late = sum(1 for r in today_att if r.status == 'L')
        p_total = len(today_att)

        # School-wide result from the most recent exam that has marks
        marks = list(Mark.objects.select_related('student', 'student__classroom', 'exam'))
        student_pcts = []   # list of (student, pct) for the latest exam
        latest_exam_name = ''
        if marks:
            latest_exam_id = max(m.exam_id for m in marks)
            em = [m for m in marks if m.exam_id == latest_exam_id]
            latest_exam_name = em[0].exam.name if em else ''
            agg = {}
            for m in em:
                o, t, _s = agg.get(m.student_id, (0, 0, m.student))
                agg[m.student_id] = (o + m.marks_obtained, t + m.total_marks, m.student)
            for o, t, s in agg.values():
                student_pcts.append((s, round(o / t * 100) if t else 0))
        result_total = len(student_pcts)
        pass_count = sum(1 for _s, p in student_pcts if p >= 50)
        pass_pct = round(pass_count / result_total * 100) if result_total else 0
        avg_pct = (round(sum(p for _s, p in student_pcts) / result_total)
                   if result_total else 0)

        class_perf = []
        for c in ClassRoom.objects.all():
            ps = [p for s, p in student_pcts if s.classroom_id == c.id]
            if ps:
                class_perf.append({'room': c, 'avg': round(sum(ps) / len(ps)),
                                   'n': len(ps)})

        p_admissions_pending = Applicant.objects.filter(stage='Offer').count()
        p_concessions_pending = ConcessionRequest.objects.filter(status='Pending').count()
        p_leaves_pending = LeaveRequest.objects.filter(status='Pending').count()
        p_att_grad, p_att_legend, p_att_donut_total = _donut_gradient([
            ('Present', p_present, '#0E7C66'),
            ('Absent', p_absent, '#C0432F'),
            ('Late / Leave', p_late, '#B07D17')])
        context.update({
            'p_students': Student.objects.count(),
            'p_teachers': Profile.objects.filter(role='teacher').count(),
            'p_classes': ClassRoom.objects.count(),
            'p_present': p_present, 'p_absent': p_absent, 'p_late': p_late,
            'p_total': p_total,
            'p_att_pct': round(p_present / p_total * 100) if p_total else 0,
            'p_att_donut': p_att_grad, 'p_att_legend': p_att_legend,
            'p_att_donut_total': p_att_donut_total,
            'p_admissions_pending': p_admissions_pending,
            'p_concessions_pending': p_concessions_pending,
            'p_leaves_pending': p_leaves_pending,
            'p_awaiting': (p_admissions_pending + p_concessions_pending
                           + p_leaves_pending),
            'latest_exam_name': latest_exam_name,
            'result_total': result_total,
            'pass_count': pass_count, 'pass_pct': pass_pct, 'avg_pct': avg_pct,
            'class_perf': class_perf,
        })
    elif role == 'teacher':
        classes = _teacher_classes(profile)
        class_ids = [c.id for c in classes]
        teaching = list(profile.teaching.select_related('classroom')) if profile else []
        subj_by_class = {}
        for ta in teaching:
            subj_by_class.setdefault(ta.classroom_id, []).append(ta.subject)
        my_classes = []
        for c in classes:
            my_classes.append({
                'room': c,
                'is_home': bool(profile and c.id == profile.classroom_id),
                'subjects': subj_by_class.get(c.id, []),
                'count': Student.objects.filter(classroom=c).count(),
            })
        subject_names = sorted({ta.subject for ta in teaching})
        taught = {(ta.classroom_id, ta.subject) for ta in teaching}
        today = timezone.localdate()
        # Only the periods this teacher personally teaches today (not the whole
        # class grid).
        todays_own = [s for s in TimetableSlot.objects.filter(
            classroom_id__in=class_ids, day=today.strftime('%a'))
            .select_related('classroom').order_by('period')
            if (s.classroom_id, s.subject) in taught]
        pending_qs = Submission.objects.filter(
            assignment__classroom_id__in=class_ids, status='Submitted')
        context.update({
            'my_classes': my_classes,
            'class_count': len(classes),
            'students_total': Student.objects.filter(classroom_id__in=class_ids).count(),
            'subject_count': len(subject_names),
            'subject_names': subject_names,
            'pending': list(pending_qs.select_related(
                'student', 'assignment', 'assignment__classroom')[:6]),
            'pending_count': pending_qs.count(),
            'todays': todays_own,
        })
    elif role in ('parent', 'student'):
        child, _kids = _active_child(request)
        classroom = child.classroom if child else None
        today = timezone.localdate()

        # Attendance — THIS month only (matches the Attendance page)
        month_att = (list(AttendanceRecord.objects.filter(
            student=child, date__year=today.year, date__month=today.month))
            if child else [])
        att_present = sum(1 for r in month_att if r.status == 'P')
        att_total = len(month_att)
        att_pct = round(att_present / att_total * 100) if att_total else 0

        # Latest exam result (only the most recent exam, not all exams mixed)
        marks = (list(Mark.objects.filter(student=child).select_related('exam'))
                 if child else [])
        latest_exam = (max((m.exam for m in marks), key=lambda e: e.id)
                       if marks else None)
        exam_marks = [m for m in marks if latest_exam and m.exam_id == latest_exam.id]
        ex_obt = sum(m.marks_obtained for m in exam_marks)
        ex_max = sum(m.total_marks for m in exam_marks)
        result_pct = round(ex_obt / ex_max * 100) if ex_max else 0

        # Today's classes (from the timetable)
        todays_classes = (list(TimetableSlot.objects.filter(
            classroom=classroom, day=today.strftime('%a')).order_by('period'))
            if classroom else [])

        # Things to do — assignments not submitted + quizzes not attempted
        todo = []
        if child and classroom:
            done_a = set(Submission.objects.filter(student=child)
                         .values_list('assignment_id', flat=True))
            for a in Assignment.objects.filter(classroom=classroom):
                if a.id not in done_a:
                    todo.append({'kind': 'assignment', 'title': a.title,
                                 'sub': 'Due %s' % a.due_date,
                                 'url': '%s?id=%d' % (reverse('my_assignments'), a.id),
                                 'action': 'Submit'})
            done_q = set(QuizAttempt.objects.filter(student=child)
                         .values_list('quiz_id', flat=True))
            for q in Quiz.objects.filter(classroom=classroom):
                if q.id not in done_q:
                    todo.append({'kind': 'quiz', 'title': q.title,
                                 'sub': '%d questions' % q.questions.count(),
                                 'url': '%s?id=%d' % (reverse('my_quizzes'), q.id),
                                 'action': 'Start'})

        # School notices a student is allowed to see, newest first, with dates
        notices = [a for a in Announcement.objects.order_by('-created')
                   if a.audience.lower() in ('all', 'students')
                   or 'student' in a.audience.lower()][:4]

        # Fee summary (challan-based) for the fees card and parent panel
        fee_challans = list(child.challans.prefetch_related('payments', 'lines')) if child else []

        context.update({
            'child': child,
            'att_pct': att_pct, 'att_present': att_present, 'att_total': att_total,
            'result_pct': result_pct, 'has_result': bool(exam_marks),
            'result_grade': grade_for(result_pct) if exam_marks else '-',
            'monthly': classroom.monthly_fee if classroom else 0,
            'fee_paid': (child.fee_status == 'Paid') if child else False,
            'fee_outstanding': sum(c.balance for c in fee_challans),
            'fee_payable': sum(c.net_payable for c in fee_challans),
            'fee_paid_total': sum(c.paid for c in fee_challans),
            'fee_months_pending': sum(1 for c in fee_challans if c.balance > 0),
            'todays_classes': todays_classes,
            'todo': todo[:6], 'todo_count': len(todo),
            'notices': notices,
        })
    elif role == 'finance':
        context.update({
            'paid': Student.objects.filter(fee_status='Paid').count(),
            'pending': Student.objects.filter(fee_status='Pending').count(),
            'overdue': Student.objects.filter(fee_status='Overdue').count(),
            'students': Student.objects.select_related('classroom')[:10],
        })

    elif role == 'owner':
        today = timezone.localdate()
        collected_month = sum(p.amount for p in FeePayment.objects.filter(
            status='Active', date__year=today.year, date__month=today.month))
        expenses_month = sum(e.amount for e in Expense.objects.filter(
            date__year=today.year, date__month=today.month))
        outstanding = 0
        defaulter_rows = []
        for s in (Student.objects.select_related('classroom')
                  .prefetch_related('challans__payments', 'challans__lines')):
            bal = sum(c.balance for c in s.challans.all())
            outstanding += bal
            if bal > 0:
                defaulter_rows.append({'student': s, 'outstanding': bal})
        defaulter_rows.sort(key=lambda r: r['outstanding'], reverse=True)
        enrollment = [{'room': c, 'count': Student.objects.filter(classroom=c).count()}
                      for c in ClassRoom.objects.all()]
        max_enroll = max([e['count'] for e in enrollment], default=0) or 1
        for e in enrollment:
            e['pct'] = round(e['count'] / max_enroll * 100)
        o_fin_grad, o_fin_legend, o_fin_total = _donut_gradient([
            ('Collected (this month)', collected_month, '#0E7C66'),
            ('Outstanding (all)', outstanding, '#C0432F')])
        o_fin_rate = (round(collected_month / o_fin_total * 100)
                      if o_fin_total else 0)
        context.update({
            'o_students': Student.objects.count(),
            'o_classes': ClassRoom.objects.count(),
            'o_teachers': Profile.objects.filter(role='teacher').count(),
            'o_collected': collected_month,
            'o_expenses': expenses_month,
            'o_net': collected_month - expenses_month,
            'o_outstanding': outstanding,
            'o_enrollment': enrollment,
            'o_fin_donut': o_fin_grad, 'o_fin_legend': o_fin_legend,
            'o_fin_donut_total': o_fin_total, 'o_fin_rate': o_fin_rate,
            'o_defaulters': defaulter_rows[:5],
            'o_month_label': today.strftime('%B %Y'),
        })

    return render(request, 'dashboard.html', context)


@login_required
@role_required('teacher')
def attendance_mark(request):
    profile = request.user.profile
    classes = _teacher_classes(profile)
    cid = request.POST.get('class') or request.GET.get('class')
    classroom = next((c for c in classes if str(c.id) == str(cid)), None) if cid else None
    if classroom is None:
        classroom = classes[0] if classes else None
    students = list(Student.objects.filter(classroom=classroom)) if classroom else []

    raw = request.POST.get('date') or request.GET.get('date')
    try:
        date = datetime.date.fromisoformat(raw) if raw else timezone.localdate()
    except (ValueError, TypeError):
        date = timezone.localdate()
    # Never allow attendance for a FUTURE date — it would pollute the register
    # and the attendance %. Clamp silently to today.
    if date > timezone.localdate():
        date = timezone.localdate()

    if request.method == 'POST' and students:
        prev = {r.student_id: r.status for r in
                AttendanceRecord.objects.filter(student__in=students, date=date)}
        newly_absent = []
        # All-or-nothing: a mid-loop failure must not leave the class half-marked.
        with transaction.atomic():
            for s in students:
                status = request.POST.get('status_%d' % s.id, 'P')
                if status not in ('P', 'A', 'L'):
                    status = 'P'
                if status == 'A' and prev.get(s.id) != 'A':
                    newly_absent.append(s)
                AttendanceRecord.objects.update_or_create(
                    student=s, date=date,
                    defaults={'status': status, 'session': _current_session()})
        sent = 0
        if newly_absent:
            school = School.objects.first()
            sname = school.name if school else 'School'
            sms_on = sms_enabled('SMS_NOTIFY_ON_ABSENT')
            email_on = email_alerts_enabled()
            for s in newly_absent:
                text = (
                    '%s: Dear %s, your child %s was marked ABSENT today (%s). '
                    'If this is unexpected, please contact the school.'
                    % (sname, s.guardian_name or 'Parent', s.name,
                       date.strftime('%d %b %Y')))
                phone = (s.guardian_phone or '').strip()
                if sms_on and phone:
                    notify(text, to_phone=phone,
                           recipients=s.guardian_name or s.name,
                           msg_type='Absent Alert')
                    sent += 1
                if email_on and (s.guardian_email or '').strip():
                    send_email_alert('Absence alert — %s' % sname, text,
                                     s.guardian_email, msg_type='Absent Alert')
                # Web push to the family's installed app / browser (best-effort).
                from .push import push_student_guardians
                push_student_guardians(s, '%s — Absent' % sname, text)
        msg = ('Attendance saved for %s (%s).'
               % (classroom, date.strftime('%d %b %Y')))
        if sent:
            note = 'logged' if settings.SMS_BACKEND == 'console' else 'sent'
            msg += ' %d absent alert(s) %s to guardians.' % (sent, note)
        messages.success(request, msg)
        return redirect('%s?class=%s&date=%s'
                        % (request.path, classroom.id, date.isoformat()))

    existing = {r.student_id: r.status for r in
                AttendanceRecord.objects.filter(student__in=students, date=date)}
    rows = [(s, existing.get(s.id, 'P')) for s in students]
    return render(request, 'attendance_mark.html', {
        'role': profile.role, 'active': 'attendance',
        'classroom': classroom, 'classes': classes, 'rows': rows,
        'date': date.isoformat(),
        # Let the teacher know this class+date was already marked, so saving
        # will update an existing record (possibly entered by someone else).
        'already_marked': bool(existing),
    })


LOW_ATTENDANCE_PCT = 75


@login_required
@role_required('admin', 'principal', 'teacher')
def attendance_register(request):
    """Printable monthly attendance register (P/A/L grid) for one class, with a
    low-attendance flag on anyone below the threshold — what board/government
    inspections ask for, and an early warning for struggling students."""
    profile = request.user.profile
    if profile.role == 'teacher':
        classes = _teacher_classes(profile)
    else:
        classes = list(ClassRoom.objects.all())
    sel = request.GET.get('class')
    classroom = next((c for c in classes if str(c.id) == str(sel)), None)
    if classroom is None and classes:
        classroom = classes[0]
    today = timezone.localdate()
    try:
        year = int(request.GET.get('year') or today.year)
        month = int(request.GET.get('month') or today.month)
    except ValueError:
        year, month = today.year, today.month
    month = min(12, max(1, month))
    days = list(range(1, pycal.monthrange(year, month)[1] + 1))

    students = (list(Student.objects.filter(
        classroom=classroom, status='Active', graduated=False)
        .order_by('roll_no', 'name')) if classroom else [])
    rows = []
    if students:
        grid = {}
        for sid, d, st in (AttendanceRecord.objects.filter(
                student__in=students, date__year=year, date__month=month)
                .values_list('student_id', 'date', 'status')):
            grid[(sid, d.day)] = st
        for s in students:
            cells, p, a, ln = [], 0, 0, 0
            for day in days:
                st = grid.get((s.id, day), '')
                if st == 'P':
                    p += 1
                elif st == 'A':
                    a += 1
                elif st == 'L':
                    ln += 1
                cells.append(st)
            marked = p + a + ln
            pct = round(p / marked * 100) if marked else None
            rows.append({'s': s, 'cells': cells, 'p': p, 'a': a, 'l': ln,
                         'marked': marked, 'pct': pct,
                         'low': pct is not None and pct < LOW_ATTENDANCE_PCT})
    return render(request, 'attendance_register.html', {
        'role': profile.role, 'active': 'attendance', 'classes': classes,
        'classroom': classroom, 'days': days, 'rows': rows,
        'year': year, 'month': month, 'month_name': FeeChallan.MONTHS[month],
        'months': [(i, FeeChallan.MONTHS[i]) for i in range(1, 13)],
        'years': [today.year - 1, today.year, today.year + 1],
        'threshold': LOW_ATTENDANCE_PCT,
        'low_count': sum(1 for r in rows if r['low']),
    })


@login_required
@role_required('admin', 'principal', 'teacher')
def attendance_sessional(request):
    """Sessional (term-wise) attendance summary: each student's present/absent/
    late totals and overall % across a whole academic session for one class —
    the consolidated figure inspections and report cards use. Exportable."""
    profile = request.user.profile
    if profile.role == 'teacher':
        classes = _teacher_classes(profile)
    else:
        classes = list(ClassRoom.objects.all())
    sel = request.GET.get('class')
    classroom = next((c for c in classes if str(c.id) == str(sel)), None)
    if classroom is None and classes:
        classroom = classes[0]

    sessions = sorted({s for s in AttendanceRecord.objects.exclude(session='')
                       .values_list('session', flat=True).distinct()},
                      reverse=True)
    cur = _current_session()
    if cur not in sessions:
        sessions.insert(0, cur)
    session = request.GET.get('session') or cur

    students = (list(Student.objects.filter(classroom=classroom, graduated=False)
                     .order_by('roll_no', 'name')) if classroom else [])
    rows = []
    if students:
        agg = {}
        for sid, st in (AttendanceRecord.objects.filter(
                student__in=students, session=session)
                .values_list('student_id', 'status')):
            d = agg.setdefault(sid, {'p': 0, 'a': 0, 'l': 0})
            if st == 'P':
                d['p'] += 1
            elif st == 'A':
                d['a'] += 1
            elif st == 'L':
                d['l'] += 1
        for s in students:
            d = agg.get(s.id, {'p': 0, 'a': 0, 'l': 0})
            marked = d['p'] + d['a'] + d['l']
            pct = round(d['p'] / marked * 100) if marked else None
            rows.append({'s': s, 'p': d['p'], 'a': d['a'], 'l': d['l'],
                         'marked': marked, 'pct': pct,
                         'low': pct is not None and pct < LOW_ATTENDANCE_PCT})

    if request.GET.get('export') == 'csv':
        header = ['Roll', 'Student', 'Present', 'Absent', 'Late', 'Marked',
                  'Percent']
        data = [[r['s'].roll_no, r['s'].name, r['p'], r['a'], r['l'],
                 r['marked'], '' if r['pct'] is None else r['pct']]
                for r in rows]
        return _csv_response('attendance_sessional_%s.csv' % session,
                             header, data)

    return render(request, 'attendance_sessional.html', {
        'role': profile.role, 'active': 'sessional', 'classes': classes,
        'classroom': classroom, 'rows': rows, 'sessions': sessions,
        'session': session, 'threshold': LOW_ATTENDANCE_PCT,
        'low_count': sum(1 for r in rows if r['low']),
    })


def _marks_signature(student_ids, subject, exam):
    """A small fingerprint of a class's marks for one subject+exam, used to
    detect concurrent edits by two teachers before overwriting."""
    if not (student_ids and subject and exam):
        return ''
    pairs = Mark.objects.filter(
        student_id__in=student_ids, subject=subject, exam=exam
    ).values_list('student_id', 'marks_obtained')
    return ';'.join('%d:%d' % (sid, m) for sid, m in sorted(pairs))


@login_required
@role_required('admin', 'principal')
def absent_list(request):
    """Daily Absent Student List: every student marked absent on a given date,
    grouped by class — the register Accounts/office run each morning. Exportable."""
    raw = request.GET.get('date')
    try:
        date = datetime.date.fromisoformat(raw) if raw else timezone.localdate()
    except (ValueError, TypeError):
        date = timezone.localdate()
    rows = list(
        AttendanceRecord.objects.filter(date=date, status='A')
        .select_related('student', 'student__classroom')
        .order_by('student__classroom__name', 'student__classroom__section',
                  'student__name'))
    if request.GET.get('export') == 'csv':
        header = ['Class', 'Roll', 'Student', 'Guardian', 'Phone']
        data = [[str(r.student.classroom or ''), r.student.roll_no,
                 r.student.name, r.student.guardian_name,
                 r.student.guardian_phone] for r in rows]
        return _csv_response('absent_%s.csv' % date.isoformat(), header, data)
    return render(request, 'absent_list.html', {
        'role': request.user.profile.role, 'active': 'absent',
        'date': date.isoformat(), 'rows': rows, 'count': len(rows),
    })


# --- Insights thresholds (tunable rules — no external AI/API involved) ---
INSIGHTS_DROP_PTS = 10      # exam-over-exam % drop that flags a student
INSIGHTS_WEAK_PCT = 50      # a subject's class average below this = weak
INSIGHTS_FAIL_PCT = 33      # a result below this = failing


def _insights_pct_by_student(exam):
    """{student_id: overall percentage} for one exam, summed across subjects."""
    agg = {}
    if not exam:
        return agg
    for sid, ob, tot in Mark.objects.filter(exam=exam).values_list(
            'student_id', 'marks_obtained', 'total_marks'):
        d = agg.setdefault(sid, [0, 0])
        d[0] += ob
        d[1] += tot
    return {sid: round(o / t * 100) for sid, (o, t) in agg.items() if t}


@login_required
@role_required('admin', 'principal')
def insights(request):
    """Rule-based 'Insights' — at-risk students, fee risk and weak subjects,
    computed entirely from the school's own data with simple rules/statistics.
    No external AI, API, or internet, so it behaves identically in the offline
    .exe and the online SaaS. Office-only (admin/principal)."""
    session = _current_session()

    students = list(Student.objects.filter(graduated=False).select_related('classroom'))
    sids = [s.id for s in students]
    id_to_student = {s.id: s for s in students}

    # --- Attendance % this session, per student ---
    att = {}
    for sid, status in (AttendanceRecord.objects.filter(
            student_id__in=sids, session=session)
            .values_list('student_id', 'status')):
        d = att.setdefault(sid, {'p': 0, 'm': 0})
        d['m'] += 1
        if status == 'P':
            d['p'] += 1

    # --- Marks trend: the two most recent exams (newest first by -id) ---
    exams = list(Exam.objects.filter(session=session)[:2])
    if len(exams) < 2:                      # new/untagged session: fall back
        exams = list(Exam.objects.all()[:2])
    latest = exams[0] if exams else None
    prev = exams[1] if len(exams) > 1 else None
    latest_pct = _insights_pct_by_student(latest)
    prev_pct = _insights_pct_by_student(prev)

    # --- At-risk students: attendance drop, result drop, or failing ---
    at_risk = []
    for s in students:
        reasons = []
        d = att.get(s.id)
        apct = round(d['p'] / d['m'] * 100) if d and d['m'] else None
        if apct is not None and apct < LOW_ATTENDANCE_PCT:
            reasons.append('Attendance %d%%' % apct)
        lp = latest_pct.get(s.id)
        pp = prev_pct.get(s.id)
        drop = None
        if lp is not None and pp is not None and (pp - lp) >= INSIGHTS_DROP_PTS:
            drop = pp - lp
            reasons.append('Result down %d%% (%d%%→%d%%)' % (drop, pp, lp))
        if lp is not None and lp < INSIGHTS_FAIL_PCT:
            reasons.append('Failing (%d%%)' % lp)
        if reasons:
            at_risk.append({
                'student': s, 'attendance': apct, 'result': lp, 'drop': drop,
                'reasons': reasons,
                # severity: number of flags first, then lower attendance
                'score': len(reasons) * 1000 + (100 - (apct if apct is not None else 100)),
            })
    at_risk.sort(key=lambda r: r['score'], reverse=True)

    # --- Fee risk: students with an outstanding challan balance ---
    bal_by_student = {}
    for c in FeeChallan.objects.all():
        if c.student_id and c.balance > 0:
            bal_by_student[c.student_id] = bal_by_student.get(c.student_id, 0) + c.balance
    fee_rows = [{'student': id_to_student[sid], 'balance': bal}
                for sid, bal in bal_by_student.items() if sid in id_to_student]
    fee_rows.sort(key=lambda r: r['balance'], reverse=True)
    fee_total = sum(r['balance'] for r in fee_rows)

    # --- Weak subjects: class average per subject in the latest exam ---
    weak = []
    if latest:
        subj = {}
        for name, ob, tot in Mark.objects.filter(exam=latest).values_list(
                'subject__name', 'marks_obtained', 'total_marks'):
            d = subj.setdefault(name, [0, 0])
            d[0] += ob
            d[1] += tot
        for name, (o, t) in subj.items():
            avg = round(o / t * 100) if t else 0
            if avg < INSIGHTS_WEAK_PCT:
                weak.append({'subject': name, 'avg': avg})
        weak.sort(key=lambda r: r['avg'])

    if request.GET.get('export') == 'csv':
        header = ['Class', 'Roll', 'Student', 'Attendance %', 'Result %', 'Flags']
        data = [[str(r['student'].classroom or ''), r['student'].roll_no,
                 r['student'].name,
                 '' if r['attendance'] is None else r['attendance'],
                 '' if r['result'] is None else r['result'],
                 '; '.join(r['reasons'])] for r in at_risk]
        return _csv_response('at_risk_%s.csv' % session, header, data)

    return render(request, 'insights.html', {
        'role': request.user.profile.role, 'active': 'insights',
        'session': session, 'latest_exam': latest, 'prev_exam': prev,
        'at_risk': at_risk[:60], 'at_risk_count': len(at_risk),
        'fee_rows': fee_rows[:30], 'fee_count': len(fee_rows), 'fee_total': fee_total,
        'weak': weak, 'total_students': len(students),
        'low_attendance_pct': LOW_ATTENDANCE_PCT,
    })


@login_required
@role_required('teacher')
def marks_entry(request):
    profile = request.user.profile
    # The office (admin/principal) can enter/moderate marks for ANY class and
    # subject; a teacher is limited to the classes and subjects they teach.
    office = profile.role in ('admin', 'principal')
    classes = list(ClassRoom.objects.all()) if office else _teacher_classes(profile)
    cid = request.POST.get('class') or request.GET.get('class')
    classroom = next((c for c in classes if str(c.id) == str(cid)), None) if cid else None
    if classroom is None:
        classroom = classes[0] if classes else None
    students = list(Student.objects.filter(classroom=classroom)) if classroom else []
    taught = (set(profile.teaching.filter(classroom=classroom)
                  .values_list('subject', flat=True)) if classroom else set())
    if office:
        subjects = list(Subject.objects.filter(classroom=classroom)) if classroom else []
    else:
        subjects = (list(Subject.objects.filter(classroom=classroom, name__in=taught))
                    if taught else [])
    # Pick which exam to enter marks for (from ?exam=/POST, else the latest).
    exam, exams = _pick_exam(request)

    subj_id = _pk(request.POST.get('subject') or request.GET.get('subject'))
    subject = None
    if subj_id:
        subject = Subject.objects.filter(id=subj_id, classroom=classroom).first()
        # A teacher may only enter marks for subjects they actually TEACH in this
        # class — the dropdown is already limited, but the POST must be checked
        # too (else a teacher merely linked to the class could write a
        # colleague's subject). Admins/principals (role bypass) are not limited.
        if subject and profile.role == 'teacher' and subject.name not in taught:
            subject = None
    if subject is None and subjects:
        subject = subjects[0]

    # Gradebook config for this subject paper: its max marks and lock state.
    config = None
    if subject and exam and classroom:
        config, _ = GradeConfig.objects.get_or_create(
            exam=exam, classroom=classroom, subject=subject.name)
    max_marks = config.max_marks if config else 100
    locked = config.locked if config else False
    is_office = profile.role in ('admin', 'principal')

    if request.method == 'POST' and subject and exam and students and config:
        action = request.POST.get('action', 'save_marks')

        if action == 'set_max':
            # Change the paper's maximum. Not allowed once locked.
            if locked:
                messages.error(request, 'Marks are locked — unlock first to change '
                               'the maximum.')
            else:
                try:
                    mx = max(1, min(1000, int(request.POST.get('max_marks') or 100)))
                    config.max_marks = mx
                    config.save(update_fields=['max_marks'])
                    messages.success(request, 'Maximum for %s set to %d.'
                                     % (subject.name, mx))
                except ValueError:
                    messages.error(request, 'Enter a valid maximum.')
            return redirect('%s?class=%s&subject=%s&exam=%s'
                            % (request.path, classroom.id, subject.id, exam.id))

        if action in ('lock', 'unlock'):
            # Anyone teaching may lock; only the office may unlock (moderation).
            if action == 'unlock' and not is_office:
                messages.error(request, 'Only the office can unlock finalised marks.')
            else:
                config.locked = (action == 'lock')
                config.locked_by = (request.user.get_full_name()
                                    or request.user.username) if config.locked else ''
                config.save(update_fields=['locked', 'locked_by'])
                _audit(request, 'Marks %sed' % action,
                       '%s / %s / %s' % (subject.name, classroom, exam.name))
                messages.success(request, 'Marks %sed for %s.'
                                 % (action, subject.name))
            return redirect('%s?class=%s&subject=%s&exam=%s'
                            % (request.path, classroom.id, subject.id, exam.id))

        # Default: save marks.
        if locked:
            messages.error(request, 'These marks are locked and cannot be changed. '
                           'Ask the office to unlock them for moderation.')
            return redirect('%s?class=%s&subject=%s&exam=%s'
                            % (request.path, classroom.id, subject.id, exam.id))
        # Concurrency guard: if another teacher changed these same marks while
        # this page was open, don't silently overwrite them. 'known_sig' is a
        # fingerprint of the marks as they were when the page loaded.
        sids = [s.id for s in students]
        known_sig = request.POST.get('known_sig', '')
        current_sig = _marks_signature(sids, subject, exam)
        if known_sig != current_sig:
            messages.error(
                request, 'These marks were changed by someone else while you were '
                'editing. The latest values are shown below — please re-check and '
                'save again.')
        else:
            with transaction.atomic():
                for s in students:
                    val = (request.POST.get('marks_%d' % s.id, '') or '').strip()
                    if val == '':
                        continue
                    try:
                        num = max(0, min(max_marks, int(val)))
                    except ValueError:
                        continue
                    Mark.objects.update_or_create(
                        student=s, subject=subject, exam=exam,
                        defaults={'marks_obtained': num, 'total_marks': max_marks})
            _audit(request, 'Marks saved',
                   '%s / %s / %s' % (subject.name, classroom, exam.name))
            messages.success(request, 'Marks saved for %s (%s, %s).'
                             % (subject.name, classroom, exam.name))
            return redirect('%s?class=%s&subject=%s&exam=%s'
                            % (request.path, classroom.id, subject.id, exam.id))

    existing = {}
    if subject and exam:
        existing = {m.student_id: m.marks_obtained for m in
                    Mark.objects.filter(student__in=students, subject=subject, exam=exam)}
    rows = [(s, existing.get(s.id, '')) for s in students]
    marks_sig = (_marks_signature([s.id for s in students], subject, exam)
                 if subject and exam else '')
    return render(request, 'marks_entry.html', {
        'role': profile.role, 'active': 'marks',
        'classroom': classroom, 'classes': classes, 'subjects': subjects,
        'subject': subject, 'exam': exam, 'exams': exams, 'rows': rows,
        'marks_sig': marks_sig, 'max_marks': max_marks, 'locked': locked,
        'locked_by': config.locked_by if config else '', 'is_office': is_office,
    })


@login_required
@role_required('parent', 'student')
def my_attendance(request):
    profile = request.user.profile
    child, _kids = _active_child(request)
    today = timezone.localdate()
    year, month = today.year, today.month

    status_by_day = {}
    if child:
        for r in AttendanceRecord.objects.filter(
                student=child, date__year=year, date__month=month):
            status_by_day[r.date.day] = r.status

    calendar = pycal
    calendar.setfirstweekday(calendar.MONDAY)
    cells = []
    for week in calendar.monthcalendar(year, month):
        for dayno in week:
            if dayno == 0:
                cells.append({'empty': True})
                continue
            d = datetime.date(year, month, dayno)
            st = status_by_day.get(dayno)
            cell = {'day': dayno, 'today': d == today, 'label': '', 'cls': ''}
            if st == 'P':
                cell['cls'], cell['label'] = 'p', 'P'
            elif st == 'A':
                cell['cls'], cell['label'] = 'a', 'A'
            elif st == 'L':
                cell['cls'], cell['label'] = 'l', 'L'
            elif d.weekday() == 6:           # Sunday = holiday
                cell['cls'] = 'off'
            elif d > today:
                cell['cls'] = 'future'
            else:
                cell['cls'] = 'off'
            cells.append(cell)

    present = sum(1 for s in status_by_day.values() if s == 'P')
    absent = sum(1 for s in status_by_day.values() if s == 'A')
    leave = sum(1 for s in status_by_day.values() if s == 'L')
    total = len(status_by_day)
    pct = round(present / total * 100) if total else 0
    return render(request, 'my_attendance.html', {
        'role': profile.role, 'active': 'attendance', 'child': child,
        'cells': cells, 'present': present, 'absent': absent, 'leave': leave,
        'total': total, 'pct': pct,
        'month_name': today.strftime('%B'), 'year': year,
        'leaves': list(child.leaves.all()[:8]) if child else [],
        'today_iso': today.isoformat(),
    })


@login_required
@role_required('parent', 'student')
def apply_leave(request):
    """Parent/student submits a leave request for the active child; it goes to
    the office/principal approvals queue."""
    child, _kids = _active_child(request)
    if request.method == 'POST' and child:
        try:
            fd = datetime.date.fromisoformat(request.POST.get('from_date', ''))
            td = datetime.date.fromisoformat(request.POST.get('to_date', ''))
        except (ValueError, TypeError):
            messages.error(request, 'Please pick valid from and to dates.')
            return redirect('my_attendance')
        reason = (request.POST.get('reason', '') or '').strip()
        if td < fd:
            messages.error(request, 'The "to" date cannot be before the "from" date.')
        elif not reason:
            messages.error(request, 'Please give a reason for the leave.')
        else:
            StudentLeave.objects.create(
                student=child, from_date=fd, to_date=td, reason=reason[:300],
                applied_by=request.user.get_full_name() or request.user.username)
            messages.success(request, 'Leave request submitted. You will see the '
                             'status here once the office decides.')
    return redirect('my_attendance')


@login_required
@role_required('parent', 'student')
def parent_messages(request):
    """The family side of the parent<->teacher thread for the active child.
    Sending posts to the shared per-student conversation; opening it marks the
    teachers' replies as read."""
    child, kids = _active_child(request)
    profile = request.user.profile
    if request.method == 'POST' and child:
        body = (request.POST.get('body', '') or '').strip()
        if body:
            Message.objects.create(
                student=child, sender=profile, sender_role=profile.role,
                sender_name=request.user.get_full_name() or request.user.username,
                body=body[:2000], seen_by_family=True, seen_by_staff=False)
        else:
            messages.error(request, 'Type a message first.')
        return redirect('parent_messages')

    thread = []
    if child:
        thread = list(child.messages.select_related('sender'))
        # Opening the thread clears the family's unread teacher replies.
        (child.messages.filter(seen_by_family=False)
         .update(seen_by_family=True))
    return render(request, 'parent_messages.html', {
        'role': profile.role, 'active': 'messages', 'child': child,
        'thread': thread, 'my_id': profile.id,
    })


@login_required
@role_required('parent', 'student')
def complaints(request):
    """Family side: raise a complaint/feedback ticket and track its status."""
    profile = request.user.profile
    child, _kids = _active_child(request)
    if request.method == 'POST':
        subject = (request.POST.get('subject', '') or '').strip()
        body = (request.POST.get('body', '') or '').strip()
        category = request.POST.get('category', 'Other')
        valid = {c for c, _ in Complaint.CATEGORIES}
        if subject and body:
            Complaint.objects.create(
                student=child, raised_by=profile,
                raised_by_name=request.user.get_full_name() or request.user.username,
                category=category if category in valid else 'Other',
                subject=subject[:140], body=body[:4000])
            messages.success(request, 'Your complaint has been submitted. The '
                             'office will respond here.')
        else:
            messages.error(request, 'Please give a subject and describe the issue.')
        return redirect('complaints')

    mine = list(Complaint.objects.filter(raised_by=profile))
    return render(request, 'complaints.html', {
        'role': profile.role, 'active': 'complaints', 'child': child,
        'complaints': mine, 'categories': Complaint.CATEGORIES,
    })


@login_required
@role_required('admin', 'principal')
def office_complaints(request):
    """Office side: respond to complaints and move them through Open -> In
    Progress -> Resolved."""
    if request.method == 'POST':
        c = Complaint.objects.filter(pk=_pk(request.POST.get('complaint_id'))).first()
        if c:
            status = request.POST.get('status', c.status)
            valid = {s for s, _ in Complaint.STATUS}
            if status in valid:
                c.status = status
            resp = (request.POST.get('response', '') or '').strip()
            if resp:
                c.response = resp[:4000]
            c.handled_by = request.user.get_full_name() or request.user.username
            c.save(update_fields=['status', 'response', 'handled_by', 'updated'])
            _audit(request, 'Complaint %s' % c.status,
                   '%s (%s)' % (c.subject, c.raised_by_name or '-'))
            messages.success(request, 'Complaint updated (%s).' % c.status)
        return redirect('office_complaints')

    tab = request.GET.get('tab', 'open')
    qs = Complaint.objects.select_related('student', 'student__classroom')
    if tab == 'resolved':
        qs = qs.filter(status='Resolved')
    elif tab == 'all':
        pass
    else:
        tab = 'open'
        qs = qs.exclude(status='Resolved')
    counts = {
        'open': Complaint.objects.exclude(status='Resolved').count(),
        'resolved': Complaint.objects.filter(status='Resolved').count(),
        'all': Complaint.objects.count(),
    }
    role = request.user.profile.role
    return render(request, 'office_complaints.html', {
        'role': role, 'active': 'complaints', 'complaints': list(qs), 'tab': tab,
        'counts': counts, 'statuses': Complaint.STATUS,
    })


def _report_card_data(student, exam, pass_mark, ranking):
    """Everything one report card needs. Shared by the single-student card and
    the bulk whole-class printout so both stay identical."""
    marks = list(Mark.objects.filter(student=student, exam=exam)
                 .select_related('subject'))
    rows, obtained, maximum, failed = [], 0, 0, []
    for m in marks:
        ok = m.percentage >= pass_mark
        if not ok:
            failed.append(m.subject.name)
        rows.append({'subject': m.subject.name, 'obtained': m.marks_obtained,
                     'total': m.total_marks, 'pct': m.percentage,
                     'grade': m.grade, 'ok': ok})
        obtained += m.marks_obtained
        maximum += m.total_marks
    pct = round(obtained / maximum * 100) if maximum else 0
    position, total_ranked = ranking.get(student.id, (None, None))
    return {
        'student': student, 'rows': rows, 'obtained': obtained,
        'maximum': maximum, 'pct': pct,
        'overall_grade': grade_for(pct) if marks else '-',
        'result': 'Pass' if (marks and not failed) else ('Fail' if marks else '-'),
        'failed': failed, 'position': position, 'total_ranked': total_ranked,
    }


@login_required
def report_card(request, pk, exam_pk):
    student = get_object_or_404(Student.objects.select_related('classroom'), pk=pk)
    exam = get_object_or_404(Exam, pk=exam_pk)
    role = request.user.profile.role
    if role in ('student', 'parent'):
        if not _owns_student(request.user.profile, student.id):
            return HttpResponseForbidden('You cannot view this report card.')
    elif role not in ('admin', 'teacher', 'principal', 'owner'):
        return HttpResponseForbidden('Not allowed.')

    school = School.objects.first()
    pass_mark = school.pass_mark if school else 40
    ranking = _class_ranking(exam, student.classroom)
    data = _report_card_data(student, exam, pass_mark, ranking)
    return render(request, 'report_card.html', {
        'exam': exam, 'school': school, 'pass_mark': pass_mark, 'role': role,
        'active': 'results' if role in ('student', 'parent') else 'students',
        **data,
    })


@login_required
@role_required('admin', 'principal', 'teacher')
def report_cards_bulk(request):
    """Print every student's report card for a class + exam in one go — the big
    after-exam job that used to mean opening each student one by one."""
    profile = request.user.profile
    if profile.role == 'teacher':
        classes = _teacher_classes(profile)
    else:
        classes = list(ClassRoom.objects.all())
    sel = request.GET.get('class')
    classroom = next((c for c in classes if str(c.id) == str(sel)), None)
    if classroom is None and classes:
        classroom = classes[0]
    exam, exams = _pick_exam(request)
    school = School.objects.first()
    pass_mark = school.pass_mark if school else 40

    cards = []
    if classroom and exam:
        ranking = _class_ranking(exam, classroom)
        students = (Student.objects.filter(classroom=classroom, graduated=False)
                    .order_by('roll_no', 'name'))
        for s in students:
            d = _report_card_data(s, exam, pass_mark, ranking)
            if d['rows']:          # skip students with no marks for this exam
                cards.append(d)
    return render(request, 'report_cards_bulk.html', {
        'role': profile.role, 'active': 'students' if profile.role != 'teacher' else 'marks',
        'classes': classes, 'classroom': classroom, 'exam': exam, 'exams': exams,
        'school': school, 'pass_mark': pass_mark, 'cards': cards,
        'sessions': _exam_sessions(),
        'sel_session': request.GET.get('session') or _current_session(),
    })


@login_required
@role_required('parent', 'student')
def my_results(request):
    profile = request.user.profile
    child, _kids = _active_child(request)
    grade_colors = {'A+': '#0E7C66', 'A': '#1E7C8A', 'B': '#2C5FA8',
                    'C': '#8A5A1E', 'D': '#B07D17', 'F': '#C0432F'}
    # Scope to ONE academic session so different years never blend, then show
    # ONE exam at a time within it (mixing exams gives a wrong total / %).
    child_sessions = (sorted(set(
        Exam.objects.filter(mark__student=child).exclude(session='')
        .values_list('session', flat=True)), reverse=True) if child else [])
    sel_session = request.GET.get('session')
    if sel_session not in child_sessions:
        cur = _current_session()
        sel_session = (cur if cur in child_sessions
                       else (child_sessions[0] if child_sessions else cur))
    exams = (list(Exam.objects.filter(mark__student=child, session=sel_session)
                  .distinct().order_by('-id')) if child else [])
    eid = request.GET.get('exam')
    exam = next((e for e in exams if str(e.id) == str(eid)), None) if eid else None
    if exam is None and exams:
        exam = exams[0]
    marks = (list(Mark.objects.filter(student=child, exam=exam)
                  .select_related('subject')) if child and exam else [])
    rows = []
    for m in marks:
        rows.append({
            'subject': m.subject.name,
            'obtained': m.marks_obtained,
            'total': m.total_marks,
            'pct': round(m.percentage),
            'grade': m.grade,
            'color': grade_colors.get(m.grade, '#6B7686'),
        })
    obtained = sum(m.marks_obtained for m in marks)
    maximum = sum(m.total_marks for m in marks)
    pct = round(obtained / maximum * 100) if maximum else 0
    overall_grade = grade_for(pct) if marks else '-'
    position, total_ranked = (_class_ranking(exam, child.classroom).get(
        child.id, (None, None)) if child else (None, None))
    return render(request, 'my_results.html', {
        'role': profile.role, 'active': 'results', 'child': child,
        'rows': rows, 'obtained': obtained, 'maximum': maximum, 'pct': pct,
        'overall_grade': overall_grade,
        'overall_color': grade_colors.get(overall_grade, '#6B7686'),
        'exam': exam,
        'exams': exams,
        'sessions': child_sessions, 'sel_session': sel_session,
        'position': position, 'total_ranked': total_ranked,
    })


@login_required
@role_required('parent', 'student')
def my_progress(request):
    """Performance TREND for the active child across every exam in a session:
    an overall percentage line plus a subject-by-exam grid, so a family can see
    whether the child is improving or slipping — not just one exam's result."""
    profile = request.user.profile
    child, _kids = _active_child(request)

    sessions = (sorted(set(
        Exam.objects.filter(mark__student=child).exclude(session='')
        .values_list('session', flat=True)), reverse=True) if child else [])
    sel_session = request.GET.get('session')
    if sel_session not in sessions:
        cur = _current_session()
        sel_session = (cur if cur in sessions
                       else (sessions[0] if sessions else cur))

    # Exams in chronological order (id ascending = the order they were created).
    exams = (list(Exam.objects.filter(mark__student=child, session=sel_session)
                  .distinct().order_by('id')) if child else [])

    # Overall % per exam + per-subject % grid.
    overall = []
    subj_marks = {}   # subject -> {exam_id: pct}
    for e in exams:
        marks = list(Mark.objects.filter(student=child, exam=e)
                     .select_related('subject'))
        obtained = sum(m.marks_obtained for m in marks)
        maximum = sum(m.total_marks for m in marks)
        pct = round(obtained / maximum * 100) if maximum else 0
        overall.append({'exam': e.name, 'pct': pct})
        for m in marks:
            subj_marks.setdefault(m.subject.name, {})[e.id] = m.percentage

    subject_rows = []
    for name in sorted(subj_marks):
        cells = [subj_marks[name].get(e.id) for e in exams]
        present = [c for c in cells if c is not None]
        trend = None
        if len(present) >= 2:
            trend = present[-1] - present[0]     # last vs first
        subject_rows.append({'subject': name, 'cells': cells,
                             'avg': round(sum(present) / len(present)) if present else None,
                             'trend': trend})

    pcts = [o['pct'] for o in overall]
    delta = (pcts[-1] - pcts[-2]) if len(pcts) >= 2 else None
    return render(request, 'my_progress.html', {
        'role': profile.role, 'active': 'progress', 'child': child,
        'exams': exams, 'overall': overall, 'subject_rows': subject_rows,
        'sessions': sessions, 'sel_session': sel_session,
        'labels_json': json.dumps([o['exam'] for o in overall]),
        'data_json': json.dumps(pcts),
        'latest': pcts[-1] if pcts else None,
        'best': max(pcts) if pcts else None, 'delta': delta,
    })


@login_required
def coming_soon(request):
    profile = getattr(request.user, 'profile', None)
    return render(request, 'coming_soon.html', {
        'role': profile.role if profile else None, 'active': '',
    })


# Quick-start steps shown at the top of the Help page, per role.
_HELP_QUICKSTART = {
    'admin': [
        'Open <b>School Settings</b> and set your school name, logo, colours, '
        'academic session and the default password for new logins.',
        'Add your classes and subjects in <b>Classes &amp; Subjects</b>.',
        'Add students in <b>Students</b> (or import many at once with '
        '<b>Import CSV</b>). A login is created automatically for each student '
        'and parent.',
        'Add teachers/staff in <b>Staff</b>; tick “Create login” to give them '
        'access. Set who teaches what.',
        'Build each class timetable in <b>Timetable</b>, and set exams in '
        '<b>Exams</b>.',
        'Turn on <b>SMS</b> and daily <b>Backup</b> in Settings when you are '
        'ready.',
    ],
    'teacher': [
        'Use <b>Mark Attendance</b> daily for your class.',
        'Enter test/exam marks in <b>Enter Marks</b>.',
        'Share work in <b>Assignments</b> and <b>Quizzes</b>.',
        'See your periods in <b>My Timetable</b> and your salary/attendance in '
        '<b>My Pay &amp; Attendance</b>.',
    ],
    'finance': [
        'Generate monthly challans in <b>Fee Collection</b>, then open a student '
        'to collect a payment or record a discount.',
        'Print a whole class’s challans at once with <b>Print challans</b>.',
        'Track unpaid fees in <b>Defaulters</b> and send reminders.',
        'See every receipt in <b>Receipts</b> and record costs in <b>Expenses</b>.',
    ],
    'parent': [
        'See your child’s <b>Attendance</b>, <b>Results</b> and <b>Fees</b>.',
        'If you have more than one child, use the switcher at the top right.',
        'Open <b>Fees</b> to view or print the fee voucher.',
    ],
    'student': [
        'Check <b>Results</b>, <b>Attendance</b>, <b>Timetable</b> and '
        '<b>Datesheet</b>.',
        'Find class notes/books in <b>Subjects &amp; Materials</b>.',
        'See and submit <b>Assignments</b> and take <b>Quizzes</b>.',
    ],
    'principal': [
        'Approve fee concessions in <b>Approvals</b>.',
        'Review school-wide <b>Academics</b> and <b>Staff</b>.',
        'Run end-of-year promotion in <b>Year-End</b>.',
    ],
    'owner': [
        'See the whole-school view of <b>Students</b>, <b>Staff</b> and '
        '<b>Finance</b>.',
    ],
}

# Module reference: what each area is for + how to use it.
_HELP_MODULES = [
    ('Students &amp; Admissions', [
        ('Students', 'Every student record — personal details, class, guardian, '
         'status. Add one at a time, or many via Import CSV. Each new student '
         'and parent gets a login automatically.'),
        ('Admissions', 'Track enquiries through test, offer and enrolment. '
         'Convert an applicant into a full student in one click.'),
    ]),
    ('Academics', [
        ('Classes &amp; Subjects', 'Set up your classes (e.g. 9-A) and the '
         'subjects taught in each.'),
        ('Timetable', 'Build each class’s weekly period timetable.'),
        ('Exams', 'Create exams and their datesheets. Marks and results are '
         'grouped by academic session so different years never mix.'),
        ('Enter Marks / Results', 'Teachers enter marks per exam; students and '
         'parents see results with grade, percentage and class position. Print '
         'one report card, or a whole class at once.'),
    ]),
    ('Attendance', [
        ('Mark Attendance', 'Teachers mark daily attendance per class. Guardians '
         'of absent students can get an automatic SMS.'),
        ('Attendance Register', 'A printable monthly P/A/L grid for a class, '
         'with students below 75% flagged.'),
    ]),
    ('Fees &amp; Finance', [
        ('Fee Collection', 'Generate monthly challans, collect payments, and '
         'give discounts/scholarships (principal-approved).'),
        ('Fee heads', 'In Settings, define extra charges (admission, annual, '
         'exam, security) that are added to challans automatically.'),
        ('Online Payments', 'Turn on in Settings to let parents pay fees online. '
         'Bank transfer works everywhere: the parent submits a reference and '
         'Accounts verifies it on the Online Payments screen. JazzCash/Easypaisa '
         'need a merchant account and an internet deployment.'),
        ('Defaulters / Receipts / Expenses', 'See who owes fees and remind them, '
         'view all receipts, and record school expenses.'),
    ]),
    ('Staff &amp; HR', [
        ('Staff', 'Your employee directory. Add one at a time or via Import CSV; '
         'give a login when someone needs system access.'),
        ('Attendance / Payroll / Leave', 'Mark staff attendance, generate '
         'payslips, and manage leave requests.'),
    ]),
    ('Communication &amp; Records', [
        ('Communication', 'Send announcements and messages; every SMS is logged.'),
        ('WhatsApp alerts', 'In Settings you can send the same alerts (absent, '
         'fee receipt, reminders) over WhatsApp as well as, or instead of, SMS. '
         'Choose SMS / WhatsApp / both. Needs a WhatsApp Business provider.'),
        ('Certificates / ID Cards', 'Issue leaving/character/bonafide '
         'certificates and print student ID cards.'),
        ('Transport / Hostel / Library / Inventory / Visitors', 'Day-to-day '
         'operations: routes, hostel rooms, books, stock and the visitor log.'),
    ]),
    ('Admin &amp; Data safety', [
        ('School Settings', 'Your school’s identity (name, logo, colours), '
         'session, pass mark, fee heads, SMS and one-click Backup.'),
        ('Users &amp; Roles', 'Create logins and set what each person can access. '
         'Most logins are created automatically when you add a student or staff.'),
        ('Audit Log', 'A record of sensitive changes — grades, fees, roles.'),
        ('Backup', 'Download a full copy of your data anytime from Settings. '
         'Keep it on a USB or cloud drive. Turn on daily automatic backups too.'),
        ('Restore', 'Settings → “Restore from backup…” walks you through it: '
         'upload a .sqlite3 backup, the system checks it and shows a preview '
         '(school, students, staff, payments), then you type RESTORE to confirm. '
         'A safety copy of the current data is saved first, and everyone signs '
         'in again afterwards.'),
    ]),
]


# Breadcrumb-style "where to click" paths for common tasks (Section 8 docs).
_HELP_PATHS = [
    ('Add a student', 'Students → Add student'),
    ('Collect a fee', 'Fee Collection → open a student → Collect payment'),
    ('Verify an online / bank payment', 'Online Payments → To verify → Verify & record'),
    ('Turn on online payments', 'School Settings → Online fee payments'),
    ('Turn on WhatsApp alerts', 'School Settings → WhatsApp notifications'),
    ('Enter marks', 'Enter Marks → pick class, subject, exam → Save'),
    ('Mark attendance', 'Mark Attendance → pick class & date → Save'),
    ('Download a backup', 'School Settings → Download backup now'),
    ('Restore a backup', 'School Settings → Restore from backup…'),
    ('Run year-end promotion', 'Year-End → review decisions → tick approval → Apply'),
    ('Change your password', 'Top-right avatar → My account'),
]

# Roadmap / coming soon — set expectations honestly about what is planned next.
_HELP_ROADMAP = [
    ('Mobile app', 'A dedicated Android/iOS app for parents. The system is '
     'already mobile-friendly in the browser.'),
    ('Automatic online-payment confirmation', 'Live JazzCash/Easypaisa auto-'
     'reconciliation once a school deploys online with a merchant account.'),
    ('Multi-campus / multi-school (SaaS)', 'One login managing several campuses. '
     'Today each school runs its own copy.'),
    ('Offline mobile sync', 'Enter attendance/marks offline and sync later.'),
]


@login_required
def help_guide(request):
    profile = getattr(request.user, 'profile', None)
    role = profile.role if profile else 'admin'
    is_admin = role in ('admin', 'owner', 'principal')
    return render(request, 'help_guide.html', {
        'role': role, 'active': 'help',
        'quickstart': _HELP_QUICKSTART.get(role, []),
        'modules': _HELP_MODULES if is_admin else [],
        'paths': _HELP_PATHS if is_admin else [],
        'roadmap': _HELP_ROADMAP,
    })


# ----------------------- Step 3: Fees & Finance -----------------------

def _make_challan(student, year, month):
    existing = FeeChallan.objects.filter(
        student=student, year=year, month=month).first()
    if existing:
        return existing, False
    cls = student.classroom
    school = School.objects.first()
    tuition = student.custom_fee or (cls.monthly_fee if cls else 0)
    hostel = (school.hostel_fee if school else 8000) if student.is_hostel else 0
    transport = student.route.fee if student.route else 0
    # Which fee heads apply depends on whether this is the student's first-ever
    # challan (one-time heads) or first of the year (annual heads).
    had_any = student.challans.exists()
    had_this_year = student.challans.filter(year=year).exists()
    # carry forward any previous unpaid balance into this challan
    prev = list(student.challans.filter(carried_forward=False)
                .prefetch_related('payments', 'lines'))
    prev_unpaid = [c for c in prev if c.balance > 0]
    arrears = sum(c.balance for c in prev_unpaid)
    challan = FeeChallan.objects.create(
        student=student, year=year, month=month,
        tuition=tuition, hostel_fee=hostel, transport_fee=transport,
        arrears=arrears, due_date=datetime.date(year, month, 10))
    for head in FeeHead.objects.filter(active=True):
        if head.amount <= 0:
            continue
        apply = (head.frequency == 'monthly'
                 or (head.frequency == 'one_time' and not had_any)
                 or (head.frequency == 'annual' and not had_this_year))
        if apply:
            ChallanLine.objects.create(
                challan=challan, label=head.name, amount=head.amount)
    if prev_unpaid:
        FeeChallan.objects.filter(
            id__in=[c.id for c in prev_unpaid]).update(carried_forward=True)
    return challan, True


def _sync_fee_status(student):
    challans = list(student.challans.filter(carried_forward=False)
                    .prefetch_related('payments', 'lines'))
    outstanding = sum(c.balance for c in challans)
    if outstanding <= 0:
        student.fee_status = 'Paid'
    elif any(c.is_overdue for c in challans):
        student.fee_status = 'Overdue'
    else:
        student.fee_status = 'Pending'
    student.save(update_fields=['fee_status'])


def _escalating_late_fee(school, challan, today):
    """Expected late fee for an overdue, unpaid challan: a base amount plus a
    per-week escalation, capped. Returns 0 when late fees are off, the challan
    is settled, or it isn't overdue yet."""
    base = school.late_fee_amount if school else 0
    if not base or challan.balance <= 0 or challan.due_date >= today:
        return 0
    weeks = (today - challan.due_date).days // 7
    fee = base + (school.late_fee_per_week or 0) * weeks
    cap = school.late_fee_max or 0
    return min(fee, cap) if cap else fee


def _refresh_late_fee(school, challan, today):
    """Bump an overdue challan's late fee toward its escalating value. Never
    lowers an existing fee, and skips challans finance has locked by hand.
    Returns True if it changed the challan."""
    if challan.late_fee_locked or challan.carried_forward:
        return False
    expected = _escalating_late_fee(school, challan, today)
    if expected > challan.late_fee:
        challan.late_fee = expected
        challan.save(update_fields=['late_fee'])
        return True
    return False


def _record_fee_payment(student, challan, amount, mode, received_by,
                        actor='system', send_alert=True):
    """Create a FeePayment (with receipt number), write the audit trail, notify
    the parent and re-sync the fee status. Shared by counter collection and
    online-payment confirmation so both are recorded identically."""
    payment = FeePayment.objects.create(
        student=student, challan=challan,
        month=challan.label if challan else '',
        amount=amount, mode=mode, received_by=received_by,
        date=timezone.localdate())
    payment.receipt_no = 'RCPT-%s-%04d' % (
        str(timezone.localdate().year)[-2:], payment.id)
    payment.save(update_fields=['receipt_no'])
    AuditLog.objects.create(
        user=actor, action='Fee collected',
        detail=('Rs %d from %s (%s) receipt %s via %s'
                % (amount, student.name, challan.label if challan else '-',
                   payment.receipt_no, mode))[:255])
    if send_alert:
        school = School.objects.first()
        sname = school.name if school else 'School'
        text = ('%s: received Rs %d for %s (%s). Receipt %s. Thank you.'
                % (sname, amount, student.name,
                   challan.label if challan else 'fees', payment.receipt_no))
        phone = (student.guardian_phone or '').strip()
        if sms_enabled('SMS_NOTIFY_ON_PAYMENT') and phone:
            notify(text, to_phone=phone,
                   recipients=student.guardian_name or student.name,
                   msg_type='Fee Receipt')
        # Email the same receipt if the school uses email alerts and we have one.
        if email_alerts_enabled() and (student.guardian_email or '').strip():
            send_email_alert('Fee received — %s' % sname, text,
                             student.guardian_email, msg_type='Fee Receipt')
        # Web push to the family's installed app / browser (best-effort).
        from .push import push_student_guardians
        push_student_guardians(student, '%s — Fee received' % sname, text)
    _sync_fee_status(student)
    return payment


@login_required
@role_required('finance')
def fee_collection(request):
    today = timezone.localdate()
    if request.method == 'POST' and request.POST.get('action') == 'generate':
        try:
            gmonth = int(request.POST.get('month') or today.month)
            gyear = int(request.POST.get('year') or today.year)
        except ValueError:
            gmonth, gyear = today.month, today.year
        cid = request.POST.get('class_id') or 'all'
        qs = (Student.objects.filter(status='Active', graduated=False)
              .select_related('classroom', 'route'))
        if cid != 'all':
            qs = qs.filter(classroom_id=cid)
        created = 0
        for s in qs:
            _, made = _make_challan(s, gyear, gmonth)
            if made:
                created += 1
        scope = ('all classes' if cid == 'all'
                 else str(ClassRoom.objects.filter(pk=cid).first() or 'class'))
        messages.success(
            request, '%d challan(s) generated for %s - %s %d.'
            % (created, scope, FeeChallan.MONTHS[gmonth], gyear))
        return redirect('fee_collection')

    rows = []
    for s in (Student.objects.select_related('classroom')
              .prefetch_related('challans__payments', 'challans__lines')):
        challans = [c for c in s.challans.all() if not c.carried_forward]
        rows.append({
            'student': s,
            'outstanding': sum(c.balance for c in challans),
            'months_pending': sum(1 for c in challans if c.balance > 0),
        })
    rows.sort(key=lambda r: r['outstanding'], reverse=True)
    return render(request, 'fee_collection.html', {
        'role': 'finance', 'active': 'fees', 'rows': rows,
        'this_month': '%s %d' % (FeeChallan.MONTHS[today.month], today.year),
        'classes': ClassRoom.objects.all(),
        'months': list(enumerate(FeeChallan.MONTHS))[1:],
        'years': [today.year - 1, today.year, today.year + 1],
        'cur_month': today.month, 'cur_year': today.year,
    })


@login_required
@role_required('finance')
def student_fees(request, pk):
    student = get_object_or_404(Student.objects.select_related('classroom'), pk=pk)
    today = timezone.localdate()

    if request.method == 'POST':
        action = request.POST.get('action')
        cid = request.POST.get('challan_id')
        challan = (FeeChallan.objects.filter(pk=cid, student=student).first()
                   if cid else None)

        def amt(field):
            try:
                return max(0, int(request.POST.get(field, '') or 0))
            except ValueError:
                return 0

        if action == 'collect' and challan:
            amount = amt('amount')
            # --- Optimistic concurrency: stop two accountants double-collecting.
            # 'known_paid' is what this challan had already been paid when the
            # page was opened. If it changed, someone else collected in the
            # meantime, so we refuse and show the fresh figures. We also do the
            # money change inside a transaction that re-reads the challan.
            known_paid = amt('known_paid')
            with transaction.atomic():
                fresh = (FeeChallan.objects.select_for_update()
                         .filter(pk=challan.id).first())
                current_paid = fresh.paid if fresh else challan.paid
                balance = fresh.balance if fresh else challan.balance
                if amount <= 0:
                    pass
                elif current_paid != known_paid:
                    messages.error(
                        request, 'This challan was just updated by someone else '
                        '(now paid Rs %d, balance Rs %d). Please re-check before '
                        'collecting again.' % (current_paid, balance))
                elif amount > balance:
                    messages.error(
                        request, 'Rs %d is more than the balance of Rs %d — it may '
                        'already be paid. Please re-check.' % (amount, balance))
                else:
                    payment = _record_fee_payment(
                        student, challan, amount,
                        mode=request.POST.get('mode', 'Cash'),
                        received_by=request.user.get_full_name() or request.user.username,
                        actor=request.user.username)
                    messages.success(request, 'Rs %d received for %s. Receipt %s.'
                                     % (amount, challan.label, payment.receipt_no))
        elif action == 'request_discount' and challan:
            amount = amt('discount')
            if amount > 0:
                ConcessionRequest.objects.create(
                    challan=challan, kind='discount', amount=amount,
                    label=(request.POST.get('discount_reason', '') or '').strip(),
                    requested_by=request.user.get_full_name() or request.user.username)
                messages.success(
                    request, 'Discount request of Rs %d sent to the Principal '
                    'for approval.' % amount)
            else:
                messages.error(request, 'Enter a discount amount greater than zero.')
        elif action == 'request_scholarship' and challan:
            amount = amt('scholarship')
            if amount > 0:
                ConcessionRequest.objects.create(
                    challan=challan, kind='scholarship', amount=amount,
                    label=(request.POST.get('scholarship_name', '') or '').strip(),
                    requested_by=request.user.get_full_name() or request.user.username)
                messages.success(
                    request, 'Scholarship request of Rs %d sent to the Principal '
                    'for approval.' % amount)
            else:
                messages.error(request, 'Enter a scholarship amount greater than zero.')
        elif action == 'late_fee' and challan:
            challan.late_fee = amt('late_fee')
            # A hand-set late fee is locked so the daily escalation won't move it.
            challan.late_fee_locked = True
            challan.save(update_fields=['late_fee', 'late_fee_locked'])
            messages.success(request, 'Late fee updated on %s (auto-escalation off '
                             'for this challan).' % challan.label)
        elif action in ('void_payment', 'refund_payment'):
            # Reverse a recorded payment: 'void' = entered in error, 'refund' =
            # money returned to the parent. Either way the amount stops counting
            # and the challan balance reopens. Only an Active payment can be
            # reversed (no double-reversal); the row is kept for the trail.
            p = (FeePayment.objects.filter(pk=_pk(request.POST.get('payment_id')),
                                           student=student, status='Active').first())
            if p:
                new_status = 'Voided' if action == 'void_payment' else 'Refunded'
                p.status = new_status
                p.reversal_reason = (request.POST.get('reason', '') or '').strip()[:200]
                p.reversed_by = request.user.get_full_name() or request.user.username
                p.reversed_on = timezone.localdate()
                p.save(update_fields=['status', 'reversal_reason', 'reversed_by',
                                      'reversed_on'])
                _audit(request, '%s payment' % new_status,
                       'Rs %d receipt %s for %s (%s)'
                       % (p.amount, p.receipt_no or '-', student.name,
                          p.reversal_reason or 'no reason given'))
                messages.success(
                    request, 'Payment of Rs %d (receipt %s) marked %s. The balance '
                    'has reopened.' % (p.amount, p.receipt_no or '-', new_status.lower()))
            else:
                messages.error(request, 'That payment could not be reversed '
                               '(already voided/refunded, or not found).')
        elif action == 'add_advance':
            # Money received ahead of a challan is HELD as credit (a deposit),
            # not counted as income until it is applied to a fee.
            amount = amt('amount')
            if amount > 0:
                student.credit_balance = (student.credit_balance or 0) + amount
                student.save(update_fields=['credit_balance'])
                _audit(request, 'Advance received',
                       'Rs %d for %s (credit now Rs %d)'
                       % (amount, student.name, student.credit_balance))
                messages.success(request, 'Advance of Rs %d added. Credit balance '
                                 'is now Rs %d.' % (amount, student.credit_balance))
            else:
                messages.error(request, 'Enter an advance amount greater than zero.')
        elif action == 'apply_credit' and challan:
            # Settle (part of) a challan from the held credit. Recognised as fee
            # income now (a receipt is issued) and the credit is drawn down.
            with transaction.atomic():
                stu = Student.objects.select_for_update().get(pk=student.id)
                fresh = FeeChallan.objects.select_for_update().get(pk=challan.id)
                use = min(stu.credit_balance or 0, fresh.balance)
                if use <= 0:
                    messages.error(request, 'No credit available, or nothing due '
                                   'on this challan.')
                else:
                    _record_fee_payment(
                        stu, fresh, use, mode='Credit',
                        received_by=request.user.get_full_name() or request.user.username,
                        actor=request.user.username, send_alert=False)
                    stu.credit_balance = (stu.credit_balance or 0) - use
                    stu.save(update_fields=['credit_balance'])
                    messages.success(request, 'Rs %d of credit applied to %s. '
                                     'Credit left: Rs %d.'
                                     % (use, fresh.label, stu.credit_balance))
                    student = stu
        elif action == 'generate':
            _, made = _make_challan(student, today.year, today.month)
            messages.success(
                request,
                ('Challan generated for %s %d.' if made
                 else 'Challan already exists for %s %d.')
                % (FeeChallan.MONTHS[today.month], today.year))
        _sync_fee_status(student)
        return redirect('student_fees', pk=student.id)

    challans = list(student.challans.prefetch_related('payments', 'lines'))
    return render(request, 'student_fees.html', {
        'role': 'finance', 'active': 'fees', 'student': student,
        'challans': challans,
        'pending_reqs': list(ConcessionRequest.objects.filter(
            challan__student=student, status='Pending').select_related('challan')),
        'outstanding': sum(c.balance for c in challans),
        'total_paid': sum(c.paid for c in challans),
        # 'Credit' is applied via its own button, not chosen as a collect mode.
        'modes': [(v, l) for v, l in FeePayment.MODE_CHOICES if v != 'Credit'],
        'credit_balance': student.credit_balance or 0,
    })


@login_required
@role_required('finance')
def challans_bulk(request):
    """Print every challan for a class + month on one page — the monthly job
    finance used to do by opening each student's voucher separately."""
    today = timezone.localdate()
    classes = list(ClassRoom.objects.all())
    sel = request.GET.get('class')
    classroom = next((c for c in classes if str(c.id) == str(sel)), None)
    if classroom is None and classes:
        classroom = classes[0]
    try:
        year = int(request.GET.get('year') or today.year)
        month = int(request.GET.get('month') or today.month)
    except ValueError:
        year, month = today.year, today.month
    month = min(12, max(1, month))

    active_students = (Student.objects.filter(
        classroom=classroom, status='Active', graduated=False)
        .select_related('classroom') if classroom else Student.objects.none())
    vouchers = []
    if classroom:
        challans = {c.student_id: c for c in FeeChallan.objects.filter(
            student__in=active_students, year=year, month=month)
            .prefetch_related('payments', 'lines')}
        for s in active_students.order_by('roll_no', 'name'):
            c = challans.get(s.id)
            if c:
                vouchers.append({'st': s, 'c': c})
    return render(request, 'challans_bulk.html', {
        'role': 'finance', 'active': 'fees', 'classes': classes,
        'classroom': classroom, 'year': year, 'month': month,
        'month_name': FeeChallan.MONTHS[month], 'vouchers': vouchers,
        'school': School.objects.first(),
        'months': [(i, FeeChallan.MONTHS[i]) for i in range(1, 13)],
        'years': [today.year - 1, today.year, today.year + 1],
        'student_total': active_students.count(),
    })


@login_required
def receipt_view(request, pk):
    payment = get_object_or_404(
        FeePayment.objects.select_related('student', 'student__classroom'), pk=pk)
    profile = getattr(request.user, 'profile', None)
    role = profile.role if profile else None
    owner = _owns_student(profile, payment.student_id)
    if role not in ('finance', 'admin') and not owner:
        return HttpResponseForbidden('You cannot view this receipt.')
    # Pass `school` so the receipt shows the school's name/campus/crest (the
    # template reads {{ school.* }}; without this every printed receipt was blank).
    return render(request, 'receipt.html', {
        'role': role, 'active': '', 'p': payment, 'school': School.objects.first()})


@login_required
def fee_card(request, pk):
    """A printable annual fee statement for one student: every month's challan
    with billed / paid / balance, plus year totals. Finance/admin see any
    student; a parent/student sees only their own."""
    student = get_object_or_404(Student.objects.select_related('classroom'), pk=pk)
    profile = getattr(request.user, 'profile', None)
    role = profile.role if profile else None
    if role not in ('finance', 'admin') and not _owns_student(profile, student.id):
        return HttpResponseForbidden('You cannot view this fee card.')

    today = timezone.localdate()
    try:
        year = int(request.GET.get('year') or today.year)
    except (ValueError, TypeError):
        year = today.year

    challans = {c.month: c for c in student.challans.filter(year=year)
                .prefetch_related('payments', 'lines')}
    rows = []
    tot_billed = tot_paid = tot_bal = 0
    for m in range(1, 13):
        c = challans.get(m)
        # "Billed" is the month's OWN net charge — gross minus the arrears rolled
        # in from earlier months minus concessions. Summing net_payable instead
        # would double-count each unpaid month (it reappears as next month's
        # arrears), so the card counts only what each month freshly charges.
        billed = max(c.gross - c.arrears - c.deductions, 0) if c else 0
        paid = c.paid if c else 0
        bal = max(billed - paid, 0)
        tot_billed += billed
        tot_paid += paid
        tot_bal += bal
        rows.append({'month': FeeChallan.MONTHS[m], 'challan': c,
                     'billed': billed, 'paid': paid, 'balance': bal})
    return render(request, 'fee_card.html', {
        'role': role, 'active': 'fees', 'student': student, 'year': year,
        'rows': rows, 'tot_billed': tot_billed, 'tot_paid': tot_paid,
        'tot_bal': tot_bal, 'school': School.objects.first(),
        'years': [today.year - 2, today.year - 1, today.year, today.year + 1],
    })


@login_required
@role_required('finance')
def receipts(request):
    payments = FeePayment.objects.select_related('student').all()
    page, page_qs = _paginate(request, payments, 30)
    return render(request, 'receipts.html', {
        'role': 'finance', 'active': 'receipts', 'payments': page,
        'page_qs': page_qs,
    })


@login_required
@role_required('finance')
def defaulters(request):
    remind = request.GET.get('remind')
    if remind == 'all':
        count = 0
        for s in (Student.objects.select_related('classroom')
                  .prefetch_related('challans__payments', 'challans__lines')):
            bal = sum(c.balance for c in s.challans.all())
            phone = (s.guardian_phone or '').strip()
            if bal > 0 and phone:
                notify(
                    'Dear %s, fee reminder from Roshni Public School. '
                    'Outstanding balance for %s is Rs %d. Kindly clear it at your '
                    'earliest. Thank you.'
                    % (s.guardian_name or 'Parent', s.name, bal),
                    to_phone=phone, recipients=s.guardian_name or s.name,
                    msg_type='Fee Reminder')
                count += 1
        note = ('logged to console' if settings.SMS_BACKEND == 'console' else 'sent')
        messages.success(request, 'Fee reminders %s for %d guardian(s).'
                         % (note, count))
        return redirect('defaulters')
    if remind:
        s = Student.objects.filter(pk=remind).first()
        if s:
            phone = (s.guardian_phone or '').strip()
            if phone:
                bal = sum(c.balance for c in s.challans.all())
                statuses = notify(
                    'Dear %s, fee reminder from Roshni Public School: outstanding '
                    'Rs %d for %s. Please clear it soon.'
                    % (s.guardian_name or 'Parent', bal, s.name),
                    to_phone=phone, recipients=s.guardian_name or s.name,
                    msg_type='Fee Reminder')
                note = ('sent' if 'Sent' in statuses
                        else 'logged to console' if 'Console' in statuses
                        else 'failed')
                messages.success(request, 'Reminder %s for %s (%s).'
                                 % (note, s.guardian_name or s.name, phone))
            else:
                messages.error(request, 'No phone number on file for %s.'
                               % (s.guardian_name or s.name))
    rows = []
    for s in (Student.objects.select_related('classroom')
              .prefetch_related('challans__payments', 'challans__lines')):
        pending = [c for c in s.challans.all() if c.balance > 0]
        if pending:
            pending.sort(key=lambda c: (c.year, c.month))
            rows.append({
                'student': s,
                'outstanding': sum(c.balance for c in pending),
                'months': ', '.join(c.label for c in pending),
                'count': len(pending),
            })
    rows.sort(key=lambda r: r['outstanding'], reverse=True)
    total_outstanding = sum(r['outstanding'] for r in rows)
    page, page_qs = _paginate(request, rows, 30)
    return render(request, 'defaulters.html', {
        'role': 'finance', 'active': 'defaulters', 'rows': page,
        'page_qs': page_qs, 'defaulter_count': len(rows),
        'total_outstanding': total_outstanding,
    })


@login_required
@role_required('finance')
def expenses(request):
    from .models import PaymentSource
    if request.method == 'POST':
        action = request.POST.get('action', '')
        if action == 'add_source':
            name = (request.POST.get('name', '') or '').strip()
            if name:
                PaymentSource.objects.get_or_create(
                    name=name,
                    defaults={'note': (request.POST.get('note', '') or '').strip()})
                messages.success(request, 'Payment source added: %s.' % name)
            return redirect('expenses')
        title = (request.POST.get('title', '') or '').strip()
        if title:
            try:
                amount = max(0, int(request.POST.get('amount', '0') or 0))
            except ValueError:
                amount = 0
            category = request.POST.get('category', 'Other')
            source = PaymentSource.objects.filter(
                pk=_pk(request.POST.get('source'))).first()
            Expense.objects.create(title=title, category=category,
                                   amount=amount, date=timezone.localdate(),
                                   source=source)
            messages.success(request, 'Expense recorded: %s.' % title)
        return redirect('expenses')

    items = Expense.objects.select_related('source').all()
    total = sum(e.amount for e in items)
    sources = list(PaymentSource.objects.all())
    # Spending per source (plus anything left unassigned).
    by_source = {s.id: {'source': s, 'total': 0} for s in sources}
    unassigned = 0
    for e in items:
        if e.source_id and e.source_id in by_source:
            by_source[e.source_id]['total'] += e.amount
        else:
            unassigned += e.amount
    return render(request, 'expenses.html', {
        'role': 'finance', 'active': 'expenses', 'items': items, 'total': total,
        'sources': sources, 'source_totals': list(by_source.values()),
        'unassigned': unassigned,
    })


@login_required
@role_required('finance')
def finance_ledger(request):
    """Income-vs-Expense (P&L) ledger for one year: fee income (active
    payments) against expenses (manual entries + payroll from generated
    payslips), month by month, with a running net surplus/deficit. Payroll is
    read from Payslip rows — it is NOT double-counted from manual expenses."""
    today = timezone.localdate()
    try:
        year = int(request.GET.get('year') or today.year)
    except (ValueError, TypeError):
        year = today.year

    # Income: active fee payments only (voided/refunded excluded).
    inc_by_month = [0] * 13
    for m, amount in FeePayment.objects.filter(
            status='Active', date__year=year).values_list('date__month', 'amount'):
        inc_by_month[m] += amount

    # Manual expenses, by month and by category.
    exp_by_month = [0] * 13
    cat_totals = {}
    for e in Expense.objects.filter(date__year=year):
        exp_by_month[e.date.month] += e.amount
        label = e.get_category_display()
        cat_totals[label] = cat_totals.get(label, 0) + e.amount

    # Payroll: generated payslips (authoritative salary cost), by month.
    payroll_by_month = [0] * 13
    for p in Payslip.objects.filter(year=year):
        payroll_by_month[p.month] += p.net
    payroll_total = sum(payroll_by_month)
    if payroll_total:
        cat_totals['Payroll (payslips)'] = payroll_total

    rows, running = [], 0
    for m in range(1, 13):
        inc = inc_by_month[m]
        exp = exp_by_month[m] + payroll_by_month[m]
        net = inc - exp
        running += net
        rows.append({'month': FeeChallan.MONTHS[m], 'month_num': m,
                     'income': inc, 'expense': exp, 'net': net, 'running': running})

    total_income = sum(inc_by_month)
    total_expense = sum(exp_by_month) + payroll_total
    cat_rows = sorted(cat_totals.items(), key=lambda kv: kv[1], reverse=True)
    return render(request, 'finance_ledger.html', {
        'role': 'finance', 'active': 'ledger', 'year': year, 'rows': rows,
        'total_income': total_income, 'total_expense': total_expense,
        'net': total_income - total_expense, 'cat_rows': cat_rows,
        'years': [today.year - 2, today.year - 1, today.year,
                  today.year + 1],
    })


# ----------------------- Owner / Director (read-only) -----------------------

@login_required
@role_required('owner')
def owner_students(request):
    rows = []
    for s in (Student.objects.select_related('classroom')
              .prefetch_related('challans__payments', 'challans__lines')):
        rows.append({'student': s,
                     'outstanding': sum(c.balance for c in s.challans.all())})
    return render(request, 'owner_students.html', {
        'role': 'owner', 'active': 'students', 'rows': rows,
        'total': len(rows),
    })


@login_required
@role_required('owner')
def owner_staff(request):
    teachers = (Profile.objects.filter(role='teacher')
                .select_related('user', 'classroom'))
    return render(request, 'owner_staff.html', {
        'role': 'owner', 'active': 'staff',
        'teachers': teachers, 'staff': Staff.objects.all(),
    })


@login_required
@role_required('owner')
def owner_finance(request):
    today = timezone.localdate()
    collected_month = sum(p.amount for p in FeePayment.objects.filter(
        status='Active', date__year=today.year, date__month=today.month))
    expenses = list(Expense.objects.all())
    expenses_month = sum(e.amount for e in expenses
                         if e.date.year == today.year and e.date.month == today.month)
    outstanding = 0
    defaulters = []
    for s in (Student.objects.select_related('classroom')
              .prefetch_related('challans__payments', 'challans__lines')):
        bal = sum(c.balance for c in s.challans.all())
        outstanding += bal
        if bal > 0:
            defaulters.append({'student': s, 'outstanding': bal})
    defaulters.sort(key=lambda r: r['outstanding'], reverse=True)
    return render(request, 'owner_finance.html', {
        'role': 'owner', 'active': 'finance',
        'collected_month': collected_month, 'expenses_month': expenses_month,
        'net': collected_month - expenses_month, 'outstanding': outstanding,
        'defaulters': defaulters,
        'recent_payments': FeePayment.objects.select_related('student')[:10],
        'month_label': today.strftime('%B %Y'),
        'monthly_payroll': sum(s.monthly_salary
                               for s in Staff.objects.filter(active=True)),
        'payslips_month': Payslip.objects.filter(
            year=today.year, month=today.month).count(),
        'total_expenses': sum(e.amount for e in expenses),
    })


@login_required
@role_required('principal')
def principal_academics(request):
    """Read-only academic overview for the Principal: class-wise attendance
    (this month) and class-wise result from the most recent exam."""
    today = timezone.localdate()

    # Class-wise attendance % for the current month
    att = list(AttendanceRecord.objects.select_related('student')
               .filter(date__year=today.year, date__month=today.month))
    att_by_class = {}
    for r in att:
        cid = r.student.classroom_id
        pres, tot = att_by_class.get(cid, (0, 0))
        att_by_class[cid] = (pres + (1 if r.status == 'P' else 0), tot + 1)

    # Class-wise result from the most recent exam that has marks
    marks = list(Mark.objects.select_related('student', 'exam'))
    pct_by_student = {}
    latest_exam_name = ''
    if marks:
        latest_exam_id = max(m.exam_id for m in marks)
        em = [m for m in marks if m.exam_id == latest_exam_id]
        latest_exam_name = em[0].exam.name if em else ''
        agg = {}
        for m in em:
            o, t = agg.get(m.student_id, (0, 0))
            agg[m.student_id] = (o + m.marks_obtained, t + m.total_marks)
        for sid, (o, t) in agg.items():
            pct_by_student[sid] = round(o / t * 100) if t else 0

    rows = []
    for c in ClassRoom.objects.all():
        s_ids = list(Student.objects.filter(classroom=c).values_list('id', flat=True))
        pres, tot = att_by_class.get(c.id, (0, 0))
        cls_pcts = [pct_by_student[i] for i in s_ids if i in pct_by_student]
        rows.append({
            'room': c,
            'students': len(s_ids),
            'att_pct': round(pres / tot * 100) if tot else None,
            'avg': round(sum(cls_pcts) / len(cls_pcts)) if cls_pcts else None,
            'pass_pct': (round(sum(1 for p in cls_pcts if p >= 50) / len(cls_pcts) * 100)
                         if cls_pcts else None),
            'graded': len(cls_pcts),
        })
    return render(request, 'principal_academics.html', {
        'role': 'principal', 'active': 'academics',
        'rows': rows, 'latest_exam_name': latest_exam_name,
        'month_label': today.strftime('%B %Y'),
    })


@login_required
@role_required('principal')
def principal_staff(request):
    teachers = (Profile.objects.filter(role='teacher')
                .select_related('user', 'classroom'))
    return render(request, 'owner_staff.html', {
        'role': 'principal', 'active': 'staff',
        'teachers': teachers, 'staff': Staff.objects.all(),
    })


@login_required
@role_required('principal')
def principal_approvals(request):
    """Principal's decision queue: enrol/reject admissions at the Offer stage,
    and approve/reject fee concessions requested by Accounts."""
    if request.method == 'POST':
        action = request.POST.get('action')
        decider = request.user.get_full_name() or request.user.username

        if action in ('approve_admission', 'reject_admission'):
            a = Applicant.objects.filter(pk=request.POST.get('applicant_id'),
                                         stage='Offer').first()
            if a and action == 'approve_admission':
                a.stage = 'Enrolled'
                a.save(update_fields=['stage'])
                
                student = auto_convert_applicant_to_student(a)
                
                messages.success(
                    request, 'Admission approved for %s. Student record and login accounts created automatically!' % a.name)
                phone = (a.phone or '').strip()
                if sms_enabled('SMS_NOTIFY_ON_ADMISSION') and phone:
                    notify(
                        'Congratulations! %s has been enrolled at Roshni Public '
                        'School. Login credentials have been sent via SMS.'
                        % a.name,
                        to_phone=phone, recipients=a.parent_name or a.name,
                        msg_type='Admission')
            elif a:
                a.stage = 'Rejected'
                a.save(update_fields=['stage'])
                messages.success(request, 'Admission rejected for %s.' % a.name)

        elif action in ('approve_concession', 'reject_concession'):
            r = (ConcessionRequest.objects
                 .filter(pk=request.POST.get('req_id'), status='Pending')
                 .select_related('challan', 'challan__student').first())
            if r and action == 'approve_concession':
                ch = r.challan
                if r.kind == 'discount':
                    ch.discount = (ch.discount or 0) + r.amount
                    ch.discount_reason = r.label
                    ch.discount_by = decider
                else:
                    ch.scholarship = (ch.scholarship or 0) + r.amount
                    ch.scholarship_name = r.label
                ch.save()
                r.status = 'Approved'
                r.decided_by = decider
                r.decided_on = timezone.now()
                r.save(update_fields=['status', 'decided_by', 'decided_on'])
                _sync_fee_status(ch.student)
                _audit(request, '%s approved' % r.get_kind_display(),
                       'Rs %d for %s (%s)' % (r.amount, r.student.name, ch.label))
                messages.success(
                    request, '%s of Rs %d approved for %s (%s).'
                    % (r.get_kind_display(), r.amount, r.student.name, ch.label))
            elif r:
                r.status = 'Rejected'
                r.decided_by = decider
                r.decided_on = timezone.now()
                r.save(update_fields=['status', 'decided_by', 'decided_on'])
                messages.success(request, '%s request rejected.' % r.get_kind_display())

        elif action in ('approve_leave', 'reject_leave'):
            lv = (LeaveRequest.objects.filter(pk=request.POST.get('leave_id'),
                                              status='Pending')
                  .select_related('staff').first())
            if lv and action == 'approve_leave':
                lv.status = 'Approved'
                lv.decided_by = decider
                lv.save(update_fields=['status', 'decided_by'])
                d = lv.from_date
                while d <= lv.to_date:
                    StaffAttendance.objects.update_or_create(
                        staff=lv.staff, date=d, defaults={'status': 'L'})
                    d += datetime.timedelta(days=1)
                messages.success(request, 'Leave approved for %s (%d day%s).'
                                 % (lv.staff.name, lv.days,
                                    '' if lv.days == 1 else 's'))
            elif lv:
                lv.status = 'Rejected'
                lv.decided_by = decider
                lv.save(update_fields=['status', 'decided_by'])
                messages.success(request, 'Leave rejected for %s.' % lv.staff.name)

        elif action in ('approve_student_leave', 'reject_student_leave'):
            slv = (StudentLeave.objects.filter(pk=request.POST.get('leave_id'),
                                               status='Pending')
                   .select_related('student').first())
            if slv and action == 'approve_student_leave':
                slv.status = 'Approved'
                slv.decided_by = decider
                slv.save(update_fields=['status', 'decided_by'])
                # Mark the student on 'Leave' across the whole approved range.
                d = slv.from_date
                while d <= slv.to_date:
                    AttendanceRecord.objects.update_or_create(
                        student=slv.student, date=d,
                        defaults={'status': 'L', 'session': _current_session()})
                    d += datetime.timedelta(days=1)
                messages.success(request, 'Leave approved for %s (%d day%s).'
                                 % (slv.student.name, slv.days,
                                    '' if slv.days == 1 else 's'))
            elif slv:
                slv.status = 'Rejected'
                slv.decided_by = decider
                slv.save(update_fields=['status', 'decided_by'])
                messages.success(request, 'Leave rejected for %s.' % slv.student.name)
        return redirect('principal_approvals')

    pending_admissions = list(Applicant.objects.filter(stage='Offer'))
    pending_concessions = list(
        ConcessionRequest.objects.filter(status='Pending')
        .select_related('challan', 'challan__student', 'challan__student__classroom'))
    pending_leaves = list(
        LeaveRequest.objects.filter(status='Pending').select_related('staff'))
    pending_student_leaves = list(
        StudentLeave.objects.filter(status='Pending')
        .select_related('student', 'student__classroom'))
    recent_decisions = list(
        ConcessionRequest.objects.exclude(status='Pending')
        .select_related('challan', 'challan__student')[:8])
    return render(request, 'principal_approvals.html', {
        'role': 'principal', 'active': 'approvals',
        'pending_admissions': pending_admissions,
        'pending_concessions': pending_concessions,
        'pending_leaves': pending_leaves,
        'pending_student_leaves': pending_student_leaves,
        'recent_decisions': recent_decisions,
        'pending_total': (len(pending_admissions) + len(pending_concessions)
                          + len(pending_leaves) + len(pending_student_leaves)),
    })


@login_required
@role_required('parent', 'student')
def my_fees(request):
    profile = request.user.profile
    child, _kids = _active_child(request)
    challans = (list(child.challans.prefetch_related('payments', 'lines'))
                if child else [])
    payment_rows = (list(child.payments.select_related('challan'))
                    if child else [])
    school = School.objects.first()
    return render(request, 'my_fees.html', {
        'role': profile.role, 'active': 'fees', 'child': child,
        'challans': challans, 'payments': payment_rows,
        'total_payable': sum(c.net_payable for c in challans),
        'total_paid': sum(c.paid for c in challans),
        'outstanding': sum(c.balance for c in challans),
        'months_pending': sum(1 for c in challans if c.balance > 0),
        'online_enabled': bool(payments.available_gateways(school)),
    })


@login_required
@role_required('parent', 'student')
def my_fee_voucher(request, pk):
    profile = request.user.profile
    child, _kids = _active_child(request)
    challan = get_object_or_404(FeeChallan, pk=pk)
    if not _owns_student(profile, challan.student_id):
        return HttpResponseForbidden('You cannot view this voucher.')
    school = School.objects.first()
    return render(request, 'my_fee_voucher.html', {
        'role': profile.role, 'active': 'fees', 'child': child, 'c': challan,
        'can_pay_online': bool(payments.available_gateways(school))
        and challan.balance > 0,
    })


# ----------------------- Online fee payments (Section 3) -----------------------

def _gateway_mode(gateway):
    """Map a gateway code to the FeePayment.mode label used on receipts."""
    return {'bank': 'Bank', 'raast': 'RAAST', 'jazzcash': 'JazzCash',
            'easypaisa': 'Easypaisa'}.get(gateway, 'Card')


@login_required
@role_required('parent', 'student')
def pay_online(request, pk):
    """Parent-facing: start an online payment for one fee challan.

    Bank transfer is recorded as 'pending' for Accounts to verify (works with
    no internet). JazzCash/Easypaisa hand off to the provider's hosted page.
    """
    profile = request.user.profile
    child, _kids = _active_child(request)
    challan = get_object_or_404(FeeChallan, pk=pk)
    if not _owns_student(profile, challan.student_id):
        return HttpResponseForbidden('You cannot pay this challan.')
    student = challan.student
    school = School.objects.first()
    gateways = payments.available_gateways(school)
    balance = challan.balance

    if not gateways or balance <= 0:
        messages.info(request, 'Online payment is not available for this '
                      'challan. Please pay at the school office.')
        return redirect('my_fees')

    if request.method == 'POST':
        gateway = request.POST.get('gateway', '')
        if not payments.gateway_available(school, gateway):
            messages.error(request, 'That payment method is not available.')
            return redirect('pay_online', pk=pk)
        try:
            amount = int(request.POST.get('amount') or balance)
        except ValueError:
            amount = balance
        amount = max(1, min(amount, balance))     # never overpay the balance

        intent = OnlinePayment.objects.create(
            student=student, challan=challan, gateway=gateway, amount=amount,
            status='initiated')
        intent.ref = payments.make_reference(intent.id)
        intent.save(update_fields=['ref'])

        if gateway in ('bank', 'raast'):
            # Offline-verify methods: the parent tells us the transfer/RAAST
            # transaction reference; Accounts matches it against the bank/RAAST
            # statement and confirms. Works with no payment API.
            err = _upload_error(request.FILES.get('proof'), IMAGE_EXTS)
            if err:
                intent.delete()
                messages.error(request, err)
                return redirect('pay_online', pk=pk)
            ref = (request.POST.get('%s_ref' % gateway, '') or '').strip()
            intent.gateway_ref = ref
            intent.payer_note = (request.POST.get('note', '') or '').strip()[:200]
            if request.FILES.get('proof'):
                intent.proof = request.FILES['proof']
            intent.status = 'pending'
            intent.save()
            label = 'RAAST payment' if gateway == 'raast' else 'bank transfer'
            messages.success(
                request, 'Thank you. Your %s of Rs %d (ref %s) has been '
                'submitted and will be confirmed by the office once verified.'
                % (label, amount, intent.ref))
            return redirect('my_fees')

        # Gateway hosted checkout (needs a public HTTPS deployment + credentials)
        return_url = request.build_absolute_uri(
            reverse('payment_callback', args=[gateway]))
        try:
            if gateway == 'jazzcash':
                post_url, fields = payments.build_jazzcash_request(
                    school, intent, return_url)
            else:
                post_url, fields = payments.build_easypaisa_request(
                    school, intent, return_url)
        except Exception as exc:      # noqa: BLE001 - show a friendly message
            intent.status = 'failed'
            intent.save(update_fields=['status'])
            messages.error(request, 'Could not start the online payment (%s). '
                           'Please try again or pay at the office.' % exc)
            return redirect('my_fees')
        return render(request, 'payment_redirect.html', {
            'post_url': post_url, 'fields': fields,
            'gateway_label': dict(gateways).get(gateway, gateway),
        })

    return render(request, 'pay_online.html', {
        'role': profile.role, 'active': 'fees', 'child': child,
        'c': challan, 'balance': balance, 'gateways': gateways,
        'bank': payments.bank_details(school),
        'has_bank': any(g == 'bank' for g, _ in gateways),
        'raast': payments.raast_details(school),
        'has_raast': any(g == 'raast' for g, _ in gateways),
    })


@csrf_exempt
def payment_callback(request, gateway):
    """Where the payment gateway sends the customer back after checkout.

    Not login- or CSRF-protected on purpose: the caller is the payment gateway
    (a cross-site POST, and sometimes a server-to-server call with no session).
    Integrity comes from the provider's cryptographic signature, which is
    verified before any money is recorded. Idempotent — safe if hit twice."""
    school = School.objects.first()
    data = request.POST.dict() if request.method == 'POST' else request.GET.dict()
    if gateway == 'jazzcash':
        ok, _ref = payments.verify_jazzcash_callback(school, data)
        bill = data.get('pp_BillReference', '')
    elif gateway == 'easypaisa':
        ok, bill = payments.verify_easypaisa_callback(school, data)
    else:
        ok, bill = False, ''

    # Lock the intent row and re-check its status INSIDE the transaction so a
    # duplicated gateway callback (common on retries) can never double-record.
    # Cap the amount to the challan's live balance so an online payment can't
    # overpay if the office collected cash for the same challan meanwhile.
    with transaction.atomic():
        intent = (OnlinePayment.objects.select_for_update()
                  .filter(ref=bill).select_related('student', 'challan').first())
        if not intent:
            messages.error(request, 'Payment could not be matched. If money was '
                           'deducted, please contact the office with your reference.')
            return redirect('my_fees')
        if intent.status == 'paid':
            messages.info(request, 'This payment was already recorded.')
            return redirect('my_fees')

        if ok:
            challan = intent.challan
            pay_amount = (max(0, min(intent.amount, challan.balance))
                          if challan else intent.amount)
            payment = _record_fee_payment(
                intent.student, challan, pay_amount,
                mode=_gateway_mode(gateway),
                received_by='%s (online)' % dict(OnlinePayment.GATEWAYS).get(gateway, gateway),
                actor='online', send_alert=True)
            intent.status = 'paid'
            intent.payment = payment
            intent.gateway_ref = data.get('pp_TxnRefNo', '') or intent.gateway_ref
            intent.save()
            messages.success(request, 'Payment of Rs %d received. Receipt %s. '
                             'Thank you.' % (pay_amount, payment.receipt_no))
        else:
            intent.status = 'failed'
            intent.save(update_fields=['status'])
            messages.error(request, 'The payment did not complete. No money was '
                           'recorded. Please try again or pay at the office.')
    return redirect('my_fees')


@login_required
@role_required('finance')
def online_payments(request):
    """Accounts queue: verify bank transfers submitted by parents, and see the
    history of gateway payments."""
    if request.method == 'POST':
        action = request.POST.get('action')
        iid = _pk(request.POST.get('intent_id'))
        # Lock the row and re-check status inside the transaction so two
        # accountants can never both verify (and double-record) the same one.
        with transaction.atomic():
            intent = (OnlinePayment.objects.select_for_update()
                      .filter(pk=iid).select_related('student', 'challan').first())
            if not intent or intent.status != 'pending':
                messages.info(request, 'That payment has already been handled.')
                return redirect('online_payments')
            if action == 'approve':
                # Cap to the challan's live balance so verifying a bank transfer
                # can't overpay if the office already collected cash for it.
                challan = intent.challan
                pay_amount = (max(0, min(intent.amount, challan.balance))
                              if challan else intent.amount)
                payment = _record_fee_payment(
                    intent.student, challan, pay_amount,
                    mode=_gateway_mode(intent.gateway),
                    received_by=request.user.get_full_name() or request.user.username,
                    actor=request.user.username)
                intent.status = 'paid'
                intent.payment = payment
                intent.verified_by = request.user.username
                intent.save()
                messages.success(
                    request, 'Verified. Rs %d recorded for %s. Receipt %s.'
                    % (pay_amount, intent.student.name, payment.receipt_no))
            elif action == 'reject':
                intent.status = 'rejected'
                intent.verified_by = request.user.username
                intent.save(update_fields=['status', 'verified_by'])
                _audit(request, 'Online payment rejected',
                       '%s ref %s Rs%d' % (intent.student.name, intent.ref,
                                           intent.amount))
                messages.success(request, 'Payment marked as rejected.')
        return redirect('online_payments')

    pending = list(OnlinePayment.objects.filter(status='pending')
                   .select_related('student', 'challan'))
    recent = list(OnlinePayment.objects.exclude(status='pending')
                  .select_related('student', 'challan')[:30])
    return render(request, 'online_payments.html', {
        'role': 'finance', 'active': 'online_payments',
        'pending': pending, 'recent': recent,
    })


@login_required
@role_required('finance', 'admin')
def payment_proof(request, pk):
    """Serve a bank-transfer proof image to Accounts/Admin only (uploads are
    never exposed on a public /media/ URL)."""
    intent = get_object_or_404(OnlinePayment, pk=pk)
    if not intent.proof:
        raise Http404('No proof uploaded.')
    return FileResponse(intent.proof.open('rb'))


# ----------------------- Step 4: Operations modules -----------------------

ADMISSION_STAGES = ['Enquiry', 'Test', 'Offer', 'Enrolled']


def admission_apply(request):
    """PUBLIC online admission form (no login). A prospective parent submits an
    application which lands in the office's admissions pipeline at the Enquiry
    stage, tagged as an online application, with optional photo + document."""
    school = School.objects.first()
    if request.method == 'POST':
        # Honeypot: real users never fill a hidden 'website' field.
        if (request.POST.get('website', '') or '').strip():
            return render(request, 'admission_apply.html',
                          {'school': school, 'done': True, 'ref': ''})
        name = (request.POST.get('name', '') or '').strip()
        parent_name = (request.POST.get('parent_name', '') or '').strip()
        phone = (request.POST.get('phone', '') or '').strip()
        errors = []
        if not name:
            errors.append('Student name is required.')
        if not parent_name:
            errors.append('Parent/guardian name is required.')
        if not phone:
            errors.append('A contact phone number is required.')

        photo = request.FILES.get('photo')
        document = request.FILES.get('document')
        for f, kinds in ((photo, IMAGE_EXTS), (document, DOC_EXTS)):
            err = _upload_error(f, kinds)
            if err:
                errors.append(err)

        dob = None
        raw_dob = (request.POST.get('date_of_birth', '') or '').strip()
        if raw_dob:
            try:
                dob = datetime.date.fromisoformat(raw_dob)
            except ValueError:
                errors.append('Date of birth is not a valid date.')

        if errors:
            for e in errors:
                messages.error(request, e)
            return render(request, 'admission_apply.html', {
                'school': school, 'form': request.POST})

        a = Applicant.objects.create(
            name=name[:120], parent_name=parent_name[:120], phone=phone[:20],
            class_applied=(request.POST.get('class_applied', '') or '').strip()[:40],
            email=(request.POST.get('email', '') or '').strip()[:254],
            gender=(request.POST.get('gender', '') or '').strip()[:10],
            address=(request.POST.get('address', '') or '').strip()[:255],
            previous_school=(request.POST.get('previous_school', '') or '').strip()[:140],
            message=(request.POST.get('message', '') or '').strip()[:2000],
            date_of_birth=dob, photo=photo, document=document,
            source='Online', stage='Enquiry')
        a.ref = 'APP-%s-%04d' % (str(timezone.localdate().year)[-2:], a.id)
        a.save(update_fields=['ref'])
        return render(request, 'admission_apply.html',
                      {'school': school, 'done': True, 'ref': a.ref})

    return render(request, 'admission_apply.html', {'school': school})


@login_required
@role_required('admin')
def admissions(request):
    if request.method == 'POST':
        name = (request.POST.get('name', '') or '').strip()
        if name:
            Applicant.objects.create(
                name=name,
                class_applied=(request.POST.get('class_applied', '') or '').strip(),
                parent_name=(request.POST.get('parent_name', '') or '').strip(),
                phone=(request.POST.get('phone', '') or '').strip(),
                stage='Enquiry')
            messages.success(request, 'Enquiry added: %s.' % name)
        return redirect('admissions')

    adv = request.GET.get('advance')
    if adv:
        a = Applicant.objects.filter(pk=adv).first()
        if a and a.stage in ADMISSION_STAGES:
            i = ADMISSION_STAGES.index(a.stage)
            if i < ADMISSION_STAGES.index('Offer'):
                a.stage = ADMISSION_STAGES[i + 1]
                a.save(update_fields=['stage'])
                messages.success(request, '%s moved to %s.' % (a.name, a.stage))
            elif a.stage == 'Offer':
                messages.info(request, '%s is at Offer — the Principal approves or '
                              'rejects enrolment from the Approvals screen.' % a.name)
        return redirect('admissions')

    counts = {s: Applicant.objects.filter(stage=s).count() for s in ADMISSION_STAGES}
    return render(request, 'admissions.html', {
        'role': 'admin', 'active': 'admissions',
        'applicants': Applicant.objects.all(),
        'enquiry_count': counts['Enquiry'], 'test_count': counts['Test'],
        'offer_count': counts['Offer'], 'enrolled_count': counts['Enrolled'],
    })


@login_required
@role_required('admin')
def applicant_document(request, pk, kind):
    """Serve an online applicant's uploaded photo or document to the office."""
    a = get_object_or_404(Applicant, pk=pk)
    f = a.photo if kind == 'photo' else a.document
    if not f:
        raise Http404('No file uploaded.')
    return FileResponse(f.open('rb'))


def auto_convert_applicant_to_student(a):
    import re
    from django.contrib.auth.models import User
    from django.utils import timezone
    from core.models import Student, Profile, School, ClassRoom
    from .sms import notify
    
    if a.converted:
        return Student.objects.filter(name=a.name, guardian_phone=a.phone).first()
        
    digits = re.findall(r'\d+', a.class_applied or '')
    classroom = ClassRoom.objects.filter(name=digits[0]).first() if digits else None

    student = Student.objects.create(
        name=a.name, admission_no=_next_admission_no(), classroom=classroom,
        guardian_name=a.parent_name, guardian_phone=a.phone,
        father_name=a.parent_name, fee_status='Pending',
        admission_type='Fresh', status='Active',
        admission_date=timezone.localdate())
        
    a.converted = True
    a.save(update_fields=['converted'])
    
    std_slug = re.sub(r'[^a-zA-Z0-9]', '', a.name.lower())[:8]
    std_username = 'std_%s%d' % (std_slug, student.id)
    school = School.objects.first()
    default_pwd = school.default_password if school else 'school123'
    
    if not User.objects.filter(username=std_username).exists():
        std_user = User.objects.create_user(
            username=std_username, password=default_pwd, first_name=student.name)
        Profile.objects.create(
            user=std_user, role='student', student=student, must_change_password=True)
            
    prt_slug = re.sub(r'[^a-zA-Z0-9]', '', a.parent_name.lower())[:8] if a.parent_name else 'parent'
    prt_username = 'prt_%s%d' % (prt_slug, student.id)
    if not User.objects.filter(username=prt_username).exists():
        prt_user = User.objects.create_user(
            username=prt_username, password=default_pwd, first_name=a.parent_name or 'Parent')
        prt_profile = Profile.objects.create(
            user=prt_user, role='parent', student=student, must_change_password=True)
        prt_profile.children.add(student)
        
    phone = (a.phone or '').strip()
    if phone:
        sname = school.name if school else 'School'
        notify(
            '%s: Enrolment complete. Logins: Parent: %s, Student: %s. '
            'Pass: %s. Sign in at school dashboard.'
            % (sname, prt_username, std_username, default_pwd),
            to_phone=phone, recipients=a.parent_name or a.name,
            msg_type='Credentials')
            
    return student


@login_required
@role_required('admin')
def applicant_convert(request, pk):
    """One-click: turn an enrolled applicant into a Student record (no re-typing),
    then open the student for the office to complete the remaining details."""
    a = get_object_or_404(Applicant, pk=pk)
    if a.stage != 'Enrolled':
        messages.error(request, 'Only enrolled applicants can become students.')
        return redirect('admissions')
    if a.converted:
        messages.info(request, '%s already has a student record.' % a.name)
        return redirect('admissions')
        
    student = auto_convert_applicant_to_student(a)
    messages.success(
        request, 'Student record created for %s from the admission. '
        'Please complete the remaining details.' % a.name)
    return redirect('student_edit', pk=student.id)


@login_required
@role_required('admin')
def communication(request):
    if request.method == 'POST' and request.POST.get('action') == 'result_sms':
        # One-click result blast: SMS each student's overall result for the
        # chosen exam to their guardian. Reuses the school's notify channel.
        from .models import Exam, Mark, grade_for
        exam = Exam.objects.filter(pk=_pk(request.POST.get('exam'))).first()
        if not exam:
            messages.error(request, 'Please choose an exam first.')
            return redirect('communication')
        agg = {}
        for m in Mark.objects.filter(exam=exam).select_related('student'):
            d = agg.setdefault(m.student_id,
                               {'student': m.student, 'obt': 0, 'tot': 0})
            d['obt'] += m.marks_obtained
            d['tot'] += m.total_marks
        school = School.objects.first()
        sname = school.name if school else 'School'
        sent = failed = skipped = 0
        for d in agg.values():
            st = d['student']
            phone = (st.guardian_phone or '').strip()
            if not phone or d['tot'] <= 0:
                skipped += 1
                continue
            pct = round(d['obt'] * 100.0 / d['tot'], 1)
            text = ('%s: %s result (%s) — %s/%s = %s%% (Grade %s). See the '
                    'parent portal for the full report.'
                    % (sname, st.name, exam.name, d['obt'], d['tot'], pct,
                       grade_for(pct)))
            res = notify(text, to_phone=phone,
                         recipients=st.guardian_name or st.name, msg_type='Result')
            if 'Failed' in res:
                failed += 1
            else:
                sent += 1
        messages.success(
            request, 'Result SMS for %s: %d sent, %d failed, %d skipped '
            '(no phone or no marks).' % (exam.name, sent, failed, skipped))
        return redirect('communication')

    if request.method == 'POST':
        body = (request.POST.get('body', '') or '').strip()
        single = (request.POST.get('to_phone', '') or '').strip()
        audience = request.POST.get('recipients', 'All Parents')
        if body:
            targets = []  # list of (label, phone)
            if single:
                targets = [(single, single)]
                audience = single
            elif audience == 'Teachers / Staff':
                for st in Staff.objects.filter(active=True):
                    if st.phone:
                        targets.append((st.name, st.phone))
            else:
                audience = 'All Parents'
                seen = set()
                for s in Student.objects.filter(graduated=False):
                    ph = (s.guardian_phone or '').strip()
                    if ph and ph not in seen:
                        seen.add(ph)
                        targets.append((s.guardian_name or s.name, ph))
            if not targets:
                messages.error(request, 'No phone numbers found for %s.' % audience)
            else:
                sent = failed = 0
                for label, phone in targets:
                    status = send_sms(body, to_phone=phone, recipients=label,
                                      msg_type='Announcement')
                    if status == 'Failed':
                        failed += 1
                    else:
                        sent += 1
                note = ('logged to console' if settings.SMS_BACKEND == 'console'
                        else 'sent')
                if failed:
                    messages.error(
                        request, '%d message(s) to %s: %d %s, %d failed (see log).'
                        % (len(targets), audience, sent, note, failed))
                else:
                    messages.success(
                        request, '%d message(s) %s for %s.'
                        % (len(targets), note, audience))
        return redirect('communication')
    from .models import Exam
    return render(request, 'communication.html', {
        'role': 'admin', 'active': 'communication',
        'messages_log': SmsMessage.objects.all()[:50],
        'sms_backend': settings.SMS_BACKEND,
        'exams': Exam.objects.all()[:50],
    })


@login_required
@role_required('admin')
def transport(request):
    if request.method == 'POST':
        name = (request.POST.get('name', '') or '').strip()
        if name:
            try:
                fee = max(0, int(request.POST.get('fee', '0') or 0))
            except ValueError:
                fee = 0
            TransportRoute.objects.create(
                name=name,
                vehicle=(request.POST.get('vehicle', '') or '').strip(),
                driver=(request.POST.get('driver', '') or '').strip(), fee=fee)
            messages.success(request, 'Route added: %s.' % name)
        return redirect('transport')
    routes = TransportRoute.objects.all()
    # Count real riders (Student.route reverse relation), not the stale static
    # `students` field which was never kept in sync.
    return render(request, 'transport.html', {
        'role': 'admin', 'active': 'transport', 'routes': routes,
        'total_students': sum(r.riders.count() for r in routes),
    })


@login_required
@role_required('admin')
def library(request):
    today = timezone.localdate()
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'add_book':
            title = (request.POST.get('title', '') or '').strip()
            if title:
                try:
                    copies = max(1, int(request.POST.get('copies', '1') or 1))
                except ValueError:
                    copies = 1
                book = Book.objects.create(
                    title=title,
                    author=(request.POST.get('author', '') or '').strip(),
                    copies=copies, available=copies)
                book.code = 'LIB-%04d' % book.id
                book.save(update_fields=['code'])
                messages.success(request, 'Book added: %s.' % title)
        elif action == 'issue':
            book = Book.objects.filter(pk=request.POST.get('book')).first()
            borrower = (request.POST.get('borrower', '') or '').strip()
            if book and borrower and book.available > 0:
                due_raw = request.POST.get('due')
                try:
                    due = (datetime.date.fromisoformat(due_raw) if due_raw
                           else today + datetime.timedelta(days=14))
                except (ValueError, TypeError):
                    due = today + datetime.timedelta(days=14)
                IssuedBook.objects.create(book=book, student_name=borrower,
                                          issued_on=today, due_on=due)
                book.available -= 1
                book.save(update_fields=['available'])
                messages.success(request, 'Issued "%s" to %s.'
                                 % (book.title, borrower))
            else:
                messages.error(request,
                               'Could not issue: no copies available or borrower missing.')
        return redirect('library')

    ret = request.GET.get('return')
    if ret:
        iss = (IssuedBook.objects.filter(pk=ret, returned=False)
               .select_related('book').first())
        if iss:
            iss.returned = True
            iss.save(update_fields=['returned'])
            iss.book.available += 1
            iss.book.save(update_fields=['available'])
            messages.success(request, 'Returned "%s".' % iss.book.title)
            
            if iss.due_on < today:
                days_overdue = (today - iss.due_on).days
                fine_amount = days_overdue * 50
                
                # Only auto-bill when the free-text borrower name maps to
                # EXACTLY one student — a namesake (or no match) would otherwise
                # get billed the wrong fine, which is worse than not auto-billing.
                _matches = list(Student.objects.filter(name__iexact=iss.student_name)[:2])
                student = _matches[0] if len(_matches) == 1 else None
                if not student and fine_amount:
                    messages.info(request, 'Book was overdue (fine Rs %d), but borrower '
                                  '"%s" is not a unique student — add the fine manually.'
                                  % (fine_amount, iss.student_name))
                if student:
                    challan = FeeChallan.objects.filter(student=student).order_by('-year', '-month').first()
                    if challan and challan.status == 'Unpaid':
                        ChallanLine.objects.create(
                            challan=challan,
                            label='Library Overdue Fine: "%s"' % iss.book.title,
                            amount=fine_amount
                        )
                        _sync_fee_status(student)
                        messages.info(request, 'Overdue fine of Rs %d auto-billed to %s\'s current challan (%s).' 
                                      % (fine_amount, student.name, challan.label))
                    else:
                        challan = FeeChallan.objects.filter(student=student, year=today.year, month=today.month).first()
                        if not challan:
                            challan = FeeChallan.objects.create(
                                student=student, year=today.year, month=today.month, tuition=0,
                                due_date=today + datetime.timedelta(days=7)
                            )
                        ChallanLine.objects.create(
                            challan=challan,
                            label='Library Overdue Fine: "%s"' % iss.book.title,
                            amount=fine_amount
                        )
                        _sync_fee_status(student)
                        messages.info(request, 'Overdue fine of Rs %d auto-billed to %s (%s).' 
                                      % (fine_amount, student.name, challan.label))
        return redirect('library')

    books = list(Book.objects.all())
    issued_qs = IssuedBook.objects.filter(returned=False).select_related('book')
    issued = [{'obj': i, 'overdue': i.due_on < today} for i in issued_qs]
    return render(request, 'library.html', {
        'role': 'admin', 'active': 'library', 'books': books,
        'available_books': [b for b in books if b.available > 0],
        'issued': issued, 'total_copies': sum(b.copies for b in books),
        'available': sum(b.available for b in books),
        'overdue': sum(1 for i in issued if i['overdue']),
    })


@login_required
@role_required('admin')
def hostel(request):
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'add_room':
            name = (request.POST.get('name', '') or '').strip()
            if name:
                try:
                    cap = max(1, int(request.POST.get('capacity', '4') or 4))
                except ValueError:
                    cap = 4
                HostelRoom.objects.create(
                    name=name, capacity=cap,
                    warden=(request.POST.get('warden', '') or '').strip())
                messages.success(request, 'Hostel room added: %s.' % name)
        elif action == 'delete_room':
            room = HostelRoom.objects.filter(pk=request.POST.get('room_id')).first()
            if room:
                label = room.name
                room.delete()
                messages.success(
                    request, 'Removed %s; its residents are now unassigned.' % label)
        elif action == 'allocate':
            residents = Student.objects.filter(is_hostel=True, graduated=False)
            changed = 0
            for s in residents:
                val = request.POST.get('room_%d' % s.id, '')
                room = HostelRoom.objects.filter(pk=val).first() if val else None
                new_id = room.id if room else None
                if s.hostel_room_id != new_id:
                    s.hostel_room = room
                    s.save(update_fields=['hostel_room'])
                    changed += 1
            messages.success(
                request, 'Allocations updated for %d student(s).' % changed)
        return redirect('hostel')

    rooms = list(HostelRoom.objects.all())
    residents = list(
        Student.objects.filter(is_hostel=True, graduated=False)
        .select_related('classroom', 'hostel_room').order_by('name'))
    unassigned = sum(1 for s in residents if not s.hostel_room_id)
    return render(request, 'hostel.html', {
        'role': 'admin', 'active': 'hostel', 'rooms': rooms,
        'residents': residents, 'unassigned': unassigned,
        'total_residents': len(residents),
        'capacity_total': sum(r.capacity for r in rooms),
    })


@login_required
@role_required('admin')
def discipline(request):
    # Discipline is confidential to the office/admin only — no teacher, parent
    # or student access.
    profile = request.user.profile
    student_qs = Student.objects.filter(graduated=False)
    student_ids = set(student_qs.values_list('id', flat=True))

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'add':
            sid = request.POST.get('student')
            if sid and int(sid) in student_ids:
                student = Student.objects.get(pk=sid)
                desc = (request.POST.get('description', '') or '').strip()
                if desc:
                    date_raw = request.POST.get('date')
                    try:
                        d = (datetime.date.fromisoformat(date_raw) if date_raw
                             else timezone.localdate())
                    except (ValueError, TypeError):
                        d = timezone.localdate()
                    cat = request.POST.get('category', 'Behaviour')
                    sev = request.POST.get('severity', 'Minor')
                    valid_cat = {c for c, _ in DisciplineRecord.CATEGORIES}
                    valid_sev = {s for s, _ in DisciplineRecord.SEVERITIES}
                    reporter = profile.user.get_full_name() or profile.user.username
                    DisciplineRecord.objects.create(
                        student=student, date=d,
                        category=cat if cat in valid_cat else 'Behaviour',
                        severity=sev if sev in valid_sev else 'Minor',
                        description=desc,
                        action_taken=(request.POST.get('action_taken', '') or '').strip(),
                        reported_by=reporter)
                    messages.success(request, 'Record logged for %s.' % student.name)
                else:
                    messages.error(request, 'Please add a description.')
        elif action in ('resolve', 'reopen', 'delete'):
            rec = DisciplineRecord.objects.filter(pk=request.POST.get('rec_id')).first()
            if rec:
                if action == 'delete':
                    _audit(request, 'Discipline record deleted',
                           '%s (%s)' % (rec.student.name, rec.get_category_display()))
                    rec.delete()
                    messages.success(request, 'Record deleted.')
                else:
                    rec.status = 'Resolved' if action == 'resolve' else 'Open'
                    rec.save(update_fields=['status'])
                    messages.success(request, 'Record marked %s.' % rec.status)
        return redirect('discipline')

    records = list(
        DisciplineRecord.objects.filter(student_id__in=student_ids)
        .select_related('student', 'student__classroom'))
    students = list(student_qs.select_related('classroom')
                    .order_by('classroom__name', 'classroom__section', 'roll_no'))
    open_count = sum(1 for r in records if r.status == 'Open')
    return render(request, 'discipline.html', {
        'role': 'admin', 'active': 'discipline', 'is_office': True,
        'records': records, 'students': students,
        'open_count': open_count, 'total': len(records),
        'resolved_count': len(records) - open_count,
        'categories': DisciplineRecord.CATEGORIES,
        'severities': DisciplineRecord.SEVERITIES,
        'today': timezone.localdate().isoformat(),
    })


@login_required
@role_required('admin')
def id_cards(request):
    classes = list(ClassRoom.objects.all())
    sel = request.GET.get('class') or ''
    qs = Student.objects.filter(graduated=False).select_related('classroom')
    active_class = None
    if sel:
        qs = qs.filter(classroom_id=sel)
        active_class = ClassRoom.objects.filter(pk=sel).first()
    students = list(qs.order_by(
        'classroom__name', 'classroom__section', 'roll_no'))
    return render(request, 'id_cards.html', {
        'role': 'admin', 'active': 'idcards', 'classes': classes,
        'students': students, 'active_class': active_class, 'sel': sel,
        'school': School.objects.first(),
    })


def _csv_response(filename, header, rows):
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    writer.writerows(rows)
    resp = HttpResponse(buf.getvalue(), content_type='text/csv; charset=utf-8')
    resp['Content-Disposition'] = 'attachment; filename="%s"' % filename
    return resp


def _money(value):
    return 'Rs {:,}'.format(int(value or 0))


def _fee_totals():
    """Aggregate billed / collected / outstanding across all challans."""
    billed = collected = outstanding = 0
    for c in FeeChallan.objects.all():
        billed += c.net_payable
        collected += c.paid
        outstanding += c.balance
    return billed, collected, outstanding


def _exam_results_by_student(exam):
    """{student_id: (obtained, total)} for one exam."""
    agg = {}
    if not exam:
        return agg
    for sid, ob, tot in Mark.objects.filter(exam=exam).values_list(
            'student_id', 'marks_obtained', 'total_marks'):
        o, t = agg.get(sid, (0, 0))
        agg[sid] = (o + ob, t + tot)
    return agg


def _class_ranking(exam, classroom):
    """{student_id: (position, total_ranked)} for one exam within a class,
    ranked by overall percentage. Computed in a single query so it is cheap
    to call for every student when printing a whole class's report cards."""
    if not exam or not classroom:
        return {}
    agg = {}
    for sid, ob, tot in (Mark.objects
                         .filter(exam=exam, student__classroom=classroom)
                         .values_list('student_id', 'marks_obtained', 'total_marks')):
        o, t = agg.get(sid, (0, 0))
        agg[sid] = (o + ob, t + tot)
    ranked = sorted(((sid, o / t) for sid, (o, t) in agg.items() if t > 0),
                    key=lambda x: x[1], reverse=True)
    total = len(ranked)
    return {sid: (i + 1, total) for i, (sid, _) in enumerate(ranked)}


def _generate_report(request, report, fmt):
    today = timezone.localdate()
    school = School.objects.first()
    pass_mark = school.pass_mark if school else 40
    students_qs = (Student.objects.filter(graduated=False)
                   .select_related('classroom')
                   .order_by('classroom__name', 'classroom__section', 'roll_no'))

    if report == 'students' and fmt == 'csv':
        rows = [[s.name, str(s.classroom) if s.classroom else '',
                 s.admission_no, s.roll_no, s.guardian_name, s.guardian_phone,
                 s.fee_status, 'Yes' if s.is_hostel else 'No']
                for s in students_qs]
        return _csv_response(
            'students.csv',
            ['Name', 'Class', 'Admission No', 'Roll No', 'Guardian',
             'Phone', 'Fee Status', 'Hostel'], rows)

    if report == 'fees' and fmt == 'csv':
        rows = []
        for s in students_qs:
            net = paid = bal = 0
            for c in s.challans.all():
                net += c.net_payable
                paid += c.paid
                bal += c.balance
            rows.append([s.name, str(s.classroom) if s.classroom else '',
                         net, paid, bal, s.fee_status])
        return _csv_response(
            'fee_status.csv',
            ['Name', 'Class', 'Net Payable', 'Paid', 'Balance', 'Status'], rows)

    if report == 'attendance' and fmt == 'csv':
        buckets = {}
        for sid, status in AttendanceRecord.objects.values_list(
                'student_id', 'status'):
            b = buckets.setdefault(sid, {'P': 0, 'A': 0, 'L': 0})
            if status in b:
                b[status] += 1
        rows = []
        for s in students_qs:
            b = buckets.get(s.id, {'P': 0, 'A': 0, 'L': 0})
            total = b['P'] + b['A'] + b['L']
            pct = round(b['P'] / total * 100, 1) if total else 0
            rows.append([s.name, str(s.classroom) if s.classroom else '',
                         b['P'], b['A'], b['L'], total, pct])
        return _csv_response(
            'attendance_summary.csv',
            ['Name', 'Class', 'Present', 'Absent', 'Late', 'Total Days',
             'Attendance %'], rows)

    if report == 'results' and fmt == 'csv':
        exam, _ = _pick_exam(request)
        agg = _exam_results_by_student(exam)
        rows = []
        for s in students_qs:
            ob, tot = agg.get(s.id, (0, 0))
            if tot == 0:
                continue
            pct = round(ob / tot * 100, 1)
            rows.append([s.name, str(s.classroom) if s.classroom else '',
                         exam.name if exam else '', ob, tot, pct,
                         grade_for(pct),
                         'Pass' if pct >= pass_mark else 'Fail'])
        return _csv_response(
            'exam_results.csv',
            ['Name', 'Class', 'Exam', 'Obtained', 'Total', 'Percentage',
             'Grade', 'Result'], rows)

    if report == 'staff' and fmt == 'csv':
        rows = [[st.name, st.designation, st.phone, st.email,
                 st.basic_salary, st.allowances, st.monthly_salary,
                 'Yes' if st.active else 'No']
                for st in Staff.objects.all().order_by('name')]
        return _csv_response(
            'staff_directory.csv',
            ['Name', 'Designation', 'Phone', 'Email', 'Basic Salary',
             'Allowances', 'Monthly Salary', 'Active'], rows)

    if report == 'discipline' and fmt == 'csv':
        rows = [[r.date.isoformat(), r.student.name,
                 str(r.student.classroom) if r.student.classroom else '',
                 r.get_category_display(), r.severity, r.status,
                 r.reported_by, r.description]
                for r in DisciplineRecord.objects.select_related(
                    'student', 'student__classroom')]
        return _csv_response(
            'discipline_records.csv',
            ['Date', 'Student', 'Class', 'Category', 'Severity', 'Status',
             'Reported By', 'Description'], rows)

    if report == 'summary' and fmt in ('print', 'pdf'):
        billed, collected, outstanding = _fee_totals()
        defaulters = students_qs.filter(fee_status='Overdue').count()
        today_recs = AttendanceRecord.objects.filter(date=today)
        present = today_recs.filter(status='P').count()
        absent = today_recs.filter(status='A').count()
        att_total = today_recs.count()
        att_pct = round(present / att_total * 100) if att_total else 0
        exam, _ = _pick_exam(request)
        agg = _exam_results_by_student(exam)
        pcts = [ob / tot * 100 for ob, tot in agg.values() if tot]
        avg_pct = round(sum(pcts) / len(pcts), 1) if pcts else 0
        pass_pct = (round(sum(1 for p in pcts if p >= pass_mark) / len(pcts) * 100)
                    if pcts else 0)
        sections = [
            {'heading': 'Enrolment', 'rows': [
                ('Students', students_qs.count()),
                ('Classes', ClassRoom.objects.count()),
                ('Active staff', Staff.objects.filter(active=True).count())]},
            {'heading': 'Fees (all time)', 'rows': [
                ('Billed', _money(billed)), ('Collected', _money(collected)),
                ('Outstanding', _money(outstanding)),
                ('Overdue students', defaulters)]},
            {'heading': 'Attendance today', 'rows': [
                ('Present', present), ('Absent', absent),
                ('Marked', att_total), ('Rate', '%d%%' % att_pct)]},
            {'heading': 'Latest exam%s' % ((': ' + exam.name) if exam else ''),
             'rows': [('Average', '%s%%' % avg_pct),
                      ('Pass rate', '%d%%' % pass_pct)]},
        ]
        return render(request, 'report_print.html', {
            'role': 'admin', 'active': 'reports',
            'title': 'School Summary Report',
            'subtitle': '%s  |  Session %s' % (
                today.isoformat(), school.session if school else '-'),
            'sections': sections})

    if report == 'fees_summary' and fmt in ('print', 'pdf'):
        billed, collected, outstanding = _fee_totals()
        rate = round(collected / billed * 100) if billed else 0
        sections = [
            {'heading': 'Totals', 'rows': [
                ('Billed (net)', _money(billed)),
                ('Collected', _money(collected)),
                ('Outstanding', _money(outstanding)),
                ('Collection rate', '%d%%' % rate)]},
            {'heading': 'Students by status', 'rows': [
                ('Fully paid', students_qs.filter(fee_status='Paid').count()),
                ('Pending', students_qs.filter(fee_status='Pending').count()),
                ('Overdue', students_qs.filter(fee_status='Overdue').count())]},
        ]
        return render(request, 'report_print.html', {
            'role': 'admin', 'active': 'reports',
            'title': 'Fee Collection Summary',
            'subtitle': today.isoformat(), 'sections': sections})

    messages.error(request, 'Unknown report requested.')
    return redirect('reports')


@login_required
@role_required('admin')
def reports(request):
    report = request.GET.get('report')
    fmt = request.GET.get('format')
    if report and fmt:
        return _generate_report(request, report, fmt)
    return render(request, 'reports.html', {
        'role': 'admin', 'active': 'reports',
    })


# Custom student report builder: pick the columns and filters you want.
# key -> (column header, value function on the Student).
_STUDENT_FIELDS = [
    ('name', 'Name', lambda s: s.name),
    ('class', 'Class', lambda s: str(s.classroom) if s.classroom else ''),
    ('roll_no', 'Roll No', lambda s: s.roll_no),
    ('admission_no', 'Admission No', lambda s: s.admission_no),
    ('gender', 'Gender', lambda s: s.gender),
    ('date_of_birth', 'Date of Birth', lambda s: s.date_of_birth or ''),
    ('blood_group', 'Blood Group', lambda s: s.blood_group),
    ('guardian_name', 'Guardian', lambda s: s.guardian_name),
    ('guardian_phone', 'Guardian Phone', lambda s: s.guardian_phone),
    ('guardian_email', 'Guardian Email', lambda s: s.guardian_email),
    ('address', 'Address', lambda s: s.address),
    ('fee_status', 'Fee Status', lambda s: s.fee_status),
    ('is_hostel', 'Hostel', lambda s: 'Yes' if s.is_hostel else 'No'),
    ('route', 'Transport Route', lambda s: s.route.name if s.route else ''),
    ('admission_date', 'Admission Date', lambda s: s.admission_date or ''),
]


@login_required
@role_required('admin')
def report_builder(request):
    """A custom report builder over the student roster: choose exactly which
    columns to include and filter by class / status, then export as CSV."""
    fields = _STUDENT_FIELDS
    field_keys = [k for k, _, _ in fields]
    selected = request.GET.getlist('col') or ['name', 'class', 'roll_no',
                                               'guardian_phone', 'fee_status']
    selected = [k for k in selected if k in field_keys]
    class_id = _pk(request.GET.get('class'))
    status = request.GET.get('status', 'active')

    qs = Student.objects.select_related('classroom', 'route')
    if status == 'active':
        qs = qs.filter(status='Active', graduated=False)
    elif status == 'left':
        qs = qs.filter(status__in=['Left', 'Struck Off'])
    elif status == 'graduated':
        qs = qs.filter(Q(status='Graduated') | Q(graduated=True))
    if class_id:
        qs = qs.filter(classroom_id=class_id)
    qs = qs.order_by('classroom__name', 'classroom__section', 'roll_no', 'name')

    if request.GET.get('export') == 'csv' and selected:
        chosen = [(hdr, fn) for k, hdr, fn in fields if k in selected]
        header = [hdr for hdr, _ in chosen]
        rows = [[fn(s) for _, fn in chosen] for s in qs]
        return _csv_response('custom_students_report.csv', header, rows)

    # Preview (first 50 rows) for the on-screen builder.
    chosen = [(hdr, fn) for k, hdr, fn in fields if k in selected]
    preview_header = [hdr for hdr, _ in chosen]
    preview_rows = [[fn(s) for _, fn in chosen] for s in qs[:50]]
    return render(request, 'report_builder.html', {
        'role': 'admin', 'active': 'reports', 'fields': fields,
        'selected': selected, 'classes': ClassRoom.objects.all(),
        'class_id': class_id or '', 'status': status,
        'preview_header': preview_header, 'preview_rows': preview_rows,
        'total': qs.count(),
    })


# ----------------------- Step 5: more operations -----------------------

@login_required
@role_required('admin')
def students_list(request):
    base = Student.objects.select_related('classroom')
    active_q = base.filter(status='Active', graduated=False)
    left_q = base.filter(status__in=['Left', 'Struck Off'])
    grad_q = base.filter(Q(status='Graduated') | Q(graduated=True))
    counts = {'active': active_q.count(), 'left': left_q.count(),
              'graduated': grad_q.count(), 'all': base.count()}

    q = (request.GET.get('q', '') or '').strip()
    if q:
        # Search box (from the topbar) looks across every student by
        # name, admission number or guardian phone.
        tab = 'all'
        students = base.filter(
            Q(name__icontains=q) | Q(admission_no__icontains=q)
            | Q(guardian_phone__icontains=q))
    else:
        tab = request.GET.get('tab', 'active')
        if tab == 'left':
            students = left_q
        elif tab == 'graduated':
            students = grad_q
        elif tab == 'all':
            students = base.all()
        else:
            tab = 'active'
            students = active_q
    page, page_qs = _paginate(request, students, 25, keep=['tab', 'q'])
    return render(request, 'students_list.html', {
        'role': 'admin', 'active': 'students',
        'students': page, 'tab': tab, 'counts': counts, 'q': q,
        'page_qs': page_qs,
    })


@login_required
@role_required('admin')
def student_detail(request, pk):
    student = get_object_or_404(
        Student.objects.select_related('classroom', 'route', 'hostel_room'), pk=pk)

    if request.method == 'POST':
        action = request.POST.get('action')
        reason = (request.POST.get('reason', '') or '').strip()
        raw = request.POST.get('left_on', '')
        try:
            when = (datetime.date.fromisoformat(raw) if raw
                    else timezone.localdate())
        except ValueError:
            when = timezone.localdate()

        if action == 'mark_left':
            student.status = 'Left'
            student.left_on = when
            student.leaving_reason = reason
            student.save(update_fields=['status', 'left_on', 'leaving_reason'])
            messages.success(request, '%s marked as Left. Record kept in the archive.'
                             % student.name)
        elif action == 'mark_struck':
            student.status = 'Struck Off'
            student.left_on = when
            student.leaving_reason = reason
            student.save(update_fields=['status', 'left_on', 'leaving_reason'])
            messages.success(request, '%s marked as Struck off. Record kept.'
                             % student.name)
        elif action == 'mark_graduated':
            student.status = 'Graduated'
            student.graduated = True
            student.left_on = when
            student.save(update_fields=['status', 'graduated', 'left_on'])
            messages.success(request, '%s marked as Graduated. Record kept in alumni.'
                             % student.name)
        elif action == 'reactivate':
            student.status = 'Active'
            student.graduated = False
            student.left_on = None
            student.leaving_reason = ''
            student.save(update_fields=['status', 'graduated', 'left_on',
                                        'leaving_reason'])
            messages.success(request, '%s re-activated.' % student.name)
        elif action == 'issue_slc':
            cert = Certificate.objects.create(student=student, cert_type='Leaving')
            return redirect('certificate_view', pk=cert.id)
        elif action == 'create_login':
            std_user = _provision_student_login(student)
            par_user, par_new = _provision_parent_login(student)
            pwd = _school_default_password()
            if std_user or par_new:
                messages.success(
                    request, 'Logins ready — student %s%s. Password: %s.'
                    % (std_user or '(exists)',
                       (', parent %s' % par_user) if par_new else '', pwd))
            else:
                messages.info(request, 'This student already has logins.')
        elif action == 'reset_login':
            # Only reset a login that belongs to this student or a guardian.
            allowed_ids = set(
                Profile.objects.filter(role='student', student=student)
                .values_list('user_id', flat=True))
            allowed_ids |= set(
                Profile.objects.filter(role='parent', children=student)
                .values_list('user_id', flat=True))
            u = User.objects.filter(pk=request.POST.get('user_id')).first()
            if u and u.id in allowed_ids:
                u.set_password(_school_default_password())
                u.save(update_fields=['password'])
                _force_change(u)
                messages.success(
                    request, "Password for %s reset to the default." % u.username)
        return redirect('student_detail', pk=student.id)

    student_login = (Profile.objects.filter(role='student', student=student)
                     .select_related('user').first())
    guardian_logins = list(Profile.objects.filter(role='parent', children=student)
                           .select_related('user'))
    return render(request, 'student_detail.html', {
        'role': 'admin', 'active': 'students', 'st': student,
        'is_active': student.status == 'Active' and not student.graduated,
        'certs': student.certificates.all(),
        'exams': Exam.objects.filter(mark__student=student).distinct(),
        'student_login': student_login, 'guardian_logins': guardian_logins,
        'default_password': _school_default_password(),
        'today': timezone.localdate().isoformat(),
    })


def _student_form_data(request):
    """Parse the shared student form POST into model field values.
    Used by both student_add (create) and student_edit (update).
    Excludes name, admission_no and fee_status (handled by callers)."""
    def g(k):
        return (request.POST.get(k, '') or '').strip()

    def d(k):
        raw = request.POST.get(k, '')
        try:
            return datetime.date.fromisoformat(raw) if raw else None
        except ValueError:
            return None

    def b(k):
        return bool(request.POST.get(k))

    classroom = ClassRoom.objects.filter(pk=_pk(request.POST.get('classroom'))).first()
    route = TransportRoute.objects.filter(pk=_pk(request.POST.get('route'))).first()
    valid_adm = {a for a, _ in Student.ADMISSION_TYPES}
    valid_status = {s for s, _ in Student.STATUS_CHOICES}
    adm = g('admission_type')
    stt = g('status')
    try:
        custom_fee = max(0, int(request.POST.get('custom_fee') or 0))
    except ValueError:
        custom_fee = 0
    return {
        'classroom': classroom, 'roll_no': g('roll_no'),
        'custom_fee': custom_fee,
        'b_form': g('b_form'), 'religion': g('religion'),
        'nationality': g('nationality') or 'Pakistani',
        'date_of_birth': d('date_of_birth'), 'gender': g('gender'),
        'blood_group': g('blood_group'),
        'father_name': g('father_name'), 'mother_name': g('mother_name'),
        'father_cnic': g('father_cnic'),
        'father_occupation': g('father_occupation'),
        'father_phone': g('father_phone'), 'mother_phone': g('mother_phone'),
        'guardian_name': g('guardian_name'),
        'guardian_phone': g('guardian_phone'),
        'guardian_email': g('guardian_email'),
        'guardian_relation': g('guardian_relation'),
        'monthly_income': g('monthly_income'),
        'address': g('address'), 'permanent_address': g('permanent_address'),
        'city': g('city'),
        'emergency_name': g('emergency_name'),
        'emergency_phone': g('emergency_phone'),
        'emergency_relation': g('emergency_relation'),
        'admission_type': adm if adm in valid_adm else 'Fresh',
        'admission_date': d('admission_date'),
        'previous_school': g('previous_school'),
        'previous_class': g('previous_class'),
        'leaving_reason': g('leaving_reason'),
        'slc_received': b('slc_received'), 'slc_number': g('slc_number'),
        'board_reg_no': g('board_reg_no'),
        'doc_birth': b('doc_birth'), 'doc_cnic': b('doc_cnic'),
        'doc_slc': b('doc_slc'), 'doc_result': b('doc_result'),
        'doc_photos': b('doc_photos'),
        'medical_notes': g('medical_notes'), 'allergies': g('allergies'),
        'is_hostel': b('is_hostel'), 'route': route,
        'pickup_point': g('pickup_point'),
        'status': stt if stt in valid_status else 'Active',
    }


@login_required
@role_required('admin')
def student_edit(request, pk):
    student = get_object_or_404(Student, pk=pk)
    if request.method == 'POST':
        name = (request.POST.get('name', '') or '').strip()
        if name:
            data = _student_form_data(request)
            student.name = name
            adm_no = (request.POST.get('admission_no', '') or '').strip()
            if adm_no:
                student.admission_no = adm_no
            for k, v in data.items():
                setattr(student, k, v)
            student.save()
            photo = request.FILES.get('photo')
            if photo:
                perr = _upload_error(photo, IMAGE_EXTS, 4)
                if perr:
                    messages.error(request, 'Photo not saved: ' + perr)
                else:
                    student.photo = photo
                    student.save(update_fields=['photo'])
            messages.success(request, 'Student updated: %s.' % student.name)
            return redirect('student_detail', pk=student.id)
        messages.error(request, 'Student name is required.')
    return render(request, 'student_add.html', {
        'role': 'admin', 'active': 'students', 'mode': 'edit', 'st': student,
        'classes': ClassRoom.objects.all(),
        'routes': TransportRoute.objects.all(),
        'admission_types': Student.ADMISSION_TYPES,
        'statuses': Student.STATUS_CHOICES,
        'today': timezone.localdate().isoformat(),
    })


def _next_admission_no():
    """Next admission number as RPS-<year>-<seq>, derived from the HIGHEST
    existing number for the year — NOT Student.objects.count(), which repeats a
    number after any student is deleted and collides under bulk/concurrent
    creation (producing duplicate admission numbers)."""
    import re as _re
    year = timezone.localdate().year
    prefix = 'RPS-%d-' % year
    top = 0
    for adm in (Student.objects.filter(admission_no__startswith=prefix)
                .values_list('admission_no', flat=True)):
        m = _re.search(r'(\d+)$', adm or '')
        if m:
            top = max(top, int(m.group(1)))
    return '%s%04d' % (prefix, top + 1)


@login_required
@role_required('admin')
def student_add(request):
    if request.method == 'POST':
        name = (request.POST.get('name', '') or '').strip()
        if name:
            data = _student_form_data(request)
            adm_no = (request.POST.get('admission_no', '') or '').strip()
            student = Student.objects.create(
                name=name, admission_no=adm_no or _next_admission_no(),
                fee_status='Pending', **data)
            photo = request.FILES.get('photo')
            if photo:
                perr = _upload_error(photo, IMAGE_EXTS, 4)
                if perr:
                    messages.error(request, 'Photo not saved: ' + perr)
                else:
                    student.photo = photo
                    student.save(update_fields=['photo'])
            # Auto-create logins so nobody has to be added twice.
            std_user = _provision_student_login(student)
            par_user, par_new = _provision_parent_login(student)
            pwd = _school_default_password()
            parent_note = ('parent %s' % par_user if par_new
                           else 'added to existing parent %s' % par_user)
            messages.success(
                request, 'Student admitted: %s (%s). Logins created — student '
                '%s, %s. Default password: %s (each person can change it after '
                'signing in).' % (name, student.admission_no, std_user,
                                  parent_note, pwd))
            return redirect('student_detail', pk=student.id)
        messages.error(request, 'Student name is required.')

    return render(request, 'student_add.html', {
        'role': 'admin', 'active': 'students', 'mode': 'add', 'st': None,
        'classes': ClassRoom.objects.all(),
        'routes': TransportRoute.objects.all(),
        'admission_types': Student.ADMISSION_TYPES,
        'statuses': Student.STATUS_CHOICES,
        'today': timezone.localdate().isoformat(),
    })


IMPORT_COLUMNS = ['Name', 'Class', 'Roll No', 'Admission No', 'Gender',
                  'Date of Birth', 'Guardian Name', 'Guardian Phone', 'Address']


def _resolve_classroom(text):
    """Match a CSV class cell like '9-A', '9 A' or '9' to a ClassRoom."""
    t = (text or '').strip()
    if not t:
        return None
    norm = t.replace('_', '-').replace(' ', '-')
    if '-' in norm:
        name, _, sec = norm.partition('-')
        c = ClassRoom.objects.filter(name__iexact=name.strip(),
                                     section__iexact=sec.strip()).first()
        if c:
            return c
    return ClassRoom.objects.filter(name__iexact=t).first()


def _csv_reader(f):
    """Return (rows, cell) for an uploaded CSV. `cell(row, 'Some Header')` reads
    a column tolerant of header case/spacing. Shared by student & staff import."""
    try:
        text = f.read().decode('utf-8-sig')
    except UnicodeDecodeError:
        text = f.read().decode('latin-1')
    reader = csv.DictReader(io.StringIO(text))
    norm = {c.lower().replace(' ', ''): c for c in (reader.fieldnames or [])}

    def cell(row, key):
        col = norm.get(key.lower().replace(' ', ''))
        return (row.get(col, '') or '').strip() if col else ''
    return reader, cell


@login_required
@role_required('admin')
def students_import(request):
    """Bulk-admit students from a CSV so a new school can onboard hundreds at
    once instead of typing each form. Every imported student still gets their
    logins auto-created, exactly like a single admission."""
    if request.method == 'POST' and request.POST.get('action') == 'template':
        return _csv_response('students_import_template.csv', IMPORT_COLUMNS,
                             [['Ayaan Khan', '9-A', '1', '', 'Male',
                               '2011-05-14', 'Imran Khan', '0300-1234567',
                               'Lahore']])

    result = None
    if request.method == 'POST' and request.FILES.get('file'):
        f = request.FILES['file']
        ferr = _upload_error(f, {'csv'}, 5)
        if ferr:
            messages.error(request, 'File not accepted: ' + ferr)
            return redirect('students_import')
        reader, cell = _csv_reader(f)
        created = 0
        errors = []
        for i, row in enumerate(reader, start=2):   # row 1 is the header
            name = cell(row, 'Name')
            if not name:
                if any((v or '').strip() for v in row.values()):
                    errors.append('Row %d: missing Name — skipped.' % i)
                continue
            dob = None
            raw_dob = cell(row, 'Date of Birth')
            if raw_dob:
                try:
                    dob = datetime.date.fromisoformat(raw_dob)
                except ValueError:
                    errors.append('Row %d (%s): bad date "%s" — imported without it.'
                                  % (i, name, raw_dob))
            try:
                student = Student.objects.create(
                    name=name,
                    classroom=_resolve_classroom(cell(row, 'Class')),
                    roll_no=cell(row, 'Roll No'),
                    admission_no=(cell(row, 'Admission No')
                                  or _next_admission_no()),
                    gender=cell(row, 'Gender'), date_of_birth=dob,
                    guardian_name=cell(row, 'Guardian Name'),
                    guardian_phone=cell(row, 'Guardian Phone'),
                    address=cell(row, 'Address'),
                    fee_status='Pending', status='Active')
                _provision_student_login(student)
                _provision_parent_login(student)
                created += 1
            except Exception as exc:      # noqa: BLE001 - report, never crash import
                errors.append('Row %d (%s): %s' % (i, name, exc))
        if created:
            _audit(request, 'Students imported', '%d from CSV' % created)
        result = {'created': created, 'errors': errors,
                  'error_count': len(errors)}
        messages.success(request, '%d student(s) imported. %d row(s) skipped.'
                         % (created, len(errors)))

    return render(request, 'students_import.html', {
        'role': 'admin', 'active': 'students', 'columns': IMPORT_COLUMNS,
        'result': result, 'default_password': _school_default_password(),
    })


STAFF_IMPORT_COLUMNS = ['Name', 'Designation', 'Phone', 'Email',
                        'Basic Salary', 'Allowances']


@login_required
@role_required('admin')
def staff_import(request):
    """Bulk-add staff from a CSV — a new school can load its whole team at once.
    Logins are not created here; add a login per person from the Staff page when
    they need system access (each role has different permissions)."""
    if request.method == 'POST' and request.POST.get('action') == 'template':
        return _csv_response('staff_import_template.csv', STAFF_IMPORT_COLUMNS,
                             [['Adeel Anwar', 'Senior Teacher', '0300-1234567',
                               'adeel@school.edu.pk', '45000', '5000']])

    def num(v):
        try:
            return max(0, int((v or '').strip() or 0))
        except ValueError:
            return 0

    result = None
    if request.method == 'POST' and request.FILES.get('file'):
        f = request.FILES['file']
        ferr = _upload_error(f, {'csv'}, 5)
        if ferr:
            messages.error(request, 'File not accepted: ' + ferr)
            return redirect('staff_import')
        reader, cell = _csv_reader(f)
        created = 0
        errors = []
        for i, row in enumerate(reader, start=2):
            name = cell(row, 'Name')
            if not name:
                if any((v or '').strip() for v in row.values()):
                    errors.append('Row %d: missing Name — skipped.' % i)
                continue
            try:
                Staff.objects.create(
                    name=name, designation=cell(row, 'Designation'),
                    phone=cell(row, 'Phone'), email=cell(row, 'Email'),
                    basic_salary=num(cell(row, 'Basic Salary')),
                    allowances=num(cell(row, 'Allowances')))
                created += 1
            except Exception as exc:      # noqa: BLE001 - report, never crash import
                errors.append('Row %d (%s): %s' % (i, name, exc))
        if created:
            _audit(request, 'Staff imported', '%d from CSV' % created)
        result = {'created': created, 'errors': errors,
                  'error_count': len(errors)}
        messages.success(request, '%d staff member(s) imported. %d row(s) skipped.'
                         % (created, len(errors)))

    return render(request, 'staff_import.html', {
        'role': 'admin', 'active': 'staff', 'columns': STAFF_IMPORT_COLUMNS,
        'result': result,
    })


@login_required
@role_required('admin')
def classes_manage(request):
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'add_class':
            nm = (request.POST.get('name', '') or '').strip()
            sec = (request.POST.get('section', '') or '').strip() or 'A'
            try:
                fee = int(request.POST.get('monthly_fee') or 0)
            except ValueError:
                fee = 0
            if nm:
                ClassRoom.objects.create(name=nm, section=sec, monthly_fee=fee)
                messages.success(request, 'Class added: %s-%s.' % (nm, sec))
            else:
                messages.error(request, 'Class name is required.')
        elif action == 'edit_class':
            c = ClassRoom.objects.filter(pk=_pk(request.POST.get('class_id'))).first()
            if c:
                sec = (request.POST.get('section', '') or '').strip()
                if sec:
                    c.section = sec
                try:
                    c.monthly_fee = int(request.POST.get('monthly_fee') or c.monthly_fee)
                except ValueError:
                    pass
                c.save()
                messages.success(request, 'Class updated: %s.' % c)
        elif action == 'delete_class':
            c = ClassRoom.objects.filter(pk=_pk(request.POST.get('class_id'))).first()
            if c:
                if Student.objects.filter(classroom=c).exists():
                    messages.error(
                        request, 'Cannot delete %s - it still has students. '
                        'Move them to another class first.' % c)
                else:
                    label = str(c)
                    c.delete()
                    messages.success(request, 'Class deleted: %s.' % label)
        elif action == 'add_subject':
            c = ClassRoom.objects.filter(pk=_pk(request.POST.get('class_id'))).first()
            nm = (request.POST.get('subject', '') or '').strip()
            if c and nm:
                Subject.objects.create(classroom=c, name=nm)
                messages.success(request, 'Subject "%s" added to %s.' % (nm, c))
        elif action == 'delete_subject':
            Subject.objects.filter(pk=request.POST.get('subject_id')).delete()
            messages.success(request, 'Subject removed.')
        return redirect('classes_manage')

    classes = ClassRoom.objects.prefetch_related('subjects').order_by('name', 'section')
    rows = [{'c': c, 'count': Student.objects.filter(classroom=c).count(),
             'subjects': list(c.subjects.all())} for c in classes]
    return render(request, 'classes_manage.html', {
        'role': 'admin', 'active': 'classes', 'rows': rows,
    })


@login_required
@role_required('admin')
def timetable_manage(request):
    """Build/edit a class's weekly timetable. Each (day, period) is one slot;
    saving the same day+period again updates it."""
    classes = list(ClassRoom.objects.all())
    sel = request.POST.get('class_id') or request.GET.get('class')
    classroom = next((c for c in classes if str(c.id) == str(sel)), None) if sel else None
    if classroom is None:
        classroom = classes[0] if classes else None
    days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']

    if request.method == 'POST' and classroom:
        action = request.POST.get('action')
        if action == 'add':
            day = request.POST.get('day', 'Mon')
            try:
                period = max(1, int(request.POST.get('period') or 1))
            except ValueError:
                period = 1
            subject = (request.POST.get('subject', '') or '').strip()
            if day in days and subject:
                TimetableSlot.objects.update_or_create(
                    classroom=classroom, day=day, period=period,
                    defaults={
                        'start_time': (request.POST.get('start_time', '') or '').strip(),
                        'subject': subject,
                        'teacher': (request.POST.get('teacher', '') or '').strip()})
                messages.success(request, 'Slot saved: %s period %d - %s.'
                                 % (day, period, subject))
            else:
                messages.error(request, 'Pick a weekday and enter a subject.')
        elif action == 'delete':
            TimetableSlot.objects.filter(
                pk=request.POST.get('slot_id'), classroom=classroom).delete()
            messages.success(request, 'Slot removed.')
        return redirect('%s?class=%s' % (reverse('timetable_manage'), classroom.id))

    slots = list(TimetableSlot.objects.filter(classroom=classroom)) if classroom else []
    by_cell = {(s.day, s.period): s for s in slots}
    time_by_period = {}
    for s in slots:
        time_by_period.setdefault(s.period, s.start_time)
    rows = []
    for p in sorted(time_by_period):
        cells = [{'day': d, 'slot': by_cell.get((d, p))} for d in days]
        rows.append({'period': p, 'time': time_by_period.get(p, ''), 'cells': cells})
    subjects = list(Subject.objects.filter(classroom=classroom)) if classroom else []
    return render(request, 'timetable_manage.html', {
        'role': 'admin', 'active': 'timetable', 'classes': classes,
        'classroom': classroom, 'days': days, 'rows': rows,
        'subjects': subjects, 'periods': [1, 2, 3, 4, 5, 6, 7, 8],
    })


@login_required
@role_required('admin')
def school_settings(request):
    school = School.objects.first() or School.objects.create()

    # --- Fee heads (configurable extra charges) ---
    fee_action = request.POST.get('fee_action')
    if request.method == 'POST' and fee_action:
        if fee_action == 'add_head':
            name = (request.POST.get('head_name', '') or '').strip()
            try:
                amount = max(0, int(request.POST.get('head_amount') or 0))
            except ValueError:
                amount = 0
            freq = request.POST.get('head_frequency', 'monthly')
            valid_freq = {f for f, _ in FeeHead.FREQUENCY}
            if name:
                FeeHead.objects.create(
                    name=name, amount=amount,
                    frequency=freq if freq in valid_freq else 'monthly')
                _audit(request, 'Fee head added', '%s Rs%d' % (name, amount))
                messages.success(request, 'Fee head added: %s.' % name)
            else:
                messages.error(request, 'Fee head name is required.')
        elif fee_action == 'toggle_head':
            h = FeeHead.objects.filter(pk=_pk(request.POST.get('head_id'))).first()
            if h:
                h.active = not h.active
                h.save(update_fields=['active'])
                messages.success(request, '%s is now %s.'
                                 % (h.name, 'active' if h.active else 'inactive'))
        elif fee_action == 'delete_head':
            h = FeeHead.objects.filter(pk=_pk(request.POST.get('head_id'))).first()
            if h:
                messages.success(request, 'Fee head removed: %s.' % h.name)
                h.delete()
        return redirect('school_settings')

    # --- Testing tools: load demo data / start fresh (destructive) ---
    data_action = request.POST.get('data_action')
    if request.method == 'POST' and data_action:
        # These WIPE the whole database. Restrict to the platform owner
        # (superuser) so an ordinary school/office admin can never nuke a
        # tenant's data with one click.
        if not request.user.is_superuser:
            messages.error(request, 'Only the platform owner can load demo data '
                           'or reset the system.')
            return redirect('school_settings')
        from django.core.management import call_command
        if data_action == 'load_demo':
            call_command('seed', '--demo')
            messages.success(request, 'Demo data loaded. This replaced everything. '
                             'Sign in with a demo account (password: roshni123).')
            return redirect('login')
        elif data_action == 'reset_blank':
            call_command('flush', '--noinput')
            call_command('ensure_admin')
            messages.success(request, 'All data cleared. Sign in as '
                             'admin / admin123, then set up your school.')
            return redirect('login')
        return redirect('school_settings')

    # --- SMS / notifications ---
    sms_action = request.POST.get('sms_action')
    if request.method == 'POST' and sms_action:
        if sms_action == 'save_sms':
            backend = request.POST.get('sms_backend', 'console')
            valid = {b for b, _ in School.SMS_BACKENDS}
            school.sms_backend = backend if backend in valid else 'console'
            school.sms_country_code = (
                (request.POST.get('sms_country_code', '') or '').strip() or '+92')
            school.sms_http_url = (request.POST.get('sms_http_url', '') or '').strip()
            method = (request.POST.get('sms_http_method', 'GET') or 'GET').upper()
            school.sms_http_method = 'POST' if method == 'POST' else 'GET'
            school.sms_twilio_sid = (request.POST.get('sms_twilio_sid', '') or '').strip()
            school.sms_twilio_token = (request.POST.get('sms_twilio_token', '') or '').strip()
            school.sms_twilio_from = (request.POST.get('sms_twilio_from', '') or '').strip()
            school.notify_absent = bool(request.POST.get('notify_absent'))
            school.notify_payment = bool(request.POST.get('notify_payment'))
            school.notify_feedue = bool(request.POST.get('notify_feedue'))
            school.email_alerts_enabled = bool(request.POST.get('email_alerts_enabled'))
            school.email_from = (request.POST.get('email_from', '') or '').strip()[:120]
            school.save()
            _audit(request, 'SMS settings saved', school.sms_backend)
            messages.success(request, 'SMS settings saved (backend: %s).'
                             % school.get_sms_backend_display())
        elif sms_action == 'test_sms':
            phone = (request.POST.get('test_phone', '') or '').strip()
            if not phone:
                messages.error(request, 'Enter a phone number to test.')
            else:
                status = send_sms(
                    '%s: this is a test message from your school management '
                    'system.' % school.name, to_phone=phone,
                    recipients='Test', msg_type='Test')
                if status in ('Sent', 'Console'):
                    note = ('logged to the server console (test mode)'
                            if status == 'Console' else 'sent')
                    messages.success(request, 'Test message %s.' % note)
                else:
                    messages.error(request, 'Test failed. Check the SMS log on '
                                   'the Communication page for the error.')
        return redirect('school_settings')

    # --- WhatsApp notifications ---
    wa_action = request.POST.get('wa_action')
    if request.method == 'POST' and wa_action:
        if wa_action == 'save_whatsapp':
            channel = request.POST.get('notify_channel', 'sms')
            valid_ch = {c for c, _ in School.NOTIFY_CHANNELS}
            school.notify_channel = channel if channel in valid_ch else 'sms'
            school.whatsapp_enabled = bool(request.POST.get('whatsapp_enabled'))
            prov = request.POST.get('whatsapp_provider', 'twilio')
            valid_pr = {p for p, _ in School.WA_PROVIDERS}
            school.whatsapp_provider = prov if prov in valid_pr else 'twilio'
            school.whatsapp_from = (request.POST.get('whatsapp_from', '') or '').strip()
            school.whatsapp_token = (request.POST.get('whatsapp_token', '') or '').strip()
            school.whatsapp_phone_id = (
                request.POST.get('whatsapp_phone_id', '') or '').strip()
            school.save()
            _audit(request, 'WhatsApp settings saved',
                   'channel=%s enabled=%s' % (school.notify_channel,
                                              school.whatsapp_enabled))
            messages.success(request, 'WhatsApp settings saved.')
        elif wa_action == 'test_whatsapp':
            phone = (request.POST.get('test_phone', '') or '').strip()
            if not phone:
                messages.error(request, 'Enter a phone number to test.')
            else:
                from .sms import send_whatsapp
                status = send_whatsapp(
                    '%s: WhatsApp test message from your school management system.'
                    % school.name, to_phone=phone, recipients='Test',
                    msg_type='Test')
                if status in ('Sent', 'Console'):
                    note = ('logged only (test mode — turn WhatsApp on to send)'
                            if status == 'Console' else 'sent')
                    messages.success(request, 'WhatsApp test %s.' % note)
                else:
                    messages.error(request, 'WhatsApp test failed. Check the log '
                                   'on the Communication page for the error.')
        return redirect('school_settings')

    # --- Online fee payments ---
    pay_action = request.POST.get('pay_action')
    if request.method == 'POST' and pay_action == 'save_payments':
        s = school
        s.online_payments_enabled = bool(request.POST.get('online_payments_enabled'))
        s.pay_bank_enabled = bool(request.POST.get('pay_bank_enabled'))
        s.pay_raast_enabled = bool(request.POST.get('pay_raast_enabled'))
        s.pay_jazzcash_enabled = bool(request.POST.get('pay_jazzcash_enabled'))
        s.pay_easypaisa_enabled = bool(request.POST.get('pay_easypaisa_enabled'))
        for f in ('pay_bank_name', 'pay_bank_title', 'pay_bank_account',
                  'pay_bank_iban', 'pay_bank_instructions',
                  'pay_raast_id', 'pay_raast_instructions',
                  'pay_jazzcash_merchant', 'pay_jazzcash_password',
                  'pay_jazzcash_salt', 'pay_easypaisa_store', 'pay_easypaisa_hash'):
            setattr(s, f, (request.POST.get(f, '') or '').strip())
        # RAAST QR image upload (optional). Remove if the box is checked.
        if request.POST.get('pay_raast_qr_clear'):
            s.pay_raast_qr = None
        elif request.FILES.get('pay_raast_qr'):
            err = _upload_error(request.FILES['pay_raast_qr'], IMAGE_EXTS)
            if err:
                messages.error(request, err)
                return redirect('school_settings')
            s.pay_raast_qr = request.FILES['pay_raast_qr']
        s.save()
        _audit(request, 'Online payment settings saved',
               'enabled=%s' % s.online_payments_enabled)
        messages.success(request, 'Online payment settings saved.')
        return redirect('school_settings')

    if request.method == 'POST':
        nm = (request.POST.get('name', '') or '').strip()
        if nm:
            school.name = nm
        school.campus = (request.POST.get('campus', '') or '').strip()
        ses = (request.POST.get('session', '') or '').strip()
        if ses:
            school.session = ses
        fg = (request.POST.get('final_grade', '') or '').strip()
        if fg:
            school.final_grade = fg
        try:
            school.pass_mark = int(request.POST.get('pass_mark') or school.pass_mark)
        except ValueError:
            pass
        try:
            school.hostel_fee = int(request.POST.get('hostel_fee') or school.hostel_fee)
        except ValueError:
            pass
        try:
            school.late_fee_amount = max(0, int(
                request.POST.get('late_fee_amount') or school.late_fee_amount))
        except ValueError:
            pass
        try:
            school.late_fee_per_week = max(0, int(
                request.POST.get('late_fee_per_week') or school.late_fee_per_week))
        except ValueError:
            pass
        try:
            school.late_fee_max = max(0, int(
                request.POST.get('late_fee_max') or school.late_fee_max))
        except ValueError:
            pass

        def _color(field, current):
            v = (request.POST.get(field, '') or '').strip()
            # accept only #RGB / #RRGGBB
            if v.startswith('#') and len(v) in (4, 7):
                return v
            return current
        school.primary_color = _color('primary_color', school.primary_color)
        school.accent_color = _color('accent_color', school.accent_color)
        dp = (request.POST.get('default_password', '') or '').strip()
        if dp:
            school.default_password = dp
        logo = request.FILES.get('logo')
        if logo:
            err = _upload_error(logo, IMAGE_EXTS, 4)
            if err:
                messages.error(request, 'Logo not saved: ' + err)
            else:
                school.logo = logo
        if request.POST.get('remove_logo') and school.logo:
            school.logo.delete(save=False)
            school.logo = None
        # Branded Android app (.apk built with PWABuilder) for the download page.
        apk = request.FILES.get('app_apk')
        if apk:
            if not apk.name.lower().endswith('.apk'):
                messages.error(request, 'App not saved: please upload a .apk file.')
            elif apk.size > 80 * 1024 * 1024:
                messages.error(request, 'App not saved: .apk is larger than 80 MB.')
            else:
                if school.app_apk:
                    school.app_apk.delete(save=False)
                school.app_apk = apk
        if request.POST.get('remove_apk') and school.app_apk:
            school.app_apk.delete(save=False)
            school.app_apk = None
        school.save()
        messages.success(request, 'School settings saved.')
        return redirect('school_settings')
    return render(request, 'school_settings.html', {
        'role': 'admin', 'active': 'settings', 'school': school,
        'fee_heads': FeeHead.objects.all(),
        'head_frequencies': FeeHead.FREQUENCY,
        'sms_backends': School.SMS_BACKENDS,
        'notify_channels': School.NOTIFY_CHANNELS,
        'wa_providers': School.WA_PROVIDERS,
    })


@login_required
@role_required('admin')
def backup_download(request):
    """One-click backup: stream a consistent snapshot of the whole database so
    the school can keep its own copy (USB, email, cloud) without touching the
    server. Uses SQLite's online backup API, safe while the system is running."""
    import os
    import sqlite3
    import tempfile

    from django.db import connections
    engine = settings.DATABASES['default'].get('ENGINE', '')
    if 'sqlite3' not in engine:
        messages.error(request, 'Backup download is available for SQLite setups.')
        return redirect('school_settings')
    # Use the LIVE connection's database, not settings.DATABASES (which always
    # points at the master db.sqlite3). Otherwise a tenant admin's backup would
    # dump the master DB — every school's data. See tenancy-architecture.
    db_path = str(connections['default'].settings_dict['NAME'])

    tmp = tempfile.NamedTemporaryFile(suffix='.sqlite3', delete=False)
    tmp.close()
    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(tmp.name)
    try:
        with dst:
            src.backup(dst)
    finally:
        src.close()
        dst.close()
    with open(tmp.name, 'rb') as fh:
        data = fh.read()
    try:
        os.unlink(tmp.name)
    except OSError:
        pass

    school = School.objects.first()
    slug = ''.join(ch for ch in (school.name if school else 'school')
                   if ch.isalnum() or ch in ' -').strip().replace(' ', '_') or 'school'
    stamp = timezone.localtime().strftime('%Y%m%d_%H%M%S')
    fname = '%s_backup_%s.sqlite3' % (slug.lower(), stamp)
    _audit(request, 'Backup downloaded', fname)
    resp = HttpResponse(data, content_type='application/x-sqlite3')
    resp['Content-Disposition'] = 'attachment; filename="%s"' % fname
    return resp


# --- Guided restore (Section 5) ------------------------------------------

# A valid backup must contain these tables, or it is from a different system.
RESTORE_REQUIRED_TABLES = ('django_migrations', 'core_school',
                           'core_student', 'auth_user')


def _validate_backup(path):
    """Check an uploaded file is one of our SQLite backups and summarise it.
    Returns (ok, error_message, preview_dict)."""
    import sqlite3
    try:
        with open(path, 'rb') as fh:
            header = fh.read(16)
    except OSError:
        return False, 'The uploaded file could not be read.', {}
    if header != b'SQLite format 3\x00':
        return False, ('This is not a valid backup file. A backup is a '
                       '.sqlite3 file downloaded from this system.'), {}
    con = sqlite3.connect(path)
    try:
        cur = con.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {r[0] for r in cur.fetchall()}
        missing = [t for t in RESTORE_REQUIRED_TABLES if t not in tables]
        if missing:
            return False, ('This file does not look like a backup of this system '
                           '(missing: %s).' % ', '.join(missing)), {}

        def count(t):
            try:
                cur.execute('SELECT COUNT(*) FROM %s' % t)
                return cur.fetchone()[0]
            except sqlite3.Error:
                return 0

        preview = {
            'students': count('core_student'), 'staff': count('core_staff'),
            'users': count('auth_user'), 'payments': count('core_feepayment'),
            'school_name': '', 'session': '',
        }
        try:
            cur.execute('SELECT name, session FROM core_school LIMIT 1')
            row = cur.fetchone()
            if row:
                preview['school_name'], preview['session'] = row[0], row[1]
        except sqlite3.Error:
            pass
        return True, '', preview
    finally:
        con.close()


@login_required
@role_required('admin')
def restore_db(request):
    """Admin-only guided restore: upload a backup -> validate -> preview ->
    typed confirmation -> replace the database. A safety snapshot of the
    current data is taken automatically before anything is overwritten."""
    import os
    import shutil

    from django.db import connections
    engine = settings.DATABASES['default'].get('ENGINE', '')
    if 'sqlite3' not in engine:
        messages.error(request, 'Restore is available for SQLite setups.')
        return redirect('school_settings')
    # LIVE connection, not settings.DATABASES — so a tenant restores ITS OWN
    # file, never the master db.sqlite3 (which would destroy every school).
    db_path = str(connections['default'].settings_dict['NAME'])
    staging = os.path.join(os.path.dirname(db_path), 'restore_staging.sqlite3')

    if request.method == 'POST':
        step = request.POST.get('step')

        if step == 'upload':
            f = request.FILES.get('backup')
            if not f:
                messages.error(request, 'Choose a backup (.sqlite3) file first.')
                return redirect('restore_db')
            if f.size > 300 * 1024 * 1024:
                messages.error(request, 'That file is too large to be a backup.')
                return redirect('restore_db')
            with open(staging, 'wb') as out:
                for chunk in f.chunks():
                    out.write(chunk)
            ok, err, preview = _validate_backup(staging)
            if not ok:
                try:
                    os.unlink(staging)
                except OSError:
                    pass
                messages.error(request, err)
                return redirect('restore_db')
            request.session['restore_ready'] = True
            return render(request, 'restore.html', {
                'role': 'admin', 'active': 'settings', 'staged': True,
                'preview': preview, 'filename': f.name})

        if step == 'confirm':
            if not request.session.get('restore_ready') \
                    or not os.path.exists(staging):
                messages.error(request, 'Please upload a backup first.')
                return redirect('restore_db')
            if (request.POST.get('confirm_text', '') or '').strip().upper() \
                    != 'RESTORE':
                _ok, _e, preview = _validate_backup(staging)
                messages.error(request, 'Type RESTORE (in capitals) to confirm.')
                return render(request, 'restore.html', {
                    'role': 'admin', 'active': 'settings', 'staged': True,
                    'preview': preview, 'filename': 'the uploaded backup'})

            # 1) Safety snapshot of the CURRENT database, so a mistaken restore
            #    can be undone.
            import sqlite3
            backups_dir = os.path.join(os.path.dirname(db_path), 'backups')
            os.makedirs(backups_dir, exist_ok=True)
            stamp = timezone.localtime().strftime('%Y%m%d_%H%M%S')
            safety = os.path.join(backups_dir, 'before_restore_%s.sqlite3' % stamp)
            try:
                src = sqlite3.connect(db_path)
                dst = sqlite3.connect(safety)
                with dst:
                    src.backup(dst)
                src.close()
                dst.close()
            except Exception:      # noqa: BLE001 - snapshot is best-effort
                safety = ''
            _audit(request, 'Database restored',
                   'safety snapshot: %s' % (os.path.basename(safety) or 'none'))

            # 2) Swap the database file in. Close Django's connection first so
            #    the file is not locked, and clear any WAL sidecars.
            from django.db import connections
            connections.close_all()
            shutil.copyfile(staging, db_path)
            for suffix in ('-wal', '-shm'):
                side = db_path + suffix
                if os.path.exists(side):
                    try:
                        os.unlink(side)
                    except OSError:
                        pass
            try:
                os.unlink(staging)
            except OSError:
                pass

            # The restored database has its own users and sessions, so the
            # current login is gone — send the admin to sign in again.
            request.session.flush()
            return redirect('%s?restored=1' % reverse('login'))

    request.session.pop('restore_ready', None)
    return render(request, 'restore.html', {
        'role': 'admin', 'active': 'settings', 'staged': False})


@login_required
@role_required('admin')
def staff_list(request):
    def amt(field):
        try:
            return max(0, int(request.POST.get(field, '') or 0))
        except ValueError:
            return 0

    if request.method == 'POST':
        name = (request.POST.get('name', '') or '').strip()
        if name:
            staff = Staff.objects.create(
                name=name,
                designation=(request.POST.get('designation', '') or '').strip(),
                phone=(request.POST.get('phone', '') or '').strip(),
                email=(request.POST.get('email', '') or '').strip(),
                basic_salary=amt('basic_salary'), allowances=amt('allowances'))
            role = request.POST.get('login_role', '')
            valid_roles = {'teacher', 'finance', 'admin', 'principal', 'owner'}
            if request.POST.get('create_login') and role in valid_roles:
                classroom = ClassRoom.objects.filter(
                    pk=_pk(request.POST.get('login_class'))).first()
                uname = _provision_staff_login(staff, role, classroom)
                messages.success(
                    request, 'Staff added: %s. Login %s created (password: %s). '
                    'They can change it after signing in.'
                    % (name, uname, _school_default_password()))
            else:
                messages.success(request, 'Staff member added: %s.' % name)
        return redirect('staff_list')
    return render(request, 'staff_list.html', {
        'role': 'admin', 'active': 'staff', 'staff': Staff.objects.all(),
        'classes': ClassRoom.objects.all(),
        'login_roles': [('teacher', 'Teacher'), ('finance', 'Accountant / Finance'),
                        ('admin', 'Administrator (Office)'),
                        ('principal', 'Principal'), ('owner', 'Owner / Director')],
    })


@login_required
@role_required('admin')
def staff_attendance(request):
    today = timezone.localdate()
    staff = list(Staff.objects.filter(active=True))
    if request.method == 'POST':
        marked = 0
        for s in staff:
            status = request.POST.get('status_%d' % s.id)
            if status in ('P', 'A', 'L', 'H'):
                StaffAttendance.objects.update_or_create(
                    staff=s, date=today, defaults={'status': status})
                marked += 1
        messages.success(request, "Attendance saved for %d staff (%s)."
                         % (marked, today.strftime('%d %b %Y')))
        return redirect('staff_attendance')

    existing = {a.staff_id: a.status for a in
                StaffAttendance.objects.filter(date=today)}
    rows = [{'staff': s, 'status': existing.get(s.id, 'P')} for s in staff]
    present = sum(1 for a in existing.values() if a == 'P')
    return render(request, 'staff_attendance.html', {
        'role': 'admin', 'active': 'staff_attendance', 'rows': rows,
        'today': today, 'marked': len(existing), 'present': present,
        'total': len(staff),
    })


@login_required
@role_required('admin')
def payroll(request):
    today = timezone.localdate()
    year, month = today.year, today.month

    def amt(field):
        try:
            return max(0, int(request.POST.get(field, '') or 0))
        except ValueError:
            return 0

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'set_salary':
            s = Staff.objects.filter(pk=request.POST.get('staff_id')).first()
            if s:
                s.basic_salary = amt('basic_salary')
                s.allowances = amt('allowances')
                s.save(update_fields=['basic_salary', 'allowances'])
                messages.success(request, 'Salary updated for %s.' % s.name)
        elif action == 'generate_one':
            s = Staff.objects.filter(pk=request.POST.get('staff_id')).first()
            if s:
                Payslip.objects.update_or_create(
                    staff=s, year=year, month=month,
                    defaults={'basic': s.basic_salary, 'allowances': s.allowances,
                              'deductions': amt('deductions')})
                messages.success(request, 'Payslip generated for %s (%s %d).'
                                 % (s.name, FeeChallan.MONTHS[month], year))
        elif action == 'generate_all':
            made = 0
            for s in Staff.objects.filter(active=True):
                _, created = Payslip.objects.get_or_create(
                    staff=s, year=year, month=month,
                    defaults={'basic': s.basic_salary, 'allowances': s.allowances})
                if created:
                    made += 1
            messages.success(request, '%d payslip(s) generated for %s %d.'
                             % (made, FeeChallan.MONTHS[month], year))
        return redirect('payroll')

    slips = {p.staff_id: p for p in Payslip.objects.filter(year=year, month=month)}
    rows = []
    for s in Staff.objects.filter(active=True):
        rows.append({'staff': s, 'slip': slips.get(s.id)})
    total_monthly = sum(s.monthly_salary for s in Staff.objects.filter(active=True))
    generated_net = sum(p.net for p in slips.values())
    return render(request, 'payroll.html', {
        'role': 'admin', 'active': 'payroll', 'rows': rows,
        'month_label': '%s %d' % (FeeChallan.MONTHS[month], year),
        'total_monthly': total_monthly, 'generated_count': len(slips),
        'generated_net': generated_net, 'staff_total': len(rows),
    })


@login_required
def payslip_pdf(request, pk):
    profile = getattr(request.user, 'profile', None)
    role = profile.role if profile else None
    p = get_object_or_404(Payslip.objects.select_related('staff'), pk=pk)
    is_owner = p.staff.user_id == request.user.id
    if role not in ('admin', 'principal', 'owner') and not is_owner:
        return HttpResponseForbidden('You cannot view this payslip.')
    return render(request, 'payslip.html', {
        'role': role, 'active': '', 'p': p, 's': p.staff,
        'school': School.objects.first(),
    })


@login_required
@role_required('admin')
def staff_leave(request):
    if request.method == 'POST':
        s = Staff.objects.filter(pk=request.POST.get('staff_id')).first()
        f = (request.POST.get('from_date', '') or '').strip()
        t = (request.POST.get('to_date', '') or '').strip()
        if s and f and t:
            LeaveRequest.objects.create(
                staff=s, from_date=f, to_date=t,
                reason=(request.POST.get('reason', '') or '').strip(),
                applied_by=request.user.get_full_name() or request.user.username)
            messages.success(request, 'Leave request filed for %s. Sent to the '
                             'Principal for approval.' % s.name)
        else:
            messages.error(request, 'Pick a staff member and both dates.')
        return redirect('staff_leave')

    return render(request, 'staff_leave.html', {
        'role': 'admin', 'active': 'leave',
        'staff': Staff.objects.filter(active=True),
        'leaves': LeaveRequest.objects.select_related('staff').all(),
    })


@login_required
@role_required('admin', 'principal')
def staff_appraisal(request):
    """Record and review periodic staff performance appraisals."""
    if request.method == 'POST':
        s = Staff.objects.filter(pk=_pk(request.POST.get('staff_id'))).first()
        period = (request.POST.get('period', '') or '').strip()
        try:
            rating = int(request.POST.get('rating') or 3)
        except ValueError:
            rating = 3
        rating = max(1, min(5, rating))
        if s and period:
            Appraisal.objects.create(
                staff=s, period=period[:40], rating=rating,
                strengths=(request.POST.get('strengths', '') or '').strip()[:2000],
                improvements=(request.POST.get('improvements', '') or '').strip()[:2000],
                reviewer=request.user.get_full_name() or request.user.username)
            _audit(request, 'Appraisal recorded', '%s (%s)' % (s.name, period))
            messages.success(request, 'Appraisal saved for %s.' % s.name)
        else:
            messages.error(request, 'Pick a staff member and a review period.')
        return redirect('staff_appraisal')

    appraisals = list(Appraisal.objects.select_related('staff'))
    # Latest appraisal + average rating per staff member.
    summary = []
    for s in Staff.objects.filter(active=True):
        aps = [a for a in appraisals if a.staff_id == s.id]
        latest = aps[0] if aps else None
        avg = round(sum(a.rating for a in aps) / len(aps), 1) if aps else None
        summary.append({'staff': s, 'latest': latest, 'avg': avg, 'count': len(aps)})
    role = request.user.profile.role
    return render(request, 'staff_appraisal.html', {
        'role': role, 'active': 'appraisal',
        'staff': Staff.objects.filter(active=True), 'summary': summary,
        'appraisals': appraisals, 'ratings': Appraisal.RATINGS,
    })


# ----------------------- Exam datesheet & seating -----------------------

def _exam_sessions():
    """All academic sessions that have exams, newest first (for the switcher)."""
    seen = list(Exam.objects.exclude(session='')
                .values_list('session', flat=True).distinct())
    current = _current_session()
    if current not in seen:
        seen.append(current)
    return sorted(set(seen), reverse=True)


def _pick_exam(request):
    """Return (selected_exam, exams_in_session) scoped to one academic session.

    Defaults to the school's current session so results/marks from different
    years never blend. ?session=YYYY-YY lets an admin look back at a past year.
    """
    sel_session = (request.GET.get('session') or request.POST.get('session')
                   or _current_session())
    exams = list(Exam.objects.filter(session=sel_session).order_by('-id'))
    eid = request.GET.get('exam') or request.POST.get('exam')
    exam = next((e for e in exams if str(e.id) == str(eid)), None) if eid else None
    if exam is None and exams:
        exam = exams[0]
    return exam, exams


@login_required
@role_required('admin')
def roll_slips(request):
    """Printable roll-number slips (admit cards) for an exam: one per student
    with their datesheet and, if seating was generated, their room + seat."""
    from .models import Seat
    exam, exams = _pick_exam(request)
    school = School.objects.first()
    classes = list(ClassRoom.objects.all())
    cid = request.GET.get('class')
    sel_class = (next((c for c in classes if str(c.id) == str(cid)), None)
                 if cid else None)

    slips = []
    if exam:
        sched = list(ExamSchedule.objects.filter(exam=exam)
                     .select_related('classroom').order_by('date', 'time'))
        by_class = {}
        for row in sched:
            by_class.setdefault(row.classroom_id, []).append(row)
        seats = {s.student_id: s for s in
                 Seat.objects.filter(exam=exam).select_related('room')}
        target = [sel_class] if sel_class else [c for c in classes
                                                if c.id in by_class]
        for c in target:
            if not c:
                continue
            papers = by_class.get(c.id, [])
            for st in (Student.objects.filter(classroom=c, graduated=False)
                       .order_by('roll_no', 'name')):
                slips.append({'student': st, 'papers': papers,
                              'seat': seats.get(st.id)})
    return render(request, 'roll_slips.html', {
        'role': 'admin', 'active': 'exams', 'school': school,
        'exam': exam, 'exams': exams, 'classes': classes,
        'sel_class': sel_class, 'slips': slips,
        'session': _current_session(), 'sessions': _exam_sessions(),
    })


@login_required
@role_required('admin')
def exam_datesheet(request):
    exam, exams = _pick_exam(request)
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'add_exam':
            name = (request.POST.get('name', '') or '').strip()
            if name:
                e = Exam.objects.create(name=name, session=_current_session())
                messages.success(request, 'Exam created: %s.' % name)
                return redirect('%s?exam=%d' % (reverse('exam_datesheet'), e.id))
        elif action == 'add_row' and exam:
            cls = ClassRoom.objects.filter(pk=_pk(request.POST.get('classroom'))).first()
            subject = (request.POST.get('subject', '') or '').strip()
            date = (request.POST.get('date', '') or '').strip()
            if cls and subject and date:
                ExamSchedule.objects.create(
                    exam=exam, classroom=cls, subject=subject, date=date,
                    time=(request.POST.get('time', '') or '').strip())
                messages.success(request, 'Paper added: %s - %s.' % (cls, subject))
            else:
                messages.error(request, 'Pick class, subject and date.')
        elif action == 'delete_row':
            ExamSchedule.objects.filter(pk=request.POST.get('row_id')).delete()
            messages.success(request, 'Paper removed.')
        if exam:
            return redirect('%s?exam=%d' % (reverse('exam_datesheet'), exam.id))
        return redirect('exam_datesheet')

    rows = list(exam.schedule.select_related('classroom')) if exam else []
    sel_session = (request.GET.get('session') or _current_session())
    return render(request, 'exam_datesheet.html', {
        'role': 'admin', 'active': 'exams', 'exam': exam, 'exams': exams,
        'rows': rows, 'classes': ClassRoom.objects.all(),
        'sessions': _exam_sessions(), 'sel_session': sel_session,
    })


@login_required
@role_required('admin')
def exam_rooms(request):
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'add':
            name = (request.POST.get('name', '') or '').strip()
            if name:
                try:
                    cap = max(1, int(request.POST.get('capacity', '') or 30))
                except ValueError:
                    cap = 30
                ExamRoom.objects.create(name=name, capacity=cap)
                messages.success(request, 'Exam room added: %s.' % name)
        elif action == 'delete':
            ExamRoom.objects.filter(pk=request.POST.get('room_id')).delete()
            messages.success(request, 'Room removed.')
        return redirect('exam_rooms')
    return render(request, 'exam_rooms.html', {
        'role': 'admin', 'active': 'exams', 'rooms': ExamRoom.objects.all(),
    })


@login_required
@role_required('admin')
def exam_seating(request):
    exam, exams = _pick_exam(request)
    rooms = list(ExamRoom.objects.all())
    if request.method == 'POST' and request.POST.get('action') == 'generate' and exam:
        if not rooms:
            messages.error(request, 'Add at least one exam room first.')
        else:
            Seat.objects.filter(exam=exam).delete()
            students = list(Student.objects.select_related('classroom').order_by(
                'classroom__name', 'classroom__section', 'roll_no'))
            ri, seat_no, made = 0, 1, 0
            for s in students:
                while ri < len(rooms) and seat_no > rooms[ri].capacity:
                    ri += 1
                    seat_no = 1
                if ri >= len(rooms):
                    messages.error(request, 'Not enough capacity for all students. '
                                   'Add more rooms or capacity, then generate again.')
                    break
                Seat.objects.create(exam=exam, student=s, room=rooms[ri],
                                    seat_no=seat_no)
                seat_no += 1
                made += 1
            else:
                messages.success(request, 'Seating generated: %d students placed.' % made)
        if exam:
            return redirect('%s?exam=%d' % (reverse('exam_seating'), exam.id))
        return redirect('exam_seating')

    seats = (list(Seat.objects.filter(exam=exam)
                  .select_related('student', 'student__classroom', 'room'))
             if exam else [])
    by_room = {}
    for st in seats:
        by_room.setdefault(st.room, []).append(st)
    room_groups = [{'room': r, 'seats': by_room[r]}
                   for r in sorted(by_room, key=lambda x: x.name)]
    return render(request, 'exam_seating.html', {
        'role': 'admin', 'active': 'exams', 'exam': exam, 'exams': exams,
        'room_groups': room_groups, 'placed': len(seats), 'rooms_count': len(rooms),
    })


@login_required
@role_required('parent', 'student')
def my_datesheet(request):
    profile = request.user.profile
    child, _kids = _active_child(request)
    classroom = child.classroom if child else None
    exam = None
    if classroom:
        sched = (ExamSchedule.objects.filter(classroom=classroom)
                 .select_related('exam').order_by('-exam_id', 'date'))
        if sched:
            exam = sched[0].exam
    rows = (list(ExamSchedule.objects.filter(exam=exam, classroom=classroom)
                 .order_by('date')) if exam and classroom else [])
    seat = (Seat.objects.filter(exam=exam, student=child).select_related('room').first()
            if exam and child else None)
    return render(request, 'my_datesheet.html', {
        'role': profile.role, 'active': 'datesheet', 'child': child,
        'exam': exam, 'rows': rows, 'seat': seat,
        'is_student': profile.role == 'student',
    })


# ----------------------- Year-end promotion / session rollover ------------

def _grade_int(name, default=-1):
    try:
        return int(name)
    except (TypeError, ValueError):
        return default


def _next_grade_name(name):
    g = _grade_int(name, None)
    return str(g + 1) if g is not None else None


@login_required
@role_required('principal')
def promotion(request):
    school = School.objects.first()
    final = school.final_grade if school else '10'
    pass_mark = school.pass_mark if school else 40

    # Per-student latest-exam result (%), used to suggest promote/detain.
    # Only this session's exams count, so last year's marks never leak in.
    result = {}
    agg = {}
    for m in Mark.objects.filter(student__graduated=False,
                                 exam__session=_current_session()):
        agg.setdefault(m.student_id, {}).setdefault(m.exam_id, [0, 0])
        agg[m.student_id][m.exam_id][0] += m.marks_obtained
        agg[m.student_id][m.exam_id][1] += m.total_marks
    for sid, exams in agg.items():
        o, t = exams[max(exams)]
        result[sid] = round(o / t * 100) if t else 0

    if request.method == 'POST' and request.POST.get('action') == 'promote':
        # The Principal must explicitly approve — this is a bulk, year-changing
        # action, so it is never a single accidental click.
        if not request.POST.get('approve'):
            messages.error(request, 'Please tick “I approve this promotion” to '
                           'continue.')
            return redirect('promotion')

        new_session = (request.POST.get('session', '') or '').strip()
        promoted = detained = graduated = 0
        carried_arrears = 0
        created_classes = []

        def _student_balance(student):
            return sum(c.balance for c in student.challans.filter(
                carried_forward=False).prefetch_related('payments', 'lines'))

        for c in sorted(ClassRoom.objects.all(),
                        key=lambda x: _grade_int(x.name), reverse=True):
            for s in Student.objects.filter(classroom=c, graduated=False):
                if request.POST.get('decision_%d' % s.id, 'promote') == 'detain':
                    detained += 1
                    continue
                # Any unpaid dues stay on the student and are carried into the
                # new session's next challan (via _make_challan's arrears logic).
                carried_arrears += _student_balance(s)
                if str(c.name) == str(final):
                    s.graduated = True
                    s.status = 'Graduated'
                    s.left_on = timezone.localdate()
                    s.classroom = None
                    s.save(update_fields=['graduated', 'status', 'left_on',
                                          'classroom'])
                    graduated += 1
                else:
                    nxt = _next_grade_name(c.name)
                    if nxt is None:
                        continue
                    target = ClassRoom.objects.filter(name=nxt, section=c.section).first()
                    if target is None:
                        target = ClassRoom.objects.create(
                            name=nxt, section=c.section, monthly_fee=c.monthly_fee)
                        created_classes.append(str(target))
                    s.classroom = target
                    s.save(update_fields=['classroom'])
                    promoted += 1
        old_session = school.session if school else ''
        if school and new_session:
            school.session = new_session
            school.save(update_fields=['session'])
        _audit(request, 'Year-end promotion',
               '%d promoted, %d detained, %d graduated; arrears carried Rs%d; '
               'session %s -> %s' % (promoted, detained, graduated,
                                     carried_arrears, old_session,
                                     new_session or old_session))
        msg = ('Promotion complete: %d promoted, %d detained, %d graduated.'
               % (promoted, detained, graduated))
        if carried_arrears:
            msg += ' Rs %d in unpaid dues carried forward.' % carried_arrears
        if created_classes:
            msg += ' New classes: %s.' % ', '.join(created_classes)
        if new_session:
            msg += ' Session is now %s.' % new_session
        messages.success(request, msg)
        return redirect('promotion')

    groups = []
    for c in sorted(ClassRoom.objects.all(), key=lambda x: _grade_int(x.name, 9999)):
        students = list(Student.objects.filter(classroom=c, graduated=False)
                        .order_by('roll_no', 'name'))
        is_final = str(c.name) == str(final)
        nn = _next_grade_name(c.name)
        target = ('Graduating' if is_final
                  else (('%s-%s' % (nn, c.section)) if nn else '—'))
        new = (not is_final) and bool(nn) and not ClassRoom.objects.filter(
            name=nn, section=c.section).exists()
        rows = []
        for s in students:
            pct = result.get(s.id)
            has = s.id in result
            fail = has and pct < pass_mark
            rows.append({'s': s, 'pct': pct, 'has': has, 'fail': fail,
                         'suggest': 'detain' if fail else 'promote'})
        groups.append({'room': c, 'is_final': is_final, 'target': target,
                       'new': new, 'rows': rows, 'count': len(students)})

    suggest = ''
    if school and '-' in school.session:
        try:
            a, b = school.session.split('-')
            suggest = '%d-%s' % (int(a) + 1, str(int(b) + 1).zfill(2))
        except ValueError:
            suggest = ''
    return render(request, 'promotion.html', {
        'role': 'principal', 'active': 'promotion', 'groups': groups,
        'session': school.session if school else '—', 'final_grade': final,
        'pass_mark': pass_mark, 'suggest': suggest,
        'total_active': Student.objects.filter(graduated=False).count(),
        'graduated_count': Student.objects.filter(graduated=True).count(),
    })


@login_required
@role_required('admin')
def certificates(request):
    if request.method == 'POST':
        student = Student.objects.filter(pk=_pk(request.POST.get('student'))).first()
        cert_type = request.POST.get('cert_type', 'Leaving')
        if student:
            cert = Certificate.objects.create(student=student, cert_type=cert_type)
            return redirect('certificate_view', pk=cert.id)
        messages.error(request, 'Please select a student.')
        return redirect('certificates')
    return render(request, 'certificates.html', {
        'role': 'admin', 'active': 'certificates',
        'students': Student.objects.select_related('classroom').all(),
        'certs': Certificate.objects.select_related('student')[:20],
    })


@login_required
@role_required('admin')
def certificate_view(request, pk):
    cert = get_object_or_404(
        Certificate.objects.select_related('student', 'student__classroom'), pk=pk)
    return render(request, 'certificate.html', {
        'role': 'admin', 'active': 'certificates', 'cert': cert,
    })


@login_required
@role_required('admin')
def calendar(request):
    if request.method == 'POST':
        title = (request.POST.get('title', '') or '').strip()
        if title:
            raw = request.POST.get('date')
            try:
                d = datetime.date.fromisoformat(raw) if raw else timezone.localdate()
            except (ValueError, TypeError):
                d = timezone.localdate()
            CalendarEvent.objects.create(
                title=title, event_type=request.POST.get('event_type', 'Event'), date=d)
            messages.success(request, 'Event added: %s.' % title)
        return redirect('calendar')
    return render(request, 'calendar.html', {
        'role': 'admin', 'active': 'calendar', 'events': CalendarEvent.objects.all(),
    })


@login_required
@role_required('admin')
def inventory(request):
    if request.method == 'POST':
        name = (request.POST.get('name', '') or '').strip()
        if name:
            try:
                qty = max(0, int(request.POST.get('quantity', '0') or 0))
            except ValueError:
                qty = 0
            try:
                reorder = max(0, int(request.POST.get('reorder_level', '0') or 0))
            except ValueError:
                reorder = 0
            InventoryItem.objects.create(
                name=name, category=request.POST.get('category', 'Other'),
                quantity=qty, reorder_level=reorder)
            messages.success(request, 'Item added: %s.' % name)
        return redirect('inventory')
    items = list(InventoryItem.objects.all())
    return render(request, 'inventory.html', {
        'role': 'admin', 'active': 'inventory', 'items': items,
        'low': sum(1 for i in items if i.low), 'total': len(items),
    })


@login_required
@role_required('admin')
def visitors(request):
    if request.method == 'POST':
        name = (request.POST.get('name', '') or '').strip()
        if name:
            count = Visitor.objects.count() + 1
            Visitor.objects.create(
                name=name, purpose=(request.POST.get('purpose', '') or '').strip(),
                to_meet=(request.POST.get('to_meet', '') or '').strip(),
                pass_no='V-%03d' % (240 + count))
            messages.success(request, 'Gate pass issued to %s.' % name)
        return redirect('visitors')
    co = request.GET.get('checkout')
    if co:
        v = Visitor.objects.filter(pk=co, checked_out=False).first()
        if v:
            v.checked_out = True
            v.save(update_fields=['checked_out'])
            messages.success(request, '%s checked out.' % v.name)
        return redirect('visitors')
    visitor_list = list(Visitor.objects.all())
    return render(request, 'visitors.html', {
        'role': 'admin', 'active': 'visitors', 'visitors': visitor_list,
        'inside': sum(1 for v in visitor_list if not v.checked_out),
        'total': len(visitor_list),
    })


# ----------------------- Step 6: Users & Roles -----------------------

@login_required
@role_required('admin')
def users_list(request):
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'create':
            username = (request.POST.get('username', '') or '').strip()
            if not username:
                messages.error(request, 'Username is required.')
            elif User.objects.filter(username=username).exists():
                messages.error(request, 'That username is already taken.')
            else:
                pwd = ((request.POST.get('password', '') or '').strip()
                       or _school_default_password())
                try:
                    validate_password(pwd)
                except ValidationError as e:
                    messages.error(request, 'Weak password: ' + ' '.join(e.messages))
                    return redirect('users_list')
                role = request.POST.get('role', 'admin')
                user = User.objects.create_user(
                    username=username, password=pwd,
                    first_name=(request.POST.get('first_name', '') or '').strip())
                extra = {}
                if role == 'teacher':
                    extra['classroom'] = ClassRoom.objects.filter(
                        pk=_pk(request.POST.get('classroom'))).first()
                if role in ('parent', 'student'):
                    extra['student'] = Student.objects.filter(
                        pk=_pk(request.POST.get('student'))).first()
                Profile.objects.create(user=user, role=role,
                                       must_change_password=True, **extra)
                _audit(request, 'User created', '%s (%s)' % (username, role))
                messages.success(request, 'User created: %s (%s).' % (username, role))
        elif action == 'update_role':
            u = User.objects.filter(pk=_pk(request.POST.get('user_id'))).first()
            if u:
                prof = getattr(u, 'profile', None) or Profile(user=u)
                prof.role = request.POST.get('role', prof.role)
                prof.save()
                _audit(request, 'Role changed', '%s -> %s' % (u.username, prof.role))
                messages.success(request, 'Role updated for %s.' % u.username)
        elif action == 'reset_password':
            u = User.objects.filter(pk=_pk(request.POST.get('user_id'))).first()
            if u:
                dp = _school_default_password()
                u.set_password(dp)
                u.save(update_fields=['password'])
                _force_change(u)
                _audit(request, 'Password reset', u.username)
                messages.success(
                    request, 'Password for %s reset to the default.' % u.username)
        elif action == 'reset_password_sms':
            # Reset the login and text the new credentials to the family's phone
            # (student/parent accounts) so they can sign in and change it.
            u = User.objects.filter(pk=_pk(request.POST.get('user_id'))).first()
            if u:
                prof = getattr(u, 'profile', None)
                st = getattr(prof, 'student', None) if prof else None
                phone = (getattr(st, 'guardian_phone', '') or '').strip() if st else ''
                if not phone:
                    messages.error(
                        request, 'No guardian phone on file for %s, so the login '
                        'could not be sent by SMS.' % u.username)
                else:
                    dp = _school_default_password()
                    u.set_password(dp)
                    u.save(update_fields=['password'])
                    _force_change(u)
                    school = School.objects.first()
                    sname = school.name if school else 'School'
                    text = ('%s login — username: %s, password: %s. Please sign '
                            'in and change your password.'
                            % (sname, u.username, dp))
                    notify(text, to_phone=phone,
                           recipients=getattr(st, 'guardian_name', '') or u.username,
                           msg_type='Login')
                    _audit(request, 'Password reset + SMS', u.username)
                    messages.success(
                        request, 'Password for %s reset and the login sent by SMS.'
                        % u.username)
        elif action == 'toggle_active':
            u = User.objects.filter(pk=_pk(request.POST.get('user_id'))).first()
            if u and not u.is_superuser and u.id != request.user.id:
                u.is_active = not u.is_active
                u.save(update_fields=['is_active'])
                state = 'active' if u.is_active else 'disabled'
                _audit(request, 'Account %s' % state, u.username)
                messages.success(request, '%s is now %s.' % (u.username, state))
            else:
                messages.error(request, 'You cannot disable this account.')
        return redirect('users_list')

    page, page_qs = _paginate(
        request, User.objects.select_related(
            'profile', 'profile__student', 'profile__classroom')
        .order_by('username'), 30)
    return render(request, 'users_list.html', {
        'role': 'admin', 'active': 'users',
        'users': page, 'page_qs': page_qs,
        'roles': Profile.ROLE_CHOICES,
        'classes': ClassRoom.objects.all(),
        'students': Student.objects.select_related('classroom').all(),
        'default_password': _school_default_password(),
    })


@login_required
@role_required('admin')
def audit_log(request):
    """Accountability trail: who changed grades, fees, roles and discipline."""
    page, page_qs = _paginate(request, AuditLog.objects.all(), 50)
    return render(request, 'audit_log.html', {
        'role': 'admin', 'active': 'audit', 'logs': page,
        'total': page.paginator.count, 'page_qs': page_qs,
    })


# ----------------- Prototype-parity: Subjects, Timetable, Profile -----------

@login_required
@role_required('parent', 'student')
def my_subjects(request):
    profile = request.user.profile
    child, _kids = _active_child(request)
    classroom = child.classroom if child else None
    type_colors = {
        'Notes': ('#E3F1EC', '#0B5F4F'), 'Book': ('#E6EEF8', '#234E86'),
        'Slides': ('#EFEAF8', '#553285'), 'Past Paper': ('#F6EEDD', '#7A5712'),
    }
    subj_id = request.GET.get('subject')
    selected = None
    if subj_id and classroom:
        selected = Subject.objects.filter(pk=subj_id, classroom=classroom).first()

    if selected:
        materials = []
        for m in selected.materials.all():
            bg, fg = type_colors.get(m.mat_type, ('#EEF1F5', '#5A6675'))
            materials.append({'obj': m, 'bg': bg, 'fg': fg})
        return render(request, 'my_subjects.html', {
            'role': profile.role, 'active': 'subjects', 'child': child,
            'selected': selected, 'materials': materials,
        })

    palette = [('#E6EEF8', '#2C5FA8'), ('#E3F1EC', '#0E7C66'),
               ('#EFEAF8', '#7A4FB0'), ('#F6EEDD', '#B07D17'),
               ('#E2F1F4', '#1E7C8A'), ('#FBE7E2', '#C0432F')]
    subjects = []
    if classroom:
        for i, s in enumerate(Subject.objects.filter(classroom=classroom)):
            bg, fg = palette[i % len(palette)]
            subjects.append({'obj': s, 'count': s.materials.count(),
                             'bg': bg, 'fg': fg})
    return render(request, 'my_subjects.html', {
        'role': profile.role, 'active': 'subjects', 'child': child,
        'subjects': subjects, 'selected': None,
    })


@login_required
@role_required('parent', 'student')
def my_timetable(request):
    profile = request.user.profile
    child, _kids = _active_child(request)
    classroom = child.classroom if child else None
    days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']
    today_name = timezone.localdate().strftime('%a')
    slots = (list(TimetableSlot.objects.filter(classroom=classroom))
             if classroom else [])
    by_cell = {(s.day, s.period): s for s in slots}
    time_by_period = {}
    for s in slots:
        time_by_period.setdefault(s.period, s.start_time)
    rows = []
    for p in sorted(time_by_period):
        cells = [{'slot': by_cell.get((d, p)), 'today': d == today_name}
                 for d in days]
        rows.append({'time': time_by_period[p], 'cells': cells})
    return render(request, 'my_timetable.html', {
        'role': profile.role, 'active': 'timetable', 'child': child,
        'days': days, 'rows': rows, 'today_name': today_name,
    })


@login_required
@role_required('parent', 'student')
def my_profile(request):
    profile = request.user.profile
    child, _kids = _active_child(request)

    # A parent may self-service the child's CONTACT details (guardian name,
    # phone, address). Academic/identity fields stay office-only. Students can
    # view but not edit these.
    if (request.method == 'POST' and child and profile.role == 'parent'
            and request.POST.get('action') == 'update_contact'):
        child.guardian_name = (request.POST.get('guardian_name', '')
                               or child.guardian_name).strip()[:120]
        child.guardian_phone = (request.POST.get('guardian_phone', '')
                                or '').strip()[:20]
        child.guardian_email = (request.POST.get('guardian_email', '')
                                or '').strip()[:254]
        child.address = (request.POST.get('address', '') or '').strip()[:255]
        child.save(update_fields=['guardian_name', 'guardian_phone',
                                  'guardian_email', 'address'])
        _audit(request, 'Contact details updated',
               '%s (by parent)' % child.name)
        messages.success(request, 'Contact details updated.')
        return redirect('my_profile')

    initials = '?'
    age = None
    if child:
        parts = child.name.split()
        initials = ''.join(w[0] for w in parts[:2]).upper()
        if child.date_of_birth:
            t = timezone.localdate()
            d = child.date_of_birth
            age = t.year - d.year - ((t.month, t.day) < (d.month, d.day))
    notes = list(child.notes.all()[:20]) if child else []
    return render(request, 'my_profile.html', {
        'role': profile.role, 'active': 'profile', 'child': child,
        'initials': initials, 'age': age, 'notes': notes,
        'can_edit': profile.role == 'parent',
    })


@login_required
def student_photo(request, pk):
    student = get_object_or_404(Student, pk=pk)
    if not student.photo:
        raise Http404('No photo on file.')
    return FileResponse(open(student.photo.path, 'rb'))


def school_logo(request):
    """Serve the school's uploaded logo (used in the sidebar, login, docs)."""
    school = School.objects.first()
    if not school or not school.logo:
        raise Http404('No logo uploaded.')
    return FileResponse(school.logo.open('rb'))


@login_required
def raast_qr(request):
    """Serve the school's static RAAST QR image to signed-in users (shown on the
    parent's Pay-online page). Not exposed on a public /media/ URL."""
    school = School.objects.first()
    if not school or not school.pay_raast_qr:
        raise Http404('No RAAST QR uploaded.')
    return FileResponse(school.pay_raast_qr.open('rb'))


# ------------------------- PWA (installable app) -------------------------

def _abs_static(request, path):
    """Absolute URL for a static asset (manifest icons must be absolute so they
    resolve regardless of the tenant path prefix)."""
    from django.templatetags.static import static
    u = static(path)
    if u.startswith('http'):
        return u
    if not u.startswith('/'):
        u = '/' + u
    return request.build_absolute_uri(u)


def web_manifest(request):
    """Per-school PWA manifest so parents can install the portal as an app.
    Name/colours follow the tenant's branding; on the main/SaaS domain it stays
    the neutral Roshni SMS identity."""
    from django.http import JsonResponse
    school = School.objects.first()
    explicit = getattr(request, 'is_explicit_tenant', False)
    name = (school.name if (explicit and school) else 'Roshni SMS')
    theme = ((school.primary_color if school else None) or '#15294D')
    start = request.build_absolute_uri(reverse('dashboard'))
    # Generic Roshni icons are always offered as a fallback. If this school has
    # uploaded a logo, put it FIRST so PWABuilder makes a branded app icon —
    # the school's own logo becomes the launcher icon on the phone.
    icons = []
    if explicit and school and getattr(school, 'logo', None):
        try:
            logo_url = request.build_absolute_uri(school.logo.url)
            icons.append({'src': logo_url, 'sizes': '512x512',
                          'type': 'image/png', 'purpose': 'any'})
        except Exception:
            pass
    icons += [
        {'src': _abs_static(request, 'icons/icon-192.png'),
         'sizes': '192x192', 'type': 'image/png'},
        {'src': _abs_static(request, 'icons/icon-512.png'),
         'sizes': '512x512', 'type': 'image/png'},
        {'src': _abs_static(request, 'icons/icon-maskable-512.png'),
         'sizes': '512x512', 'type': 'image/png', 'purpose': 'maskable'},
    ]
    data = {
        'name': name,
        'short_name': (name[:12] or 'Roshni'),
        'start_url': start,
        'scope': start,
        'display': 'standalone',
        'orientation': 'portrait',
        'background_color': '#0B1120',
        'theme_color': theme,
        'icons': icons,
    }
    return JsonResponse(data, content_type='application/manifest+json')


def service_worker(request):
    """Service worker (served at the tenant root so its scope covers the whole
    portal). Network-first so content is never stale online, with a cached
    fallback offline; push handlers deliver web-push notifications."""
    from django.http import HttpResponse
    js = """
const CACHE = 'roshni-shell-v2';
self.addEventListener('install', e => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));

// Network-first: always fresh when online, fall back to cache offline.
self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;
  e.respondWith((async () => {
    try {
      const net = await fetch(e.request);
      const c = await caches.open(CACHE);
      c.put(e.request, net.clone());
      return net;
    } catch (err) {
      const cached = await caches.match(e.request);
      if (cached) return cached;
      throw err;
    }
  })());
});

// Web push: show the notification the server sent.
self.addEventListener('push', e => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch (_) { d = { body: e.data && e.data.text() }; }
  const title = d.title || 'School update';
  e.waitUntil(self.registration.showNotification(title, {
    body: d.body || '',
    icon: '/static/icons/icon-192.png',
    badge: '/static/icons/icon-192.png',
    data: { url: d.url || '/' }
  }));
});

// Focus/open the app when a notification is tapped.
self.addEventListener('notificationclick', e => {
  e.notification.close();
  const url = (e.notification.data && e.notification.data.url) || '/';
  e.waitUntil((async () => {
    const all = await clients.matchAll({ type: 'window', includeUncontrolled: true });
    for (const c of all) { if ('focus' in c) return c.focus(); }
    if (clients.openWindow) return clients.openWindow(url);
  })());
});
"""
    resp = HttpResponse(js, content_type='application/javascript')
    resp['Service-Worker-Allowed'] = '/'
    resp['Cache-Control'] = 'no-cache'
    return resp


def assetlinks(request):
    """Digital Asset Links, served at the bare-domain /.well-known/assetlinks.json.
    Verifies every school's Android (TWA) app so it opens full-screen without a
    browser address bar. One file covers all schools on this domain — the list
    comes from settings.TWA_ASSETLINKS (env ROSHNI_TWA_ASSETLINKS). Public, no
    login, no tenant scope (it must live on the root domain)."""
    from django.conf import settings
    from django.http import JsonResponse
    statements = []
    for entry in getattr(settings, 'TWA_ASSETLINKS', []) or []:
        pkg = entry.get('package')
        fps = entry.get('sha256')
        if not pkg or not fps:
            continue
        if isinstance(fps, str):
            fps = [fps]
        statements.append({
            'relation': ['delegate_permission/common.handle_all_urls'],
            'target': {'namespace': 'android_app', 'package_name': pkg,
                       'sha256_cert_fingerprints': fps},
        })
    return JsonResponse(statements, safe=False,
                        content_type='application/json')


def app_download(request):
    """A friendly 'Get the app' page for a school's portal: the Download App
    button for the school's branded .apk (if uploaded) plus install steps, and
    the browser 'Install app' (PWA) route as an always-available alternative."""
    school = School.objects.first()
    explicit = getattr(request, 'is_explicit_tenant', False)
    apk_url = ''
    if explicit and school and getattr(school, 'app_apk', None):
        try:
            apk_url = school.app_apk.url
        except Exception:
            apk_url = ''
    return render(request, 'app_download.html', {
        'school': school if explicit else None,
        'apk_url': apk_url,
    })


@login_required
def push_subscribe(request):
    """Save (or refresh) the current browser's Web Push subscription."""
    from django.http import JsonResponse
    if request.method != 'POST':
        return JsonResponse({'ok': False}, status=405)
    from .models import PushSubscription
    try:
        data = json.loads((request.body or b'').decode() or '{}')
    except Exception:
        return JsonResponse({'ok': False, 'error': 'bad json'}, status=400)
    endpoint = data.get('endpoint')
    keys = data.get('keys') or {}
    if not endpoint or not keys.get('p256dh') or not keys.get('auth'):
        return JsonResponse({'ok': False, 'error': 'incomplete'}, status=400)
    PushSubscription.objects.update_or_create(
        endpoint=endpoint,
        defaults={'user': request.user, 'p256dh': keys['p256dh'],
                  'auth': keys['auth']})
    return JsonResponse({'ok': True})


@login_required
def push_test(request):
    """Send a test push to the signed-in user's own browsers (self-check)."""
    from django.http import JsonResponse
    from .push import send_web_push
    n = send_web_push([request.user], 'Test notification',
                      'Push notifications are working. 🎉',
                      url=request.build_absolute_uri(reverse('dashboard')))
    return JsonResponse({'ok': True, 'sent': n})


@login_required
def profile_photo(request, pk):
    """Serve a user's avatar."""
    prof = Profile.objects.filter(user_id=pk).first()
    if not prof or not prof.photo:
        raise Http404('No photo.')
    return FileResponse(prof.photo.open('rb'))


@login_required
def account(request):
    """Every user manages their own account: profile picture + password link.
    An admin may also manage another user's photo via ?user=<id>."""
    target = request.user
    is_admin = getattr(getattr(request.user, 'profile', None), 'role', '') == 'admin'
    uid = _pk(request.POST.get('user_id') or request.GET.get('user'))
    if is_admin and uid:
        other = User.objects.filter(pk=uid).first()
        if other:
            target = other
    prof = getattr(target, 'profile', None)

    if request.method == 'POST' and prof:
        if request.POST.get('remove_photo') and prof.photo:
            prof.photo.delete(save=False)
            prof.photo = None
            prof.save(update_fields=['photo'])
            messages.success(request, 'Photo removed.')
        else:
            photo = request.FILES.get('photo')
            err = _upload_error(photo, IMAGE_EXTS, 4)
            if err:
                messages.error(request, err)
            elif photo:
                prof.photo = photo
                prof.save(update_fields=['photo'])
                messages.success(request, 'Profile picture updated.')
        dest = reverse('account')
        return redirect('%s?user=%d' % (dest, target.id) if target != request.user
                        else dest)

    return render(request, 'account.html', {
        'role': getattr(getattr(request.user, 'profile', None), 'role', ''),
        'active': 'account', 'target': target, 'prof': prof,
        'is_self': target == request.user,
    })


# ============== Assignments & Quizzes (functional) ==============

@login_required
@role_required('parent', 'student')
def my_assignments(request):
    profile = request.user.profile
    child, _kids = _active_child(request)
    classroom = child.classroom if child else None
    is_student = profile.role == 'student'

    # ---------- Parent: subject-wise progress summary only ----------
    if not is_student:
        summary = []
        if classroom and child:
            done_ids = set(Submission.objects.filter(student=child)
                           .values_list('assignment_id', flat=True))
            subj_map = {}
            for a in Assignment.objects.filter(classroom=classroom):
                name = a.subject.name if a.subject else 'General'
                rec = subj_map.setdefault(name, [0, 0])
                rec[0] += 1
                if a.id in done_ids:
                    rec[1] += 1
            for name, (total, done) in subj_map.items():
                summary.append({'subject': name, 'total': total,
                                'done': done, 'pending': total - done})
        return render(request, 'my_assignments.html', {
            'role': profile.role, 'active': 'assignments', 'child': child,
            'is_student': False, 'summary': summary, 'assignment': None,
        })

    # ---------- Student: one assignment (download brief + upload/edit) -------
    aid = request.GET.get('id')
    if aid and classroom:
        assignment = Assignment.objects.filter(pk=aid, classroom=classroom).first()
        if assignment:
            submission = Submission.objects.filter(
                assignment=assignment, student=child).first()
            if request.method == 'POST':
                up = request.FILES.get('file')
                text = (request.POST.get('answer_text', '') or '').strip()
                serr = _upload_error(up, DOC_EXTS)
                if serr:
                    messages.error(request, serr)
                    return redirect('%s?id=%s' % (request.path, assignment.id))
                if submission is None:
                    submission = Submission(assignment=assignment, student=child)
                if up:
                    submission.file = up
                submission.answer_text = text
                submission.status = 'Submitted'
                submission.grade = ''
                submission.save()
                messages.success(request, 'Your work has been submitted.')
                return redirect('%s?id=%s' % (request.path, assignment.id))
            return render(request, 'my_assignments.html', {
                'role': profile.role, 'active': 'assignments', 'child': child,
                'is_student': True, 'assignment': assignment,
                'submission': submission,
            })

    # ---------- Student: list ----------
    assignments = []
    if classroom and child:
        subs = {s.assignment_id: s
                for s in Submission.objects.filter(student=child)}
        for a in Assignment.objects.filter(classroom=classroom):
            assignments.append({'obj': a, 'submission': subs.get(a.id)})
    return render(request, 'my_assignments.html', {
        'role': profile.role, 'active': 'assignments', 'child': child,
        'is_student': True, 'assignments': assignments, 'assignment': None,
    })


@login_required
@role_required('parent', 'student')
def my_quizzes(request):
    profile = request.user.profile
    child, _kids = _active_child(request)
    classroom = child.classroom if child else None
    is_student = profile.role == 'student'

    qid = request.GET.get('id')
    if qid and classroom:
        quiz = Quiz.objects.filter(pk=qid, classroom=classroom).first()
        if quiz:
            questions = list(quiz.questions.all())
            attempt = QuizAttempt.objects.filter(quiz=quiz, student=child).first()
            if request.method == 'POST' and is_student:
                score = sum(1 for q in questions
                            if request.POST.get('q_%d' % q.id, '') == q.correct)
                attempt, _ = QuizAttempt.objects.update_or_create(
                    quiz=quiz, student=child,
                    defaults={'score': score, 'total': len(questions)})
                messages.success(request, 'Quiz submitted. Score: %d / %d'
                                 % (score, len(questions)))
                return redirect('%s?id=%s' % (request.path, quiz.id))
            taking = is_student and (attempt is None or request.GET.get('retake'))
            return render(request, 'my_quizzes.html', {
                'role': profile.role, 'active': 'quizzes', 'child': child,
                'quiz': quiz, 'questions': questions, 'attempt': attempt,
                'taking': taking, 'is_student': is_student,
            })

    quizzes = []
    if classroom and child:
        atts = {a.quiz_id: a
                for a in QuizAttempt.objects.filter(student=child)}
        for q in Quiz.objects.filter(classroom=classroom):
            quizzes.append({'obj': q, 'attempt': atts.get(q.id),
                            'count': q.questions.count()})
    return render(request, 'my_quizzes.html', {
        'role': profile.role, 'active': 'quizzes', 'child': child,
        'quizzes': quizzes, 'quiz': None, 'is_student': is_student,
    })


@login_required
@role_required('teacher')
def teacher_assignments(request):
    profile = request.user.profile
    classes = _teacher_classes(profile)
    cid = request.POST.get('class') or request.GET.get('class')
    classroom = next((c for c in classes if str(c.id) == str(cid)), None) if cid else None
    if classroom is None:
        classroom = classes[0] if classes else None
    subjects = list(Subject.objects.filter(classroom=classroom)) if classroom else []

    # Delete an assignment (and its submissions) — mistakes used to be permanent.
    if request.method == 'POST' and request.POST.get('action') == 'delete':
        a = Assignment.objects.filter(
            pk=_pk(request.POST.get('assignment_id')), classroom=classroom).first()
        if a:
            a.delete()
            messages.success(request, 'Assignment deleted.')
        return redirect('%s?class=%s' % (reverse('teacher_assignments'),
                                         classroom.id if classroom else ''))

    aid = request.GET.get('id')
    if aid:
        assignment = Assignment.objects.filter(pk=aid, classroom=classroom).first()
        if assignment:
            if request.method == 'POST' and request.POST.get('action') == 'edit':
                title = (request.POST.get('title', '') or '').strip()
                if title:
                    assignment.title = title
                    assignment.description = (request.POST.get('description', '') or '').strip()
                    subj = Subject.objects.filter(
                        pk=_pk(request.POST.get('subject')), classroom=classroom).first()
                    if subj:
                        assignment.subject = subj
                    raw = request.POST.get('due_date', '')
                    try:
                        if raw:
                            assignment.due_date = datetime.date.fromisoformat(raw)
                    except ValueError:
                        pass
                    assignment.save()
                    messages.success(request, 'Assignment updated.')
                return redirect('%s?id=%s&class=%s'
                                % (request.path, assignment.id, assignment.classroom_id))
            if request.method == 'POST' and request.POST.get('action') == 'grade':
                sub = Submission.objects.filter(
                    pk=request.POST.get('submission_id'),
                    assignment=assignment).first()
                if sub:
                    sub.grade = (request.POST.get('grade', '') or '').strip()
                    sub.status = 'Graded' if sub.grade else 'Submitted'
                    sub.save()
                    messages.success(request, 'Saved.')
                return redirect('%s?id=%s&class=%s'
                                % (request.path, assignment.id, assignment.classroom_id))
            students = list(Student.objects.filter(classroom=classroom))
            subs = {s.student_id: s
                    for s in Submission.objects.filter(assignment=assignment)}
            rows = [{'student': st, 'submission': subs.get(st.id)}
                    for st in students]
            return render(request, 'teacher_assignments.html', {
                'role': 'teacher', 'active': 'assignments',
                'classroom': classroom, 'classes': classes, 'assignment': assignment,
                'rows': rows, 'subjects': subjects,
            })

    if request.method == 'POST' and request.POST.get('action') == 'create' and classroom:
        title = (request.POST.get('title', '') or '').strip()
        if title:
            subj = Subject.objects.filter(
                pk=_pk(request.POST.get('subject')), classroom=classroom).first()
            raw = request.POST.get('due_date', '')
            try:
                due = datetime.date.fromisoformat(raw) if raw else timezone.localdate()
            except ValueError:
                due = timezone.localdate()
            assignment = Assignment.objects.create(
                classroom=classroom, subject=subj, title=title,
                description=(request.POST.get('description', '') or '').strip(),
                due_date=due)
            up = request.FILES.get('attachment')
            if up:
                aerr = _upload_error(up, DOC_EXTS)
                if aerr:
                    messages.error(request, 'Attachment not saved: ' + aerr)
                else:
                    assignment.attachment = up
                    assignment.save()
            messages.success(request, 'Assignment created.')
        return redirect('%s?class=%s' % (reverse('teacher_assignments'),
                                         classroom.id if classroom else ''))

    assignments = []
    if classroom:
        for a in Assignment.objects.filter(classroom=classroom):
            assignments.append({'obj': a, 'count': a.submissions.count()})
    return render(request, 'teacher_assignments.html', {
        'role': 'teacher', 'active': 'assignments', 'classroom': classroom,
        'classes': classes, 'assignments': assignments, 'assignment': None,
        'subjects': subjects,
    })


@login_required
@role_required('teacher')
def teacher_quizzes(request):
    profile = request.user.profile
    classes = _teacher_classes(profile)
    cid = request.POST.get('class') or request.GET.get('class')
    classroom = next((c for c in classes if str(c.id) == str(cid)), None) if cid else None
    if classroom is None:
        classroom = classes[0] if classes else None
    subjects = list(Subject.objects.filter(classroom=classroom)) if classroom else []

    # Delete a whole quiz (and its questions/attempts).
    if request.method == 'POST' and request.POST.get('action') == 'delete':
        q = Quiz.objects.filter(
            pk=_pk(request.POST.get('quiz_id')), classroom=classroom).first()
        if q:
            q.delete()
            messages.success(request, 'Quiz deleted.')
        return redirect('%s?class=%s' % (reverse('teacher_quizzes'),
                                         classroom.id if classroom else ''))

    qid = request.GET.get('id')
    if qid:
        quiz = Quiz.objects.filter(pk=qid, classroom=classroom).first()
        if quiz:
            if request.method == 'POST' and request.POST.get('action') == 'del_q':
                Question.objects.filter(
                    pk=_pk(request.POST.get('question_id')), quiz=quiz).delete()
                messages.success(request, 'Question removed.')
                return redirect('%s?id=%s&class=%s'
                                % (request.path, quiz.id, quiz.classroom_id))
            if request.method == 'POST' and request.POST.get('action') == 'edit':
                title = (request.POST.get('title', '') or '').strip()
                if title:
                    quiz.title = title
                    subj = Subject.objects.filter(
                        pk=_pk(request.POST.get('subject')), classroom=classroom).first()
                    if subj:
                        quiz.subject = subj
                    try:
                        quiz.time_limit = max(1, int(
                            request.POST.get('time_limit', quiz.time_limit)
                            or quiz.time_limit))
                    except ValueError:
                        pass
                    quiz.save()
                    messages.success(request, 'Quiz updated.')
                return redirect('%s?id=%s&class=%s'
                                % (request.path, quiz.id, quiz.classroom_id))
            if request.method == 'POST' and request.POST.get('action') == 'add_q':
                text = (request.POST.get('text', '') or '').strip()
                if text:
                    Question.objects.create(
                        quiz=quiz, text=text,
                        option_a=(request.POST.get('option_a', '') or '').strip(),
                        option_b=(request.POST.get('option_b', '') or '').strip(),
                        option_c=(request.POST.get('option_c', '') or '').strip(),
                        option_d=(request.POST.get('option_d', '') or '').strip(),
                        correct=request.POST.get('correct', 'A'),
                        order=quiz.questions.count() + 1)
                    messages.success(request, 'Question added.')
                return redirect('%s?id=%s&class=%s'
                                % (request.path, quiz.id, quiz.classroom_id))
            questions = list(quiz.questions.all())
            attempts = list(quiz.attempts.select_related('student'))
            return render(request, 'teacher_quizzes.html', {
                'role': 'teacher', 'active': 'quizzes', 'classroom': classroom,
                'classes': classes, 'quiz': quiz, 'questions': questions,
                'attempts': attempts, 'subjects': subjects,
            })

    if request.method == 'POST' and request.POST.get('action') == 'create' and classroom:
        title = (request.POST.get('title', '') or '').strip()
        if title:
            subj = Subject.objects.filter(
                pk=_pk(request.POST.get('subject')), classroom=classroom).first()
            try:
                tl = max(1, int(request.POST.get('time_limit', '10') or 10))
            except ValueError:
                tl = 10
            Quiz.objects.create(classroom=classroom, subject=subj,
                                title=title, time_limit=tl)
            messages.success(request, 'Quiz created. Now add questions to it.')
        return redirect('%s?class=%s' % (reverse('teacher_quizzes'),
                                         classroom.id if classroom else ''))

    quizzes = []
    if classroom:
        for q in Quiz.objects.filter(classroom=classroom):
            quizzes.append({'obj': q, 'count': q.questions.count(),
                            'attempts': q.attempts.count()})
    return render(request, 'teacher_quizzes.html', {
        'role': 'teacher', 'active': 'quizzes', 'classroom': classroom,
        'classes': classes, 'quizzes': quizzes, 'quiz': None, 'subjects': subjects,
    })


# ---------------- Teacher self-service (own schedule + HR) ----------------

@login_required
@role_required('teacher')
def teacher_timetable(request):
    """The teacher's OWN weekly schedule: only the periods they personally
    teach (matched to their teaching assignments), not the whole class grid."""
    profile = request.user.profile
    teaching = list(profile.teaching.select_related('classroom'))
    taught = {(t.classroom_id, t.subject) for t in teaching}
    class_ids = {t.classroom_id for t in teaching}
    days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']
    today_name = timezone.localdate().strftime('%a')

    my_slots = [s for s in TimetableSlot.objects.filter(
        classroom_id__in=class_ids).select_related('classroom')
        if (s.classroom_id, s.subject) in taught]
    by_cell = {(s.day, s.period): s for s in my_slots}
    time_by_period = {}
    for s in my_slots:
        time_by_period.setdefault(s.period, s.start_time)
    rows = []
    for p in sorted(time_by_period):
        cells = [{'slot': by_cell.get((d, p)), 'today': d == today_name}
                 for d in days]
        rows.append({'period': p, 'time': time_by_period[p], 'cells': cells})
    return render(request, 'teacher_timetable.html', {
        'role': 'teacher', 'active': 'timetable', 'rows': rows,
        'days': days, 'today_name': today_name, 'total': len(my_slots),
    })


@login_required
@role_required('teacher')
def teacher_notes(request):
    """Teacher writes light behaviour/remark notes (praise, concern, general)
    on students in their own classes. These are shared with the parent/student,
    unlike the confidential office-only DisciplineRecord."""
    profile = request.user.profile
    classes = _teacher_classes(profile)
    cid = request.POST.get('class') or request.GET.get('class')
    classroom = next((c for c in classes if str(c.id) == str(cid)), None) if cid else None
    if classroom is None:
        classroom = classes[0] if classes else None
    student_ids = set(
        Student.objects.filter(classroom=classroom).values_list('id', flat=True)
    ) if classroom else set()

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'add':
            sid = _pk(request.POST.get('student'))
            text = (request.POST.get('text', '') or '').strip()
            kind = request.POST.get('kind', 'Note')
            valid = {k for k, _ in StudentNote.KINDS}
            if sid and int(sid) in student_ids and text:
                StudentNote.objects.create(
                    student_id=int(sid), text=text[:400],
                    kind=kind if kind in valid else 'Note', teacher=profile,
                    teacher_name=profile.user.get_full_name() or profile.user.username)
                messages.success(request, 'Note saved.')
            else:
                messages.error(request, 'Pick a student in your class and write a note.')
        elif action == 'delete':
            # A teacher may remove only their own notes.
            n = StudentNote.objects.filter(
                pk=_pk(request.POST.get('note_id')), teacher=profile).first()
            if n:
                n.delete()
                messages.success(request, 'Note deleted.')
        return redirect('%s?class=%s' % (reverse('teacher_notes'),
                                         classroom.id if classroom else ''))

    students = list(Student.objects.filter(classroom=classroom)) if classroom else []
    notes = list(StudentNote.objects.filter(student__classroom=classroom)
                 .select_related('student')[:80]) if classroom else []
    return render(request, 'teacher_notes.html', {
        'role': 'teacher', 'active': 'notes', 'classes': classes,
        'classroom': classroom, 'students': students, 'notes': notes,
        'kinds': StudentNote.KINDS, 'my_id': profile.id,
        'today_iso': timezone.localdate().isoformat(),
    })


@login_required
@role_required('teacher')
def teacher_messages(request):
    """The teacher side of parent<->teacher threads. Lists students in the
    teacher's classes with unread counts; opening one shows the conversation
    and lets the teacher reply. Replies are limited to the teacher's own
    students (a teacher can't message a class they don't take)."""
    profile = request.user.profile
    classes = _teacher_classes(profile)
    class_ids = [c.id for c in classes]
    student_qs = Student.objects.filter(classroom_id__in=class_ids,
                                        graduated=False).select_related('classroom')
    sid = _pk(request.GET.get('student') or request.POST.get('student'))
    student = student_qs.filter(pk=sid).first() if sid else None

    if request.method == 'POST' and student:
        body = (request.POST.get('body', '') or '').strip()
        if body:
            Message.objects.create(
                student=student, sender=profile, sender_role='teacher',
                sender_name=request.user.get_full_name() or request.user.username,
                body=body[:2000], seen_by_staff=True, seen_by_family=False)
        else:
            messages.error(request, 'Type a message first.')
        return redirect('%s?student=%s' % (reverse('teacher_messages'), student.id))

    thread = []
    if student:
        thread = list(student.messages.select_related('sender'))
        (student.messages.filter(seen_by_staff=False).update(seen_by_staff=True))

    # Sidebar list: students who have a thread, newest activity first, plus the
    # unread count per student. Students with no messages are still reachable
    # via the "start a conversation" picker.
    unread = {}
    for m in Message.objects.filter(student__in=student_qs, seen_by_staff=False):
        unread[m.student_id] = unread.get(m.student_id, 0) + 1
    with_msgs = (student_qs.filter(messages__isnull=False).distinct()
                 .order_by('-messages__created'))
    convo_students = []
    seen_ids = set()
    for s in with_msgs:
        if s.id in seen_ids:
            continue
        seen_ids.add(s.id)
        convo_students.append({'student': s, 'unread': unread.get(s.id, 0)})
    return render(request, 'teacher_messages.html', {
        'role': 'teacher', 'active': 'messages', 'classes': classes,
        'all_students': student_qs.order_by('classroom__name', 'roll_no'),
        'convo_students': convo_students, 'student': student, 'thread': thread,
        'my_id': profile.id,
    })


@login_required
@role_required('teacher')
def teacher_analytics(request):
    """Read-only performance analytics for a teacher's own class + exam:
    subject-wise average / pass rate / top+low score, and a ranked student
    list. All numbers come from existing Mark rows — no new data entry."""
    profile = request.user.profile
    classes = _teacher_classes(profile)
    cid = request.GET.get('class')
    classroom = next((c for c in classes if str(c.id) == str(cid)), None) if cid else None
    if classroom is None:
        classroom = classes[0] if classes else None
    exam, exams = _pick_exam(request)
    school = School.objects.first()
    pass_mark = school.pass_mark if school else 40
    taught = (set(profile.teaching.filter(classroom=classroom)
                  .values_list('subject', flat=True)) if classroom else set())

    students = list(Student.objects.filter(classroom=classroom)) if classroom else []
    subj_rows, student_rows = [], []
    class_avg = class_pass = None
    if classroom and exam and students:
        sids = [s.id for s in students]
        marks = list(Mark.objects.filter(student_id__in=sids, exam=exam)
                     .select_related('subject', 'student'))
        # Subject-wise summary.
        by_subj = {}
        for m in marks:
            by_subj.setdefault(m.subject, []).append(m)
        for subj in sorted(by_subj, key=lambda s: s.name):
            pcts = [m.percentage for m in by_subj[subj]]
            subj_rows.append({
                'subject': subj, 'n': len(pcts), 'mine': subj.name in taught,
                'avg': round(sum(pcts) / len(pcts)),
                'pass_pct': round(sum(1 for p in pcts if p >= pass_mark) / len(pcts) * 100),
                'top': round(max(pcts)), 'low': round(min(pcts)),
            })
        # Per-student totals, ranked.
        agg = {}
        for m in marks:
            o, t = agg.get(m.student_id, (0, 0))
            agg[m.student_id] = (o + m.marks_obtained, t + m.total_marks)
        for s in students:
            o, t = agg.get(s.id, (0, 0))
            if t:
                student_rows.append({'student': s, 'pct': round(o / t * 100),
                                     'obtained': o, 'total': t})
        student_rows.sort(key=lambda r: r['pct'], reverse=True)
        for i, r in enumerate(student_rows, 1):
            r['rank'] = i
        cls_pcts = [r['pct'] for r in student_rows]
        if cls_pcts:
            class_avg = round(sum(cls_pcts) / len(cls_pcts))
            class_pass = round(sum(1 for p in cls_pcts if p >= pass_mark)
                               / len(cls_pcts) * 100)
    return render(request, 'teacher_analytics.html', {
        'role': 'teacher', 'active': 'analytics', 'classes': classes,
        'classroom': classroom, 'exam': exam, 'exams': exams,
        'subj_rows': subj_rows, 'student_rows': student_rows,
        'class_avg': class_avg, 'class_pass': class_pass, 'pass_mark': pass_mark,
        'graded': len(student_rows), 'total_students': len(students),
    })


@login_required
@role_required('teacher')
def my_hr(request):
    """The teacher's own HR view: personal attendance summary, payslips and
    self-service leave requests. Works only if an admin has linked their login
    to a Staff record."""
    staff = getattr(request.user, 'staff_record', None)

    if request.method == 'POST' and staff:
        try:
            fd = datetime.date.fromisoformat(request.POST.get('from_date', ''))
            td = datetime.date.fromisoformat(request.POST.get('to_date', ''))
        except (ValueError, TypeError):
            messages.error(request, 'Please pick valid from and to dates.')
            return redirect('my_hr')
        reason = (request.POST.get('reason', '') or '').strip()
        if td < fd:
            messages.error(request, 'The "to" date cannot be before the "from" date.')
        elif not reason:
            messages.error(request, 'Please give a reason for the leave.')
        else:
            LeaveRequest.objects.create(
                staff=staff, from_date=fd, to_date=td, reason=reason[:200],
                applied_by=request.user.get_full_name() or request.user.username)
            messages.success(request, 'Leave request submitted. The Principal will '
                             'see it in the approvals queue.')
        return redirect('my_hr')

    att, payslips, leaves = [], [], []
    summary = {'P': 0, 'A': 0, 'L': 0, 'H': 0}
    if staff:
        att = list(staff.attendance.all()[:60])
        for a in att:
            if a.status in summary:
                summary[a.status] += 1
        payslips = list(staff.payslips.all())
        leaves = list(staff.leaves.all()[:20])
    marked = summary['P'] + summary['A'] + summary['L'] + summary['H']
    return render(request, 'my_hr.html', {
        'role': 'teacher', 'active': 'myhr', 'staff': staff, 'att': att,
        'summary': summary, 'payslips': payslips, 'marked': marked,
        'leaves': leaves, 'today_iso': timezone.localdate().isoformat(),
        'att_pct': round(summary['P'] / marked * 100) if marked else 0,
    })


# ---------- Material download (generates a real PDF, no dependencies) ----------

def _pdf_escape(s):
    return s.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')


def _build_pdf(lines):
    """Build a simple one-page PDF from (text, font_size) lines. No libraries."""
    content = "BT\n"
    y = 780
    for text, size in lines:
        content += "/F1 %d Tf\n" % size
        content += "1 0 0 1 60 %d Tm\n" % y
        content += "(%s) Tj\n" % _pdf_escape(text)
        y -= int(size * 1.7) + 6
    content += "ET"
    cb = content.encode('latin-1', 'replace')

    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length %d >>\nstream\n" % len(cb) + cb + b"\nendstream",
    ]
    pdf = b"%PDF-1.4\n"
    offsets = []
    for i, obj in enumerate(objs, start=1):
        offsets.append(len(pdf))
        pdf += ("%d 0 obj\n" % i).encode() + obj + b"\nendobj\n"
    xref_pos = len(pdf)
    pdf += b"xref\n0 %d\n" % (len(objs) + 1)
    pdf += b"0000000000 65535 f \n"
    for off in offsets:
        pdf += b"%010d 00000 n \n" % off
    pdf += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF" % (
        len(objs) + 1, xref_pos)
    return pdf


@login_required
@role_required('parent', 'student')
def material_download(request, pk):
    profile = request.user.profile
    child, _kids = _active_child(request)
    classroom = child.classroom if child else None
    material = get_object_or_404(Material, pk=pk)
    # Only allow files that belong to the child's own class
    if not classroom or material.subject.classroom_id != classroom.id:
        return HttpResponseForbidden('You cannot access this file.')

    # Serve the REAL uploaded file. If the school hasn't uploaded one yet, say so
    # honestly instead of handing back a fake "sample" PDF pretending to be it.
    if not material.file:
        messages.info(request, 'The teacher has not uploaded a file for "%s" yet.'
                      % material.title)
        return redirect('my_subjects')
    try:
        return FileResponse(material.file.open('rb'), as_attachment=True,
                            filename=material.file.name.split('/')[-1])
    except (FileNotFoundError, ValueError):
        return HttpResponseForbidden('This file is no longer available.')


# ---------- Assignment / submission file serving (permission-checked) -------

def _can_see_class(profile, classroom):
    if profile.role == 'teacher':
        return classroom.id in [c.id for c in _teacher_classes(profile)]
    if profile.role in ('parent', 'student'):
        return any(c.classroom_id == classroom.id for c in profile.child_list())
    return profile.role == 'admin'


@login_required
def assignment_file(request, pk):
    assignment = get_object_or_404(Assignment, pk=pk)
    if not _can_see_class(request.user.profile, assignment.classroom):
        return HttpResponseForbidden('You cannot access this file.')
    if not assignment.attachment:
        raise Http404('No file attached.')
    return FileResponse(assignment.attachment.open('rb'), as_attachment=True,
                        filename=assignment.attachment.name.split('/')[-1])


@login_required
def submission_file(request, pk):
    sub = get_object_or_404(Submission, pk=pk)
    profile = request.user.profile
    classroom = sub.assignment.classroom
    allowed = (
        (profile.role == 'teacher'
         and classroom.id in [c.id for c in _teacher_classes(profile)])
        or (profile.role in ('parent', 'student')
            and _owns_student(profile, sub.student_id))
        or profile.role == 'admin')
    if not allowed:
        return HttpResponseForbidden('You cannot access this file.')
    if not sub.file:
        raise Http404('No file uploaded.')
    return FileResponse(sub.file.open('rb'), as_attachment=True,
                        filename=sub.file.name.split('/')[-1])


@login_required
@role_required('teacher')
def assignment_submissions_zip(request, pk):
    import io
    import zipfile
    profile = request.user.profile
    assignment = get_object_or_404(Assignment, pk=pk)
    if assignment.classroom_id not in [c.id for c in _teacher_classes(profile)]:
        return HttpResponseForbidden('You cannot access this.')

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        subs = (Submission.objects.filter(assignment=assignment)
                .select_related('student'))
        added = 0
        for s in subs:
            base = ('%s - %s' % (s.student.roll_no or s.student_id,
                                 s.student.name)).replace('/', '-')
            if s.file:
                try:
                    data = s.file.open('rb').read()
                    ext = (s.file.name.rsplit('.', 1)[-1]
                           if '.' in s.file.name else 'dat')
                    zf.writestr('%s.%s' % (base, ext), data)
                    added += 1
                except Exception:
                    pass
            elif s.answer_text:
                zf.writestr('%s.txt' % base, s.answer_text)
                added += 1
        if added == 0:
            zf.writestr('README.txt', 'No submissions have been uploaded yet.')
    buf.seek(0)
    fname = ('%s - submissions.zip' % assignment.title).replace('"', '')
    resp = HttpResponse(buf.getvalue(), content_type='application/zip')
    resp['Content-Disposition'] = 'attachment; filename="%s"' % fname
    return resp


from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.utils import timezone
from .models import School

@login_required(login_url='login')
def saas_admin_dashboard(request):
    if not request.user.is_superuser:
        raise PermissionDenied
        
    import json
    import sqlite3
    import os
    from django.conf import settings
    from django.utils import timezone
    from django.db.models import Sum
    from django.db.models.functions import TruncMonth
    from core.models import School, SaasTransaction
    
    # Handle creating a new SaaS Transaction
    if request.method == 'POST' and 'add_transaction' in request.POST:
        amount = request.POST.get('amount')
        t_type = request.POST.get('transaction_type')
        school_id = request.POST.get('school') or None
        desc = request.POST.get('description') or ''
        t_date = request.POST.get('date') or timezone.localdate()
        
        if amount and t_type:
            SaasTransaction.objects.create(
                amount=int(amount),
                transaction_type=t_type,
                school_id=school_id,
                description=desc,
                date=t_date
            )
            messages.success(request, "SaaS Transaction logged successfully!")
            return redirect('saas_admin_dashboard')

    schools = School.objects.all().order_by('name')
    today = timezone.localdate()
    
    total_schools = schools.count()
    active_schools_count = schools.filter(subscription_active=True).count()
    total_saas_revenue = sum(s.subscription_rate for s in schools.filter(subscription_active=True))
    
    # Calculate SaaS Platform own finances
    saas_income = SaasTransaction.objects.filter(transaction_type='income').aggregate(total=Sum('amount'))['total'] or 0
    saas_expense = SaasTransaction.objects.filter(transaction_type='expense').aggregate(total=Sum('amount'))['total'] or 0
    saas_profit = saas_income - saas_expense
    
    # Fetch recent platform transactions
    recent_transactions = SaasTransaction.objects.all().select_related('school')[:15]
    
    # Prepare school subscription rates chart data
    school_names = []
    sub_rates = []
    
    for school in schools:
        school.portal_url = school.get_portal_url(request)
        if school.subscription_end and school.subscription_end < today:
            school.is_expired = True
        else:
            school.is_expired = False
            
        # Get count of students/staff dynamically from SQLite files
        sub = school.subdomain or 'default'
        if sub == 'default':
            db_path = os.path.join(settings.BASE_DIR, "db.sqlite3")
        else:
            db_path = os.path.join(settings.BASE_DIR, f"{sub}.sqlite3")
            
        stats = {'students': 0, 'staff': 0}
        if os.path.exists(db_path):
            try:
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM core_student")
                stats['students'] = cursor.fetchone()[0] or 0
                cursor.execute("SELECT COUNT(*) FROM core_staff")
                stats['staff'] = cursor.fetchone()[0] or 0
                conn.close()
            except Exception:
                pass
                
        school.student_count = stats['students']
        school.staff_count = stats['staff']
        
        school_names.append(school.name)
        sub_rates.append(school.subscription_rate)

    # Group SaaS transactions by month for the line chart
    monthly_qs = SaasTransaction.objects.annotate(month_date=TruncMonth('date')).values('month_date', 'transaction_type').annotate(total=Sum('amount')).order_by('month_date')
    
    # Format monthly data for Chart.js
    months_dict = {}
    for item in monthly_qs:
        m_str = item['month_date'].strftime('%b %Y')
        if m_str not in months_dict:
            months_dict[m_str] = {'income': 0, 'expense': 0}
        months_dict[m_str][item['transaction_type']] = item['total'] or 0
        
    chart_months = list(months_dict.keys())
    chart_income = [months_dict[m]['income'] for m in chart_months]
    chart_expense = [months_dict[m]['expense'] for m in chart_months]

    return render(request, 'saas_admin.html', {
        'schools': schools,
        'today': today,
        'active': 'saas_admin',
        'total_schools': total_schools,
        'active_schools_count': active_schools_count,
        'total_saas_revenue': total_saas_revenue,
        'saas_income': saas_income,
        'saas_expense': saas_expense,
        'saas_profit': saas_profit,
        'recent_transactions': recent_transactions,
        'school_names_json': json.dumps(school_names),
        'sub_rates_json': json.dumps(sub_rates),
        'chart_months_json': json.dumps(chart_months),
        'chart_income_json': json.dumps(chart_income),
        'chart_expense_json': json.dumps(chart_expense),
    })

def _init_tenant_db(school, *, force=False):
    """Thin wrapper around the shared clean-tenant builder (core.tenancy) so the
    provisioning path can never drift back to a raw copy of the master."""
    from .tenancy import build_clean_tenant_db
    return build_clean_tenant_db(school, force=force)


@login_required(login_url='login')
def saas_school_add(request):
    if not request.user.is_superuser:
        raise PermissionDenied
        
    if request.method == 'POST':
        name = request.POST.get('name')
        subdomain = request.POST.get('subdomain')
        start_date = request.POST.get('subscription_start') or None
        end_date = request.POST.get('subscription_end') or None
        rate = request.POST.get('subscription_rate') or 5000
        
        admin_username = request.POST.get('admin_username')
        admin_email = request.POST.get('admin_email')
        admin_password = request.POST.get('admin_password')

        from core.crypto import hash_password
        if name and subdomain:
            school = School.objects.create(
                name=name,
                subdomain=subdomain,
                subscription_start=start_date,
                subscription_end=end_date,
                subscription_active=True,
                admin_username=admin_username or '',
                admin_email=admin_email or '',
                # Store a password HASH, never plaintext.
                admin_password=hash_password(admin_password),
                subscription_rate=int(rate)
            )
            
            if admin_username and admin_password:
                # Build a CLEAN tenant database — only this school's admin, never
                # the master's users/data (that was the cross-tenant leak).
                _init_tenant_db(school)

            messages.success(request, f"School '{name}' and Admin account created successfully!")
            return redirect('saas_admin_dashboard')
            
    return render(request, 'saas_school_form.html', {
        'title': 'Add New School',
        'active': 'saas_admin'
    })

@login_required(login_url='login')
def saas_school_edit(request, pk):
    if not request.user.is_superuser:
        raise PermissionDenied
        
    school = get_object_or_404(School, pk=pk)
    if request.method == 'POST':
        school.name = request.POST.get('name')
        school.subdomain = request.POST.get('subdomain')
        school.subscription_start = request.POST.get('subscription_start') or None
        school.subscription_end = request.POST.get('subscription_end') or None
        school.subscription_active = request.POST.get('subscription_active') == 'on'
        school.subscription_rate = int(request.POST.get('subscription_rate') or 5000)
        
        old_username = school.admin_username
        admin_username = request.POST.get('admin_username')
        admin_email = request.POST.get('admin_email')
        admin_password = request.POST.get('admin_password')

        from core.crypto import hash_password, apply_stored_password
        school.admin_username = admin_username or ''
        school.admin_email = admin_email or ''
        if admin_password:
            # Store a password HASH, never plaintext.
            school.admin_password = hash_password(admin_password)

        school.save()
        
        if admin_username:
            import os
            import copy
            import shutil
            from django.db import connections
            
            subdomain = school.subdomain or 'default'
            tenant_db_path = os.path.join(settings.BASE_DIR, f"{subdomain}.sqlite3")
            if not os.path.exists(tenant_db_path):
                # First-time provisioning — build the tenant DB CLEAN (only this
                # school's admin), never a raw copy of the master's data.
                _init_tenant_db(school)

            conn = connections['default']
            conn.close()
            original_db_name = conn.settings_dict['NAME']
            conn.settings_dict = copy.deepcopy(conn.settings_dict)
            conn.settings_dict['NAME'] = tenant_db_path
            
            try:
                from django.contrib.auth.models import User
                from core.models import Profile, School as TenantSchool
                
                # Sync school data inside tenant database
                tenant_school = TenantSchool.objects.filter(subdomain=subdomain).first()
                if not tenant_school:
                    tenant_school = TenantSchool.objects.create(
                        name=school.name,
                        subdomain=subdomain,
                        subscription_start=school.subscription_start,
                        subscription_end=school.subscription_end,
                        subscription_active=school.subscription_active,
                        admin_username=school.admin_username,
                        admin_email=school.admin_email,
                        admin_password=school.admin_password,
                        subscription_rate=school.subscription_rate
                    )
                else:
                    tenant_school.name = school.name
                    tenant_school.subscription_start = school.subscription_start
                    tenant_school.subscription_end = school.subscription_end
                    tenant_school.subscription_active = school.subscription_active
                    tenant_school.admin_username = school.admin_username
                    tenant_school.admin_email = school.admin_email
                    # Keep the tenant copy in sync with the master's stored HASH.
                    tenant_school.admin_password = school.admin_password
                    tenant_school.subscription_rate = school.subscription_rate
                    tenant_school.save()
                
                # Sync user/profile inside tenant database
                user = User.objects.filter(username=admin_username).first()
                if not user and old_username:
                    user = User.objects.filter(username=old_username).first()
                    
                if user:
                    user.username = admin_username
                    user.email = admin_email or ''
                    if admin_password:
                        user.set_password(admin_password)
                    # A tenant admin must NEVER be a superuser: the tenant DB is
                    # copied from master (which has a superuser 'admin'), and if
                    # the reused row is a superuser the routing middleware bounces
                    # it off the school portal on every login.
                    user.is_superuser = False
                    user.is_staff = False
                    user.save()
                    
                    profile = getattr(user, 'profile', None)
                    if profile:
                        profile.school = tenant_school
                        profile.role = 'admin'
                        profile.save()
                    else:
                        Profile.objects.create(
                            user=user,
                            role='admin',
                            school=tenant_school,
                            must_change_password=False
                        )
                else:
                    if not User.objects.filter(username=admin_username).exists():
                        user = User(
                            username=admin_username,
                            email=admin_email or '',
                            first_name=school.name
                        )
                        # Use the plaintext just entered; otherwise fall back to
                        # the school's stored password HASH (never plaintext).
                        if admin_password:
                            user.set_password(admin_password)
                        else:
                            apply_stored_password(user, school.admin_password)
                        user.save()
                        Profile.objects.create(
                            user=user,
                            role='admin',
                            school=tenant_school,
                            must_change_password=False
                        )
            finally:
                conn.close()
                conn.settings_dict['NAME'] = original_db_name
                    
        messages.success(request, f"School '{school.name}' and Admin credentials updated successfully!")
        return redirect('saas_admin_dashboard')
        
    start_str = school.subscription_start.strftime('%Y-%m-%d') if school.subscription_start else ''
    end_str = school.subscription_end.strftime('%Y-%m-%d') if school.subscription_end else ''
    
    return render(request, 'saas_school_form.html', {
        'school': school,
        'start_str': start_str,
        'end_str': end_str,
        'title': f"Edit School - {school.name}",
        'active': 'saas_admin'
    })

@login_required(login_url='login')
def saas_school_toggle(request, pk):
    if not request.user.is_superuser:
        raise PermissionDenied
        
    school = get_object_or_404(School, pk=pk)
    school.subscription_active = not school.subscription_active
    school.save()
    status = "activated" if school.subscription_active else "deactivated"
    messages.success(request, f"School '{school.name}' has been {status}.")
    return redirect('saas_admin_dashboard')

@login_required(login_url='login')
def saas_school_delete(request, pk):
    if not request.user.is_superuser:
        raise PermissionDenied
        
    school = get_object_or_404(School, pk=pk)
    name = school.name
    subdomain = school.subdomain or 'default'
    
    # Delete the tenant database file associated with this subdomain
    if subdomain != 'default':
        import os
        tenant_db_path = os.path.join(settings.BASE_DIR, f"{subdomain}.sqlite3")
        if os.path.exists(tenant_db_path):
            try:
                os.remove(tenant_db_path)
            except OSError:
                pass
                
    school.delete()
    messages.success(request, f"School '{name}' and its database file deleted successfully.")
    return redirect('saas_admin_dashboard')

@login_required(login_url='login')
def saas_transaction_add(request):
    if not request.user.is_superuser:
        raise PermissionDenied
        
    from core.models import School, SaasTransaction
    from django.utils import timezone
    
    if request.method == 'POST':
        amount = request.POST.get('amount')
        t_type = request.POST.get('transaction_type')
        school_id = request.POST.get('school') or None
        desc = request.POST.get('description') or ''
        t_date = request.POST.get('date') or timezone.localdate()
        
        if amount and t_type:
            SaasTransaction.objects.create(
                amount=int(amount),
                transaction_type=t_type,
                school_id=school_id,
                description=desc,
                date=t_date
            )
            messages.success(request, "SaaS Transaction logged successfully!")
            return redirect('saas_admin_dashboard')
            
    schools = School.objects.all().order_by('name')
    return render(request, 'saas_transaction_form.html', {
        'schools': schools,
        'today': timezone.localdate(),
        'active': 'saas_admin'
    })


def subscription_expired(request):
    school = getattr(request, 'tenant', None)
    return render(request, 'subscription_expired.html', {
        'school': school
    })

def logout_then_login(request):
    """
    Log out the current user via a GET request safely, then redirect to the login page.
    """
    from django.contrib.auth import logout
    logout(request)
    next_url = request.GET.get('next', 'login')
    return redirect(next_url)


def run_daily_jobs(school, today):
    from core.models import Student, FeeChallan, ChallanLine
    from .sms import notify
    import datetime
    
    # 1. Auto-Apply / escalate Late Fees on overdue, unpaid, unlocked challans.
    if school.late_fee_amount > 0:
        for ch in FeeChallan.objects.filter(due_date__lt=today,
                                            carried_forward=False):
            if _refresh_late_fee(school, ch, today):
                _sync_fee_status(ch.student)
                print(f"[Automation] Late fee now Rs {ch.late_fee} on {ch}")
                
    # 2. Auto-Generate Monthly Challans (Runs on 1st of the month).
    # Use the SAME _make_challan the office uses, so auto-generated challans
    # include fee heads / one-time / annual charges (the old inline version
    # silently dropped them). _make_challan is idempotent (skips if one exists).
    if today.day == 1:
        active_students = Student.objects.filter(graduated=False, status='Active')
        for s in active_students:
            _challan, created = _make_challan(s, today.year, today.month)
            if created:
                _sync_fee_status(s)
                print(f"[Automation] Generated monthly challan for {s.name}")

    # 3. Auto-Send Defaulter Reminders (Runs on 5th and 15th of the month)
    if today.day in (5, 15):
        overdue_students = Student.objects.filter(fee_status='Overdue', graduated=False)
        for s in overdue_students:
            unpaid_ch = s.challans.filter(carried_forward=False)
            total_balance = sum(ch.balance for ch in unpaid_ch)
            if total_balance > 0 and s.guardian_phone:
                sname = school.name if school else 'School'
                notify(
                    '%s: Fee Reminder. Dear %s, the outstanding balance for %s is Rs %d. '
                    'Please clear the dues. Ignore if already paid.'
                    % (sname, s.guardian_name or 'Parent', s.name, total_balance),
                    to_phone=s.guardian_phone, recipients=s.guardian_name or s.name,
                    msg_type='Fee Reminder'
                )
                print(f"[Automation] Sent fee reminder SMS to {s.guardian_phone} for {s.name}")