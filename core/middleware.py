"""Security middleware: force a first-login password change, and sign users
out after a period of inactivity. Both are no-ops for anonymous users and for
static/media requests (which are handled earlier by WhiteNoise)."""
import time

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.urls import reverse


class ForcePasswordChangeMiddleware:
    """If a user's login was auto-created (or reset), make them set their own
    password before they can use anything else."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, 'user', None)
        if user is not None and user.is_authenticated:
            profile = getattr(user, 'profile', None)
            if profile is not None and profile.must_change_password:
                allowed = {
                    reverse('password_change'),
                    reverse('password_change_done'),
                    reverse('logout'),
                }
                if request.path not in allowed:
                    messages.info(
                        request,
                        'For your security, please set a new password to '
                        'continue.')
                    return redirect('password_change')
        return self.get_response(request)


class SessionIdleTimeoutMiddleware:
    """Sign a user out after SESSION_IDLE_TIMEOUT seconds of no activity."""

    def __init__(self, get_response):
        self.get_response = get_response
        self.timeout = int(getattr(settings, 'SESSION_IDLE_TIMEOUT', 30 * 60))

    def __call__(self, request):
        user = getattr(request, 'user', None)
        if user is not None and user.is_authenticated and self.timeout > 0:
            now = int(time.time())
            last = request.session.get('last_activity')
            if last and (now - last) > self.timeout:
                logout(request)
                return redirect('%s?timeout=1' % reverse('login'))
            request.session['last_activity'] = now
        return self.get_response(request)


class TenantMiddleware:
    """Extracts tenant subdomain from the request host header and attaches the
    corresponding School model to request.tenant."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # 0. Restrict Django Admin to superusers only
        if request.path.startswith('/admin/'):
            user = getattr(request, 'user', None)
            if not (user and user.is_authenticated and user.is_superuser):
                from django.core.exceptions import PermissionDenied
                raise PermissionDenied
                
        host = request.get_host().split(':')[0]
        parts = host.split('.')
        
        # 1. Resolve subdomain
        subdomain = None
        if len(parts) > 2:
            subdomain = parts[0]
        elif len(parts) == 2 and parts[1] == 'localhost':
            subdomain = parts[0]
            
        from core.models import School
        school = None
        is_explicit_tenant = False
        
        if subdomain and subdomain not in ('www', 'localhost', '127'):
            school = School.objects.filter(subdomain=subdomain).first()
            if school:
                is_explicit_tenant = True
            
        # 2. Path-based resolution if no subdomain matches
        is_path_based = False
        if not school:
            path_parts = [p for p in request.path_info.split('/') if p]
            if path_parts:
                first_seg = path_parts[0]
                if first_seg not in ('saas-admin', 'admin', 'static', 'media', 'logout', 'subscription-expired'):
                    possible_school = School.objects.filter(subdomain=first_seg).first()
                    if possible_school:
                        school = possible_school
                        is_explicit_tenant = True
                        is_path_based = True
                        # Strip the prefix so Django URLs match normally
                        new_path = '/' + '/'.join(path_parts[1:])
                        if not new_path.endswith('/') and len(path_parts) > 1:
                            new_path += '/'
                        request.path_info = new_path
                        request.path = new_path
                        
        user = getattr(request, 'user', None)
        is_superuser = user.is_superuser if (user and user.is_authenticated) else False

        # Verify that the session's tenant matches the request's active school tenant!
        # If the session belongs to a different school/tenant, we log them out
        # to prevent session leakage across database boundaries.
        if user and user.is_authenticated:
            session_tenant_id = request.session.get('tenant_id')
            if is_superuser:
                # If they are superuser, they should only have a 'saas' session.
                # If they have a school tenant ID in the session, they are a tenant user leaked into root!
                if session_tenant_id and session_tenant_id != 'saas':
                    from django.contrib.auth import logout
                    logout(request)
                    user = None
                    is_superuser = False
            else:
                # If they are a regular school user, their session tenant ID must match the active school's ID!
                if not school or session_tenant_id != school.id:
                    from django.contrib.auth import logout
                    logout(request)
                    user = None
                    
        # 3. User session-based routing and verification
        is_superuser = user.is_superuser if (user and user.is_authenticated) else False
        
        # If the user is a superuser and visits a school portal (subdomain or path segment),
        # log them out to prevent auto-accessing the school portal as superuser.
        if is_superuser and is_explicit_tenant:
            allowed_paths = [
                reverse('logout_get'),
                '/static/',
                '/media/',
                '/saas-admin/'
            ]
            if not any(request.path.startswith(p) for p in allowed_paths):
                sub = school.subdomain or 'default'
                next_url = f"/{sub}/login/" if is_path_based else "/login/"
                return redirect(reverse('logout_get') + f"?next={next_url}")
        
        if user and user.is_authenticated and not is_superuser:
            profile = getattr(user, 'profile', None)
            if profile and profile.school:
                # If they visit a path with a different school subdomain/prefix, log them out
                if school and profile.school != school:
                    allowed_paths = [
                        reverse('logout_get'),
                        '/static/',
                        '/media/'
                    ]
                    if not any(request.path.startswith(p) for p in allowed_paths):
                        sub = profile.school.subdomain or 'default'
                        next_url = f"/{sub}/login/"
                        return redirect(reverse('logout_get') + f"?next={next_url}")
                elif not school:
                    # Keep them on their school
                    school = profile.school
                    is_explicit_tenant = True
                    
        # Fallback to the first school in the database if no tenant found
        if not school:
            school = School.objects.first()
            
        request.tenant = school
        
        # Calculate subscription status (using the global database record!)
        # Only lock down if it is an explicit school tenant request! The SaaS root/admin itself is never expired.
        from django.utils import timezone
        request.tenant_expired = False
        if school and is_explicit_tenant:
            today = timezone.localdate()
            if (school.subscription_end and school.subscription_end < today) or not school.subscription_active:
                request.tenant_expired = True
                
        # 4. Database-per-tenant SQLite switcher
        import os
        import shutil
        import copy
        from django.db import connections
        from django.conf import settings

        db_path = os.path.join(settings.BASE_DIR, "db.sqlite3")
        if school and school.subdomain and school.subdomain != 'default' and not request.path.startswith('/saas-admin/'):
            db_path = os.path.join(settings.BASE_DIR, f"{school.subdomain}.sqlite3")
            if not os.path.exists(db_path):
                shutil.copyfile(os.path.join(settings.BASE_DIR, "db.sqlite3"), db_path)

        conn = connections['default']
        conn.close()
        conn.settings_dict = copy.deepcopy(settings.DATABASES['default'])
        conn.settings_dict['NAME'] = db_path
                    
        if request.tenant_expired and not is_superuser:
            allowed_paths = [
                reverse('subscription_expired'),
                reverse('login'),
                reverse('logout'),
                '/saas-admin/',
                '/admin/',
                '/static/',
                '/media/'
            ]
            is_allowed = any(request.path.startswith(p) for p in allowed_paths)
            if not is_allowed:
                return redirect('subscription_expired')
                
        # Lazy Cron daily trigger
        if school:
            today = timezone.localdate()
            if not school.last_daily_run or school.last_daily_run < today:
                from core.views import run_daily_jobs
                try:
                    run_daily_jobs(school, today)
                    school.last_daily_run = today
                    school.save(update_fields=['last_daily_run'])
                except Exception as e:
                    print(f"[Automation Error] Failed to run daily jobs: {e}")
                    
        return self.get_response(request)
