from django.urls import path

from . import views

app_name = "projects"

urlpatterns = [
    path("my/", views.my_projects, name="my_projects"),
    path("<int:pk>/start/", views.timer_start, name="timer_start"),
    path("<int:pk>/stop/", views.timer_stop, name="timer_stop"),
]
