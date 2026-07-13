from django.contrib import admin

from .models import UpworkJobEntry, UpworkProfile, UpworkSetting


@admin.register(UpworkSetting)
class UpworkSettingAdmin(admin.ModelAdmin):
    list_display = ("connect_rate", "updated_at")


@admin.register(UpworkProfile)
class UpworkProfileAdmin(admin.ModelAdmin):
    list_display = ("name", "project_manager", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name", "project_manager__full_name", "project_manager__email")
    list_select_related = ("project_manager",)


@admin.register(UpworkJobEntry)
class UpworkJobEntryAdmin(admin.ModelAdmin):
    list_display = (
        "profile",
        "date",
        "jobs_applied",
        "proposal_views",
        "responses",
        "offers",
        "hired",
        "connects_used",
        "connect_rate",
        "amount_spent",
    )
    list_filter = ("profile", "date")
    search_fields = ("profile__name",)
    list_select_related = ("profile",)
    readonly_fields = ("connect_rate", "amount_spent")
