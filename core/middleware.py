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
        if subdomain and subdomain not in ('www', 'localhost', '127'):
            school = School.objects.filter(subdomain=subdomain).first()
            
        # 2. Path-based resolution if no subdomain matches
        if not school:
            path_parts = [p for p in request.path_info.split('/') if p]
            if path_parts:
                first_seg = path_parts[0]
                if first_seg not in ('saas-admin', 'admin', 'static', 'media', 'logout', 'subscription-expired'):
                    possible_school = School.objects.filter(subdomain=first_seg).first()
                    if possible_school:
                        school = possible_school
                        # Strip the prefix so Django URLs match normally
                        new_path = '/' + '/'.join(path_parts[1:])
                        if not new_path.endswith('/') and len(path_parts) > 1:
                            new_path += '/'
                        request.path_info = new_path
                        request.path = new_path
                        
        # 3. User session-based routing and verification
        user = getattr(request, 'user', None)
        is_superuser = user.is_superuser if (user and user.is_authenticated) else False
        
        if user and user.is_authenticated and not is_superuser:
            profile = getattr(user, 'profile', None)
            if profile and profile.school:
                # If they visit a path with a different school subdomain/prefix, log them out
                if school and profile.school != school:
                    allowed_paths = [
                        reverse('logout'),
                        '/static/',
                        '/media/'
                    ]
                    if not any(request.path.startswith(p) for p in allowed_paths):
                        logout(request)
                        messages.error(request, "Access denied. Please log in through your school's subdomain portal.")
                        return redirect('login')
                elif not school:
                    # Keep them on their school
                    school = profile.school
                    
        # Fallback to the first school in the database if no tenant found
        if not school:
            school = School.objects.first()
            
        request.tenant = school
        
        # Calculate subscription status
        from django.utils import timezone
        request.tenant_expired = False
        if school:
            today = timezone.localdate()
            if (school.subscription_end and school.subscription_end < today) or not school.subscription_active:
                request.tenant_expired = True
                    
        if request.tenant_expired and not is_superuser:
            allowed_paths = [
                reverse('subscription_expired'),
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
