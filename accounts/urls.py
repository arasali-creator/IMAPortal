from django.urls import path
from .views import register, login_view, logout_view, dashboard, profile_view, pending_view, approval_status, reset_password_view

urlpatterns = [
    path('', login_view, name='login'),
    path('register/', register, name='register'),
    path('pending/', pending_view, name='pending'),
    path('approval-status/', approval_status, name='approval_status'),
    path('reset-password/', reset_password_view, name='reset_password'),
    path('dashboard/', dashboard, name='dashboard'),
    path('profile/', profile_view, name='profile'),
    path('logout/', logout_view, name='logout'),
]
