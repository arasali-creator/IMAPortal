from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods

from attendance.models import Attendance
from leaves.models import LeaveRequest
from .forms import EmployeeRegistrationForm, CNICLoginForm
from .models import Employee, PasswordResetRequest

@require_http_methods(["GET", "POST"])
def register(request):
    if request.method == 'POST':
        form = EmployeeRegistrationForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            return render(request, 'accounts/registration_submitted.html')
    else:
        form = EmployeeRegistrationForm()
    return render(request, 'accounts/register.html', {'form': form})

@require_http_methods(["GET", "POST"])
def login_view(request):
    if request.method == 'POST':
        form = CNICLoginForm(request.POST)
        if form.is_valid():
            user = form.cleaned_data['user_object']
            if form.cleaned_data.get('inactive'):
                # stash CNIC in session for the pending view (no password stored)
                request.session['pending_cnic'] = user.cnic
                return redirect('pending')
            login(request, user)
            return redirect('dashboard')
    else:
        form = CNICLoginForm()
    return render(request, 'accounts/login.html', {'form': form})

def pending_view(request):
    cnic = request.session.get('pending_cnic')
    return render(request, 'accounts/pending.html', {'cnic': cnic})

@require_GET
def approval_status(request):
    """AJAX polling endpoint to check if a CNIC is approved"""
    cnic = request.GET.get('cnic')
    ok = False
    if cnic:
        ok = Employee.objects.filter(cnic=cnic, is_active=True).exists()
    return JsonResponse({'approved': ok})

@login_required
def dashboard(request):
    if getattr(request.user, "role", None) in ("admin", "pm"):
        return redirect('console:dashboard')

    employee = request.user
    today = timezone.localdate()
    month_start = today.replace(day=1)

    working_days_so_far = sum(
        1 for d in range(1, today.day + 1) if date(today.year, today.month, d).weekday() < 5
    )

    present_dates = set(
        Attendance.objects.filter(employee=employee, check_in__date__gte=month_start, check_in__date__lte=today)
        .values_list("check_in__date", flat=True).distinct()
    )
    present_days = len(present_dates)

    approved_leaves_month = LeaveRequest.objects.filter(
        employee=employee, status="Approved", start_date__lte=today, end_date__gte=month_start,
    )
    leave_dates = set()
    for leave in approved_leaves_month:
        cursor = max(leave.start_date, month_start)
        end = min(leave.end_date, today)
        while cursor <= end:
            if cursor.weekday() < 5 and cursor not in present_dates:
                leave_dates.add(cursor)
            cursor += timedelta(days=1)
    leave_days = len(leave_dates)

    absent_days = max(working_days_so_far - present_days - leave_days, 0)
    attendance_pct = round((present_days / working_days_so_far) * 100) if working_days_so_far else 0

    today_attendance = Attendance.objects.filter(employee=employee, check_in__date=today).order_by("-check_in").first()
    is_checked_in = bool(today_attendance and not today_attendance.check_out)

    leave_totals = LeaveRequest.objects.filter(employee=employee).aggregate(
        pending=Count("id", filter=Q(status="Pending")),
        approved=Count("id", filter=Q(status="Approved")),
        rejected=Count("id", filter=Q(status="Rejected")),
    )
    recent_leaves = LeaveRequest.objects.filter(employee=employee).order_by("-created_at")[:5]

    context = {
        "today": today,
        "attendance_pct": attendance_pct,
        "present_days": present_days,
        "absent_days": absent_days,
        "leave_days": leave_days,
        "is_checked_in": is_checked_in,
        "today_attendance": today_attendance,
        "leave_totals": leave_totals,
        "recent_leaves": recent_leaves,
    }
    return render(request, 'accounts/dashboard.html', context)


@login_required
def profile_view(request):
    return render(request, 'accounts/profile.html')

def logout_view(request):
    logout(request)
    messages.success(request, 'Logged out successfully.')
    return redirect('login')

@require_http_methods(["GET", "POST"])
def reset_password_view(request):
    sent = False
    if request.method == "POST":
        identifier = request.POST.get("cnic_or_email", "").strip()
        if identifier:
            employee = Employee.objects.filter(cnic=identifier).first()
            if not employee:
                employee = Employee.objects.filter(email__iexact=identifier).first()
            PasswordResetRequest.objects.create(
                employee=employee,
                identifier=identifier,
            )
        sent = True
    return render(request, "accounts/reset_password.html", {"sent": sent})
