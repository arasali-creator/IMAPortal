from datetime import date, datetime
from decimal import Decimal
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
from payroll.models import EmployeeSalary, SalaryPayment, Expense

def _month_bounds(month_str):
    today = timezone.localdate()
    if month_str:
        try:
            year, month = month_str.split("-")
            year = int(year)
            month = int(month)
            start = date(year, month, 1)
        except (ValueError, TypeError):
            start = today.replace(day=1)
    else:
        start = today.replace(day=1)
    if start.month == 12:
        end = date(start.year + 1, 1, 1)
    else:
        end = date(start.year, start.month + 1, 1)
    return start, end, start.strftime("%Y-%m"), start.strftime("%B %Y")


@login_required
def user_payroll_summary(request):
    employee = request.user
    month_param = request.GET.get("month", "")
    month_start, month_end, month_value, month_label = _month_bounds(month_param)

    salary_profile = (
        EmployeeSalary.objects.filter(
            employee=employee,
            salary_month__gte=month_start,
            salary_month__lt=month_end,
        )
        .order_by("-salary_month", "-id")
        .first()
    )

    payments = (
        SalaryPayment.objects.filter(employee=employee, date_paid__gte=month_start, date_paid__lt=month_end)
        .order_by("-date_paid")
    )
    expenses = (
        Expense.objects.filter(employee=employee, date__gte=month_start, date__lt=month_end)
        .order_by("-date")
    )

    total_salary_usd = salary_profile.monthly_salary_usd if salary_profile else Decimal("0")
    total_salary_pkr = salary_profile.monthly_salary_pkr if salary_profile else Decimal("0")

    total_paid_usd = sum(p.amount_usd for p in payments)
    total_paid_pkr = sum(p.amount_pkr for p in payments)

    total_expenses_usd = sum(e.amount_usd for e in expenses)
    total_expenses_pkr = sum(e.amount_pkr for e in expenses)

    remaining_pkr = total_salary_pkr - total_paid_pkr - total_expenses_pkr

    all_payment_dates = SalaryPayment.objects.filter(employee=employee).values_list("date_paid", flat=True)
    all_expense_dates = Expense.objects.filter(employee=employee).values_list("date", flat=True)
    all_salary_months = EmployeeSalary.objects.filter(employee=employee).values_list("salary_month", flat=True)
    month_set = {
        d.strftime("%Y-%m")
        for d in list(all_payment_dates) + list(all_expense_dates) + list(all_salary_months)
        if d
    }
    available_months = sorted(month_set, reverse=True)
    if month_value not in available_months:
        available_months.insert(0, month_value)
    available_months = [
        {
            "value": m,
            "label": datetime.strptime(m, "%Y-%m").strftime("%B %Y"),
        }
        for m in available_months
    ]

    context = {
        "employee": employee,
        "salary_profile": salary_profile,
        "payments": payments,
        "expenses": expenses,
        "total_salary_usd": total_salary_usd,
        "total_salary_pkr": total_salary_pkr,
        "total_paid_usd": total_paid_usd,
        "total_paid_pkr": total_paid_pkr,
        "total_expenses_usd": total_expenses_usd,
        "total_expenses_pkr": total_expenses_pkr,
        "remaining_pkr": remaining_pkr,
        "selected_month": month_value,
        "selected_month_label": month_label,
        "available_months": available_months,
    }
    return render(request, "payroll/my_summary.html", context)


@login_required
def user_payroll_export_pdf(request):
    employee = request.user
    month_param = request.GET.get("month", "")
    month_start, month_end, month_value, month_label = _month_bounds(month_param)

    salary_profile = EmployeeSalary.objects.filter(employee=employee, active=True).first()
    payments = SalaryPayment.objects.filter(
        employee=employee, date_paid__gte=month_start, date_paid__lt=month_end
    ).order_by("date_paid")
    expenses = Expense.objects.filter(
        employee=employee, date__gte=month_start, date__lt=month_end
    ).order_by("date")

    total_salary_usd = salary_profile.monthly_salary_usd if salary_profile else Decimal("0")
    total_salary_pkr = salary_profile.monthly_salary_pkr if salary_profile else Decimal("0")
    total_paid_usd = sum(p.amount_usd for p in payments)
    total_paid_pkr = sum(p.amount_pkr for p in payments)
    total_expenses_usd = sum(e.amount_usd for e in expenses)
    total_expenses_pkr = sum(e.amount_pkr for e in expenses)

    response = HttpResponse(content_type="application/pdf")
    filename = f"payroll_{employee.pk}_{month_value}.pdf"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'

    c = canvas.Canvas(response, pagesize=A4)
    width, height = A4

    brand_orange = colors.HexColor("#ff6600")
    dark = colors.HexColor("#1f2937")
    muted = colors.HexColor("#6b7280")
    light = colors.HexColor("#f3f4f6")

    def draw_header():
        c.setFillColor(brand_orange)
        c.rect(0, height - 1.0 * inch, width, 1.0 * inch, stroke=0, fill=1)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 16)
        c.drawString(0.8 * inch, height - 0.65 * inch, "IMA Sales Solution")
        c.setFont("Helvetica", 10)
        c.drawString(0.8 * inch, height - 0.88 * inch, "Monthly Payroll Summary")
        c.setFillColor(colors.black)

    def draw_meta(y):
        c.setFont("Helvetica-Bold", 11)
        c.setFillColor(dark)
        c.drawString(0.8 * inch, y, month_label)
        y -= 0.2 * inch
        c.setFont("Helvetica", 9)
        c.setFillColor(muted)
        c.drawString(0.8 * inch, y, f"Employee: {employee.get_full_name()}")
        return y - 0.25 * inch

    def draw_summary(y):
        c.setFillColor(light)
        c.rect(0.8 * inch, y - 0.55 * inch, width - 1.6 * inch, 0.55 * inch, stroke=0, fill=1)
        c.setFillColor(dark)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(0.9 * inch, y - 0.2 * inch, "Salary (USD)")
        c.drawString(2.5 * inch, y - 0.2 * inch, "Salary (PKR)")
        c.drawString(4.2 * inch, y - 0.2 * inch, "Paid (PKR)")
        c.drawString(5.6 * inch, y - 0.2 * inch, "Expenses (PKR)")
        c.setFont("Helvetica", 9)
        c.drawString(0.9 * inch, y - 0.38 * inch, f"{total_salary_usd}")
        c.drawString(2.5 * inch, y - 0.38 * inch, f"{total_salary_pkr}")
        c.drawString(4.2 * inch, y - 0.38 * inch, f"{total_paid_pkr}")
        c.drawString(5.6 * inch, y - 0.38 * inch, f"{total_expenses_pkr}")
        return y - 0.75 * inch

    def draw_table(title, headers, rows, y):
        c.setFont("Helvetica-Bold", 10)
        c.setFillColor(dark)
        c.drawString(0.8 * inch, y, title)
        y -= 0.16 * inch

        x_positions = [0.8 * inch, 2.6 * inch, 4.3 * inch, 5.5 * inch]
        row_height = 0.22 * inch
        c.setFillColor(light)
        c.rect(0.8 * inch, y - row_height + 0.04 * inch, width - 1.6 * inch, row_height, stroke=0, fill=1)
        c.setFillColor(dark)
        c.setFont("Helvetica-Bold", 9)
        for idx, header in enumerate(headers):
            c.drawString(x_positions[idx], y - 0.14 * inch, header)
        y -= row_height + 0.05 * inch

        c.setFont("Helvetica", 9)
        if not rows:
            c.setFillColor(muted)
            c.drawString(0.8 * inch, y, "No records for this month.")
            return y - 0.2 * inch

        for idx, row in enumerate(rows):
            if y < 1.2 * inch:
                c.showPage()
                draw_header()
                y = height - 1.2 * inch
            if idx % 2 == 0:
                c.setFillColor(colors.whitesmoke)
                c.rect(0.8 * inch, y - row_height + 0.04 * inch, width - 1.6 * inch, row_height, stroke=0, fill=1)
            c.setFillColor(dark)
            for col_idx, value in enumerate(row):
                c.drawString(x_positions[col_idx], y - 0.14 * inch, str(value))
            y -= row_height
        return y - 0.15 * inch

    draw_header()
    y = height - 1.2 * inch
    y = draw_meta(y)
    y = draw_summary(y)

    payment_rows = [
        (p.date_paid.strftime("%Y-%m-%d"), "Salary Payment", f"{p.amount_usd}", f"{p.amount_pkr}")
        for p in payments
    ]
    y = draw_table("Salary Payments", ["Date", "Type", "USD", "PKR"], payment_rows, y)

    expense_rows = [
        (e.date.strftime("%Y-%m-%d"), e.get_category_display(), f"{e.amount_usd}", f"{e.amount_pkr}")
        for e in expenses
    ]
    y = draw_table("Expenses", ["Date", "Category", "USD", "PKR"], expense_rows, y)

    c.setFont("Helvetica-Bold", 10)
    c.setFillColor(dark)
    c.drawString(0.8 * inch, y, "Totals")
    y -= 0.2 * inch
    c.setFont("Helvetica", 9)
    c.setFillColor(muted)
    c.drawString(0.8 * inch, y, f"Total Paid (USD): {total_paid_usd}")
    y -= 0.16 * inch
    c.drawString(0.8 * inch, y, f"Total Paid (PKR): {total_paid_pkr}")
    y -= 0.16 * inch
    c.drawString(0.8 * inch, y, f"Total Expenses (USD): {total_expenses_usd}")
    y -= 0.16 * inch
    c.drawString(0.8 * inch, y, f"Total Expenses (PKR): {total_expenses_pkr}")

    c.showPage()
    c.save()
    return response
