"""Template context available on every page."""
from django.conf import settings

from .models import School


def _rgb(hexstr):
    """Parse #rgb / #rrggbb into an (r, g, b) tuple, or None if unparseable."""
    h = (hexstr or '').lstrip('#')
    if len(h) == 3:
        h = ''.join(c * 2 for c in h)
    if len(h) != 6:
        return None
    try:
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        return None


def _luminance(hexstr):
    """Perceived brightness 0..1 (sRGB relative luminance)."""
    rgb = _rgb(hexstr)
    if not rgb:
        return 0.0

    def lin(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = rgb
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def _ink_on(hexstr):
    """Return a readable text colour (near-black or white) for the given bg."""
    return '#0F172A' if _luminance(hexstr) > 0.42 else '#FFFFFF'


def _shade(hexstr, factor):
    """Scale each channel by factor (<1 darkens, >1 lightens), clamped."""
    rgb = _rgb(hexstr)
    if not rgb:
        return hexstr
    r, g, b = (max(0, min(255, int(c * factor))) for c in rgb)
    return '#%02X%02X%02X' % (r, g, b)


def _logo_version(school):
    """A stable token that changes only when the logo file changes, used to
    cache-bust the browser's copy of the logo (so it caches hard but still
    updates after a re-upload). Falls back to file size, then a constant."""
    logo = getattr(school, 'logo', None)
    if not logo:
        return ''
    try:
        return str(int(logo.storage.get_modified_time(logo.name).timestamp()))
    except Exception:
        try:
            return str(logo.size)
        except Exception:
            return '1'


def _brand_theme(primary, accent):
    """Derive every colour the theme needs from the two brand colours so text
    stays readable on any chosen colour and the sidebar follows the primary."""
    # If the primary is already very dark, lighten the second gradient stop a
    # touch so the sidebar still shows depth; otherwise darken it.
    p_dark = _luminance(primary) < 0.15
    ar = _rgb(accent) or (14, 124, 102)
    return {
        'brand_primary': primary,
        'brand_primary_d': _shade(primary, 1.7 if p_dark else 0.72),
        'brand_primary_ink': _ink_on(primary),
        'brand_accent': accent,
        'brand_accent_d': _shade(accent, 0.82),
        'brand_accent_ink': _ink_on(accent),
        # "r, g, b" of the accent, so shadows/tints can be rgba(var(--accent-rgb),a)
        # and always harmonise with the chosen accent instead of a fixed colour.
        'brand_accent_rgb': '%d, %d, %d' % ar,
    }


def pwa(request):
    """Expose the Web Push public key (applicationServerKey) to templates so the
    browser can subscribe. Empty string disables push cleanly."""
    return {'vapid_public_key': getattr(settings, 'VAPID_PUBLIC_KEY', '')}


def branding(request):
    """Expose the school's name, logo and theme colours to every template so
    the whole system (and the login page) shows the school's own identity."""
    user = getattr(request, 'user', None)
    prof = getattr(user, 'profile', None) if (user and user.is_authenticated) else None
    my_photo = bool(prof and prof.photo)

    school = getattr(request, 'tenant', None)
    is_explicit_tenant = getattr(request, 'is_explicit_tenant', False)

    if not is_explicit_tenant or not school:
        ctx = {'brand_name': 'Roshni SMS', 'brand_logo': False,
               'brand_logo_ver': '', 'brand_school': None, 'hidden_nav': set(),
               'current_session': '2025-26', 'my_photo': my_photo}
        ctx.update(_brand_theme('#15294D', '#0E7C66'))
        return ctx

    # We're in a real tenant context, and by now the DB connection is switched
    # to the tenant's own database. Read the school's OWN record so name, logo
    # and colours reflect what that school set in its Settings (the request
    # .tenant object came from the master registry and would show stale values).
    tenant_school = School.objects.first() or school
    ctx = {
        'brand_name': tenant_school.name,
        'brand_logo': bool(tenant_school.logo),
        'brand_logo_ver': _logo_version(tenant_school),
        'brand_school': tenant_school,
        'hidden_nav': {k.strip() for k in
                       (tenant_school.hidden_nav or '').split(',') if k.strip()},
        'current_session': tenant_school.session or '2025-26',
        'my_photo': my_photo,
    }
    ctx.update(_brand_theme(tenant_school.primary_color or '#15294D',
                            tenant_school.accent_color or '#0E7C66'))
    return ctx


def nav_children(request):
    """For a parent with more than one child, expose the child list and the
    currently-selected child id so base.html can show a child switcher.
    Returns nothing for other roles (keeps templates clean)."""
    user = getattr(request, 'user', None)
    profile = getattr(user, 'profile', None) if user else None
    if not profile or profile.role != 'parent':
        return {}
    kids = profile.child_list()
    if len(kids) < 2:
        return {}
    active = request.session.get('child_id')
    if not any(k.id == active for k in kids):
        active = kids[0].id
    return {'nav_children': kids, 'active_child_id': active}


def notifications(request):
    """Dynamically build real-time in-app alerts based on the user's logged-in role."""
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return {}

    profile = getattr(user, 'profile', None)
    role = profile.role if profile else 'admin'
    
    alerts = []
    badge_counts = {}
    
    # Import inside functions to avoid circular imports
    from .models import Applicant, LeaveRequest, ConcessionRequest, OnlinePayment, InventoryItem, Submission, Announcement, Student, School, Message, Complaint
    from django.utils import timezone
    today = timezone.localdate()
    
    if user.is_superuser:
        # SaaS Admin notifications
        expired_count = School.objects.filter(subscription_end__lt=today, subscription_active=True).count()
        suspended_count = School.objects.filter(subscription_active=False).count()
        total_saas = expired_count + suspended_count
        if total_saas > 0:
            badge_counts['saas_admin_dashboard'] = total_saas
            if expired_count > 0:
                alerts.append({
                    'text': f'{expired_count} school subscriptions have expired.',
                    'url_name': 'saas_admin_dashboard',
                    'type': 'danger'
                })
            if suspended_count > 0:
                alerts.append({
                    'text': f'{suspended_count} school portals are currently suspended.',
                    'url_name': 'saas_admin_dashboard',
                    'type': 'warning'
                })
                
    elif role == 'admin':
        # 1. New Admissions
        enquiries = Applicant.objects.filter(stage='Enquiry').count()
        if enquiries > 0:
            badge_counts['admissions'] = enquiries
            alerts.append({
                'text': f'{enquiries} new admission enquiries to review.',
                'url_name': 'admissions',
                'type': 'info'
            })
        # 2. Low stock inventory items
        low_stock = InventoryItem.objects.all()
        low_count = sum(1 for item in low_stock if item.low)
        if low_count > 0:
            badge_counts['inventory'] = low_count
            alerts.append({
                'text': f'{low_count} items in inventory are running low.',
                'url_name': 'inventory',
                'type': 'warning'
            })
        # 3. Open complaints from families
        open_complaints = Complaint.objects.exclude(status='Resolved').count()
        if open_complaints > 0:
            badge_counts['office_complaints'] = open_complaints
            alerts.append({
                'text': f'{open_complaints} complaint(s) awaiting a response.',
                'url_name': 'office_complaints',
                'type': 'warning'
            })

    elif role == 'principal':
        # 1. Leaves Awaiting Approval
        leaves = LeaveRequest.objects.filter(status='Pending').count()
        # 2. Concessions Pending
        concessions = ConcessionRequest.objects.filter(status='Pending').count()
        # 3. Admissions to enrol
        enrol = Applicant.objects.filter(stage='Offer').count()
        
        total_approvals = leaves + concessions + enrol
        if total_approvals > 0:
            badge_counts['principal_approvals'] = total_approvals
            if leaves > 0:
                alerts.append({
                    'text': f'{leaves} staff leave requests pending approval.',
                    'url_name': 'principal_approvals',
                    'type': 'warning'
                })
            if concessions > 0:
                alerts.append({
                    'text': f'{concessions} fee concession requests pending.',
                    'url_name': 'principal_approvals',
                    'type': 'warning'
                })
            if enrol > 0:
                alerts.append({
                    'text': f'{enrol} admission offers ready for enrollment.',
                    'url_name': 'principal_approvals',
                    'type': 'info'
                })

    elif role == 'teacher':
        # 1. Submissions to grade
        if profile.classroom_id:
            pending_submissions = Submission.objects.filter(grade__isnull=True, assignment__classroom_id=profile.classroom_id).count()
            if pending_submissions > 0:
                badge_counts['teacher_assignments'] = pending_submissions
                alerts.append({
                    'text': f'{pending_submissions} assignments submissions to grade.',
                    'url_name': 'teacher_assignments',
                    'type': 'warning'
                })
        # 2. Unread parent messages across the teacher's classes.
        class_ids = list(profile.teaching.values_list('classroom_id', flat=True))
        if profile.classroom_id:
            class_ids.append(profile.classroom_id)
        if class_ids:
            unread_msgs = Message.objects.filter(
                student__classroom_id__in=class_ids, seen_by_staff=False).count()
            if unread_msgs > 0:
                badge_counts['teacher_messages'] = unread_msgs
                alerts.append({
                    'text': f'{unread_msgs} new message(s) from parents.',
                    'url_name': 'teacher_messages',
                    'type': 'info'
                })

    elif role == 'finance':
        # 1. Online payments to confirm (model stores lowercase 'pending')
        payments = OnlinePayment.objects.filter(status='pending').count()
        if payments > 0:
            badge_counts['online_payments'] = payments
            alerts.append({
                'text': f'{payments} online fee payments pending proof check.',
                'url_name': 'online_payments',
                'type': 'warning'
            })
        # 2. Overdue/defaulter count
        defaulters = Student.objects.filter(fee_status='Overdue').count()
        if defaulters > 0:
            badge_counts['defaulters'] = defaulters
            alerts.append({
                'text': f'{defaulters} student fee accounts are overdue.',
                'url_name': 'defaulters',
                'type': 'danger'
            })

    elif role in ['student', 'parent']:
        # If parent or student, get the active child/student record
        student = None
        if role == 'student':
            student = getattr(profile, 'student', None)
        else: # parent
            active_child_id = request.session.get('child_id')
            if active_child_id:
                student = Student.objects.filter(id=active_child_id).first()
            else:
                kids = profile.child_list()
                if kids:
                    student = kids[0]
                    
        if student:
            if student.fee_status == 'Overdue':
                alerts.append({
                    'text': 'Your fee voucher is overdue. Please pay as soon as possible.',
                    'url_name': 'my_fees',
                    'type': 'danger'
                })
            # Unread teacher replies for the active child.
            unread_msgs = Message.objects.filter(
                student=student, seen_by_family=False).count()
            if unread_msgs > 0:
                badge_counts['parent_messages'] = unread_msgs
                alerts.append({
                    'text': f'{unread_msgs} new message(s) from the school.',
                    'url_name': 'parent_messages',
                    'type': 'info'
                })
                
        # Announcements — only those meant for this audience (never leak a
        # staff-/admin-only notice to a parent or student).
        def _for_family(aud):
            a = (aud or 'all').lower()
            return 'all' in a or 'parent' in a or 'student' in a
        recent_ann = [a for a in Announcement.objects.order_by('-id')[:5]
                      if _for_family(a.audience)][:1]
        for ann in recent_ann:
            alerts.append({
                'text': f'Announcement: "{ann.title}"',
                'url_name': 'dashboard',
                'type': 'info'
            })

    return {
        'notifications': alerts,
        'notifications_count': len(alerts),
        'badge_counts': badge_counts
    }
