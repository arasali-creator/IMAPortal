from django.contrib.auth import views as auth_views
from django.urls import path

from .views import register, login_view, logout_view, dashboard, profile_view, pending_view, approval_status, my_notifications, my_notifications_unread

urlpatterns = [
    path('', login_view, name='login'),
    path('register/', register, name='register'),
    path('pending/', pending_view, name='pending'),
    path('approval-status/', approval_status, name='approval_status'),
    path('password-reset/', auth_views.PasswordResetView.as_view(
        template_name='accounts/password_reset_form.html',
        email_template_name='accounts/password_reset_email.html',
        html_email_template_name='accounts/password_reset_email_html.html',
        subject_template_name='accounts/password_reset_subject.txt',
    ), name='password_reset'),
    path('password-reset/sent/', auth_views.PasswordResetDoneView.as_view(
        template_name='accounts/password_reset_done.html',
    ), name='password_reset_done'),
    path('password-reset/complete/', auth_views.PasswordResetCompleteView.as_view(
        template_name='accounts/password_reset_complete.html',
    ), name='password_reset_complete'),
    path('password-reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(
        template_name='accounts/password_reset_confirm.html',
    ), name='password_reset_confirm'),
    path('notifications/', my_notifications, name='my_notifications'),
    path('notifications/unread/', my_notifications_unread, name='my_notifications_unread'),
    path('dashboard/', dashboard, name='dashboard'),
    path('profile/', profile_view, name='profile'),
    path('logout/', logout_view, name='logout'),
]
