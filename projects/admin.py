from django.contrib import admin

from .models import Project, ProjectTimeLog


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("name", "project_manager", "upwork_profile_name", "billing_type", "hourly_rate_usd", "fixed_price_usd", "entries_required", "status", "created_at")
    list_filter = ("status", "billing_type", "project_manager")
    search_fields = ("name", "upwork_profile_name", "description")
    filter_horizontal = ("members",)


@admin.register(ProjectTimeLog)
class ProjectTimeLogAdmin(admin.ModelAdmin):
    list_display = ("project", "employee", "started_at", "ended_at")
    list_filter = ("project",)
    search_fields = ("project__name", "employee__full_name", "employee__email")
