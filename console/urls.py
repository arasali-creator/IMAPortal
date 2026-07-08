from django.urls import path

from . import views

app_name = "console"

urlpatterns = [
    path("", views.dashboard_view, name="dashboard"),
    path("employees/", views.employees_list, name="employees_list"),
    path("employees/new/", views.employee_create, name="employee_create"),
    path("employees/bulk-delete/", views.employees_bulk_delete, name="employees_bulk_delete"),
    path("employees/<int:pk>/", views.employee_detail, name="employee_detail"),
    path("employees/<int:pk>/delete/", views.employee_delete, name="employee_delete"),
    path("employees/<int:pk>/approve/", views.employee_approve, name="employee_approve"),
    path("employees/<int:pk>/promote/", views.employee_promote, name="employee_promote"),
    path("employees/<int:pk>/demote/", views.employee_demote, name="employee_demote"),
    path("teams/", views.teams_list, name="teams_list"),
    path("teams/new/", views.team_create, name="team_create"),
    path("teams/<int:pk>/edit/", views.team_edit, name="team_edit"),
    path("teams/<int:pk>/delete/", views.team_delete, name="team_delete"),
    path("notifications/", views.notifications_list, name="notifications_list"),
    path("notifications/unread-count/", views.notification_unread_count, name="notification_unread_count"),
    path("notifications/mark-all-read/", views.notification_mark_all_read, name="notification_mark_all_read"),
    path("notifications/<int:pk>/mark-read/", views.notification_mark_read, name="notification_mark_read"),
    path("password-resets/", views.password_resets_list, name="password_resets_list"),
    path("password-resets/<int:pk>/resolve/", views.password_reset_mark_resolved, name="password_reset_mark_resolved"),
    path("attendance/", views.attendance_list, name="attendance_list"),
    path("attendance/monthly/", views.attendance_monthly, name="attendance_monthly"),
    path("attendance/employee/<int:employee_id>/", views.attendance_employee_detail, name="attendance_employee_detail"),
    path("leaves/", views.leaves_list, name="leaves_list"),
    path("leaves/<int:pk>/approve/", views.leave_approve, name="leave_approve"),
    path("leaves/<int:pk>/reject/", views.leave_reject, name="leave_reject"),
    path("pm-calculations/", views.pm_calculations_view, name="pm_calculations"),
    path("my-payroll/", views.my_payroll_view, name="my_payroll"),
    path("employee-salary/", views.employee_salary_view, name="employee_salary"),
    path("global-settings/", views.global_settings_view, name="global_settings"),
    path("company-summary/", views.company_summary_view, name="company_summary"),
    path("branch-expenses/", views.branch_expenses_view, name="branch_expenses"),
]
