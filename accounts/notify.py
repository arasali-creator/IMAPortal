"""One-call user notifications: in-app record + email (sent in a background thread)."""

import threading

from django.conf import settings
from django.core.mail import send_mail

from .models import Employee, UserNotification


def _send_email_async(subject, body, recipients):
    def _send():
        try:
            send_mail(
                subject,
                body,
                getattr(settings, "DEFAULT_FROM_EMAIL", None) or settings.EMAIL_HOST_USER or "noreply@imasalessolution.com",
                recipients,
                fail_silently=True,
            )
        except Exception:
            pass

    threading.Thread(target=_send, daemon=True).start()


def notify(user, title, body="", url="", email=True):
    """Create an in-app notification for `user` and email them (non-blocking)."""
    UserNotification.objects.create(recipient=user, title=title, body=body, url=url)
    if email and user.email:
        _send_email_async(
            f"IMA Office Portal — {title}",
            f"Hello {user.get_short_name()},\n\n{body or title}\n\n— IMA Office Portal",
            [user.email],
        )


def notify_admins(title, body="", url="", email=True):
    """Notify every active admin (in-app + email)."""
    admins = Employee.objects.filter(role="admin", is_active=True)
    emails = []
    for admin_user in admins:
        UserNotification.objects.create(recipient=admin_user, title=title, body=body, url=url)
        if admin_user.email:
            emails.append(admin_user.email)
    if email and emails:
        _send_email_async(
            f"IMA Office Portal — {title}",
            f"{body or title}\n\n— IMA Office Portal",
            emails,
        )
