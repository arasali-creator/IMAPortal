from django.contrib import admin

from .models import Branch, BranchExpense, FixedExpense, PMAdvance, PMIncome, PMSplitSetting, PayrollGlobalSetting


@admin.register(PayrollGlobalSetting)
class PayrollGlobalSettingAdmin(admin.ModelAdmin):
    list_display = ("usd_to_pkr_rate", "updated_at")


@admin.register(PMSplitSetting)
class PMSplitSettingAdmin(admin.ModelAdmin):
    list_display = ("pm", "pm_share_percent", "updated_at")
    search_fields = ("pm__full_name", "pm__email", "pm__cnic")
    list_select_related = ("pm",)


@admin.register(PMIncome)
class PMIncomeAdmin(admin.ModelAdmin):
    change_form_template = "admin/payroll/change_form.html"
    list_display = (
        "pm",
        "income_date",
        "amount_usd",
        "rate_usd_to_pkr",
        "pm_share_percent",
        "withdrawn_by_ceo",
    )
    list_filter = ("source", "withdrawn_by_ceo", "income_date")
    search_fields = ("pm__full_name", "pm__email", "pm__cnic", "description")
    list_select_related = ("pm", "created_by")
    exclude = ("pm_share_percent", "rate_usd_to_pkr")

    def save_model(self, request, obj, form, change):
        if not obj.created_by:
            obj.created_by = request.user
        if not change and "pm_share_percent" not in form.changed_data:
            setting = getattr(obj.pm, "pm_split_setting", None)
            if setting:
                obj.pm_share_percent = setting.pm_share_percent
        if not change and "rate_usd_to_pkr" not in form.changed_data:
            obj.rate_usd_to_pkr = PayrollGlobalSetting.current_rate()
        super().save_model(request, obj, form, change)


@admin.register(PMAdvance)
class PMAdvanceAdmin(admin.ModelAdmin):
    change_form_template = "admin/payroll/change_form.html"
    list_display = ("pm", "advance_type", "advance_date", "amount_pkr")
    list_filter = ("advance_type", "advance_date")
    search_fields = ("pm__full_name", "pm__email", "pm__cnic", "notes")
    list_select_related = ("pm", "created_by")

    def save_model(self, request, obj, form, change):
        if not obj.created_by:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ("name", "created_at")
    search_fields = ("name",)


@admin.register(FixedExpense)
class FixedExpenseAdmin(admin.ModelAdmin):
    list_display = ("name", "branch", "expense_type", "amount_pkr", "day_of_month", "is_active")
    list_filter = ("expense_type", "is_active", "day_of_month", "branch")
    search_fields = ("name",)


@admin.register(BranchExpense)
class BranchExpenseAdmin(admin.ModelAdmin):
    list_display = ("branch", "note", "amount_pkr", "paid_date", "paid_by", "fixed_expense")
    list_filter = ("branch", "paid_date", "fixed_expense")
    search_fields = ("note", "branch__name")
    list_select_related = ("branch", "paid_by", "fixed_expense")
