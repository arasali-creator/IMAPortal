from datetime import date
from django.db.models import Sum
from django.shortcuts import render

# ✅ Update these imports to match your actual model names
from payroll.models import SalaryPayment, Expense


def payroll_dashboard(request):
    """
    Dashboard KPIs:
    - total payroll (sum of SalaryPayment.amount/net/paid field)
    - total expenses
    - paid vs pending (if model has a status/paid flag)
    - monthly trend (last 6 months)
    """

    # --- IMPORTANT ---
    # Adjust field names to your models:
    # - SalaryPayment amount field: change 'amount' to your field name (e.g. 'net_pay', 'net_salary', 'paid_amount')
    # - Paid status field: change 'is_paid' to your field (e.g. 'status' == 'Paid')
    amount_field = "amount"     # <-- change if needed
    paid_flag_field = "is_paid" # <-- change if needed (or set to None)

    # totals
    total_payroll = SalaryPayment.objects.aggregate(total=Sum(amount_field)).get("total") or 0
    total_expenses = Expense.objects.aggregate(total=Sum("amount")).get("total") or 0

    # paid/pending
    paid_total = 0
    pending_total = 0
    if paid_flag_field:
        paid_total = (
            SalaryPayment.objects.filter(**{paid_flag_field: True})
            .aggregate(total=Sum(amount_field))
            .get("total")
            or 0
        )
        pending_total = (
            SalaryPayment.objects.filter(**{paid_flag_field: False})
            .aggregate(total=Sum(amount_field))
            .get("total")
            or 0
        )

    # monthly trend (simple version)
    # If you have a date field like "payment_date" or "month", update here:
    date_field = "created_at"  # <-- change to your real field, e.g. "payment_date"

    # last 6 months labels
    today = date.today()
    months = []
    y, m = today.year, today.month
    for _ in range(6):
        months.append((y, m))
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    months.reverse()

    labels = [f"{y}-{m:02d}" for (y, m) in months]
    payroll_series = []
    expense_series = []

    for (yy, mm) in months:
        start = date(yy, mm, 1)
        if mm == 12:
            end = date(yy + 1, 1, 1)
        else:
            end = date(yy, mm + 1, 1)

        p = (
            SalaryPayment.objects.filter(**{f"{date_field}__gte": start, f"{date_field}__lt": end})
            .aggregate(total=Sum(amount_field))
            .get("total")
            or 0
        )
        e = (
            Expense.objects.filter(date__gte=start, date__lt=end)  # <-- change Expense date field if needed
            .aggregate(total=Sum("amount"))
            .get("total")
            or 0
        )

        payroll_series.append(float(p))
        expense_series.append(float(e))

    context = {
        "title": "Payroll Dashboard",
        "total_payroll": total_payroll,
        "total_expenses": total_expenses,
        "paid_total": paid_total,
        "pending_total": pending_total,
        "labels": labels,
        "payroll_series": payroll_series,
        "expense_series": expense_series,
    }
    return render(request, "admin/payroll_dashboard.html", context)


def payroll_report_monthly(request):
    # Simple placeholder page (you can expand)
    return render(request, "admin/payroll_report_monthly.html", {"title": "Monthly Payroll Report"})


def payroll_report_expense_vs_salary(request):
    # Simple placeholder page (you can expand)
    return render(request, "admin/payroll_report_expense_vs_salary.html", {"title": "Expenses vs Salary"})
