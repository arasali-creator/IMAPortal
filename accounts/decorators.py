from functools import wraps

from django.shortcuts import render


def role_required(*roles):
    """Restrict a view to superusers or employees whose `role` is in `roles`."""

    def decorator(view_func):
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            user = request.user
            if user.is_authenticated and (user.is_superuser or getattr(user, "role", None) in roles):
                return view_func(request, *args, **kwargs)
            return render(request, "console/403.html", status=403)

        return wrapped

    return decorator
