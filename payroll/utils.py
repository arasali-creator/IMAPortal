from decimal import Decimal

from accounts.models import Employee

from .models import EmployeeSalary, EmployeeSalaryExpense, EmployeeSalaryPayment, PayrollGlobalSetting


def calculate_pm_available_balance(pm_share_amount, expense_amount, amount_paid_amount):
    return pm_share_amount - expense_amount - amount_paid_amount


def team_members_for_pm(pm):
    return Employee.objects.filter(role="employee", teams__project_manager=pm).distinct().order_by("full_name", "email")


def salary_records_for_period(pm, period, year, month, employee=None):
    salaries = EmployeeSalary.objects.filter(pm=pm)
    expenses = EmployeeSalaryExpense.objects.filter(pm=pm)
    payments = EmployeeSalaryPayment.objects.filter(pm=pm)

    if employee is not None:
        salaries = salaries.filter(employee=employee)
        expenses = expenses.filter(employee=employee)
        payments = payments.filter(employee=employee)

    if period == "year":
        salaries = salaries.filter(work_date__year=year)
        expenses = expenses.filter(paid_date__year=year)
        payments = payments.filter(paid_date__year=year)
    else:
        salaries = salaries.filter(work_date__year=year, work_date__month=month)
        expenses = expenses.filter(paid_date__year=year, paid_date__month=month)
        payments = payments.filter(paid_date__year=year, paid_date__month=month)

    return (
        salaries.select_related("employee", "pm"),
        expenses.select_related("employee", "paid_by", "pm"),
        payments.select_related("employee", "paid_by", "pm"),
    )


def summarize_employee_salary(pm, period, year, month, employee=None):
    salaries, expenses, payments = salary_records_for_period(pm=pm, period=period, year=year, month=month, employee=employee)

    total_income_pkr = Decimal("0.00")
    total_expenses_pkr = Decimal("0.00")
    total_paid_pkr = Decimal("0.00")
    rows = {}

    for salary in salaries:
        total_income_pkr += salary.income_amount
        row = rows.setdefault(
            salary.employee_id,
            {
                "employee": salary.employee,
                "income_pkr": Decimal("0.00"),
                "expenses_pkr": Decimal("0.00"),
                "paid_pkr": Decimal("0.00"),
                "balance_pkr": Decimal("0.00"),
            },
        )
        row["income_pkr"] += salary.income_amount

    for expense in expenses:
        total_expenses_pkr += expense.amount_pkr or Decimal("0.00")
        row = rows.setdefault(
            expense.employee_id,
            {
                "employee": expense.employee,
                "income_pkr": Decimal("0.00"),
                "expenses_pkr": Decimal("0.00"),
                "paid_pkr": Decimal("0.00"),
                "balance_pkr": Decimal("0.00"),
            },
        )
        row["expenses_pkr"] += expense.amount_pkr or Decimal("0.00")

    for payment in payments:
        total_paid_pkr += payment.amount_pkr or Decimal("0.00")
        row = rows.setdefault(
            payment.employee_id,
            {
                "employee": payment.employee,
                "income_pkr": Decimal("0.00"),
                "expenses_pkr": Decimal("0.00"),
                "paid_pkr": Decimal("0.00"),
                "balance_pkr": Decimal("0.00"),
            },
        )
        row["paid_pkr"] += payment.amount_pkr or Decimal("0.00")

    for row in rows.values():
        row["balance_pkr"] = row["income_pkr"] - row["expenses_pkr"] - row["paid_pkr"]

    total_balance_pkr = total_income_pkr - total_expenses_pkr - total_paid_pkr
    rate = PayrollGlobalSetting.current_rate() or Decimal("1.00")
    total_balance_usd = total_balance_pkr / rate if rate else Decimal("0.00")

    employee_rows = sorted(rows.values(), key=lambda item: (item["employee"].full_name or item["employee"].email or "").lower())

    return {
        "salaries": salaries.order_by("-work_date", "-created_at"),
        "expenses": expenses.order_by("-paid_date", "-created_at"),
        "payments": payments.order_by("-paid_date", "-created_at"),
        "employee_rows": employee_rows,
        "total_income_pkr": total_income_pkr,
        "total_expenses_pkr": total_expenses_pkr,
        "total_paid_pkr": total_paid_pkr,
        "total_balance_pkr": total_balance_pkr,
        "total_balance_usd": total_balance_usd,
    }


def summarize_employee_payroll(employee, period, year, month):
    salaries = EmployeeSalary.objects.filter(employee=employee)
    expenses = EmployeeSalaryExpense.objects.filter(employee=employee)
    payments = EmployeeSalaryPayment.objects.filter(employee=employee)

    if period == "year":
        salaries = salaries.filter(work_date__year=year)
        expenses = expenses.filter(paid_date__year=year)
        payments = payments.filter(paid_date__year=year)
    else:
        salaries = salaries.filter(work_date__year=year, work_date__month=month)
        expenses = expenses.filter(paid_date__year=year, paid_date__month=month)
        payments = payments.filter(paid_date__year=year, paid_date__month=month)

    total_income_pkr = sum((salary.income_amount for salary in salaries), Decimal("0.00"))
    total_expenses_pkr = sum((expense.amount_pkr or Decimal("0.00") for expense in expenses), Decimal("0.00"))
    total_paid_pkr = sum((payment.amount_pkr or Decimal("0.00") for payment in payments), Decimal("0.00"))
    total_balance_pkr = total_income_pkr - total_expenses_pkr - total_paid_pkr
    rate = PayrollGlobalSetting.current_rate() or Decimal("1.00")

    return {
        "salaries": salaries.select_related("pm").order_by("-work_date", "-created_at"),
        "expenses": expenses.select_related("pm", "paid_by").order_by("-paid_date", "-created_at"),
        "payments": payments.select_related("pm", "paid_by").order_by("-paid_date", "-created_at"),
        "total_income_pkr": total_income_pkr,
        "total_expenses_pkr": total_expenses_pkr,
        "total_paid_pkr": total_paid_pkr,
        "total_balance_pkr": total_balance_pkr,
        "total_balance_usd": total_balance_pkr / rate if rate else Decimal("0.00"),
    }
