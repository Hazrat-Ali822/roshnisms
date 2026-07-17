"""Template context available on every page."""
from .models import School


def branding(request):
    """Expose the school's name, logo and theme colours to every template so
    the whole system (and the login page) shows the school's own identity."""
    user = getattr(request, 'user', None)
    prof = getattr(user, 'profile', None) if (user and user.is_authenticated) else None
    my_photo = bool(prof and prof.photo)

    school = getattr(request, 'tenant', None)
    is_explicit_tenant = getattr(request, 'is_explicit_tenant', False)
        
    if not is_explicit_tenant or not school:
        return {'brand_name': 'Roshni SMS', 'brand_logo': False,
                'brand_primary': '#15294D', 'brand_accent': '#0E7C66',
                'current_session': '2025-26', 'my_photo': my_photo}
    return {
        'brand_name': school.name,
        'brand_logo': bool(school.logo),
        'brand_primary': school.primary_color or '#15294D',
        'brand_accent': school.accent_color or '#0E7C66',
        'current_session': school.session or '2025-26',
        'my_photo': my_photo,
    }


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
    from .models import Applicant, LeaveRequest, ConcessionRequest, OnlinePayment, InventoryItem, Submission, Announcement, Student, School
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
