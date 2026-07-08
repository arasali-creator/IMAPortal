from django.urls import path
from . import views

app_name = "attendance"

urlpatterns = [
    path("check-in/", views.check_in, name="check_in"),
    path("check-out/", views.check_out, name="check_out"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("monthly/", views.my_monthly, name="my_monthly"),
]
