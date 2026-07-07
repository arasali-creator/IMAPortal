import logging
from decimal import Decimal

from django.conf import settings
from django.core.mail import send_mail
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone

from .models import PMIncome

logger = logging.getLogger(__name__)


@receiver(post_save, sender=PMIncome)
def _notify_pm_on_income_added(sender, instance, created, **kwargs):
    if not created:
        return
    pm = instance.pm
    if not pm or not getattr(pm, "email", None):
        return

    created_by = instance.created_by
    if not created_by:
        return
    if not (getattr(created_by, "is_superuser", False) or getattr(created_by, "role", None) == "admin"):
        return

    subject = "Upwork Withdrawal Notification"
    pm_name = pm.full_name or pm.email
    withdraw_by = created_by.full_name or created_by.email
    amount_usd = f"{(instance.amount_usd or Decimal('0.00')):.2f}"
    amount_pkr = f"{instance.amount_pkr:.0f}"
    timestamp = timezone.localtime(instance.created_at).strftime("%Y-%m-%d %H:%M")
    message = (
        f"Dear {pm_name},\n\n"
        "This is to inform you that a withdrawal has been made from the Upwork account.\n\n"
        "Details:\n\n"
        f"Amount Withdrawn: ${amount_usd} (PKR {amount_pkr})\n\n"
        f"Withdrawn By: {withdraw_by}\n\n"
        f"Date & Time: {timestamp}\n\n"
        "If you have any questions regarding this transaction, please contact the admin.\n\n"
        "Best regards,\n"
        "Finance Department"
    )
    html_message = f"""
    <div style="background:#f7f8fc;padding:24px 16px;font-family:'Outfit',Arial,sans-serif;color:#0f172a;">
      <div style="max-width:640px;margin:0 auto;background:#ffffff;border:1px solid rgba(15,23,42,.10);border-radius:18px;box-shadow:0 18px 40px rgba(2,6,23,.08);overflow:hidden;">
        <div style="padding:18px 22px;background:linear-gradient(135deg, rgba(255,122,26,.18), rgba(255,102,0,.08));border-bottom:1px solid rgba(15,23,42,.08);">
          <div style="font-size:18px;font-weight:900;color:#181818;">Upwork Withdrawal Notification</div>
          <div style="font-size:13px;color:#64748b;margin-top:4px;">Office Portal • Finance Department</div>
        </div>
        <div style="padding:22px;">
          <p style="margin:0 0 12px 0;font-size:15px;">Dear <strong>{pm_name}</strong>,</p>
          <p style="margin:0 0 16px 0;color:#475569;">This is to inform you that a withdrawal has been made from the Upwork account.</p>
          <div style="border:1px solid rgba(15,23,42,.08);border-radius:14px;padding:14px 16px;background:#ffffff;">
            <div style="font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:#64748b;margin-bottom:8px;">Details</div>
            <table style="width:100%;border-collapse:collapse;font-size:14px;">
              <tr>
                <td style="padding:8px 0;color:#64748b;">Amount Withdrawn</td>
                <td style="padding:8px 0;font-weight:800;color:#0f172a;">${amount_usd} <span style="color:#64748b;font-weight:600;">(PKR {amount_pkr})</span></td>
              </tr>
              <tr>
                <td style="padding:8px 0;color:#64748b;">Withdrawn By</td>
                <td style="padding:8px 0;font-weight:800;color:#0f172a;">{withdraw_by}</td>
              </tr>
              <tr>
                <td style="padding:8px 0;color:#64748b;">Date & Time</td>
                <td style="padding:8px 0;font-weight:800;color:#0f172a;">{timestamp}</td>
              </tr>
            </table>
          </div>
          <p style="margin:16px 0 0 0;color:#475569;">If you have any questions regarding this transaction, please contact the admin.</p>
          <p style="margin:18px 0 0 0;font-weight:800;color:#181818;">Best regards,<br>Finance Department</p>
        </div>
        <div style="padding:14px 22px;border-top:1px solid rgba(15,23,42,.08);font-size:12px;color:#94a3b8;">
          This is an automated email from Office Portal.
        </div>
      </div>
    </div>
    """
    try:
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [pm.email],
            fail_silently=False,
            html_message=html_message,
        )
        if getattr(created_by, "email", None) and created_by.email != pm.email:
            send_mail(
                subject,
                message,
                settings.DEFAULT_FROM_EMAIL,
                [created_by.email],
                fail_silently=False,
                html_message=html_message,
            )
    except Exception:
        logger.exception("Failed to send income notification for PMIncome id=%s", instance.pk)
