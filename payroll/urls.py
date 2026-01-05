from django.urls import path
from . import views
from django.contrib import admin
from payroll.admin_views import payroll_dashboard, payroll_report_monthly, payroll_report_expense_vs_salary

urlpatterns = [
    path("my-summary/", views.user_payroll_summary, name="user_payroll_summary"),
    path("my-summary/export/", views.user_payroll_export_pdf, name="user_payroll_export_pdf"),
    path("admin/payroll/dashboard/", admin.site.admin_view(payroll_dashboard), name="payroll-dashboard"),
    path("admin/payroll/reports/monthly/", admin.site.admin_view(payroll_report_monthly), name="payroll-report-monthly"),
    path("admin/payroll/reports/expense-vs-salary/", admin.site.admin_view(payroll_report_expense_vs_salary), name="payroll-report-expense-vs-salary"),
]
