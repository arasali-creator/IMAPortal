from django.db import connection
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Employee
from attendance.models import Attendance
from leaves.models import LeaveRequest


class EmployeeDashboardTests(TestCase):
    def setUp(self):
        self.employee = Employee.objects.create_user(
            cnic="6666666666666",
            email="dashboard-employee@example.com",
            password="testpass123",
            full_name="Dashboard Employee",
            role="employee",
            is_active=True,
        )
        self.admin = Employee.objects.create_user(
            cnic="7777777777777",
            email="dashboard-admin@example.com",
            password="testpass123",
            full_name="Dashboard Admin",
            role="admin",
            is_active=True,
        )

    def test_employee_dashboard_renders_with_real_stats(self):
        today = timezone.localdate()
        Attendance.objects.create(employee=self.employee, check_in=timezone.now())
        LeaveRequest.objects.create(employee=self.employee, reason="Sick", status="Approved")
        LeaveRequest.objects.create(employee=self.employee, reason="Pending one", status="Pending")

        self.client.force_login(self.employee)
        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["present_days"], 1)
        self.assertTrue(response.context["is_checked_in"])
        self.assertEqual(response.context["leave_totals"]["pending"], 1)
        self.assertEqual(response.context["leave_totals"]["approved"], 1)
        self.assertContains(response, "Dashboard Employee")

    def test_admin_still_redirects_to_console_dashboard(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("dashboard"))
        self.assertRedirects(response, reverse("console:dashboard"))

    def test_profile_page_renders(self):
        self.client.force_login(self.employee)
        response = self.client.get(reverse("profile"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Dashboard Employee")


class EmployeeDeletionCleanupTests(TestCase):
    def setUp(self):
        self.employee = Employee.objects.create_user(
            cnic="5555555555555",
            email="delete-me@example.com",
            password="testpass123",
            full_name="Delete Me",
            role="employee",
            is_active=True,
        )

    def test_delete_employee_cleans_orphaned_legacy_foreign_keys(self):
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE chat_chatroom (
                    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                    name varchar(120) NOT NULL,
                    is_group bool NOT NULL,
                    direct_key varchar(64) NOT NULL UNIQUE,
                    created_at datetime NOT NULL,
                    created_by_id bigint NULL REFERENCES accounts_employee (id) DEFERRABLE INITIALLY DEFERRED
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE chat_chatroommember (
                    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                    joined_at datetime NOT NULL,
                    last_read_at datetime NULL,
                    room_id bigint NOT NULL REFERENCES chat_chatroom (id) DEFERRABLE INITIALLY DEFERRED,
                    user_id bigint NOT NULL REFERENCES accounts_employee (id) DEFERRABLE INITIALLY DEFERRED
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE payroll_employeesalary (
                    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                    salary_month date NOT NULL,
                    effective_from date NOT NULL,
                    monthly_salary_usd decimal NOT NULL,
                    monthly_salary_pkr decimal NOT NULL,
                    active bool NOT NULL,
                    created_at datetime NOT NULL,
                    employee_id bigint NOT NULL REFERENCES accounts_employee (id) DEFERRABLE INITIALLY DEFERRED,
                    paid_by_id bigint NULL REFERENCES accounts_employee (id) DEFERRABLE INITIALLY DEFERRED
                )
                """
            )

            now = timezone.now()
            cursor.execute(
                """
                INSERT INTO chat_chatroom (name, is_group, direct_key, created_at, created_by_id)
                VALUES (%s, %s, %s, %s, %s)
                """,
                ["Legacy Room", False, "direct-1-2", now, None],
            )
            room_id = cursor.lastrowid
            cursor.execute(
                """
                INSERT INTO chat_chatroommember (joined_at, last_read_at, room_id, user_id)
                VALUES (%s, %s, %s, %s)
                """,
                [now, None, room_id, self.employee.id],
            )
            cursor.execute(
                """
                INSERT INTO payroll_employeesalary (
                    salary_month,
                    effective_from,
                    monthly_salary_usd,
                    monthly_salary_pkr,
                    active,
                    created_at,
                    employee_id,
                    paid_by_id
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                ["2026-03-01", "2026-03-01", "100.00", "28000.00", True, now, self.employee.id, None],
            )

        self.employee.delete()

        self.assertFalse(Employee.objects.filter(pk=self.employee.pk).exists())
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM chat_chatroommember WHERE user_id = %s", [self.employee.pk])
            self.assertEqual(cursor.fetchone()[0], 0)
            cursor.execute("SELECT COUNT(*) FROM payroll_employeesalary WHERE employee_id = %s", [self.employee.pk])
            self.assertEqual(cursor.fetchone()[0], 0)
