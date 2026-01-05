from django.urls import path
from . import views

urlpatterns = [
    path("my-leaves/", views.my_leave_requests, name="my_leave_requests"),
]
