from datetime import date
from django.contrib import admin
from django.db.models import Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone

from accounts.models import Employee
from attendance.models import Attendance
from payroll.models import Expense, GlobalSetting, SalaryPayment


def _next_month_start(d: date) -> date:
    if d.month == 12:
        return d.replace(year=d.year + 1, month=1, day=1)
    return d.replace(month=d.month + 1, day=1)


def _month_range_start(d: date, months_back: int) -> date:
    cursor = d.replace(day=1)
    for _ in range(months_back):
        if cursor.month == 1:
            cursor = cursor.replace(year=cursor.year - 1, month=12, day=1)
        else:
            cursor = cursor.replace(month=cursor.month - 1, day=1)
    return cursor


def _build_month_series(start: date, end: date):
    months = []
    cursor = start
    while cursor < end:
        months.append(cursor)
        cursor = _next_month_start(cursor)
    return months


def _format_time(dt):
    if not dt:
        return "-"
    return timezone.localtime(dt).strftime("%H:%M")


_original_index = admin.site.index


def _office_portal_index(self, request, extra_context=None):
    extra_context = extra_context or {}

    today = timezone.localdate()
    month_start = today.replace(day=1)
    month_end = _next_month_start(month_start)

    employees_count = Employee.objects.count()
    attendance_today = Attendance.objects.filter(check_in__date=today).count()

    payments_month_total = (
        SalaryPayment.objects.filter(date_paid__gte=month_start, date_paid__lt=month_end)
        .aggregate(total=Sum("amount_pkr"))
        .get("total")
        or 0
    )
    expenses_month_total = (
        Expense.objects.filter(date__gte=month_start, date__lt=month_end)
        .aggregate(total=Sum("amount_pkr"))
        .get("total")
        or 0
    )

    range_start = _month_range_start(month_start, 5)
    range_end = _next_month_start(month_start)
    months = _build_month_series(range_start, range_end)

    payment_rows = (
        SalaryPayment.objects.filter(date_paid__gte=range_start, date_paid__lt=range_end)
        .annotate(m=TruncMonth("date_paid"))
        .values("m")
        .annotate(total=Sum("amount_pkr"))
    )
    payment_map = {
        (row["m"].date() if hasattr(row["m"], "date") else row["m"]): row["total"] or 0
        for row in payment_rows
        if row.get("m")
    }

    expense_rows = (
        Expense.objects.filter(date__gte=range_start, date__lt=range_end)
        .annotate(m=TruncMonth("date"))
        .values("m")
        .annotate(total=Sum("amount_pkr"))
    )
    expense_map = {
        (row["m"].date() if hasattr(row["m"], "date") else row["m"]): row["total"] or 0
        for row in expense_rows
        if row.get("m")
    }

    trend_labels = [m.strftime("%b %Y") for m in months]
    payroll_series = [float(payment_map.get(m, 0)) for m in months]
    expense_series = [float(expense_map.get(m, 0)) for m in months]

    cat_rows = (
        Expense.objects.filter(date__gte=month_start, date__lt=month_end)
        .values("category")
        .annotate(total=Sum("amount_pkr"))
    )
    cat_map = {row["category"]: float(row["total"] or 0) for row in cat_rows}
    cat_labels = [label for _, label in Expense.CATEGORY_CHOICES]
    cat_series = [cat_map.get(key, 0) for key, _ in Expense.CATEGORY_CHOICES]

    recent_employees = []
    for emp in Employee.objects.order_by("-date_joined")[:5]:
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
    for log in Attendance.objects.select_related("employee").order_by("-check_in")[:5]:
        recent_attendance.append(
            {
                "employee": str(log.employee),
                "date": log.check_in.date() if log.check_in else today,
                "check_in": _format_time(log.check_in),
                "check_out": _format_time(log.check_out),
                "hours_worked": log.hours_worked,
            }
        )

    extra_context.update(
        {
            "rate": GlobalSetting.current_rate(),
            "employees_count": employees_count,
            "attendance_today": attendance_today,
            "payments_month_total": payments_month_total,
            "expenses_month_total": expenses_month_total,
            "trend_labels": trend_labels,
            "payroll_series": payroll_series,
            "expense_series": expense_series,
            "cat_labels": cat_labels,
            "cat_series": cat_series,
            "recent_employees": recent_employees,
            "recent_attendance": recent_attendance,
        }
    )

    return _original_index(request, extra_context=extra_context)


admin.site.index = _office_portal_index.__get__(admin.site, admin.site.__class__)
