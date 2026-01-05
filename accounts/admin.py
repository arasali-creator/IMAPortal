# accounts/admin.py

from django.contrib import admin
from django import forms
from django.contrib.admin.models import LogEntry, ADDITION, CHANGE, DELETION
from django.urls import reverse
from django.http import JsonResponse
from django.utils.html import format_html
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import Permission
from .models import Employee, Team, PasswordResetRequest, Notification
from .utils import sync_notifications, notifications_queryset_for_user
from django.utils import timezone
from datetime import timedelta
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin
from unfold.forms import AdminPasswordChangeForm, UserChangeForm, UserCreationForm


class EmployeeCreationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = Employee
        fields = ("cnic", "email", "full_name", "role")


class EmployeeChangeForm(UserChangeForm):
    user_permissions = forms.ModelMultipleChoiceField(
        queryset=Permission.objects.all(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
from unfold.admin import ModelAdmin

@admin.register(Employee)
class EmployeeAdmin(ModelAdmin):
    model = Employee
    form = EmployeeChangeForm
    add_form = EmployeeCreationForm
    change_list_template = "accounts/change_list.html"
    change_form_template = "admin/accounts/employee/change_form.html"
    list_display = ('full_name', 'cnic', 'email', 'role', 'is_active', 'is_staff')
    list_filter = ('role', 'is_active', 'is_staff')
    search_fields = ('full_name', 'cnic', 'email')
    ordering = ('cnic',)

    fieldsets = (
        ('Login', {'fields': ('cnic', 'email', 'password')}),
        ('Personal Info', {
            'fields': (
                'full_name',
                'fathers_name',
                'gender',
                'marital_status',
                'contact_number',
                'residential_address'
            )
        }),
        ('Documents', {
            'fields': (
                'profile_picture',
                'cnic_front',
                'cnic_back',
                'degree_certificate',
                'father_cnic'
            )
        }),
        ('Emergency', {
            'fields': (
                'emergency_contact_name',
                'emergency_relationship',
                'emergency_contact_number',
                'emergency_contact_address'
            )
        }),
        ('Additional', {
            'fields': ('blood_group', 'role')
        }),
        ('Permissions', {
            'fields': (
                'is_active',
                'is_staff',
                'is_superuser',
                'groups',
                'user_permissions'
            )
        }),
        ('Important dates', {'fields': ('last_login',)}),
    )

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('cnic', 'email', 'full_name', 'password1', 'password2', 'role')
        }),
    )

    actions = ['approve_accounts', 'make_project_manager']

    @admin.action(description='Approve selected accounts (activate)')
    def approve_accounts(self, request, queryset):
        queryset.update(is_active=True)

    @admin.action(description='Promote to Project Manager')
    def make_project_manager(self, request, queryset):
        queryset.update(role='pm')

    # ✅ Fixed: Limit Employee view for Project Managers
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        if request.user.is_authenticated:
            if getattr(request.user, "role", None) == 'admin':
                return qs
            if getattr(request.user, "role", None) == 'pm':
                return qs.filter(teams__project_manager=request.user).distinct()
        return qs.none()

    def has_module_permission(self, request):
        if not request.user.is_authenticated:
            return False
        if request.user.is_superuser or getattr(request.user, "role", None) == "admin":
            return True
        return request.user.has_perm("accounts.view_employee")

    def has_view_permission(self, request, obj=None):
        return self.has_module_permission(request)

    class Media:
        css = {"all": ("css/admin/accounts.css",)}
        
@admin.register(Team)
class TeamAdmin(ModelAdmin):
    # ✅ Use custom 3-grid cards page for Teams list
    change_list_template = "accounts/team/change_list.html"
    change_form_template = "admin/accounts/team/change_form.html"

    list_display = ('name', 'project_manager', 'member_count')
    search_fields = ('name', 'project_manager__full_name')
    filter_horizontal = ('members',)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs.select_related('project_manager').prefetch_related('members')
        if request.user.is_authenticated:
            role = getattr(request.user, "role", None)
            if role == 'admin':
                return qs.select_related('project_manager').prefetch_related('members')
            if role == 'pm':
                return qs.filter(project_manager=request.user).select_related('project_manager').prefetch_related('members')
        return qs.none()

    def has_module_permission(self, request):
        if not request.user.is_authenticated:
            return False
        if request.user.is_superuser or getattr(request.user, "role", None) == "admin":
            return True
        return request.user.has_perm("accounts.view_team")

    def has_view_permission(self, request, obj=None):
        return self.has_module_permission(request)

    def member_count(self, obj):
        return obj.members.count()
    member_count.short_description = "Team Members"

    class Media:
        css = {"all": ("css/admin/accounts.css",)}

@admin.register(PasswordResetRequest)
class PasswordResetRequestAdmin(ModelAdmin):
    list_display = ("identifier", "employee", "status", "created_at", "resolved_at")
    list_filter = ("status", "created_at")
    search_fields = ("identifier", "employee__full_name", "employee__email", "employee__cnic")
    readonly_fields = ("created_at", "resolved_at")

    @admin.action(description="Mark selected as resolved")
    def mark_resolved(self, request, queryset):
        queryset.update(status="resolved", resolved_at=timezone.now())

    actions = ["mark_resolved"]


@admin.register(Notification)
class NotificationAdmin(ModelAdmin):
    change_list_template = "admin/accounts/notification/change_list.html"
    change_form_template = "admin/accounts/notification/change_form.html"
    list_display = (
        "action_time",
        "actor",
        "action_label",
        "object_link",
        "read_status",
        "mark_read_link",
    )
    list_filter = ("is_read", "action_flag", "content_type")
    search_fields = ("object_repr", "change_message", "actor__full_name", "actor__email", "actor__cnic")
    ordering = ("-action_time",)
    actions = ["mark_selected_read"]
    readonly_fields = (
        "log_entry_id",
        "actor",
        "content_type",
        "object_id",
        "object_repr",
        "action_flag",
        "change_message",
        "action_time",
        "url",
        "created_at",
    )
    fieldsets = (
        ("Notification", {"fields": ("object_repr", "is_read", "action_flag", "action_time")}),
        ("Actor", {"fields": ("actor",)}),
        ("Target", {"fields": ("content_type", "object_id", "url")}),
        ("Details", {"fields": ("change_message", "log_entry_id", "created_at")}),
    )

    def changelist_view(self, request, extra_context=None):
        cutoff = timezone.now() - timedelta(days=30)
        sync_notifications(cutoff)
        extra_context = extra_context or {}
        extra_context["mark_all_read_url"] = reverse("admin:accounts_notification_mark_all_read")
        qs = notifications_queryset_for_user(
            request.user, Notification.objects.filter(action_time__gte=cutoff)
        )
        extra_context["notif_total"] = qs.count()
        extra_context["notif_unread"] = qs.filter(is_read=False).count()
        extra_context["notif_read"] = qs.filter(is_read=True).count()
        return super().changelist_view(request, extra_context=extra_context)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        cutoff = timezone.now() - timedelta(days=30)
        qs = qs.filter(action_time__gte=cutoff)
        return notifications_queryset_for_user(request.user, qs)

    def has_module_permission(self, request):
        if not request.user.is_authenticated:
            return False
        if request.user.is_superuser or getattr(request.user, "role", None) == "admin":
            return True
        return request.user.has_perm("accounts.view_notification")

    def has_view_permission(self, request, obj=None):
        return self.has_module_permission(request)

    @admin.display(description="Action")
    def action_label(self, obj):
        if obj.action_flag == ADDITION:
            label = "Added"
            css = "added"
        elif obj.action_flag == CHANGE:
            label = "Updated"
            css = "updated"
        elif obj.action_flag == DELETION:
            label = "Deleted"
            css = "deleted"
        else:
            label = "Changed"
            css = "updated"
        return format_html('<span class="notif-pill {}">{}</span>', css, label)

    @admin.display(description="Item")
    def object_link(self, obj):
        if obj.url:
            return format_html('<a href="{}">{}</a>', obj.url, obj.object_repr)
        return obj.object_repr

    @admin.display(description="Status")
    def read_status(self, obj):
        label = "Read" if obj.is_read else "Unread"
        css = "read" if obj.is_read else "unread"
        return format_html('<span class="notif-status {}">{}</span>', css, label)

    @admin.display(description="Clear")
    def mark_read_link(self, obj):
        if obj.is_read:
            return "-"
        url = reverse("admin:accounts_notification_mark_read", args=[obj.pk])
        return format_html('<a class="button" href="{}">Mark read</a>', url)

    @admin.action(description="Mark selected as read")
    def mark_selected_read(self, request, queryset):
        queryset.update(is_read=True)

    def get_urls(self):
        from django.urls import path

        urls = super().get_urls()
        custom = [
            path(
                "unread-count/",
                self.admin_site.admin_view(self.unread_count_view),
                name="accounts_notification_unread_count",
            ),
            path(
                "mark-all-read/",
                self.admin_site.admin_view(self.mark_all_read_view),
                name="accounts_notification_mark_all_read",
            ),
            path(
                "<int:pk>/mark-read/",
                self.admin_site.admin_view(self.mark_read_view),
                name="accounts_notification_mark_read",
            ),
        ]
        return custom + urls

    def mark_all_read_view(self, request):
        qs = notifications_queryset_for_user(request.user, Notification.objects.all())
        qs.update(is_read=True)
        return self._redirect_back(request)

    def mark_read_view(self, request, pk):
        qs = notifications_queryset_for_user(request.user, Notification.objects.all())
        qs.filter(pk=pk).update(is_read=True)
        return self._redirect_back(request)

    def unread_count_view(self, request):
        cutoff = timezone.now() - timedelta(days=30)
        sync_notifications(cutoff)
        qs = notifications_queryset_for_user(
            request.user, Notification.objects.filter(action_time__gte=cutoff)
        )
        count = qs.filter(is_read=False).count()
        return JsonResponse({"ok": True, "count": count})

    def _redirect_back(self, request):
        from django.shortcuts import redirect

        return redirect(request.META.get("HTTP_REFERER", reverse("admin:accounts_notification_changelist")))
