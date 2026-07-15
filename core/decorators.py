from functools import wraps

from django.http import HttpResponseForbidden


def role_required(*roles):
    """Allow the view only for users whose profile.role is in `roles`.

    Used to protect role-specific module pages we add in later phases,
    e.g. @role_required('teacher') on the attendance-marking view.
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            profile = getattr(request.user, 'profile', None)
            if (not request.user.is_authenticated or profile is None
                    or profile.role not in roles):
                return HttpResponseForbidden('You do not have access to this page.')
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator
