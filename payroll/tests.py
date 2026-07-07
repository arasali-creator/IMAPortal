from decimal import Decimal
from datetime import date

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from accounts.models import Employee, Team
from payroll.models import (
    EmployeeSalary,
    EmployeeSalaryExpense,
    EmployeeSalaryPayment,
    PMAdvance,
    PMIncome,
    PMSplitSetting,
    PayrollGlobalSetting,
)
from payroll.utils import summarize_employee_payroll, summarize_employee_salary


class EmployeeSalaryTests(TestCase):
    def setUp(self):
        self.pm = Employee.objects.create_user(
            cnic="1111111111111",
            email="pm@example.com",
            password="testpass123",
            full_name="PM User",
            role="pm",
            is_active=True,
            is_staff=True,
        )
        self.employee = Employee.objects.create_user(
            cnic="2222222222222",
            email="employee@example.com",
            password="testpass123",
            full_name="Team Member",
            role="employee",
            is_active=True,
        )
        self.other_employee = Employee.objects.create_user(
            cnic="3333333333333",
            email="other@example.com",
            password="testpass123",
            full_name="Other Member",
            role="employee",
            is_active=True,
        )
        self.team = Team.objects.create(name="Team A", project_manager=self.pm)
        self.team.members.add(self.employee)
        self.admin = Employee.objects.create_user(
            cnic="4444444444444",
            email="admin@example.com",
            password="testpass123",
            full_name="Admin User",
            role="admin",
            is_active=True,
            is_staff=True,
        )

    def test_salary_validation_rejects_employee_outside_pm_team(self):
        salary = EmployeeSalary(
            pm=self.pm,
            employee=self.other_employee,
            salary_type="fixed_budget",
            upwork_profile_name="Profile A",
            project_name="Project A",
            entries_email=Decimal("10"),
            per_entry_rate=Decimal("25"),
        )

        with self.assertRaises(ValidationError):
            salary.full_clean()

    def test_salary_summary_uses_income_minus_expenses_and_payments(self):
        EmployeeSalary.objects.create(
            pm=self.pm,
            employee=self.employee,
            salary_type="fixed_budget",
            upwork_profile_name="Profile A",
            project_name="Project A",
            entries_email=Decimal("10"),
            per_entry_rate=Decimal("50"),
            work_date=date(2026, 3, 14),
        )
        EmployeeSalary.objects.create(
            pm=self.pm,
            employee=self.employee,
            salary_type="timer",
            upwork_profile_name="Profile B",
            project_name="Project B",
            number_of_hours=Decimal("5"),
            per_hour_rate=Decimal("100"),
            work_date=date(2026, 3, 14),
        )
        EmployeeSalaryExpense.objects.create(
            pm=self.pm,
            employee=self.employee,
            expense_type="advance_taken",
            note="Advance",
            amount_pkr=Decimal("200"),
            paid_by=self.pm,
            paid_date=date(2026, 3, 14),
        )
        EmployeeSalaryPayment.objects.create(
            pm=self.pm,
            employee=self.employee,
            amount_pkr=Decimal("300"),
            paid_by=self.pm,
            paid_date=date(2026, 3, 14),
        )

        summary = summarize_employee_salary(pm=self.pm, period="month", year=2026, month=3)

        self.assertEqual(summary["total_income_pkr"], Decimal("1000"))
        self.assertEqual(summary["total_expenses_pkr"], Decimal("200"))
        self.assertEqual(summary["total_paid_pkr"], Decimal("300"))
        self.assertEqual(summary["total_balance_pkr"], Decimal("500"))
        self.assertEqual(len(summary["employee_rows"]), 1)

    def test_employee_salary_page_renders_for_pm(self):
        self.client.force_login(self.pm)

        response = self.client.get(reverse("admin:employee_salary"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Employee Salary")
        self.assertContains(response, "Team Member")

    def test_pm_summary_page_shows_detailed_income_and_expense_sections(self):
        EmployeeSalary.objects.create(
            pm=self.pm,
            employee=self.employee,
            salary_type="fixed_budget",
            upwork_profile_name="Profile A",
            project_name="Project A",
            entries_email=Decimal("10"),
            per_entry_rate=Decimal("50"),
            work_date=date(2026, 3, 14),
        )
        self.client.force_login(self.pm)

        response = self.client.get(
            reverse("payroll:my_summary"),
            {"period": "month", "year": 2026, "month": 3},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Income Details")
        self.assertContains(response, "Expense Details")
        self.assertContains(response, "Team Salary Balance Summary")

    def test_employee_salary_summary_page_renders_for_employee(self):
        EmployeeSalary.objects.create(
            pm=self.pm,
            employee=self.employee,
            salary_type="fixed_budget",
            upwork_profile_name="Profile A",
            project_name="Project A",
            entries_email=Decimal("10"),
            per_entry_rate=Decimal("50"),
            work_date=date(2026, 3, 14),
        )
        EmployeeSalaryExpense.objects.create(
            pm=self.pm,
            employee=self.employee,
            expense_type="fines",
            amount_pkr=Decimal("100"),
            paid_by=self.pm,
            paid_date=date(2026, 3, 14),
        )
        EmployeeSalaryPayment.objects.create(
            pm=self.pm,
            employee=self.employee,
            amount_pkr=Decimal("150"),
            paid_by=self.pm,
            paid_date=date(2026, 3, 14),
        )
        self.client.force_login(self.employee)

        response = self.client.get(
            reverse("payroll:employee_salary_summary"),
            {"period": "month", "year": 2026, "month": 3},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Salary Paid History")
        self.assertContains(response, "Fines")

    def test_employee_payroll_summary_returns_paid_and_balance(self):
        EmployeeSalary.objects.create(
            pm=self.pm,
            employee=self.employee,
            salary_type="fixed_budget",
            upwork_profile_name="Profile A",
            project_name="Project A",
            entries_email=Decimal("10"),
            per_entry_rate=Decimal("50"),
            work_date=date(2026, 3, 14),
        )
        EmployeeSalaryPayment.objects.create(
            pm=self.pm,
            employee=self.employee,
            amount_pkr=Decimal("125"),
            paid_by=self.pm,
            paid_date=date(2026, 3, 14),
        )

        summary = summarize_employee_payroll(employee=self.employee, period="month", year=2026, month=3)

        self.assertEqual(summary["total_income_pkr"], Decimal("500"))
        self.assertEqual(summary["total_paid_pkr"], Decimal("125"))
        self.assertEqual(summary["total_balance_pkr"], Decimal("375"))

    def test_pm_calculation_page_renders_salary_section_for_admin(self):
        EmployeeSalary.objects.create(
            pm=self.pm,
            employee=self.employee,
            salary_type="fixed_budget",
            upwork_profile_name="Profile A",
            project_name="Project A",
            entries_email=Decimal("10"),
            per_entry_rate=Decimal("50"),
            work_date=date(2026, 3, 14),
        )
        self.client.force_login(self.admin)

        response = self.client.get(
            reverse("admin:pm_calculations"),
            {"pm": self.pm.id, "period": "month", "year": 2026, "month": 3},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Amount paid to employee in term of salaries")

    def test_pm_summary_available_balance_uses_pm_share_before_deductions(self):
        PayrollGlobalSetting.objects.create(usd_to_pkr_rate=Decimal("100.00"))
        PMSplitSetting.objects.create(pm=self.pm, pm_share_percent=Decimal("50.00"))
        PMIncome.objects.create(
            pm=self.pm,
            source="upwork",
            description="Main income",
            amount_usd=Decimal("600.00"),
            rate_usd_to_pkr=Decimal("100.00"),
            pm_share_percent=Decimal("50.00"),
            income_date=date(2026, 3, 14),
            withdrawn_by=self.admin,
        )
        PMAdvance.objects.create(
            pm=self.pm,
            advance_type="cash_taken",
            amount_pkr=Decimal("5000.00"),
            advance_date=date(2026, 3, 14),
            paid_by=self.admin,
        )
        PMAdvance.objects.create(
            pm=self.pm,
            advance_type="upwork_job_paid",
            amount_pkr=Decimal("4000.00"),
            advance_date=date(2026, 3, 14),
            paid_by=self.admin,
        )
        EmployeeSalaryPayment.objects.create(
            pm=self.pm,
            employee=self.employee,
            amount_pkr=Decimal("2000.00"),
            paid_by=self.pm,
            paid_date=date(2026, 3, 14),
        )

        self.client.force_login(self.pm)
        response = self.client.get(
            reverse("payroll:my_summary"),
            {"period": "month", "year": 2026, "month": 3},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_income_pkr"], Decimal("60000.00"))
        self.assertEqual(response.context["total_pm_share_pkr"], Decimal("30000.00"))
        self.assertEqual(response.context["available_balance_pkr"], Decimal("22000.00"))

    def test_admin_pm_calculations_available_balance_uses_pm_share_before_deductions(self):
        PayrollGlobalSetting.objects.create(usd_to_pkr_rate=Decimal("100.00"))
        PMSplitSetting.objects.create(pm=self.pm, pm_share_percent=Decimal("50.00"))
        PMIncome.objects.create(
            pm=self.pm,
            source="upwork",
            description="Main income",
            amount_usd=Decimal("600.00"),
            rate_usd_to_pkr=Decimal("100.00"),
            pm_share_percent=Decimal("50.00"),
            income_date=date(2026, 3, 14),
            withdrawn_by=self.admin,
        )
        PMAdvance.objects.create(
            pm=self.pm,
            advance_type="cash_taken",
            amount_pkr=Decimal("5000.00"),
            advance_date=date(2026, 3, 14),
            paid_by=self.admin,
        )
        PMAdvance.objects.create(
            pm=self.pm,
            advance_type="upwork_job_paid",
            amount_pkr=Decimal("4000.00"),
            advance_date=date(2026, 3, 14),
            paid_by=self.admin,
        )
        EmployeeSalaryPayment.objects.create(
            pm=self.pm,
            employee=self.employee,
            amount_pkr=Decimal("2000.00"),
            paid_by=self.pm,
            paid_date=date(2026, 3, 14),
        )

        self.client.force_login(self.admin)
        response = self.client.get(
            reverse("admin:pm_calculations"),
            {"pm": self.pm.id, "period": "month", "year": 2026, "month": 3},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["summary"]["total_income_pkr"], Decimal("60000.00"))
        self.assertEqual(response.context["summary"]["total_pm_share_pkr"], Decimal("30000.00"))
        self.assertEqual(response.context["summary"]["available_balance_pkr"], Decimal("22000.00"))
