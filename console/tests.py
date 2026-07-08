from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Employee, Team
from attendance.models import Attendance
from leaves.models import LeaveRequest


class ConsolePermissionTests(TestCase):
    def setUp(self):
        self.admin = Employee.objects.create_user(
            cnic="5555555555555",
            email="console-admin@example.com",
            password="testpass123",
            full_name="Console Admin",
            role="admin",
            is_active=True,
            is_staff=True,
        )
        self.pm = Employee.objects.create_user(
            cnic="6666666666666",
            email="console-pm@example.com",
            password="testpass123",
            full_name="Console PM",
            role="pm",
            is_active=True,
            is_staff=True,
        )
        self.employee = Employee.objects.create_user(
            cnic="7777777777777",
            email="console-employee@example.com",
            password="testpass123",
            full_name="Console Employee",
            role="employee",
            is_active=True,
        )
        self.pending_employee = Employee.objects.create_user(
            cnic="8888888888888",
            email="console-pending@example.com",
            password="testpass123",
            full_name="Console Pending",
            role="employee",
            is_active=False,
        )
        self.team = Team.objects.create(name="Console Team", project_manager=self.pm)
        self.team.members.add(self.employee)

    def test_admin_only_pages_reject_non_superuser_pm(self):
        self.client.force_login(self.pm)
        for name in ("console:pm_calculations", "console:global_settings"):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 403, name)

    def test_admin_only_pages_reject_pm_even_with_is_superuser_flag(self):
        self.pm.is_superuser = True
        self.pm.save(update_fields=["is_superuser"])
        self.client.force_login(self.pm)
        for name in ("console:pm_calculations", "console:global_settings"):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 403, name)

    def test_console_rejects_employee_even_with_is_superuser_flag(self):
        self.employee.is_superuser = True
        self.employee.save(update_fields=["is_superuser"])
        self.client.force_login(self.employee)
        response = self.client.get(reverse("console:dashboard"))
        self.assertEqual(response.status_code, 403)

    def test_admin_only_pages_allow_admin(self):
        self.client.force_login(self.admin)
        for name in ("console:pm_calculations", "console:global_settings"):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 200, name)

    def test_plain_employee_is_denied_console_access(self):
        self.client.force_login(self.employee)
        response = self.client.get(reverse("console:dashboard"))
        self.assertEqual(response.status_code, 403)

    def test_pm_sees_only_own_team_in_employees_list(self):
        other_pm = Employee.objects.create_user(
            cnic="9999999999999",
            email="console-other-pm@example.com",
            password="testpass123",
            full_name="Other PM",
            role="pm",
            is_active=True,
        )
        other_team_member = Employee.objects.create_user(
            cnic="1010101010101",
            email="console-other-member@example.com",
            password="testpass123",
            full_name="Other Team Member",
            role="employee",
            is_active=True,
        )
        Team.objects.create(name="Other Team", project_manager=other_pm).members.add(other_team_member)

        self.client.force_login(self.pm)
        response = self.client.get(reverse("console:employees_list"))
        self.assertContains(response, "Console Employee")
        self.assertNotContains(response, "Other Team Member")

    def test_admin_approve_action_activates_employee(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("console:employee_approve", args=[self.pending_employee.pk]))
        self.assertEqual(response.status_code, 302)
        self.pending_employee.refresh_from_db()
        self.assertTrue(self.pending_employee.is_active)

    def test_pm_cannot_approve_employee(self):
        self.client.force_login(self.pm)
        response = self.client.post(reverse("console:employee_approve", args=[self.pending_employee.pk]))
        self.assertEqual(response.status_code, 403)
        self.pending_employee.refresh_from_db()
        self.assertFalse(self.pending_employee.is_active)

    def test_admin_promote_then_demote_employee(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("console:employee_promote", args=[self.employee.pk]))
        self.employee.refresh_from_db()
        self.assertEqual(self.employee.role, "pm")

        self.client.post(reverse("console:employee_demote", args=[self.employee.pk]))
        self.employee.refresh_from_db()
        self.assertEqual(self.employee.role, "employee")

    def test_pm_can_approve_own_team_leave(self):
        from leaves.models import LeaveRequest

        leave = LeaveRequest.objects.create(employee=self.employee, reason="Test leave")
        self.client.force_login(self.pm)
        response = self.client.post(reverse("console:leave_approve", args=[leave.pk]))
        self.assertEqual(response.status_code, 302)
        leave.refresh_from_db()
        self.assertEqual(leave.pm_status, "Approved")
        self.assertEqual(leave.status, "Approved")

    def test_pm_cannot_view_attendance_detail_outside_own_team(self):
        other_pm = Employee.objects.create_user(
            cnic="1212121212121", email="console-other-pm2@example.com", password="testpass123",
            full_name="Other PM Two", role="pm", is_active=True,
        )
        outside_employee = Employee.objects.create_user(
            cnic="1313131313131", email="console-outside@example.com", password="testpass123",
            full_name="Outside Employee", role="employee", is_active=True,
        )
        Team.objects.create(name="Other Team Two", project_manager=other_pm).members.add(outside_employee)

        self.client.force_login(self.pm)
        response = self.client.get(reverse("console:attendance_employee_detail", args=[outside_employee.pk]))
        self.assertEqual(response.status_code, 403)

        response_own = self.client.get(reverse("console:attendance_employee_detail", args=[self.employee.pk]))
        self.assertEqual(response_own.status_code, 200)

    def test_pm_sees_own_attendance_alongside_team(self):
        Attendance.objects.create(employee=self.employee, check_in=timezone.now())
        Attendance.objects.create(employee=self.pm, check_in=timezone.now())

        self.client.force_login(self.pm)
        response = self.client.get(reverse("console:attendance_list"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["present_count"], 2)
        self.assertEqual(response.context["total_employees"], 2)

    def test_pm_can_view_own_attendance_detail(self):
        self.client.force_login(self.pm)
        response = self.client.get(reverse("console:attendance_employee_detail", args=[self.pm.pk]))
        self.assertEqual(response.status_code, 200)

    def test_pm_sees_own_leave_request_alongside_team(self):
        LeaveRequest.objects.create(employee=self.employee, reason="Team leave")
        LeaveRequest.objects.create(employee=self.pm, reason="My own leave")

        self.client.force_login(self.pm)
        response = self.client.get(reverse("console:leaves_list"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["leaves"]), 2)
        self.assertContains(response, "My own leave")

    def test_employee_detail_form_saves_changes(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("console:employee_detail", args=[self.employee.pk]),
            {
                "cnic": self.employee.cnic,
                "email": self.employee.email,
                "full_name": "Updated Name",
                "role": "employee",
                "is_active": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.employee.refresh_from_db()
        self.assertEqual(self.employee.full_name, "Updated Name")
