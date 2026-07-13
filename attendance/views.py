import calendar
from datetime import date, timedelta

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils.timezone import localtime, now

from leaves.models import LeaveRequest

from .models import Attendance
from .utils import CELL_ICONS


@login_required
def check_in(request):
    today = localtime(now()).date()
    if not Attendance.objects.filter(employee=request.user, check_in__date=today, check_out__isnull=True).exists():
        Attendance.objects.create(employee=request.user, check_in=localtime(now()))
    return redirect("attendance:dashboard")

@login_required
def check_out(request):
    attendance = Attendance.objects.filter(employee=request.user, check_out__isnull=True).last()
    if attendance:
        attendance.check_out = localtime(now())
        attendance.save()
    return redirect("attendance:dashboard")

@login_required
def dashboard(request):
    today = localtime(now()).date()

    # Daily records & hours
    today_records = Attendance.objects.filter(employee=request.user, check_in__date=today)
    today_hours = round(sum([a.hours_worked for a in today_records]), 2)

    # Weekly hours
    start_week = today - timedelta(days=today.weekday())
    end_week = start_week + timedelta(days=6)
    week_records = Attendance.objects.filter(employee=request.user, check_in__date__range=[start_week, end_week])
    week_hours = round(sum([a.hours_worked for a in week_records]), 2)

    # Monthly hours
    start_month = today.replace(day=1)
    month_records = Attendance.objects.filter(employee=request.user, check_in__date__gte=start_month)
    month_hours = round(sum([a.hours_worked for a in month_records]), 2)

    # Check if currently checked in
    current_attendance = Attendance.objects.filter(employee=request.user, check_in__date=today, check_out__isnull=True).first()
    is_checked_in = bool(current_attendance)

    return render(request, "attendance/dashboard.html", {
        "today_hours": today_hours,
        "week_hours": week_hours,
        "month_hours": month_hours,
        "records": today_records,
        "is_checked_in": is_checked_in
    })


@login_required
def my_monthly(request):
    """Day-by-day attendance for one month, for the logged-in employee."""
    today = localtime(now()).date()
    try:
        year = int(request.GET.get("year", today.year))
        month = int(request.GET.get("month", today.month))
    except (TypeError, ValueError):
        year, month = today.year, today.month
    if not (1 <= month <= 12):
        month = today.month
    if not (2000 <= year <= today.year + 1):
        year = today.year

    days_in_month = calendar.monthrange(year, month)[1]
    month_start = date(year, month, 1)
    month_end = date(year, month, days_in_month)

    by_day = {}
    for rec in Attendance.objects.filter(
        employee=request.user, check_in__date__gte=month_start, check_in__date__lte=month_end
    ):
        by_day.setdefault(localtime(rec.check_in).date().day, []).append(rec)

    leave_days_set = set()
    for lv in LeaveRequest.objects.filter(
        employee=request.user, status="Approved", start_date__lte=month_end, end_date__gte=month_start
    ):
        d = max(lv.start_date, month_start)
        end = min(lv.end_date, month_end)
        while d <= end:
            leave_days_set.add(d.day)
            d += timedelta(days=1)

    rows = []
    present_days = absent_days = leave_days = 0
    total_hours = 0.0
    for daynum in range(1, days_in_month + 1):
        d = date(year, month, daynum)
        recs = by_day.get(daynum, [])
        check_in_time = min((localtime(r.check_in) for r in recs), default=None)
        check_out_time = max((localtime(r.check_out) for r in recs if r.check_out), default=None)
        hours = round(sum(r.hours_worked for r in recs), 2)

        if recs:
            status = "present"
            present_days += 1
            total_hours += hours
        elif daynum in leave_days_set:
            status = "leave"
            leave_days += 1
        elif d.weekday() >= 5:
            status = "weekend"
        elif d <= today:
            status = "absent"
            absent_days += 1
        else:
            status = "future"

        rows.append({
            "date": d,
            "status": status,
            "icon": CELL_ICONS.get(status, ""),
            "weekday": d.strftime("%a")[0],
            "check_in": check_in_time,
            "check_out": check_out_time,
            "hours": hours if recs else None,
        })

    return render(request, "attendance/my_monthly.html", {
        "rows": rows,
        "year": year,
        "month": month,
        "month_label": date(year, month, 1),
        "present_days": present_days,
        "absent_days": absent_days,
        "leave_days": leave_days,
        "total_hours": round(total_hours, 2),
        "year_options": list(range(today.year - 4, today.year + 1)),
        "months": [(m, calendar.month_name[m]) for m in range(1, 13)],
    })
