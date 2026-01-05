# leaves/admin.py
from django.contrib import admin, messages
from django.contrib.admin.models import LogEntry, CHANGE
from django.contrib.contenttypes.models import ContentType
from django.db.models import Count, Q
from django.db.models.functions import TruncMonth, TruncYear
from django.urls import path
from django.shortcuts import redirect
from django.utils.html import format_html

from unfold.admin import ModelAdmin

from .models import LeaveRequest
from accounts.models import Employee, Team


@admin.register(LeaveRequest)
class LeaveRequestAdmin(ModelAdmin):
    # ✅ Card view template
    change_list_template = "leaves/change_list.html"

    list_display = (
        "employee",
        "reason",
        "start_date",
        "end_date",
        "pm_status",
        "admin_status",
        "status",
        "created_at",
        "updated_at",
    )
    list_filter = ("pm_status", "admin_status", "status")
    search_fields = ("employee__full_name", "employee__email", "reason")
    date_hierarchy = "created_at"
    readonly_fields = ("created_at", "updated_at")

    actions = ["approve_leave", "reject_leave"]

    # ---------------------------
    # Role-based visibility
    # ---------------------------
    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related("employee")

        if request.user.is_superuser:
            return qs

        role = getattr(request.user, "role", None)

        # PM sees leaves of their team members
        if role == "pm":
            teams = Team.objects.filter(project_manager=request.user).prefetch_related("members")
            member_ids = []
            for t in teams:
                member_ids += list(t.members.values_list("id", flat=True))
            if not member_ids:
                return qs.none()
            return qs.filter(employee_id__in=set(member_ids))

        # employee sees only own
        return qs.filter(employee=request.user)

    def has_module_permission(self, request):
        if not request.user.is_authenticated:
            return False
        if request.user.is_superuser or getattr(request.user, "role", None) == "admin":
            return True
        return request.user.has_perm("leaves.view_leaverequest")

    def has_view_permission(self, request, obj=None):
        return self.has_module_permission(request)

    # ---------------------------
    # Inline approve/reject via URL (for card buttons)
    # ---------------------------
    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "<int:pk>/approve/",
                self.admin_site.admin_view(self.card_approve),
                name="leaves_leaverequest_approve",
            ),
            path(
                "<int:pk>/reject/",
                self.admin_site.admin_view(self.card_reject),
                name="leaves_leaverequest_reject",
            ),
        ]
        return custom + urls

    def _apply_decision(self, request, obj: LeaveRequest, decision: str):
        role = getattr(request.user, "role", None)

        if role == "pm":
            obj.pm_status = decision
        elif role == "admin" or request.user.is_superuser:
            obj.admin_status = decision
        else:
            return False

        # final status rules (same as your logic)
        if decision == "Approved":
            if obj.pm_status == "Approved" or obj.admin_status == "Approved":
                obj.status = "Approved"
        else:  # Rejected
            if obj.pm_status == "Rejected" and obj.admin_status == "Rejected":
                obj.status = "Rejected"

        obj.save()
        LogEntry.objects.log_action(
            user_id=request.user.pk,
            content_type_id=ContentType.objects.get_for_model(obj).pk,
            object_id=obj.pk,
            object_repr=str(obj),
            action_flag=CHANGE,
            change_message=f"Leave {decision.lower()} by {role or 'user'}",
        )
        return True

    def card_approve(self, request, pk: int):
        obj = LeaveRequest.objects.select_related("employee").filter(pk=pk).first()
        if not obj:
            self.message_user(request, "Leave not found.", level=messages.ERROR)
            return redirect("..")

        ok = self._apply_decision(request, obj, "Approved")
        if ok:
            self.message_user(request, "Leave approved.", level=messages.SUCCESS)
        else:
            self.message_user(request, "You are not allowed to approve.", level=messages.ERROR)
        return redirect(request.META.get("HTTP_REFERER", ".."))

    def card_reject(self, request, pk: int):
        obj = LeaveRequest.objects.select_related("employee").filter(pk=pk).first()
        if not obj:
            self.message_user(request, "Leave not found.", level=messages.ERROR)
            return redirect("..")

        ok = self._apply_decision(request, obj, "Rejected")
        if ok:
            self.message_user(request, "Leave rejected.", level=messages.WARNING)
        else:
            self.message_user(request, "You are not allowed to reject.", level=messages.ERROR)
        return redirect(request.META.get("HTTP_REFERER", ".."))

    # ---------------------------
    # Summary context (month/year tables)
    # ---------------------------
    def changelist_view(self, request, extra_context=None):
        cl = self.get_changelist_instance(request)
        qs = cl.get_queryset(request)

        totals = qs.aggregate(
            total=Count("id"),
            approved=Count("id", filter=Q(status="Approved")),
            rejected=Count("id", filter=Q(status="Rejected")),
            pending=Count("id", filter=Q(status="Pending")),
        )

        month_rows = []
        monthly = (
            qs.annotate(m=TruncMonth("created_at"))
            .values("m")
            .annotate(
                total=Count("id"),
                approved=Count("id", filter=Q(status="Approved")),
                rejected=Count("id", filter=Q(status="Rejected")),
                pending=Count("id", filter=Q(status="Pending")),
            )
            .order_by("m")
        )
        for row in monthly:
            if not row["m"]:
                continue
            m = row["m"]
            month_rows.append(
                {
                    "label": m.strftime("%b %Y"),
                    "total": row["total"] or 0,
                    "approved": row["approved"] or 0,
                    "rejected": row["rejected"] or 0,
                    "pending": row["pending"] or 0,
                }
            )

        year_rows = []
        yearly = (
            qs.annotate(y=TruncYear("created_at"))
            .values("y")
            .annotate(
                total=Count("id"),
                approved=Count("id", filter=Q(status="Approved")),
                rejected=Count("id", filter=Q(status="Rejected")),
                pending=Count("id", filter=Q(status="Pending")),
            )
            .order_by("y")
        )
        for row in yearly:
            if not row["y"]:
                continue
            y = row["y"].year
            year_rows.append(
                {
                    "year": y,
                    "total": row["total"] or 0,
                    "approved": row["approved"] or 0,
                    "rejected": row["rejected"] or 0,
                    "pending": row["pending"] or 0,
                }
            )

        extra_context = extra_context or {}
        extra_context["summary"] = {
            "total": totals["total"] or 0,
            "approved": totals["approved"] or 0,
            "rejected": totals["rejected"] or 0,
            "pending": totals["pending"] or 0,
        }
        extra_context["month_rows"] = month_rows
        extra_context["year_rows"] = year_rows

        return super().changelist_view(request, extra_context=extra_context)

    # ---------------------------
    # Existing bulk actions still work
    # ---------------------------
    @admin.action(description="Approve selected leave requests")
    def approve_leave(self, request, queryset):
        updated = 0
        for leave in queryset:
            if self._apply_decision(request, leave, "Approved"):
                updated += 1
        self.message_user(request, f"{updated} leave(s) approved.", level=messages.SUCCESS)

    @admin.action(description="Reject selected leave requests")
    def reject_leave(self, request, queryset):
        updated = 0
        for leave in queryset:
            if self._apply_decision(request, leave, "Rejected"):
                updated += 1
        self.message_user(request, f"{updated} leave(s) rejected.", level=messages.WARNING)

    class Media:
        css = {"all": ("css/admin/leaves.css",)}
