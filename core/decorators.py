from functools import wraps

from django.http import HttpResponseForbidden


def role_required(*roles):
    """Allow the view only for users whose profile.role is in `roles`,
    or if they are an Administrator (role='admin').
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            profile = getattr(request.user, 'profile', None)
            if not request.user.is_authenticated or profile is None:
                return HttpResponseForbidden('You do not have access to this page.')
            # Admin role has access to everything
            if profile.role == 'admin' or profile.role in roles:
                return view_func(request, *args, **kwargs)
            return HttpResponseForbidden('You do not have access to this page.')
        return wrapper
    return decorator
