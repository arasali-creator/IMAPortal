# attendance/admin.py
import calendar
from datetime import time, date

from django.contrib import admin
from django.utils import timezone
from django.urls import path, reverse
from django.shortcuts import render
from django.db.models import Min, Max, Count
from django.db.models.functions import TruncMonth, TruncYear

from accounts.models import Employee, Team
from leaves.models import LeaveRequest
from .models import Attendance


@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ("employee", "check_in", "check_out", "hours_worked")
    list_filter = ("employee", "check_in")
    search_fields = ("employee__full_name", "employee__email", "employee__cnic")

    # ✅ Dashboard list template
    change_list_template = "attendance/change_list.html"

    # ✅ Better detail form layout (keep it)
    autocomplete_fields = ("employee",)
    readonly_fields = ("hours_worked", "attendance_date", "status_badge")

    fieldsets = (
        ("Employee", {"fields": ("employee", "attendance_date", "status_badge")}),
        ("Time", {"fields": (("check_in", "check_out"), "hours_worked")}),
    )

    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related("employee")
        if request.user.is_superuser or getattr(request.user, "role", None) == "admin":
            return qs
        if getattr(request.user, "role", None) == "pm":
            teams = Team.objects.filter(project_manager=request.user)
            member_ids = teams.values_list("members__id", flat=True)
            return qs.filter(employee_id__in=member_ids)
        return qs.none()

    # -------------------------
    # Detail helpers
    # -------------------------
    def attendance_date(self, obj):
        return obj.check_in.date() if obj and obj.check_in else "-"
    attendance_date.short_description = "Date"

    def status_badge(self, obj):
        if not obj or not obj.check_in:
            return "-"
        return "✅ Completed" if obj.check_out else "⏳ In progress"
    status_badge.short_description = "Status"

    # -------------------------
    # ✅ Dashboard (Today cards)
    # -------------------------
    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}

        today = timezone.localdate()
        LATE_AFTER = time(10, 15)

        todays_qs = (
            self.get_queryset(request)
            .filter(check_in__date=today)
            .order_by("employee_id", "-check_in")
        )

        latest_by_employee = {}
        for att in todays_qs:
            if att.employee_id not in latest_by_employee:
                latest_by_employee[att.employee_id] = att
        todays_cards = list(latest_by_employee.values())

        employees_qs = Employee.objects.all()
        if getattr(request.user, "role", None) == "pm":
            teams = Team.objects.filter(project_manager=request.user)
            member_ids = teams.values_list("members__id", flat=True)
            employees_qs = employees_qs.filter(id__in=member_ids)
        total_employees = employees_qs.count()

        present_ids = set(latest_by_employee.keys())
        present_count = len(present_ids)

        late_ids = set(
            todays_qs
            .filter(check_in__time__gt=LATE_AFTER)
            .values_list("employee_id", flat=True)
            .distinct()
        )
        late_count = len(late_ids)

        pending_checkout_count = sum(1 for a in todays_cards if a.check_out is None)

        completed_hours = [a.hours_worked for a in todays_cards if a.check_out]
        avg_hours_worked = round(sum(completed_hours) / len(completed_hours), 2) if completed_hours else 0

        absent_count = max(total_employees - present_count, 0)
        absent_employees = employees_qs.exclude(id__in=present_ids)

        extra_context.update({
            "today": today,
            "late_after": LATE_AFTER.strftime("%I:%M %p"),
            "total_employees": total_employees,
            "present_count": present_count,
            "late_count": late_count,
            "pending_checkout_count": pending_checkout_count,
            "absent_count": absent_count,
            "avg_hours_worked": avg_hours_worked,
            "todays_cards": todays_cards,
            "absent_employees": absent_employees[:12],
            # ✅ for "View Monthly" button
            "monthly_url": reverse("admin:attendance_monthly"),
        })



        # Month-wise + year-wise summary (Present / Absent / On Leave)
        base_qs = self.get_queryset(request)
        approved_leaves = LeaveRequest.objects.filter(status="Approved")
        if getattr(request.user, "role", None) == "pm":
            approved_leaves = approved_leaves.filter(employee__in=employees_qs)
        total_employees_all = employees_qs.count()

        def month_start(d):
            return d.replace(day=1)

        def next_month(d):
            if d.month == 12:
                return d.replace(year=d.year + 1, month=1, day=1)
            return d.replace(month=d.month + 1, day=1)

        min_att = base_qs.aggregate(min_date=Min("check_in"), max_date=Max("check_in"))
        min_leave = approved_leaves.aggregate(min_date=Min("start_date"), max_date=Max("end_date"))
        min_date = min(
            [d.date() if hasattr(d, "date") else d for d in [min_att["min_date"], min_leave["min_date"]] if d]
            or [None]
        )
        max_date = max(
            [d.date() if hasattr(d, "date") else d for d in [min_att["max_date"], min_leave["max_date"]] if d]
            or [None]
        )

        month_rows = []
        year_rows = []

        if min_date and max_date:
            cursor = month_start(min_date)
            end = next_month(month_start(max_date))

            while cursor < end:
                nxt = next_month(cursor)
                present_ids = set(
                    base_qs.filter(check_in__date__gte=cursor, check_in__date__lt=nxt)
                    .values_list("employee_id", flat=True)
                    .distinct()
                )
                on_leave_ids = set(
                    approved_leaves.filter(start_date__lte=nxt, end_date__gte=cursor)
                    .values_list("employee_id", flat=True)
                    .distinct()
                )
                absent_count = max(total_employees_all - len(present_ids | on_leave_ids), 0)

                month_rows.append(
                    {
                        "label": cursor.strftime("%b %Y"),
                        "present": len(present_ids),
                        "absent": absent_count,
                        "on_leave": len(on_leave_ids),
                    }
                )
                cursor = nxt

            # Year rows
            start_year = min_date.year
            end_year = max_date.year
            for y in range(start_year, end_year + 1):
                y_start = date(y, 1, 1)
                y_end = date(y + 1, 1, 1)
                present_ids = set(
                    base_qs.filter(check_in__date__gte=y_start, check_in__date__lt=y_end)
                    .values_list("employee_id", flat=True)
                    .distinct()
                )
                on_leave_ids = set(
                    approved_leaves.filter(start_date__lte=y_end, end_date__gte=y_start)
                    .values_list("employee_id", flat=True)
                    .distinct()
                )
                absent_count = max(total_employees_all - len(present_ids | on_leave_ids), 0)

                year_rows.append(
                    {
                        "year": y,
                        "present": len(present_ids),
                        "absent": absent_count,
                        "on_leave": len(on_leave_ids),
                    }
                )

        # Summary (current month)
        current_month = month_start(today)
        next_m = next_month(current_month)
        present_ids = set(
            base_qs.filter(check_in__date__gte=current_month, check_in__date__lt=next_m)
            .values_list("employee_id", flat=True)
            .distinct()
        )
        on_leave_ids = set(
            approved_leaves.filter(start_date__lte=next_m, end_date__gte=current_month)
            .values_list("employee_id", flat=True)
            .distinct()
        )
        absent_count = max(total_employees_all - len(present_ids | on_leave_ids), 0)

        extra_context.update(
            {
                "att_summary": {
                    "present": len(present_ids),
                    "absent": absent_count,
                    "on_leave": len(on_leave_ids),
                },
                "att_month_rows": month_rows,
                "att_year_rows": year_rows,
            }
        )

        return super().changelist_view(request, extra_context=extra_context)

    # -------------------------
    # ✅ Monthly Matrix + Employee Detail URLs
    # -------------------------
    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "monthly/",
                self.admin_site.admin_view(self.monthly_view),
                name="attendance_monthly",
            ),
            path(
                "employee/<int:employee_id>/",
                self.admin_site.admin_view(self.employee_detail_view),
                name="attendance_employee_detail",
            ),
        ]
        return custom + urls

    # -------------------------
    # ✅ Monthly Matrix View (your existing)
    # -------------------------
    def monthly_view(self, request):
        today = timezone.localdate()

        year = int(request.GET.get("year", today.year))
        month = int(request.GET.get("month", today.month))

        year = max(2000, min(year, 2100))
        month = max(1, min(month, 12))

        _, days_in_month = calendar.monthrange(year, month)

        days = []
        for d in range(1, days_in_month + 1):
            dt = date(year, month, d)
            days.append({
                "day": d,
                "weekday": dt.strftime("%a")[0],
                "is_weekend": dt.weekday() >= 5,
                "date": dt,
            })

        month_start = date(year, month, 1)
        month_end = date(year, month, days_in_month)

        month_att = (
            self.get_queryset(request)
            .filter(check_in__date__gte=month_start, check_in__date__lte=month_end)
            .values("employee_id", "check_in__date")
            .annotate(first_in=Min("check_in"))
        )
        present_map = {(x["employee_id"], x["check_in__date"]): x["first_in"] for x in month_att}

        employees = Employee.objects.all().order_by("full_name", "email")
        if getattr(request.user, "role", None) == "pm":
            teams = Team.objects.filter(project_manager=request.user)
            member_ids = teams.values_list("members__id", flat=True)
            employees = employees.filter(id__in=member_ids)

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
                    cells.append({
                        "type": "present",
                        "tooltip": f"Present · In {timezone.localtime(first_in).strftime('%I:%M %p')}",
                    })
                else:
                    cells.append({"type": "absent", "tooltip": "Absent"})

            rows.append({"employee": e, "cells": cells})

        prev_year, prev_month = (year - 1, 12) if month == 1 else (year, month - 1)
        next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)

        context = dict(
            self.admin_site.each_context(request),
            year=year,
            month=month,
            month_label=f"{calendar.month_abbr[month]} {year}",
            prev_year=prev_year,
            prev_month=prev_month,
            next_year=next_year,
            next_month=next_month,
            days=days,
            rows=rows,
        )
        return render(request, "attendance/monthly.html", context)

    # -------------------------
    # ✅ Employee Detail Attendance (NEW)
    # -------------------------
    def employee_detail_view(self, request, employee_id: int):
        today = timezone.localdate()

        year = int(request.GET.get("year", today.year))
        month = int(request.GET.get("month", today.month))
        year = max(2000, min(year, 2100))
        month = max(1, min(month, 12))

        employee = Employee.objects.get(pk=employee_id)
        if getattr(request.user, "role", None) == "pm":
            teams = Team.objects.filter(project_manager=request.user)
            member_ids = teams.values_list("members__id", flat=True)
            if employee_id not in set(member_ids):
                return render(request, "admin/403.html", status=403)

        _, days_in_month = calendar.monthrange(year, month)
        month_start = date(year, month, 1)
        month_end = date(year, month, days_in_month)

        # list of days
        days = []
        for d in range(1, days_in_month + 1):
            dt = date(year, month, d)
            days.append({
                "day": d,
                "weekday": dt.strftime("%a")[0],
                "is_weekend": dt.weekday() >= 5,
                "date": dt,
            })

        # present map for that employee only
        month_att = (
            self.get_queryset(request)
            .filter(employee_id=employee_id, check_in__date__gte=month_start, check_in__date__lte=month_end)
            .values("check_in__date")
            .annotate(first_in=Min("check_in"))
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
                cells.append({
                    "type": "present",
                    "tooltip": f"Present · In {timezone.localtime(first_in).strftime('%I:%M %p')}",
                })
            else:
                cells.append({"type": "absent", "tooltip": "Absent"})

        # recent sessions
        recent_qs = (
            self.get_queryset(request)
            .filter(employee_id=employee_id)
            .order_by("-check_in")[:25]
        )

        prev_year, prev_month = (year - 1, 12) if month == 1 else (year, month - 1)
        next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)

        context = dict(
            self.admin_site.each_context(request),
            employee=employee,
            year=year,
            month=month,
            month_label=f"{calendar.month_name[month]} {year}",
            prev_year=prev_year,
            prev_month=prev_month,
            next_year=next_year,
            next_month=next_month,
            days=days,
            cells=cells,
            recent_qs=recent_qs,
            # quick links
            back_to_dashboard=reverse("admin:attendance_attendance_changelist"),
            back_to_monthly=reverse("admin:attendance_monthly"),
        )
        return render(request, "attendance/employee_detail.html", context)

    def has_module_permission(self, request):
        if not request.user.is_authenticated:
            return False
        if request.user.is_superuser or getattr(request.user, "role", None) == "admin":
            return True
        return request.user.has_perm("attendance.view_attendance")

    def has_view_permission(self, request, obj=None):
        return self.has_module_permission(request)

    class Media:
        css = {
            "all": (
                "css/admin/attendance.css",
                "css/admin/attendance_form.css",
                "css/admin/attendance_monthly.css",
            )
        }
