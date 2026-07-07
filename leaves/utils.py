# leaves/utils.py
from django.contrib.admin.models import LogEntry, CHANGE
from django.contrib.contenttypes.models import ContentType

from .models import LeaveRequest


def apply_leave_decision(request, obj: LeaveRequest, decision: str):
    """Apply an Approved/Rejected decision to a leave request based on the acting user's role."""
    role = getattr(request.user, "role", None)

    if role == "pm":
        obj.pm_status = decision
    elif role == "admin" or request.user.is_superuser:
        obj.admin_status = decision
    else:
        return False

    if decision == "Approved":
        if obj.pm_status == "Approved" or obj.admin_status == "Approved":
            obj.status = "Approved"
    else:  # Rejected
        if obj.pm_status == "Rejected" and obj.admin_status == "Rejected":
            obj.status = "Rejected"

    obj.save()
    LogEntry.objects.log_action(
        user_id=request.user.pk,
        content_type_id=ContentType.objects.get_for_model(obj).pk,
        object_id=obj.pk,
        object_repr=str(obj),
        action_flag=CHANGE,
        change_message=f"Leave {decision.lower()} by {role or 'user'}",
    )
    return True
