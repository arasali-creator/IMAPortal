"""One-call user notifications: in-app record + branded HTML email (background thread)."""

import os
import threading

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

from .models import Employee, UserNotification

PORTAL_BASE_URL = os.environ.get("PORTAL_BASE_URL", "https://portal.imasalessolution.com").rstrip("/")


def _absolute_url(url):
    if not url:
        return PORTAL_BASE_URL
    if url.startswith("http://") or url.startswith("https://"):
        return url
    return f"{PORTAL_BASE_URL}{url}"


def _from_address():
    return getattr(settings, "DEFAULT_FROM_EMAIL", None) or settings.EMAIL_HOST_USER or "noreply@imasalessolution.com"


def _send_email_async(subject, title, body, recipients, greeting="", cta_url="", cta_label="Open Portal"):
    html = render_to_string("accounts/email/base_email.html", {
        "title": title,
        "body": body,
        "greeting": greeting,
        "cta_url": cta_url,
        "cta_label": cta_label,
    })
    text = f"{'Hello ' + greeting + ',' if greeting else ''}\n\n{body}\n\n{cta_url}\n\n— IMA Office Portal"

    def _send():
        try:
            msg = EmailMultiAlternatives(subject, text, _from_address(), recipients)
            msg.attach_alternative(html, "text/html")
            msg.send(fail_silently=True)
        except Exception:
            pass

    threading.Thread(target=_send, daemon=True).start()


def notify(user, title, body="", url="", email=True):
    """Create an in-app notification for `user` and email them (non-blocking)."""
    UserNotification.objects.create(recipient=user, title=title, body=body, url=url)
    if email and user.email:
        _send_email_async(
            f"IMA Office Portal — {title}",
            title,
            body or title,
            [user.email],
            greeting=user.get_short_name(),
            cta_url=_absolute_url(url),
            cta_label="View in Portal",
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
            title,
            body or title,
            emails,
            cta_url=_absolute_url(url),
            cta_label="Open in Console",
        )
