from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.utils.timezone import localtime, now
from datetime import timedelta
from .models import Attendance

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
