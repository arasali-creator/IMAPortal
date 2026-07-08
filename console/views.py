import calendar
from datetime import date as date_cls
from datetime import time as time_cls
from datetime import timedelta
from decimal import Decimal
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Min, Max, Q
from django.db.models.functions import TruncMonth, TruncYear
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from accounts.decorators import role_required
from accounts.models import Employee, Notification, PasswordResetRequest, Team
from accounts.utils import notifications_queryset_for_user, sync_notifications
from attendance.models import Attendance
from leaves.models import LeaveRequest
from leaves.utils import apply_leave_decision
from payroll.models import (
    Branch,
    BranchExpense,
    EmployeeSalary,
    EmployeeSalaryExpense,
    EmployeeSalaryPayment,
    FixedExpense,
    PMAdvance,
    PMIncome,
    PMSplitSetting,
    PayrollGlobalSetting,
)
from payroll.utils import calculate_pm_available_balance, summarize_employee_salary, team_members_for_pm
from payroll.views import build_pm_payroll_context

from .forms import EmployeeCreateForm, EmployeeEditForm, TeamForm

STAFF_ROLES = ("admin", "pm")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _format_time(dt):
    if not dt:
        return "-"
    return timezone.localtime(dt).strftime("%H:%M")


def _month_options():
    return [
        (1, "January"), (2, "February"), (3, "March"), (4, "April"),
        (5, "May"), (6, "June"), (7, "July"), (8, "August"),
        (9, "September"), (10, "October"), (11, "November"), (12, "December"),
    ]


def _year_options(today):
    current_year = today.year
    return list(range(current_year - 4, current_year + 1))


def _current_period(request, today):
    period = request.GET.get("period", "month")
    year = int(request.GET.get("year", today.year))
    month = int(request.GET.get("month", today.month))
    return period, year, month


def _redirect_with_query(request, **extra_params):
    params = request.GET.copy()
    for key, value in extra_params.items():
        if value in [None, ""]:
            params.pop(key, None)
        else:
            params[key] = value
    query = urlencode(params, doseq=True)
    return HttpResponseRedirect(f"{request.path}?{query}" if query else request.path)


def _is_admin(request):
    return getattr(request.user, "role", None) == "admin"


def _pm_team_member_ids(user):
    """Employees managed by this PM — does not include the PM themselves."""
    teams = Team.objects.filter(project_manager=user)
    ids = set()
    for team in teams.prefetch_related("members"):
        ids.update(team.members.values_list("id", flat=True))
    return ids


def _pm_scope_ids(user):
    """Team members plus the PM's own id — used for attendance/leaves so a PM sees their own records too."""
    return _pm_team_member_ids(user) | {user.id}


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@login_required
@role_required(*STAFF_ROLES)
def dashboard_view(request):
    today = timezone.localdate()

    employees_qs = Employee.objects.all()
    attendance_qs = Attendance.objects.select_related("employee")
    if not _is_admin(request):
        member_ids = _pm_team_member_ids(request.user)
        employees_qs = employees_qs.filter(id__in=member_ids)
        attendance_qs = attendance_qs.filter(employee_id__in=_pm_scope_ids(request.user))

    recent_employees = []
    for emp in employees_qs.order_by("-date_joined")[:5]:
        recent_employees.append(
            {
                "name": emp.full_name or emp.email or emp.cnic,
                "email": emp.email,
                "department": emp.get_department_display() if emp.department else "-",
                "role": emp.get_role_display() if emp.role else "-",
                "date_joined": emp.date_joined,
            }
        )

    recent_attendance = []
    for log in attendance_qs.order_by("-check_in")[:5]:
        recent_attendance.append(
            {
                "employee": str(log.employee),
                "date": log.check_in.date() if log.check_in else today,
                "check_in": _format_time(log.check_in),
                "check_out": _format_time(log.check_out),
                "hours_worked": log.hours_worked,
            }
        )

    context = {
        "employees_count": employees_qs.count(),
        "attendance_today": attendance_qs.filter(check_in__date=today).count(),
        "recent_employees": recent_employees,
        "recent_attendance": recent_attendance,
    }
    return render(request, "console/dashboard.html", context)


# ---------------------------------------------------------------------------
# Employees
# ---------------------------------------------------------------------------

@login_required
@role_required(*STAFF_ROLES)
def employees_list(request):
    qs = Employee.objects.all().order_by("-date_joined")
    if not _is_admin(request):
        qs = qs.filter(teams__project_manager=request.user).distinct()

    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(full_name__icontains=q) | qs.filter(cnic__icontains=q) | qs.filter(email__icontains=q)

    return render(request, "console/employees_list.html", {"employees": qs, "q": q})


@login_required
@role_required(*STAFF_ROLES)
def employee_detail(request, pk):
    qs = Employee.objects.all()
    if not _is_admin(request):
        qs = qs.filter(teams__project_manager=request.user).distinct()
    employee = get_object_or_404(qs, pk=pk)

    if request.method == "POST":
        form = EmployeeEditForm(request.POST, request.FILES, instance=employee)
        if form.is_valid():
            form.save()
            messages.success(request, "Employee updated.")
            return redirect("console:employee_detail", pk=employee.pk)
    else:
        form = EmployeeEditForm(instance=employee)

    return render(request, "console/employee_detail.html", {"employee": employee, "form": form})


@login_required
@role_required("admin")
def employee_create(request):
    if request.method == "POST":
        form = EmployeeCreateForm(request.POST)
        if form.is_valid():
            employee = form.save()
            messages.success(request, f"{employee} created.")
            return redirect("console:employee_detail", pk=employee.pk)
    else:
        form = EmployeeCreateForm()
    return render(request, "console/employee_form.html", {"form": form})


@login_required
@role_required("admin")
def employee_delete(request, pk):
    employee = get_object_or_404(Employee, pk=pk)
    if request.method == "POST":
        if employee.pk == request.user.pk:
            messages.error(request, "You cannot delete your own account.")
        else:
            name = str(employee)
            employee.delete()
            messages.success(request, f"{name} deleted.")
    return redirect("console:employees_list")


@login_required
@role_required("admin")
def employees_bulk_delete(request):
    if request.method == "POST":
        ids = request.POST.getlist("selected")
        qs = Employee.objects.filter(pk__in=ids).exclude(pk=request.user.pk)
        count = qs.count()
        for employee in qs:
            employee.delete()
        if count:
            messages.success(request, f"Deleted {count} employee(s).")
        else:
            messages.error(request, "No employees selected.")
    return redirect("console:employees_list")


@login_required
@role_required("admin")
def employee_approve(request, pk):
    employee = get_object_or_404(Employee, pk=pk)
    if request.method == "POST":
        employee.is_active = True
        employee.save(update_fields=["is_active"])
        messages.success(request, f"{employee} approved.")
    return redirect(request.META.get("HTTP_REFERER") or "console:employees_list")


@login_required
@role_required("admin")
def employee_promote(request, pk):
    employee = get_object_or_404(Employee, pk=pk)
    if request.method == "POST":
        employee.role = "pm"
        employee.save(update_fields=["role"])
        messages.success(request, f"{employee} promoted to Project Manager.")
    return redirect(request.META.get("HTTP_REFERER") or "console:employees_list")


@login_required
@role_required("admin")
def employee_demote(request, pk):
    employee = get_object_or_404(Employee, pk=pk)
    if request.method == "POST":
        employee.role = "employee"
        employee.save(update_fields=["role"])
        messages.success(request, f"{employee} demoted to Employee.")
    return redirect(request.META.get("HTTP_REFERER") or "console:employees_list")


# ---------------------------------------------------------------------------
# Teams
# ---------------------------------------------------------------------------

@login_required
@role_required(*STAFF_ROLES)
def teams_list(request):
    qs = Team.objects.select_related("project_manager").prefetch_related("members")
    if not _is_admin(request):
        qs = qs.filter(project_manager=request.user)
    return render(request, "console/teams_list.html", {"teams": qs})


@login_required
@role_required("admin")
def team_create(request):
    if request.method == "POST":
        form = TeamForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Team created.")
            return redirect("console:teams_list")
    else:
        form = TeamForm()
    return render(request, "console/team_form.html", {"form": form, "team": None})


@login_required
@role_required("admin")
def team_edit(request, pk):
    team = get_object_or_404(Team, pk=pk)
    if request.method == "POST":
        form = TeamForm(request.POST, instance=team)
        if form.is_valid():
            form.save()
            messages.success(request, "Team updated.")
            return redirect("console:teams_list")
    else:
        form = TeamForm(instance=team)
    return render(request, "console/team_form.html", {"form": form, "team": team})


@login_required
@role_required("admin")
def team_delete(request, pk):
    team = get_object_or_404(Team, pk=pk)
    if request.method == "POST":
        team.delete()
        messages.success(request, "Team deleted.")
    return redirect("console:teams_list")


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

@login_required
@role_required(*STAFF_ROLES)
def notifications_list(request):
    cutoff = timezone.now() - timedelta(days=30)
    sync_notifications(cutoff)
    qs = notifications_queryset_for_user(request.user, Notification.objects.filter(action_time__gte=cutoff))
    return render(
        request,
        "console/notifications_list.html",
        {
            "notifications": qs.order_by("-action_time"),
            "notif_total": qs.count(),
            "notif_unread": qs.filter(is_read=False).count(),
        },
    )


@login_required
@role_required(*STAFF_ROLES)
def notification_mark_read(request, pk):
    qs = notifications_queryset_for_user(request.user, Notification.objects.all())
    qs.filter(pk=pk).update(is_read=True)
    return redirect(request.META.get("HTTP_REFERER") or "console:notifications_list")


@login_required
@role_required(*STAFF_ROLES)
def notification_mark_all_read(request):
    qs = notifications_queryset_for_user(request.user, Notification.objects.all())
    qs.update(is_read=True)
    return redirect(request.META.get("HTTP_REFERER") or "console:notifications_list")


@login_required
def notification_unread_count(request):
    cutoff = timezone.now() - timedelta(days=30)
    sync_notifications(cutoff)
    qs = notifications_queryset_for_user(request.user, Notification.objects.filter(action_time__gte=cutoff))
    return JsonResponse({"ok": True, "count": qs.filter(is_read=False).count()})


# ---------------------------------------------------------------------------
# Password reset requests
# ---------------------------------------------------------------------------

@login_required
@role_required("admin")
def password_resets_list(request):
    qs = PasswordResetRequest.objects.select_related("employee").order_by("-created_at")
    return render(request, "console/password_resets_list.html", {"requests": qs})


@login_required
@role_required("admin")
def password_reset_mark_resolved(request, pk):
    reset_request = get_object_or_404(PasswordResetRequest, pk=pk)
    if request.method == "POST":
        reset_request.status = "resolved"
        reset_request.resolved_at = timezone.now()
        reset_request.save(update_fields=["status", "resolved_at"])
        messages.success(request, "Marked resolved.")
    return redirect("console:password_resets_list")


# ---------------------------------------------------------------------------
# Attendance
# ---------------------------------------------------------------------------

LATE_AFTER = time_cls(10, 15)


def _attendance_base_qs(request):
    qs = Attendance.objects.select_related("employee")
    employees_qs = Employee.objects.all()
    if not _is_admin(request):
        scope_ids = _pm_scope_ids(request.user)
        qs = qs.filter(employee_id__in=scope_ids)
        employees_qs = employees_qs.filter(id__in=scope_ids)
    return qs, employees_qs


def _month_start(d):
    return d.replace(day=1)


def _next_month(d):
    if d.month == 12:
        return d.replace(year=d.year + 1, month=1, day=1)
    return d.replace(month=d.month + 1, day=1)


@login_required
@role_required(*STAFF_ROLES)
def attendance_list(request):
    today = timezone.localdate()
    base_qs, employees_qs = _attendance_base_qs(request)

    todays_qs = base_qs.filter(check_in__date=today).order_by("employee_id", "-check_in")
    latest_by_employee = {}
    for att in todays_qs:
        if att.employee_id not in latest_by_employee:
            latest_by_employee[att.employee_id] = att
    todays_cards = list(latest_by_employee.values())

    total_employees = employees_qs.count()
    present_ids = set(latest_by_employee.keys())
    present_count = len(present_ids)
    late_ids = set(
        todays_qs.filter(check_in__time__gt=LATE_AFTER).values_list("employee_id", flat=True).distinct()
    )
    late_count = len(late_ids)
    pending_checkout_count = sum(1 for a in todays_cards if a.check_out is None)
    completed_hours = [a.hours_worked for a in todays_cards if a.check_out]
    avg_hours_worked = round(sum(completed_hours) / len(completed_hours), 2) if completed_hours else 0
    absent_count = max(total_employees - present_count, 0)
    absent_employees = employees_qs.exclude(id__in=present_ids)[:12]

    approved_leaves = LeaveRequest.objects.filter(status="Approved")
    if not _is_admin(request):
        approved_leaves = approved_leaves.filter(employee__in=employees_qs)
    total_employees_all = employees_qs.count()

    min_att = base_qs.aggregate(min_date=Min("check_in"), max_date=Max("check_in"))
    min_leave = approved_leaves.aggregate(min_date=Min("start_date"), max_date=Max("end_date"))
    min_date = min(
        [d.date() if hasattr(d, "date") else d for d in [min_att["min_date"], min_leave["min_date"]] if d] or [None]
    )
    max_date = max(
        [d.date() if hasattr(d, "date") else d for d in [min_att["max_date"], min_leave["max_date"]] if d] or [None]
    )

    month_rows, year_rows = [], []
    if min_date and max_date:
        cursor = _month_start(min_date)
        end = _next_month(_month_start(max_date))
        while cursor < end:
            nxt = _next_month(cursor)
            present_ids_m = set(
                base_qs.filter(check_in__date__gte=cursor, check_in__date__lt=nxt)
                .values_list("employee_id", flat=True).distinct()
            )
            on_leave_ids = set(
                approved_leaves.filter(start_date__lte=nxt, end_date__gte=cursor)
                .values_list("employee_id", flat=True).distinct()
            )
            absent_c = max(total_employees_all - len(present_ids_m | on_leave_ids), 0)
            month_rows.append({
                "label": cursor.strftime("%b %Y"),
                "present": len(present_ids_m), "absent": absent_c, "on_leave": len(on_leave_ids),
            })
            cursor = nxt

        for y in range(min_date.year, max_date.year + 1):
            y_start, y_end = date_cls(y, 1, 1), date_cls(y + 1, 1, 1)
            present_ids_y = set(
                base_qs.filter(check_in__date__gte=y_start, check_in__date__lt=y_end)
                .values_list("employee_id", flat=True).distinct()
            )
            on_leave_ids = set(
                approved_leaves.filter(start_date__lte=y_end, end_date__gte=y_start)
                .values_list("employee_id", flat=True).distinct()
            )
            absent_c = max(total_employees_all - len(present_ids_y | on_leave_ids), 0)
            year_rows.append({
                "year": y, "present": len(present_ids_y), "absent": absent_c, "on_leave": len(on_leave_ids),
            })

    context = {
        "today": today,
        "late_after": LATE_AFTER.strftime("%I:%M %p"),
        "total_employees": total_employees,
        "present_count": present_count,
        "late_count": late_count,
        "pending_checkout_count": pending_checkout_count,
        "absent_count": absent_count,
        "avg_hours_worked": avg_hours_worked,
        "todays_cards": todays_cards,
        "absent_employees": absent_employees,
        "month_rows": month_rows,
        "year_rows": year_rows,
    }
    return render(request, "console/attendance_list.html", context)


@login_required
@role_required(*STAFF_ROLES)
def attendance_monthly(request):
    today = timezone.localdate()
    year = max(2000, min(int(request.GET.get("year", today.year)), 2100))
    month = max(1, min(int(request.GET.get("month", today.month)), 12))
    _, days_in_month = calendar.monthrange(year, month)

    days = []
    for d in range(1, days_in_month + 1):
        dt = date_cls(year, month, d)
        days.append({"day": d, "weekday": dt.strftime("%a")[0], "is_weekend": dt.weekday() >= 5, "date": dt})

    month_start_d, month_end_d = date_cls(year, month, 1), date_cls(year, month, days_in_month)
    base_qs, employees_qs = _attendance_base_qs(request)
    employees = employees_qs.order_by("full_name", "email")

    month_att = (
        base_qs.filter(check_in__date__gte=month_start_d, check_in__date__lte=month_end_d)
        .values("employee_id", "check_in__date").annotate(first_in=Min("check_in"))
    )
    present_map = {(x["employee_id"], x["check_in__date"]): x["first_in"] for x in month_att}

    rows = []
    for e in employees:
        cells = []
        for info in days:
            dt = info["date"]
            if info["is_weekend"]:
                cells.append({"type": "weekend", "tooltip": "Weekend"})
                continue
            first_in = present_map.get((e.id, dt))
            if first_in:
                cells.append({"type": "present", "tooltip": f"Present · In {timezone.localtime(first_in).strftime('%I:%M %p')}"})
            else:
                cells.append({"type": "absent", "tooltip": "Absent"})
        rows.append({"employee": e, "cells": cells})

    prev_year, prev_month = (year - 1, 12) if month == 1 else (year, month - 1)
    next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)

    context = {
        "year": year, "month": month, "month_label": f"{calendar.month_abbr[month]} {year}",
        "prev_year": prev_year, "prev_month": prev_month, "next_year": next_year, "next_month": next_month,
        "days": days, "rows": rows,
    }
    return render(request, "console/attendance_monthly.html", context)


@login_required
@role_required(*STAFF_ROLES)
def attendance_employee_detail(request, employee_id):
    today = timezone.localdate()
    year = max(2000, min(int(request.GET.get("year", today.year)), 2100))
    month = max(1, min(int(request.GET.get("month", today.month)), 12))

    employee = get_object_or_404(Employee, pk=employee_id)
    if not _is_admin(request):
        if employee.id not in _pm_scope_ids(request.user):
            return render(request, "console/403.html", status=403)

    _, days_in_month = calendar.monthrange(year, month)
    month_start_d, month_end_d = date_cls(year, month, 1), date_cls(year, month, days_in_month)

    days = []
    for d in range(1, days_in_month + 1):
        dt = date_cls(year, month, d)
        days.append({"day": d, "weekday": dt.strftime("%a")[0], "is_weekend": dt.weekday() >= 5, "date": dt})

    month_att = (
        Attendance.objects.filter(employee_id=employee_id, check_in__date__gte=month_start_d, check_in__date__lte=month_end_d)
        .values("check_in__date").annotate(first_in=Min("check_in"))
    )
    present_map = {x["check_in__date"]: x["first_in"] for x in month_att}

    cells = []
    for info in days:
        dt = info["date"]
        if info["is_weekend"]:
            cells.append({"type": "weekend", "tooltip": "Weekend"})
            continue
        first_in = present_map.get(dt)
        if first_in:
            cells.append({"type": "present", "tooltip": f"Present · In {timezone.localtime(first_in).strftime('%I:%M %p')}"})
        else:
            cells.append({"type": "absent", "tooltip": "Absent"})

    recent_qs = Attendance.objects.filter(employee_id=employee_id).order_by("-check_in")[:25]

    prev_year, prev_month = (year - 1, 12) if month == 1 else (year, month - 1)
    next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)

    context = {
        "employee": employee, "year": year, "month": month, "month_label": f"{calendar.month_name[month]} {year}",
        "prev_year": prev_year, "prev_month": prev_month, "next_year": next_year, "next_month": next_month,
        "days": days, "cells": cells, "recent_qs": recent_qs,
    }
    return render(request, "console/attendance_employee_detail.html", context)


# ---------------------------------------------------------------------------
# Leave requests
# ---------------------------------------------------------------------------

@login_required
@role_required(*STAFF_ROLES)
def leaves_list(request):
    qs = LeaveRequest.objects.select_related("employee").order_by("-created_at")
    if not _is_admin(request):
        qs = qs.filter(employee_id__in=_pm_scope_ids(request.user))

    status = request.GET.get("status")
    filtered_qs = qs.filter(status=status) if status else qs

    totals = qs.aggregate(
        total=Count("id"),
        approved=Count("id", filter=Q(status="Approved")),
        rejected=Count("id", filter=Q(status="Rejected")),
        pending=Count("id", filter=Q(status="Pending")),
    )

    month_rows = []
    monthly = (
        qs.annotate(m=TruncMonth("created_at")).values("m")
        .annotate(
            total=Count("id"), approved=Count("id", filter=Q(status="Approved")),
            rejected=Count("id", filter=Q(status="Rejected")), pending=Count("id", filter=Q(status="Pending")),
        ).order_by("m")
    )
    for row in monthly:
        if not row["m"]:
            continue
        month_rows.append({
            "label": row["m"].strftime("%b %Y"),
            "total": row["total"] or 0, "approved": row["approved"] or 0,
            "rejected": row["rejected"] or 0, "pending": row["pending"] or 0,
        })

    year_rows = []
    yearly = (
        qs.annotate(y=TruncYear("created_at")).values("y")
        .annotate(
            total=Count("id"), approved=Count("id", filter=Q(status="Approved")),
            rejected=Count("id", filter=Q(status="Rejected")), pending=Count("id", filter=Q(status="Pending")),
        ).order_by("y")
    )
    for row in yearly:
        if not row["y"]:
            continue
        year_rows.append({
            "year": row["y"].year,
            "total": row["total"] or 0, "approved": row["approved"] or 0,
            "rejected": row["rejected"] or 0, "pending": row["pending"] or 0,
        })

    context = {
        "leaves": filtered_qs, "status": status,
        "summary": totals, "month_rows": month_rows, "year_rows": year_rows,
    }
    return render(request, "console/leaves_list.html", context)


@login_required
@role_required(*STAFF_ROLES)
def leave_approve(request, pk):
    leave = get_object_or_404(LeaveRequest.objects.select_related("employee"), pk=pk)
    if request.method == "POST":
        if apply_leave_decision(request, leave, "Approved"):
            messages.success(request, "Leave approved.")
        else:
            messages.error(request, "You are not allowed to approve.")
    return redirect(request.META.get("HTTP_REFERER") or "console:leaves_list")


@login_required
@role_required(*STAFF_ROLES)
def leave_reject(request, pk):
    leave = get_object_or_404(LeaveRequest.objects.select_related("employee"), pk=pk)
    if request.method == "POST":
        if apply_leave_decision(request, leave, "Rejected"):
            messages.success(request, "Leave rejected.")
        else:
            messages.error(request, "You are not allowed to reject.")
    return redirect(request.META.get("HTTP_REFERER") or "console:leaves_list")


# ---------------------------------------------------------------------------
# PM calculations (admin only) — ported from office_portal/custom_admin.py
# ---------------------------------------------------------------------------

@login_required
@role_required("admin")
def pm_calculations_view(request):
    pms = Employee.objects.filter(role="pm").order_by("full_name", "email")
    paid_by_users = Employee.objects.filter(role__in=["pm", "admin"]).order_by("full_name", "email")
    today = timezone.localdate()
    period, year, month = _current_period(request, today)

    selected_pm_id = request.GET.get("pm")
    selected_pm = None
    summary = None
    incomes = PMIncome.objects.none()
    advances = PMAdvance.objects.none()
    salary_data = {
        "salaries": EmployeeSalary.objects.none(),
        "expenses": EmployeeSalaryExpense.objects.none(),
        "payments": EmployeeSalaryPayment.objects.none(),
        "employee_rows": [],
        "total_income_pkr": Decimal("0.00"),
        "total_expenses_pkr": Decimal("0.00"),
        "total_paid_pkr": Decimal("0.00"),
        "total_balance_pkr": Decimal("0.00"),
        "total_balance_usd": Decimal("0.00"),
    }

    if request.method == "POST":
        action = request.POST.get("action")
        redirect_pm = selected_pm_id or request.POST.get("pm_id")
        if action == "edit_income":
            income_id = request.POST.get("income_id")
            note = (request.POST.get("note") or "").strip()
            amount_usd = request.POST.get("amount_usd") or "0"
            withdrawn_at = request.POST.get("withdrawn_at") or today
            withdrawn_by_id = request.POST.get("withdrawn_by") or None
            if income_id:
                try:
                    income = PMIncome.objects.get(pk=income_id)
                    income.description = note
                    income.amount_usd = Decimal(amount_usd or "0.00")
                    income.income_date = withdrawn_at
                    income.withdrawn_at = withdrawn_at
                    withdrawn_by = Employee.objects.filter(pk=withdrawn_by_id).first() if withdrawn_by_id else None
                    income.withdrawn_by = withdrawn_by
                    income.withdrawn_by_ceo = (
                        True if withdrawn_by and getattr(withdrawn_by, "role", None) == "admin" else False
                    )
                    if "rate_usd_to_pkr" not in request.POST:
                        income.rate_usd_to_pkr = PayrollGlobalSetting.current_rate()
                    income.save()
                except PMIncome.DoesNotExist:
                    pass
            return _redirect_with_query(request, pm=redirect_pm, period=period, year=year, month=month)
        if action == "delete_income":
            income_id = request.POST.get("income_id")
            if income_id:
                PMIncome.objects.filter(pk=income_id).delete()
            return _redirect_with_query(request, pm=redirect_pm, period=period, year=year, month=month)
        if action == "edit_advance":
            advance_id = request.POST.get("advance_id")
            advance_type = request.POST.get("advance_type") or "cash_taken"
            amount_pkr = request.POST.get("amount_pkr") or "0"
            note = (request.POST.get("note") or "").strip()
            advance_date = request.POST.get("advance_date") or today
            paid_by_id = request.POST.get("paid_by") or None
            if advance_id:
                try:
                    adv = PMAdvance.objects.get(pk=advance_id)
                    adv.advance_type = advance_type
                    adv.amount_pkr = Decimal(amount_pkr or "0.00")
                    adv.advance_date = advance_date
                    adv.notes = note
                    adv.paid_by_id = paid_by_id or None
                    adv.save()
                except PMAdvance.DoesNotExist:
                    pass
            return _redirect_with_query(request, pm=redirect_pm, period=period, year=year, month=month)
        if action == "delete_advance":
            advance_id = request.POST.get("advance_id")
            if advance_id:
                PMAdvance.objects.filter(pk=advance_id).delete()
            return _redirect_with_query(request, pm=redirect_pm, period=period, year=year, month=month)
        if action == "add_income":
            pm_id = request.POST.get("pm_id")
            note = (request.POST.get("note") or "").strip()
            amount_usd = request.POST.get("amount_usd") or "0"
            withdrawn_at = request.POST.get("withdrawn_at") or today
            withdrawn_by_id = request.POST.get("withdrawn_by") or None
            if pm_id:
                pm = Employee.objects.filter(role="pm", pk=pm_id).first()
                if pm:
                    pm_share_percent = getattr(getattr(pm, "pm_split_setting", None), "pm_share_percent", None)
                    rate = PayrollGlobalSetting.current_rate()
                    withdrawn_by = Employee.objects.filter(pk=withdrawn_by_id).first() if withdrawn_by_id else None
                    withdrawn_by_ceo = (
                        True if withdrawn_by and getattr(withdrawn_by, "role", None) == "admin" else False
                    )
                    PMIncome.objects.create(
                        pm=pm,
                        source="upwork",
                        description=note,
                        amount_usd=Decimal(amount_usd or "0.00"),
                        rate_usd_to_pkr=rate,
                        pm_share_percent=pm_share_percent if pm_share_percent is not None else Decimal("50.00"),
                        income_date=withdrawn_at,
                        withdrawn_by_ceo=withdrawn_by_ceo,
                        withdrawn_by=withdrawn_by,
                        withdrawn_at=withdrawn_at,
                        created_by=request.user,
                    )
            return _redirect_with_query(request, pm=pm_id or redirect_pm, period=period, year=year, month=month)
        if action == "add_advance":
            pm_id = request.POST.get("pm_id")
            advance_type = request.POST.get("advance_type") or "cash_taken"
            amount_pkr = request.POST.get("amount_pkr") or "0"
            note = (request.POST.get("note") or "").strip()
            advance_date = request.POST.get("advance_date") or today
            paid_by_id = request.POST.get("paid_by") or None
            if pm_id:
                pm = Employee.objects.filter(role="pm", pk=pm_id).first()
                if pm:
                    PMAdvance.objects.create(
                        pm=pm,
                        advance_type=advance_type,
                        amount_pkr=Decimal(amount_pkr or "0.00"),
                        advance_date=advance_date,
                        notes=note,
                        paid_by_id=paid_by_id or None,
                        created_by=request.user,
                    )
            return _redirect_with_query(request, pm=pm_id or redirect_pm, period=period, year=year, month=month)

    if selected_pm_id:
        selected_pm = get_object_or_404(pms, pk=selected_pm_id)
        incomes = PMIncome.objects.filter(pm=selected_pm)
        advances = PMAdvance.objects.filter(pm=selected_pm)
        if period == "year":
            incomes = incomes.filter(income_date__year=year)
            advances = advances.filter(advance_date__year=year)
        else:
            incomes = incomes.filter(income_date__year=year, income_date__month=month)
            advances = advances.filter(advance_date__year=year, advance_date__month=month)

        total_income_usd = Decimal("0.00")
        total_income_pkr = Decimal("0.00")
        total_pm_share_usd = Decimal("0.00")
        total_pm_share_pkr = Decimal("0.00")
        for income in incomes:
            total_income_usd += income.amount_usd or Decimal("0.00")
            total_income_pkr += income.amount_pkr
            total_pm_share_usd += income.pm_share_usd
            total_pm_share_pkr += income.pm_share_pkr

        total_advances_usd = Decimal("0.00")
        total_advances_pkr = Decimal("0.00")
        cash_online_usd = Decimal("0.00")
        cash_online_pkr = Decimal("0.00")
        jobs_connects_usd = Decimal("0.00")
        jobs_connects_pkr = Decimal("0.00")
        for adv in advances:
            total_advances_usd += adv.amount_usd or Decimal("0.00")
            total_advances_pkr += adv.amount_pkr
            if adv.advance_type in ["cash_taken", "online_taken"]:
                cash_online_usd += adv.amount_usd or Decimal("0.00")
                cash_online_pkr += adv.amount_pkr
            if adv.advance_type in ["upwork_job_paid", "upwork_connects"]:
                jobs_connects_usd += adv.amount_usd or Decimal("0.00")
                jobs_connects_pkr += adv.amount_pkr

        split_percent = Decimal("50.00")
        setting = getattr(selected_pm, "pm_split_setting", None)
        if setting and setting.pm_share_percent is not None:
            split_percent = setting.pm_share_percent

        salary_data = summarize_employee_salary(pm=selected_pm, period=period, year=year, month=month)
        salary_balance_pkr = salary_data["total_balance_pkr"]
        salary_balance_usd = salary_data["total_balance_usd"]
        salary_paid_pkr = salary_data["total_paid_pkr"]
        rate = PayrollGlobalSetting.current_rate()
        salary_paid_usd = salary_paid_pkr / rate if rate else Decimal("0.00")
        for row in salary_data["employee_rows"]:
            row["pm_share_pkr"] = row["paid_pkr"] * split_percent / Decimal("100.00")
        jobs_connects_divided_usd = jobs_connects_usd * split_percent / Decimal("100.00")
        jobs_connects_divided_pkr = jobs_connects_pkr * split_percent / Decimal("100.00")
        salary_divided_usd = salary_paid_usd * split_percent / Decimal("100.00")
        salary_divided_pkr = salary_paid_pkr * split_percent / Decimal("100.00")
        available_balance_usd = calculate_pm_available_balance(
            total_pm_share_usd,
            jobs_connects_divided_usd + salary_divided_usd,
            cash_online_usd,
        )
        available_balance_pkr = calculate_pm_available_balance(
            total_pm_share_pkr,
            jobs_connects_divided_pkr + salary_divided_pkr,
            cash_online_pkr,
        )

        summary = {
            "total_income_usd": total_income_usd,
            "total_income_pkr": total_income_pkr,
            "total_pm_share_usd": total_pm_share_usd,
            "total_pm_share_pkr": total_pm_share_pkr,
            "total_advances_usd": total_advances_usd,
            "total_advances_pkr": total_advances_pkr,
            "balance_usd": total_pm_share_usd - total_advances_usd,
            "balance_pkr": total_pm_share_pkr - total_advances_pkr,
            "cash_online_usd": cash_online_usd,
            "cash_online_pkr": cash_online_pkr,
            "jobs_connects_divided_usd": jobs_connects_divided_usd,
            "jobs_connects_divided_pkr": jobs_connects_divided_pkr,
            "salary_balance_usd": salary_balance_usd,
            "salary_balance_pkr": salary_balance_pkr,
            "salary_paid_usd": salary_paid_usd,
            "salary_paid_pkr": salary_paid_pkr,
            "salary_divided_usd": salary_divided_usd,
            "salary_divided_pkr": salary_divided_pkr,
            "split_percent": split_percent,
            "available_balance_usd": available_balance_usd,
            "available_balance_pkr": available_balance_pkr,
        }

    context = {
        "title": "PM Calculations",
        "pms": pms,
        "selected_pm": selected_pm,
        "summary": summary,
        "incomes": incomes,
        "advances": advances,
        "salary_rows": salary_data["employee_rows"],
        "salary_entries": salary_data["salaries"],
        "salary_expenses": salary_data["expenses"],
        "salary_payments": salary_data["payments"],
        "paid_by_users": paid_by_users,
        "today": today,
        "current_user_id": request.user.id,
        "period": period,
        "year": year,
        "month": month,
        "year_options": _year_options(today),
        "months": _month_options(),
    }
    return render(request, "console/pm_calculations.html", context)


# ---------------------------------------------------------------------------
# My Payroll (pm only) — same numbers as the admin "My Payroll" page
# ---------------------------------------------------------------------------

@login_required
@role_required("pm")
def my_payroll_view(request):
    context = build_pm_payroll_context(request, request.user)
    return render(request, "console/my_payroll.html", context)


# ---------------------------------------------------------------------------
# Employee salary (admin + pm, scoped to own team) — ported
# ---------------------------------------------------------------------------

@login_required
@role_required(*STAFF_ROLES)
def employee_salary_view(request):
    role = getattr(request.user, "role", None)
    today = timezone.localdate()
    period, year, month = _current_period(request, today)
    pms = Employee.objects.filter(role="pm").order_by("full_name", "email")

    if _is_admin(request):
        selected_pm_id = request.GET.get("pm")
        selected_pm = get_object_or_404(pms, pk=selected_pm_id) if selected_pm_id else None
    else:
        selected_pm = request.user
        selected_pm_id = str(request.user.id)
        pms = pms.filter(pk=request.user.id)

    team_members = team_members_for_pm(selected_pm) if selected_pm else Employee.objects.none()
    selected_employee_id = request.GET.get("employee")
    selected_employee = get_object_or_404(team_members, pk=selected_employee_id) if selected_employee_id else None

    if request.method == "POST":
        action = request.POST.get("action")
        acting_pm_id = request.POST.get("pm_id") or selected_pm_id
        acting_pm = Employee.objects.filter(role="pm", pk=acting_pm_id).first() if acting_pm_id else None

        if role == "pm":
            acting_pm = request.user
            acting_pm_id = str(request.user.id)

        redirect_employee = selected_employee_id

        if not acting_pm:
            messages.error(request, "Select a PM before saving salary details.")
            return _redirect_with_query(request, pm=selected_pm_id, employee=selected_employee_id, period=period, year=year, month=month)

        if action == "add_salary":
            salary = EmployeeSalary(
                pm=acting_pm,
                employee_id=request.POST.get("employee_id"),
                salary_type=request.POST.get("salary_type") or "fixed_budget",
                upwork_profile_name=(request.POST.get("upwork_profile_name") or "").strip(),
                project_name=(request.POST.get("project_name") or "").strip(),
                work_date=request.POST.get("work_date") or today,
                created_by=request.user,
            )
            redirect_employee = request.POST.get("employee_id") or redirect_employee
            if salary.salary_type == "fixed_budget":
                salary.entries_email = Decimal(request.POST.get("entries_email") or "0")
                salary.per_entry_rate = Decimal(request.POST.get("per_entry_rate") or "0")
            else:
                salary.number_of_hours = Decimal(request.POST.get("number_of_hours") or "0")
                salary.per_hour_rate = Decimal(request.POST.get("per_hour_rate") or "0")
            try:
                salary.full_clean()
                salary.save()
                messages.success(request, "Salary entry added.")
            except Exception as exc:
                messages.error(request, f"Could not save salary entry: {exc}")

        if action == "delete_salary":
            salary_id = request.POST.get("salary_id")
            salary = EmployeeSalary.objects.filter(pk=salary_id).first()
            if salary and (_is_admin(request) or salary.pm_id == request.user.id):
                redirect_employee = str(salary.employee_id)
                salary.delete()
                messages.success(request, "Salary entry deleted.")
            else:
                messages.error(request, "You do not have permission to delete this salary entry.")

        if action == "edit_salary":
            salary_id = request.POST.get("salary_id")
            salary = EmployeeSalary.objects.filter(pk=salary_id).first()
            if salary and (_is_admin(request) or salary.pm_id == request.user.id):
                redirect_employee = request.POST.get("employee_id") or str(salary.employee_id)
                salary.employee_id = request.POST.get("employee_id") or salary.employee_id
                salary.salary_type = request.POST.get("salary_type") or "fixed_budget"
                salary.upwork_profile_name = (request.POST.get("upwork_profile_name") or "").strip()
                salary.project_name = (request.POST.get("project_name") or "").strip()
                salary.work_date = request.POST.get("work_date") or salary.work_date
                if salary.salary_type == "fixed_budget":
                    salary.entries_email = Decimal(request.POST.get("entries_email") or "0")
                    salary.per_entry_rate = Decimal(request.POST.get("per_entry_rate") or "0")
                else:
                    salary.number_of_hours = Decimal(request.POST.get("number_of_hours") or "0")
                    salary.per_hour_rate = Decimal(request.POST.get("per_hour_rate") or "0")
                try:
                    salary.full_clean()
                    salary.save()
                    messages.success(request, "Salary entry updated.")
                except Exception as exc:
                    messages.error(request, f"Could not update salary entry: {exc}")
            else:
                messages.error(request, "You do not have permission to edit this salary entry.")

        if action == "add_salary_expense":
            expense = EmployeeSalaryExpense(
                pm=acting_pm,
                employee_id=request.POST.get("employee_id"),
                expense_type=request.POST.get("expense_type") or "other",
                note=(request.POST.get("note") or "").strip(),
                amount_pkr=Decimal(request.POST.get("amount_pkr") or "0"),
                paid_by_id=request.POST.get("paid_by") or acting_pm.id,
                paid_date=request.POST.get("paid_date") or today,
                created_by=request.user,
            )
            redirect_employee = request.POST.get("employee_id") or redirect_employee
            try:
                expense.full_clean()
                expense.save()
                messages.success(request, "Expense entry added.")
            except Exception as exc:
                messages.error(request, f"Could not save expense entry: {exc}")

        if action == "delete_salary_expense":
            expense_id = request.POST.get("expense_id")
            expense = EmployeeSalaryExpense.objects.filter(pk=expense_id).first()
            if expense and (_is_admin(request) or expense.pm_id == request.user.id):
                redirect_employee = str(expense.employee_id)
                expense.delete()
                messages.success(request, "Expense entry deleted.")
            else:
                messages.error(request, "You do not have permission to delete this expense entry.")

        if action == "edit_salary_expense":
            expense_id = request.POST.get("expense_id")
            expense = EmployeeSalaryExpense.objects.filter(pk=expense_id).first()
            if expense and (_is_admin(request) or expense.pm_id == request.user.id):
                redirect_employee = request.POST.get("employee_id") or str(expense.employee_id)
                expense.employee_id = request.POST.get("employee_id") or expense.employee_id
                expense.expense_type = request.POST.get("expense_type") or "other"
                expense.note = (request.POST.get("note") or "").strip()
                expense.amount_pkr = Decimal(request.POST.get("amount_pkr") or "0")
                expense.paid_date = request.POST.get("paid_date") or expense.paid_date
                expense.paid_by_id = request.POST.get("paid_by") or expense.paid_by_id or expense.pm_id
                try:
                    expense.full_clean()
                    expense.save()
                    messages.success(request, "Expense entry updated.")
                except Exception as exc:
                    messages.error(request, f"Could not update expense entry: {exc}")
            else:
                messages.error(request, "You do not have permission to edit this expense entry.")

        if action == "add_salary_payment":
            payment = EmployeeSalaryPayment(
                pm=acting_pm,
                employee_id=request.POST.get("employee_id"),
                amount_pkr=Decimal(request.POST.get("amount_pkr") or "0"),
                note=(request.POST.get("note") or "").strip(),
                paid_date=request.POST.get("paid_date") or today,
                paid_by=request.user if getattr(request.user, "role", None) in ["pm", "admin"] else None,
                created_by=request.user,
            )
            redirect_employee = request.POST.get("employee_id") or redirect_employee
            try:
                payment.full_clean()
                payment.save()
                messages.success(request, "Salary payment added.")
            except Exception as exc:
                messages.error(request, f"Could not save salary payment: {exc}")

        if action == "delete_salary_payment":
            payment_id = request.POST.get("payment_id")
            payment = EmployeeSalaryPayment.objects.filter(pk=payment_id).first()
            if payment and (_is_admin(request) or payment.pm_id == request.user.id):
                redirect_employee = str(payment.employee_id)
                payment.delete()
                messages.success(request, "Salary payment deleted.")
            else:
                messages.error(request, "You do not have permission to delete this salary payment.")

        if action == "edit_salary_payment":
            payment_id = request.POST.get("payment_id")
            payment = EmployeeSalaryPayment.objects.filter(pk=payment_id).first()
            if payment and (_is_admin(request) or payment.pm_id == request.user.id):
                redirect_employee = request.POST.get("employee_id") or str(payment.employee_id)
                payment.employee_id = request.POST.get("employee_id") or payment.employee_id
                payment.amount_pkr = Decimal(request.POST.get("amount_pkr") or "0")
                payment.note = (request.POST.get("note") or "").strip()
                payment.paid_date = request.POST.get("paid_date") or payment.paid_date
                payment.paid_by_id = request.POST.get("paid_by") or payment.paid_by_id
                try:
                    payment.full_clean()
                    payment.save()
                    messages.success(request, "Salary payment updated.")
                except Exception as exc:
                    messages.error(request, f"Could not update salary payment: {exc}")
            else:
                messages.error(request, "You do not have permission to edit this salary payment.")

        return _redirect_with_query(
            request,
            pm=acting_pm_id,
            employee=redirect_employee,
            period=period,
            year=year,
            month=month,
        )

    salary_data = None
    if selected_pm:
        salary_data = summarize_employee_salary(
            pm=selected_pm,
            period=period,
            year=year,
            month=month,
            employee=selected_employee,
        )

    context = {
        "title": "Employee Salary",
        "pms": pms,
        "selected_pm": selected_pm,
        "team_members": team_members,
        "selected_employee": selected_employee,
        "salary_data": salary_data,
        "salary_type_choices": EmployeeSalary.SALARY_TYPE_CHOICES,
        "expense_type_choices": EmployeeSalaryExpense.EXPENSE_TYPE_CHOICES,
        "period": period,
        "year": year,
        "month": month,
        "year_options": _year_options(today),
        "months": _month_options(),
        "today": today,
        "current_user_id": request.user.id,
        "is_pm_user": role == "pm",
    }
    return render(request, "console/employee_salary.html", context)


# ---------------------------------------------------------------------------
# Global settings (admin only) — now editable
# ---------------------------------------------------------------------------

@login_required
@role_required("admin")
def global_settings_view(request):
    setting = PayrollGlobalSetting.objects.order_by("-updated_at").first()
    splits = PMSplitSetting.objects.select_related("pm").order_by("pm__full_name", "pm__email")
    pms_without_split = Employee.objects.filter(role="pm").exclude(
        id__in=splits.values_list("pm_id", flat=True)
    )

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "update_rate":
            rate = request.POST.get("usd_to_pkr_rate") or "0"
            try:
                if setting:
                    setting.usd_to_pkr_rate = Decimal(rate)
                    setting.save()
                else:
                    PayrollGlobalSetting.objects.create(usd_to_pkr_rate=Decimal(rate))
                messages.success(request, "USD to PKR rate updated.")
            except Exception as exc:
                messages.error(request, f"Could not update rate: {exc}")
        elif action == "update_split":
            pm_id = request.POST.get("pm_id")
            percent = request.POST.get("pm_share_percent") or "50"
            if pm_id:
                try:
                    split, _created = PMSplitSetting.objects.get_or_create(pm_id=pm_id)
                    split.pm_share_percent = Decimal(percent)
                    split.save()
                    messages.success(request, "PM split updated.")
                except Exception as exc:
                    messages.error(request, f"Could not update split: {exc}")
        return redirect("console:global_settings")

    context = {
        "title": "Global Settings",
        "setting": setting,
        "splits": splits,
        "pms_without_split": pms_without_split,
    }
    return render(request, "console/global_settings.html", context)


# ---------------------------------------------------------------------------
# Company summary (admin only) — ported
# ---------------------------------------------------------------------------

@login_required
@role_required("admin")
def company_summary_view(request):
    today = timezone.localdate()
    period, year, month = _current_period(request, today)

    incomes = PMIncome.objects.all()
    advances = PMAdvance.objects.all()

    if period == "year":
        incomes = incomes.filter(income_date__year=year)
        advances = advances.filter(advance_date__year=year)
    else:
        incomes = incomes.filter(income_date__year=year, income_date__month=month)
        advances = advances.filter(advance_date__year=year, advance_date__month=month)

    total_income_usd = Decimal("0.00")
    total_income_pkr = Decimal("0.00")
    for income in incomes:
        total_income_usd += income.amount_usd or Decimal("0.00")
        total_income_pkr += income.amount_pkr

    total_expense_usd = Decimal("0.00")
    total_expense_pkr = Decimal("0.00")
    for adv in advances:
        total_expense_usd += adv.amount_usd or Decimal("0.00")
        total_expense_pkr += adv.amount_pkr

    summary = {
        "total_income_usd": total_income_usd,
        "total_income_pkr": total_income_pkr,
        "total_expense_usd": total_expense_usd,
        "total_expense_pkr": total_expense_pkr,
        "profit_usd": total_income_usd - total_expense_usd,
        "profit_pkr": total_income_pkr - total_expense_pkr,
    }

    context = {
        "title": "Company Summary",
        "period": period,
        "year": year,
        "month": month,
        "year_options": _year_options(today),
        "months": _month_options(),
        "summary": summary,
        "incomes": incomes.select_related("pm").order_by("-income_date", "-created_at"),
        "advances": advances.select_related("pm").order_by("-advance_date", "-created_at"),
    }
    return render(request, "console/company_summary.html", context)


# ---------------------------------------------------------------------------
# Branch expenses (admin only) — ported
# ---------------------------------------------------------------------------

@login_required
@role_required("admin")
def branch_expenses_view(request):
    today = timezone.localdate()
    period = request.GET.get("period", "month")
    year = int(request.GET.get("year", today.year))
    month = int(request.GET.get("month", today.month))
    branches = Branch.objects.all()
    selected_branch_id = request.GET.get("branch")
    selected_branch = None

    if request.method == "POST":
        action = request.POST.get("action")
        period = request.POST.get("period", period)
        year = int(request.POST.get("year", year))
        month = int(request.POST.get("month", month))
        if action == "add_branch":
            name = (request.POST.get("branch_name") or "").strip()
            if name:
                branch, _created = Branch.objects.get_or_create(name=name)
                period_qs = f"period={period}&year={year}&month={month}"
                return HttpResponseRedirect(f"{request.path}?branch={branch.id}&{period_qs}")
        if action == "edit_branch":
            branch_id = request.POST.get("branch_id")
            name = (request.POST.get("branch_name") or "").strip()
            if branch_id and name:
                Branch.objects.filter(pk=branch_id).update(name=name)
        if action == "delete_branch":
            branch_id = request.POST.get("branch_id")
            if branch_id:
                Branch.objects.filter(pk=branch_id).delete()
        if action == "add_fixed":
            name = (request.POST.get("fixed_name") or "").strip()
            amount = request.POST.get("fixed_amount") or "0"
            branch_id = request.POST.get("branch_id")
            expense_type = request.POST.get("fixed_type") or "fixed"
            if name and branch_id:
                FixedExpense.objects.get_or_create(
                    name=name,
                    branch_id=branch_id,
                    defaults={
                        "amount_pkr": Decimal(amount or "0.00"),
                        "expense_type": expense_type,
                    },
                )
        if action == "add_expense":
            branch_id = request.POST.get("branch_id")
            note = (request.POST.get("note") or "").strip()
            amount = request.POST.get("amount") or "0"
            paid_date = request.POST.get("paid_date") or today
            paid_by_id = request.POST.get("paid_by") or request.user.id
            fixed_id = request.POST.get("fixed_expense") or None
            if branch_id and note:
                if fixed_id:
                    try:
                        fixed = FixedExpense.objects.get(pk=fixed_id)
                        if Decimal(amount or "0.00") > (fixed.amount_pkr or Decimal("0.00")):
                            amount = fixed.amount_pkr
                    except FixedExpense.DoesNotExist:
                        pass
                BranchExpense.objects.create(
                    branch_id=branch_id,
                    note=note,
                    amount_pkr=Decimal(amount or "0.00"),
                    paid_date=paid_date,
                    paid_by_id=paid_by_id or None,
                    fixed_expense_id=fixed_id or None,
                )
        if action == "edit_expense":
            exp_id = request.POST.get("expense_id")
            note = (request.POST.get("note") or "").strip()
            amount = request.POST.get("amount") or "0"
            paid_date = request.POST.get("paid_date") or today
            paid_by_id = request.POST.get("paid_by") or request.user.id
            fixed_id = request.POST.get("fixed_expense") or None
            if exp_id and note:
                try:
                    exp = BranchExpense.objects.get(pk=exp_id)
                    if fixed_id:
                        try:
                            fixed = FixedExpense.objects.get(pk=fixed_id)
                            if Decimal(amount or "0.00") > (fixed.amount_pkr or Decimal("0.00")):
                                amount = fixed.amount_pkr
                        except FixedExpense.DoesNotExist:
                            fixed_id = None
                    exp.note = note
                    exp.amount_pkr = Decimal(amount or "0.00")
                    exp.paid_date = paid_date
                    exp.paid_by_id = paid_by_id or None
                    exp.fixed_expense_id = fixed_id or None
                    exp.save()
                except BranchExpense.DoesNotExist:
                    pass
        if action == "delete_expense":
            exp_id = request.POST.get("expense_id")
            if exp_id:
                BranchExpense.objects.filter(pk=exp_id).delete()

    if selected_branch_id:
        selected_branch = get_object_or_404(branches, pk=selected_branch_id)

    expenses = BranchExpense.objects.none()
    fixed_expenses = FixedExpense.objects.filter(is_active=True)
    if selected_branch:
        fixed_expenses = fixed_expenses.filter(branch=selected_branch)
        if period == "year":
            expenses = BranchExpense.objects.filter(branch=selected_branch, paid_date__year=year)
        else:
            expenses = BranchExpense.objects.filter(
                branch=selected_branch, paid_date__year=year, paid_date__month=month
            )

    total_expenses_pkr = Decimal("0.00")
    for exp in expenses:
        total_expenses_pkr += exp.amount_pkr or Decimal("0.00")

    fixed_total = Decimal("0.00")
    for fx in fixed_expenses.filter(expense_type="fixed"):
        fixed_total += fx.amount_pkr or Decimal("0.00")

    fixed_paid = Decimal("0.00")
    for exp in expenses:
        if exp.fixed_expense_id:
            fixed_paid += exp.amount_pkr or Decimal("0.00")

    need_to_pay = fixed_total - fixed_paid
    if need_to_pay < 0:
        need_to_pay = Decimal("0.00")

    paid_by_users = Employee.objects.filter(role__in=["pm", "admin"]).order_by("full_name", "email")
    months = _month_options()

    context = {
        "title": "Branches Expenses",
        "branches": branches,
        "selected_branch": selected_branch,
        "expenses": expenses.select_related("paid_by", "fixed_expense").order_by("-paid_date", "-created_at"),
        "fixed_expenses": fixed_expenses,
        "paid_by_users": paid_by_users,
        "current_user_id": request.user.id,
        "period": period,
        "year": year,
        "month": month,
        "year_options": _year_options(today),
        "months": months,
        "summary": {
            "total_expenses_pkr": total_expenses_pkr,
            "paid_expenses_pkr": total_expenses_pkr,
            "need_to_pay_pkr": need_to_pay,
        },
        "current_month_label": (
            f"{dict(months).get(month, month)} {year}" if period == "month" else str(year)
        ),
        "today": today,
    }
    return render(request, "console/branch_expenses.html", context)
