from functools import wraps

from django.shortcuts import render


def role_required(*roles):
    """Restrict a view to employees whose `role` is in `roles`.

    Deliberately ignores `is_superuser` — that flag only controls access to
    Django's built-in /admin/, not the console. Console access is governed
    solely by the `role` field so that promote/demote actions actually take
    effect for every account, including ones that also have is_superuser set.
    """

    def decorator(view_func):
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            user = request.user
            if user.is_authenticated and getattr(user, "role", None) in roles:
                return view_func(request, *args, **kwargs)
            return render(request, "console/403.html", status=403)

        return wrapped

    return decorator
