from decimal import Decimal

from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import render
from django.template.response import TemplateResponse
from django.utils import timezone

from .models import PMAdvance, PMIncome, PMSplitSetting, PayrollGlobalSetting
from .utils import calculate_pm_available_balance, summarize_employee_payroll, summarize_employee_salary


def _period_context(request):
    today = timezone.localdate()
    period = request.GET.get("period", "month")
    year = int(request.GET.get("year", today.year))
    month = int(request.GET.get("month", today.month))
    current_year = today.year
    return {
        "today": today,
        "period": period,
        "year": year,
        "month": month,
        "year_options": list(range(current_year - 4, current_year + 1)),
        "months": [
            (1, "January"),
            (2, "February"),
            (3, "March"),
            (4, "April"),
            (5, "May"),
            (6, "June"),
            (7, "July"),
            (8, "August"),
            (9, "September"),
            (10, "October"),
            (11, "November"),
            (12, "December"),
        ],
    }


def build_pm_payroll_context(request, user):
    """Compute a PM's own income/advance/salary summary for the given period.

    Shared by the admin "My Payroll" page (pm_summary) and the console's
    my_payroll view so both show identical numbers.
    """
    period_ctx = _period_context(request)
    period = period_ctx["period"]
    year = period_ctx["year"]
    month = period_ctx["month"]

    split_setting = PMSplitSetting.objects.filter(pm=user).first()
    split_percent = split_setting.pm_share_percent if split_setting else Decimal("50.00")

    incomes = PMIncome.objects.filter(pm=user)
    advances = PMAdvance.objects.filter(pm=user)

    if period == "year":
        incomes = incomes.filter(income_date__year=year)
        advances = advances.filter(advance_date__year=year)
    else:
        incomes = incomes.filter(income_date__year=year, income_date__month=month)
        advances = advances.filter(advance_date__year=year, advance_date__month=month)

    incomes = incomes.order_by("-income_date", "-created_at")
    advances = advances.order_by("-advance_date", "-created_at")

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
        total_advances_pkr += adv.amount_pkr or Decimal("0.00")
        if adv.advance_type in ["cash_taken", "online_taken"]:
            cash_online_usd += adv.amount_usd or Decimal("0.00")
            cash_online_pkr += adv.amount_pkr or Decimal("0.00")
        if adv.advance_type in ["upwork_job_paid", "upwork_connects"]:
            jobs_connects_usd += adv.amount_usd or Decimal("0.00")
            jobs_connects_pkr += adv.amount_pkr or Decimal("0.00")

    balance_usd = total_pm_share_usd - total_advances_usd
    balance_pkr = total_pm_share_pkr - total_advances_pkr
    jobs_connects_divided_usd = jobs_connects_usd * split_percent / Decimal("100.00")
    jobs_connects_divided_pkr = jobs_connects_pkr * split_percent / Decimal("100.00")

    salary_data = summarize_employee_salary(pm=user, period=period, year=year, month=month)
    rate = PayrollGlobalSetting.current_rate()
    salary_paid_pkr = salary_data["total_paid_pkr"]
    salary_paid_usd = salary_paid_pkr / rate if rate else Decimal("0.00")
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

    return {
        "title": "My Payroll",
        "split_percent": split_percent,
        "incomes": incomes,
        "advances": advances,
        "total_income_usd": total_income_usd,
        "total_income_pkr": total_income_pkr,
        "total_pm_share_usd": total_pm_share_usd,
        "total_pm_share_pkr": total_pm_share_pkr,
        "total_advances_usd": total_advances_usd,
        "total_advances_pkr": total_advances_pkr,
        "balance_usd": balance_usd,
        "balance_pkr": balance_pkr,
        "cash_online_usd": cash_online_usd,
        "cash_online_pkr": cash_online_pkr,
        "jobs_connects_divided_usd": jobs_connects_divided_usd,
        "jobs_connects_divided_pkr": jobs_connects_divided_pkr,
        "salary_paid_usd": salary_paid_usd,
        "salary_paid_pkr": salary_paid_pkr,
        "salary_divided_usd": salary_divided_usd,
        "salary_divided_pkr": salary_divided_pkr,
        "available_balance_usd": available_balance_usd,
        "available_balance_pkr": available_balance_pkr,
        "salary_data": salary_data,
        **period_ctx,
    }


@login_required
def pm_summary(request):
    user = request.user
    if getattr(user, "role", None) != "pm":
        return HttpResponseForbidden("Only PMs can view this page.")

    context = admin.site.each_context(request)
    context.update(build_pm_payroll_context(request, user))
    return TemplateResponse(request, "payroll/my_summary.html", context)


@login_required
def employee_salary_summary(request):
    user = request.user
    if getattr(user, "role", None) != "employee":
        return HttpResponseForbidden("Only employees can view this page.")

    period_ctx = _period_context(request)
    salary_data = summarize_employee_payroll(
        employee=user,
        period=period_ctx["period"],
        year=period_ctx["year"],
        month=period_ctx["month"],
    )

    context = {
        "salary_data": salary_data,
        **period_ctx,
    }
    return render(request, "payroll/employee_salary_summary.html", context)
