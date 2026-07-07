from django.urls import path

from .views import employee_salary_summary, pm_summary


app_name = "payroll"

urlpatterns = [
    path("my-summary/", pm_summary, name="my_summary"),
    path("salary-summary/", employee_salary_summary, name="employee_salary_summary"),
]
