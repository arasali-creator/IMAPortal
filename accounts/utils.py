from datetime import timedelta

from django.contrib.admin.models import LogEntry
from django.contrib.contenttypes.models import ContentType
from django.db.models import Q
from django.db.utils import OperationalError, ProgrammingError
from django.urls import reverse
from django.utils import timezone

from attendance.models import Attendance
from leaves.models import LeaveRequest
from .models import Employee, Team, Notification


def sync_notifications(cutoff):
    recent_entries = (
        LogEntry.objects.filter(action_time__gte=cutoff)
        .select_related("content_type", "user")
        .order_by("-action_time")
    )
    existing_ids = set(
        Notification.objects.filter(log_entry_id__in=recent_entries.values_list("id", flat=True))
        .values_list("log_entry_id", flat=True)
    )
    to_create = []
    for entry in recent_entries:
        if entry.pk in existing_ids:
            continue
        url = ""
        if entry.content_type and entry.object_id:
            try:
                url = reverse(
                    f"admin:{entry.content_type.app_label}_{entry.content_type.model}_change",
                    args=[entry.object_id],
                )
            except Exception:
                url = ""
        to_create.append(
            Notification(
                log_entry_id=entry.pk,
                actor=entry.user,
                content_type=entry.content_type,
                object_id=entry.object_id,
                object_repr=entry.object_repr,
                action_flag=entry.action_flag,
                change_message=entry.change_message,
                action_time=entry.action_time,
                url=url,
            )
        )
    if to_create:
        Notification.objects.bulk_create(to_create, ignore_conflicts=True)
    Notification.objects.filter(action_time__lt=cutoff).delete()


def notifications_queryset_for_user(user, qs=None):
    if qs is None:
        qs = Notification.objects.all()
    if not user.is_authenticated:
        return qs.none()
    role = getattr(user, "role", None)
    if user.is_superuser or role == "admin":
        return qs
    if role != "pm":
        return qs.none()

    teams = Team.objects.filter(project_manager=user)
    team_ids = list(teams.values_list("id", flat=True))
    member_ids = list(
        Employee.objects.filter(teams__project_manager=user)
        .values_list("id", flat=True)
        .distinct()
    )
    if user.id not in member_ids:
        member_ids.append(user.id)

    q = Q(actor=user)

    ct_employee = ContentType.objects.get_for_model(Employee)
    ct_team = ContentType.objects.get_for_model(Team)
    ct_leave = ContentType.objects.get_for_model(LeaveRequest)
    ct_att = ContentType.objects.get_for_model(Attendance)

    if member_ids:
        q |= Q(content_type=ct_employee, object_id__in=member_ids)
        leave_ids = LeaveRequest.objects.filter(employee_id__in=member_ids).values_list("id", flat=True)
        att_ids = Attendance.objects.filter(employee_id__in=member_ids).values_list("id", flat=True)
        q |= Q(content_type=ct_leave, object_id__in=leave_ids)
        q |= Q(content_type=ct_att, object_id__in=att_ids)

    if team_ids:
        q |= Q(content_type=ct_team, object_id__in=team_ids)

    return qs.filter(q)


def notifications_unread_badge(request):
    try:
        cutoff = timezone.now() - timedelta(days=30)
        sync_notifications(cutoff)
        qs = notifications_queryset_for_user(request.user, Notification.objects.filter(action_time__gte=cutoff))
        count = qs.filter(is_read=False).count()
        return count or ""
    except (OperationalError, ProgrammingError):
        return ""


def _has_perm(user, perm_codename):
    if user.is_superuser or getattr(user, "role", None) == "admin":
        return True
    return user.has_perm(perm_codename)


def can_view_employees(request):
    return _has_perm(request.user, "accounts.view_employee")


def can_view_teams(request):
    return _has_perm(request.user, "accounts.view_team")


def can_view_attendance(request):
    return _has_perm(request.user, "attendance.view_attendance")


def can_view_leaves(request):
    return _has_perm(request.user, "leaves.view_leaverequest")


def can_view_notifications(request):
    return _has_perm(request.user, "accounts.view_notification")




def can_view_payroll_incomes(request):
    return _has_perm(request.user, "payroll.view_pmincome")


def can_view_payroll_advances(request):
    return _has_perm(request.user, "payroll.view_pmadvance")


def can_view_payroll_splits(request):
    return _has_perm(request.user, "payroll.view_pmsplitsetting")


def can_view_employee_salary(request):
    return request.user.is_superuser or getattr(request.user, "role", None) in ["admin", "pm"]


def can_view_my_payroll(request):
    return getattr(request.user, "role", None) == "pm"


def can_view_pm_calculations(request):
    return request.user.is_superuser or getattr(request.user, "role", None) == "admin"


def can_view_global_settings(request):
    return request.user.is_superuser or getattr(request.user, "role", None) == "admin"


def can_view_company_summary(request):
    return request.user.is_superuser or getattr(request.user, "role", None) == "admin"


def can_view_branch_expenses(request):
    return request.user.is_superuser or getattr(request.user, "role", None) == "admin"
