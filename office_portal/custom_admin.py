from decimal import Decimal
from urllib.parse import urlencode

from django.contrib import admin, messages
from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.template.response import TemplateResponse
from django.urls import path
from django.utils import timezone

from accounts.models import Employee
from attendance.models import Attendance
from payroll.models import (
    Branch,
    BranchExpense,
    EmployeeSalary,
    EmployeeSalaryExpense,
    EmployeeSalaryPayment,
    FixedExpense,
    PMAdvance,
    PMIncome,
    PayrollGlobalSetting,
)
from payroll.utils import calculate_pm_available_balance, summarize_employee_salary, team_members_for_pm


def _format_time(dt):
    if not dt:
        return "-"
    return timezone.localtime(dt).strftime("%H:%M")


def _month_options():
    return [
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


_original_index = admin.site.index
_original_get_urls = admin.site.get_urls


def _office_portal_index(self, request, extra_context=None):
    extra_context = extra_context or {}

    today = timezone.localdate()

    employees_count = Employee.objects.count()
    attendance_today = Attendance.objects.filter(check_in__date=today).count()

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
            "employees_count": employees_count,
            "attendance_today": attendance_today,
            "recent_employees": recent_employees,
            "recent_attendance": recent_attendance,
        }
    )

    return _original_index(request, extra_context=extra_context)


admin.site.index = _office_portal_index.__get__(admin.site, admin.site.__class__)


@staff_member_required
def pm_calculations_view(request):
    if not (request.user.is_superuser or getattr(request.user, "role", None) == "admin"):
        return TemplateResponse(request, "admin/403.html", status=403)

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

    context = admin.site.each_context(request)
    year_options = _year_options(today)
    months = _month_options()
    context.update(
        {
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
            "year_options": year_options,
            "months": months,
        }
    )
    return TemplateResponse(request, "admin/pm_calculations.html", context)


@staff_member_required
def employee_salary_view(request):
    role = getattr(request.user, "role", None)
    if not (request.user.is_superuser or role in ["admin", "pm"]):
        return TemplateResponse(request, "admin/403.html", status=403)

    today = timezone.localdate()
    period, year, month = _current_period(request, today)
    pms = Employee.objects.filter(role="pm").order_by("full_name", "email")

    if request.user.is_superuser or role == "admin":
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
            if salary and (request.user.is_superuser or role == "admin" or salary.pm_id == request.user.id):
                redirect_employee = str(salary.employee_id)
                salary.delete()
                messages.success(request, "Salary entry deleted.")
            else:
                messages.error(request, "You do not have permission to delete this salary entry.")

        if action == "edit_salary":
            salary_id = request.POST.get("salary_id")
            salary = EmployeeSalary.objects.filter(pk=salary_id).first()
            if salary and (request.user.is_superuser or role == "admin" or salary.pm_id == request.user.id):
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
            if expense and (request.user.is_superuser or role == "admin" or expense.pm_id == request.user.id):
                redirect_employee = str(expense.employee_id)
                expense.delete()
                messages.success(request, "Expense entry deleted.")
            else:
                messages.error(request, "You do not have permission to delete this expense entry.")

        if action == "edit_salary_expense":
            expense_id = request.POST.get("expense_id")
            expense = EmployeeSalaryExpense.objects.filter(pk=expense_id).first()
            if expense and (request.user.is_superuser or role == "admin" or expense.pm_id == request.user.id):
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
                paid_by=request.user if getattr(request.user, "role", None) in ["pm", "admin"] or request.user.is_superuser else None,
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
            if payment and (request.user.is_superuser or role == "admin" or payment.pm_id == request.user.id):
                redirect_employee = str(payment.employee_id)
                payment.delete()
                messages.success(request, "Salary payment deleted.")
            else:
                messages.error(request, "You do not have permission to delete this salary payment.")

        if action == "edit_salary_payment":
            payment_id = request.POST.get("payment_id")
            payment = EmployeeSalaryPayment.objects.filter(pk=payment_id).first()
            if payment and (request.user.is_superuser or role == "admin" or payment.pm_id == request.user.id):
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

    context = admin.site.each_context(request)
    context.update(
        {
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
            "is_pm_user": role == "pm" and not request.user.is_superuser,
        }
    )
    return TemplateResponse(request, "admin/employee_salary.html", context)


@staff_member_required
def global_settings_view(request):
    if not (request.user.is_superuser or getattr(request.user, "role", None) == "admin"):
        return TemplateResponse(request, "admin/403.html", status=403)

    setting = PayrollGlobalSetting.objects.order_by("-updated_at").first()
    context = admin.site.each_context(request)
    context.update(
        {
            "title": "Global Settings",
            "setting": setting,
        }
    )
    return TemplateResponse(request, "admin/global_settings.html", context)


@staff_member_required
def company_summary_view(request):
    if not (request.user.is_superuser or getattr(request.user, "role", None) == "admin"):
        return TemplateResponse(request, "admin/403.html", status=403)

    today = timezone.localdate()
    period = request.GET.get("period", "month")
    year = int(request.GET.get("year", today.year))
    month = int(request.GET.get("month", today.month))

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

    current_year = today.year
    year_options = list(range(current_year - 4, current_year + 1))
    months = [
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
    ]

    context = admin.site.each_context(request)
    context.update(
        {
            "title": "Company Summary",
            "period": period,
            "year": year,
            "month": month,
            "year_options": year_options,
            "months": months,
            "summary": summary,
            "incomes": incomes.select_related("pm").order_by("-income_date", "-created_at"),
            "advances": advances.select_related("pm").order_by("-advance_date", "-created_at"),
        }
    )
    return TemplateResponse(request, "admin/company_summary.html", context)


@staff_member_required
def branch_expenses_view(request):
    if not (request.user.is_superuser or getattr(request.user, "role", None) == "admin"):
        return TemplateResponse(request, "admin/403.html", status=403)

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
                branch, _ = Branch.objects.get_or_create(name=name)
                period_qs = f"period={period}&year={year}&month={month}"
                return_url = f"{request.path}?branch={branch.id}&{period_qs}"
                return HttpResponseRedirect(return_url)
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
                        fixed = None
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
            expenses = BranchExpense.objects.filter(
                branch=selected_branch,
                paid_date__year=year,
            )
        else:
            expenses = BranchExpense.objects.filter(
                branch=selected_branch,
                paid_date__year=year,
                paid_date__month=month,
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
    current_year = today.year
    year_options = list(range(current_year - 4, current_year + 1))
    months = [
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
    ]

    context = admin.site.each_context(request)
    context.update(
        {
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
            "year_options": year_options,
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
    )
    return TemplateResponse(request, "admin/branch_expenses.html", context)

def _office_portal_get_urls(self):
    urls = _original_get_urls()
    custom = [
        path("employee-salary/", employee_salary_view, name="employee_salary"),
        path("pm-calculations/", pm_calculations_view, name="pm_calculations"),
        path("company-summary/", company_summary_view, name="company_summary"),
        path("branch-expenses/", branch_expenses_view, name="branch_expenses"),
        path("global-settings/", global_settings_view, name="global_settings"),
    ]
    return custom + urls


admin.site.get_urls = _office_portal_get_urls.__get__(admin.site, admin.site.__class__)
