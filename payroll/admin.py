# payroll/admin.py (CLEAN + FIXED - FULL FILE)
# ✅ Removes duplicates
# ✅ Fixes Employee search_fields (uses full_name)
# ✅ Uses *filtered* queryset (respects search + filters + date hierarchy)
# ✅ Fixes quick_filters (no NoneType / preserves params safely)
# ✅ Provides month options + recent rows as dicts for template

from __future__ import annotations
import csv
from datetime import date, timedelta
from decimal import Decimal
from django.http import HttpResponse, JsonResponse, Http404
from django.contrib import admin, messages
from django import forms
from django.db.models import Count, Sum, Avg, Min, Max
from django.db.models.functions import TruncMonth, TruncYear
from django.shortcuts import render
from django.urls import path, reverse
from django.utils.html import format_html
from django.utils.http import urlencode
from django.utils.timezone import localdate, now
from django.utils.http import urlencode
from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
import textwrap
from unfold.admin import ModelAdmin

from accounts.models import Employee, Team
from .models import (
    Expense,
    GlobalSetting,
    EmployeeSalary,
    SalaryPayment,
    PMSalaryShare,
    PMResponsibility,  # kept import in case used elsewhere
    quantize2,
)


# -----------------------------
# Helpers
# -----------------------------
def fmt_money(v, currency: str = "USD") -> str:
    if v is None:
        return "—"
    return f"{v:,.2f} {currency}"


def per_employee_totals(employee_ids=None):
    """
    Returns dict keyed by employee_id with:
    salary_usd, salary_pkr,
    paid_usd, paid_pkr, paid_pm_usd, paid_admin_usd,
    exp_usd, exp_pkr
    """
    data = {}
    qs_e = Employee.objects.all()
    if employee_ids is not None:
        qs_e = qs_e.filter(id__in=employee_ids)

    sal = (
        EmployeeSalary.objects.filter(employee__in=qs_e)
        .values("employee_id")
        .annotate(
            salary_usd=Sum("monthly_salary_usd"),
            salary_pkr=Sum("monthly_salary_pkr"),
        )
    )
    for r in sal:
        data.setdefault(r["employee_id"], {}).update(
            {
                "salary_usd": r["salary_usd"] or Decimal("0"),
                "salary_pkr": r["salary_pkr"] or Decimal("0"),
            }
        )

    paid = (
        SalaryPayment.objects.filter(employee__in=qs_e)
        .values("employee_id")
        .annotate(
            paid_usd=Sum("amount_usd"),
            paid_pkr=Sum("amount_pkr"),
            paid_pm_usd=Sum("pm_share_usd"),
            paid_admin_usd=Sum("admin_share_usd"),
        )
    )
    for r in paid:
        data.setdefault(r["employee_id"], {}).update(
            {
                "paid_usd": r["paid_usd"] or Decimal("0"),
                "paid_pkr": r["paid_pkr"] or Decimal("0"),
                "paid_pm_usd": r["paid_pm_usd"] or Decimal("0"),
                "paid_admin_usd": r["paid_admin_usd"] or Decimal("0"),
            }
        )

    ex = (
        Expense.objects.filter(employee__in=qs_e)
        .values("employee_id")
        .annotate(
            exp_usd=Sum("amount_usd"),
            exp_pkr=Sum("amount_pkr"),
        )
    )
    for r in ex:
        data.setdefault(r["employee_id"], {}).update(
            {
                "exp_usd": r["exp_usd"] or Decimal("0"),
                "exp_pkr": r["exp_pkr"] or Decimal("0"),
            }
        )

    # fill missing keys
    for e_id in qs_e.values_list("id", flat=True):
        data.setdefault(e_id, {}).setdefault("salary_usd", Decimal("0"))
        data[e_id].setdefault("salary_pkr", Decimal("0"))
        data[e_id].setdefault("paid_usd", Decimal("0"))
        data[e_id].setdefault("paid_pkr", Decimal("0"))
        data[e_id].setdefault("paid_pm_usd", Decimal("0"))
        data[e_id].setdefault("paid_admin_usd", Decimal("0"))
        data[e_id].setdefault("exp_usd", Decimal("0"))
        data[e_id].setdefault("exp_pkr", Decimal("0"))

    return data


def _safe_querystring(base_get, **updates) -> str:
    """
    Build querystring from request.GET while updating/removing keys safely.

    Example:
      _safe_querystring(request.GET, date__gte="2025-12-01", date__lt="2026-01-01")
      _safe_querystring(request.GET, date__gte=None, date__lt=None)  # removes keys
    """
    q = base_get.copy()
    for k, v in updates.items():
        if v is None:
            q.pop(k, None)
        else:
            q[k] = v
    return "?" + urlencode(q, doseq=True) if q else "?"


def _next_month_start(d: date) -> date:
    if d.month == 12:
        return d.replace(year=d.year + 1, month=1, day=1)
    return d.replace(month=d.month + 1, day=1)


def _parse_month(value):
    if not value:
        return None
    try:
        parts = value.split("-")
        if len(parts) != 2:
            return None
        y = int(parts[0])
        m = int(parts[1])
        return date(y, m, 1)
    except (TypeError, ValueError):
        return None


def _pm_share_map(pm_ids):
    shares = {pm_id: Decimal("50.00") for pm_id in pm_ids}
    for pm_id, pct in PMSalaryShare.objects.filter(pm_id__in=pm_ids).values_list("pm_id", "share_percentage"):
        shares[pm_id] = pct or Decimal("50.00")
    for pm_id, pct in PMResponsibility.objects.filter(pm_id__in=pm_ids).values_list("pm_id", "percentage"):
        if pm_id not in shares:
            shares[pm_id] = pct or Decimal("50.00")
    return shares


def _settlement_for_records(payments_qs=None, expenses_qs=None):
    payments_qs = payments_qs or SalaryPayment.objects.none()
    expenses_qs = expenses_qs or Expense.objects.none()
    employee_ids = set(payments_qs.values_list("employee_id", flat=True)) | set(
        expenses_qs.values_list("employee_id", flat=True)
    )
    pm_by_employee = {}
    if employee_ids:
        pairs = Team.objects.filter(members__id__in=employee_ids).values_list(
            "members__id", "project_manager_id"
        )
        for member_id, pm_id in pairs:
            pm_by_employee.setdefault(member_id, pm_id)
    pm_ids = {pm_id for pm_id in pm_by_employee.values() if pm_id}
    share_map = _pm_share_map(pm_ids)

    admin_owes = Decimal("0")
    pm_owes = Decimal("0")

    def handle(obj, amount_attr):
        nonlocal admin_owes, pm_owes
        pm_id = pm_by_employee.get(obj.employee_id)
        if not pm_id or not obj.paid_by_id:
            return
        paid_by = obj.paid_by
        if paid_by.role not in ("pm", "admin"):
            return
        amount = getattr(obj, amount_attr) or Decimal("0")
        pct = (share_map.get(pm_id, Decimal("50.00")) or Decimal("50.00")) / Decimal("100")
        if paid_by.role == "pm" and paid_by.id == pm_id:
            admin_owes += amount * (Decimal("1") - pct)
        elif paid_by.role == "admin":
            pm_owes += amount * pct

    for obj in payments_qs.select_related("paid_by"):
        handle(obj, "amount_pkr")
    for obj in expenses_qs.select_related("paid_by"):
        handle(obj, "amount_pkr")

    return {
        "admin_owes_pkr": admin_owes,
        "pm_owes_pkr": pm_owes,
        "net_pkr": admin_owes - pm_owes,
    }

def _invoice_pdf(title, rows):
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    left = 50
    right = width - 50
    y = height - 72

    def new_page():
        nonlocal y
        c.showPage()
        y = height - 72

    # Header block
    c.setFillColorRGB(1, 0.4, 0)
    c.roundRect(left, y - 4, right - left, 52, 10, fill=1, stroke=0)
    c.setFillColorRGB(1, 1, 1)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(left + 14, y + 28, title)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(left + 14, y + 10, "IMA Sales Solution")
    c.setFillColorRGB(0, 0, 0)
    y -= 28

    def draw_card(x, y_top, w, label, value):
        val = str(value) if value is not None else "-"
        lines = textwrap.wrap(val, 40) or ["-"]
        height_needed = 44 + (len(lines) - 1) * 12
        y_bottom = y_top - height_needed
        c.setFillColorRGB(1, 1, 1)
        c.setStrokeColorRGB(0.86, 0.88, 0.92)
        c.roundRect(x, y_bottom, w, height_needed, 8, fill=1, stroke=1)
        c.setFillColorRGB(0.4, 0.45, 0.52)
        c.setFont("Helvetica-Bold", 8)
        c.drawString(x + 10, y_top - 16, label.upper())
        c.setFillColorRGB(0.06, 0.09, 0.16)
        c.setFont("Helvetica-Bold", 11)
        line_y = y_top - 30
        for line in lines:
            c.drawString(x + 10, line_y, line)
            line_y -= 12
        return height_needed + 10

    col_gap = 14
    col_w = (right - left - col_gap) / 2
    y -= 30
    i = 0
    while i < len(rows):
        row = rows[i]
        label = row[0]
        value = row[1]
        span = len(row) == 3 and row[2]
        if y < 120:
            new_page()
            y -= 10
        if span:
            used = draw_card(left, y, right - left, label, value)
            y -= used
            i += 1
            continue
        used_left = draw_card(left, y, col_w, label, value)
        used_right = 0
        if i + 1 < len(rows):
            next_row = rows[i + 1]
            next_label = next_row[0]
            next_value = next_row[1]
            next_span = len(next_row) == 3 and next_row[2]
            if not next_span:
                used_right = draw_card(left + col_w + col_gap, y, col_w, next_label, next_value)
                i += 2
            else:
                i += 1
        else:
            i += 1
        y -= max(used_left, used_right or 0)

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer.getvalue()


def _pkr_to_usd(amount_pkr):
    rate = GlobalSetting.current_rate()
    if not rate:
        return Decimal("0")
    return quantize2(Decimal(amount_pkr) / rate)


class EmployeeSalaryPkrForm(forms.ModelForm):
    monthly_salary_pkr_input = forms.DecimalField(
        label="Monthly Salary (PKR)",
        max_digits=14,
        decimal_places=2,
        min_value=Decimal("0.01"),
        help_text="Enter PKR; USD is calculated automatically.",
    )

    class Meta:
        model = EmployeeSalary
        fields = ["employee", "paid_by", "salary_month", "effective_from", "monthly_salary_usd", "active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "monthly_salary_usd" in self.fields:
            self.fields["monthly_salary_usd"].disabled = True
            self.fields["monthly_salary_usd"].required = False
            self.fields["monthly_salary_usd"].help_text = "Calculated from PKR."
            self.fields["monthly_salary_usd"].validators = []
            self.fields["monthly_salary_usd"].min_value = None
        if self.instance and getattr(self.instance, "pk", None):
            self.fields["monthly_salary_pkr_input"].initial = self.instance.monthly_salary_pkr

    def clean(self):
        cleaned = super().clean()
        pkr = cleaned.get("monthly_salary_pkr_input")
        if pkr is not None:
            cleaned["monthly_salary_usd"] = _pkr_to_usd(pkr)
        return cleaned


class SalaryPaymentPkrForm(forms.ModelForm):
    amount_pkr_input = forms.DecimalField(
        label="Amount (PKR)",
        max_digits=14,
        decimal_places=2,
        min_value=Decimal("0.01"),
        help_text="Enter PKR; USD is calculated automatically.",
    )

    class Meta:
        model = SalaryPayment
        fields = ["employee", "paid_by", "amount_usd", "date_paid", "reference", "note"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "amount_usd" in self.fields:
            self.fields["amount_usd"].disabled = True
            self.fields["amount_usd"].required = False
            self.fields["amount_usd"].help_text = "Calculated from PKR."
            self.fields["amount_usd"].validators = []
            self.fields["amount_usd"].min_value = None
        if self.instance and getattr(self.instance, "pk", None):
            self.fields["amount_pkr_input"].initial = self.instance.amount_pkr
        self.field_order = [
            "employee",
            "paid_by",
            "amount_pkr_input",
            "amount_usd",
            "date_paid",
            "reference",
            "note",
        ]

    def clean(self):
        cleaned = super().clean()
        pkr = cleaned.get("amount_pkr_input")
        if pkr is not None:
            cleaned["amount_usd"] = _pkr_to_usd(pkr)
        return cleaned


class ExpensePkrForm(forms.ModelForm):
    amount_pkr_input = forms.DecimalField(
        label="Amount (PKR)",
        max_digits=14,
        decimal_places=2,
        min_value=Decimal("0.01"),
        help_text="Enter PKR; USD is calculated automatically.",
    )

    class Meta:
        model = Expense
        fields = ["employee", "paid_by", "category", "amount_usd", "notes", "date"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "amount_usd" in self.fields:
            self.fields["amount_usd"].disabled = True
            self.fields["amount_usd"].required = False
            self.fields["amount_usd"].help_text = "Calculated from PKR."
            self.fields["amount_usd"].validators = []
            self.fields["amount_usd"].min_value = None
        if self.instance and getattr(self.instance, "pk", None):
            self.fields["amount_pkr_input"].initial = self.instance.amount_pkr
        self.field_order = [
            "employee",
            "paid_by",
            "category",
            "amount_pkr_input",
            "amount_usd",
            "notes",
            "date",
        ]

    def clean(self):
        cleaned = super().clean()
        pkr = cleaned.get("amount_pkr_input")
        if pkr is not None:
            cleaned["amount_usd"] = _pkr_to_usd(pkr)
        return cleaned


# -----------------------------
# PMSalaryShare
# -----------------------------
@admin.register(PMSalaryShare)
class PMSalaryShareAdmin(ModelAdmin):
    list_display = ("pm", "share_percentage", "note")
    search_fields = ("pm__full_name", "pm__email")
    list_editable = ("share_percentage",)
    change_list_template = "admin/payroll/pmsalaryshare_changelist.html"

    def changelist_view(self, request, extra_context=None):
        cl = self.get_changelist_instance(request)
        qs = cl.get_queryset(request).select_related("pm")

        stats = qs.aggregate(
            count=Count("id"),
            avg=Avg("share_percentage"),
            min=Min("share_percentage"),
            max=Max("share_percentage"),
        )

        # Monthly PM share table (last 12 months)
        today = localdate()
        this_month = today.replace(day=1)
        cursor = this_month
        for _ in range(11):
            if cursor.month == 1:
                cursor = cursor.replace(year=cursor.year - 1, month=12, day=1)
            else:
                cursor = cursor.replace(month=cursor.month - 1, day=1)
        range_start = cursor
        range_end = _next_month_start(this_month)

        pm_ids = list(qs.values_list("pm_id", flat=True))
        teams = Team.objects.filter(project_manager_id__in=pm_ids).prefetch_related("members")
        member_to_pm = {}
        for t in teams:
            for mid in t.members.values_list("id", flat=True):
                member_to_pm[mid] = t.project_manager_id

        member_ids = list(member_to_pm.keys())

        salary_qs = EmployeeSalary.objects.filter(
            employee_id__in=member_ids,
            salary_month__gte=range_start,
            salary_month__lt=range_end,
        )
        payments_qs = SalaryPayment.objects.filter(
            employee_id__in=member_ids,
            date_paid__gte=range_start,
            date_paid__lt=range_end,
        )

        salary_map = {}
        for s in salary_qs:
            pm_id = member_to_pm.get(s.employee_id)
            if not pm_id:
                continue
            m = s.salary_month.replace(day=1)
            key = (pm_id, m)
            salary_map[key] = salary_map.get(key, Decimal("0")) + (s.monthly_salary_pkr or Decimal("0"))

        paid_map = {}
        for p in payments_qs:
            pm_id = member_to_pm.get(p.employee_id)
            if not pm_id:
                continue
            if not p.amount_usd:
                continue
            ratio = (p.pm_share_usd or Decimal("0")) / p.amount_usd
            pm_share_pkr = (p.amount_pkr or Decimal("0")) * ratio
            m = p.date_paid.replace(day=1)
            key = (pm_id, m)
            paid_map[key] = paid_map.get(key, Decimal("0")) + pm_share_pkr

        months = []
        cursor = range_start
        while cursor < range_end:
            months.append(cursor)
            cursor = _next_month_start(cursor)

        month_rows = []
        for pm in qs:
            for m_start in months:
                key = (pm.pm_id, m_start)
                total_salary = salary_map.get(key, Decimal("0"))
                pm_share = (total_salary * (pm.share_percentage or Decimal("0")) / Decimal("100"))
                pm_paid = paid_map.get(key, Decimal("0"))
                pm_due = pm_share - pm_paid
                month_rows.append(
                    {
                        "pm": pm.pm,
                        "month": m_start.strftime("%b %Y"),
                        "share_pct": pm.share_percentage or Decimal("0"),
                        "salary_pkr": total_salary,
                        "pm_share_pkr": pm_share,
                        "pm_paid_pkr": pm_paid,
                        "pm_due_pkr": pm_due,
                    }
                )

        extra_context = extra_context or {}
        extra_context["summary"] = {
            "title": "PM Salary Shares",
            "count": stats["count"] or 0,
            "avg": stats["avg"] or Decimal("0"),
            "min": stats["min"] or Decimal("0"),
            "max": stats["max"] or Decimal("0"),
            "add_url": reverse("admin:payroll_pmsalaryshare_add"),
        }
        extra_context["month_rows"] = month_rows
        return super().changelist_view(request, extra_context=extra_context)


# -----------------------------
# GlobalSetting (Dashboard + Summary)
# -----------------------------
@admin.register(GlobalSetting)
class GlobalSettingAdmin(ModelAdmin):
    list_display = ("usd_to_pkr_rate", "updated_at", "note")
    search_fields = ("note",)
    actions = ["recalculate_all_pkr"]

    change_list_template = "admin/payroll/globalsetting_changelist.html"
    change_form_template = "admin/payroll/globalsetting/change_form.html"

    def has_add_permission(self, request):
        return request.user.is_superuser

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "dashboard/",
                self.admin_site.admin_view(self.dashboard_view),
                name="payroll_dashboard",
            ),
            path(
                "summary/",
                self.admin_site.admin_view(self.summary_view),
                name="payroll_company_summary",
            ),
            path(
                "invoices/",
                self.admin_site.admin_view(self.monthly_invoices_view),
                name="payroll_monthly_invoices",
            ),
            path(
                "invoices/export/",
                self.admin_site.admin_view(self.monthly_invoice_export),
                name="payroll_monthly_invoice_export",
            ),
        ]
        return custom + urls

    def dashboard_view(self, request):
        if not request.user.is_authenticated:
            raise Http404
        role = getattr(request.user, "role", None)
        if not (
            request.user.is_superuser
            or role == "admin"
            or request.user.has_perm("payroll.view_salarypayment")
            or request.user.has_perm("payroll.view_expense")
        ):
            raise Http404

        employee_ids = None
        teams_qs = Team.objects.all()
        if role == "pm":
            teams_qs = Team.objects.filter(project_manager=request.user)
            employee_ids = list(
                Employee.objects.filter(teams__project_manager=request.user)
                .values_list("id", flat=True)
                .distinct()
            )

        salary_qs = EmployeeSalary.objects.all()
        payment_qs = SalaryPayment.objects.all()
        expense_qs = Expense.objects.all()
        if employee_ids is not None:
            salary_qs = salary_qs.filter(employee_id__in=employee_ids)
            payment_qs = payment_qs.filter(employee_id__in=employee_ids)
            expense_qs = expense_qs.filter(employee_id__in=employee_ids)

        salaries = salary_qs.aggregate(
            total_usd=Sum("monthly_salary_usd"),
            total_pkr=Sum("monthly_salary_pkr"),
        )
        paid = payment_qs.aggregate(
            total_usd=Sum("amount_usd"),
            total_pkr=Sum("amount_pkr"),
        )
        expenses = expense_qs.aggregate(
            total_usd=Sum("amount_usd"),
            total_pkr=Sum("amount_pkr"),
        )
        expense_rows = (
            expense_qs.values("category")
            .annotate(
                total_usd=Sum("amount_usd"),
                total_pkr=Sum("amount_pkr"),
            )
            .order_by("category")
        )
        expense_totals = {r["category"]: r for r in expense_rows}
        expense_labels = dict(Expense.CATEGORY_CHOICES)
        expense_categories = [
            Expense.UPWORK_JOB,
            Expense.ADVANCE,
            Expense.UPWORK_CONNECTS,
            Expense.OTHER,
        ]
        expense_boxes = []
        for key in expense_categories:
            row = expense_totals.get(key, {})
            expense_boxes.append(
                {
                    "key": key,
                    "label": expense_labels.get(key, key),
                    "total_usd": row.get("total_usd") or Decimal("0"),
                    "total_pkr": row.get("total_pkr") or Decimal("0"),
                }
            )

        teams = []
        for team in teams_qs:
            emp_ids = team.members.values_list("id", flat=True)

            total_salary = (
                EmployeeSalary.objects.filter(employee__in=emp_ids).aggregate(
                    total=Sum("monthly_salary_usd")
                )["total"]
                or Decimal("0")
            )

            paid_usd = (
                SalaryPayment.objects.filter(employee__in=emp_ids).aggregate(
                    total=Sum("amount_usd")
                )["total"]
                or Decimal("0")
            )

            try:
                share_obj = PMSalaryShare.objects.get(pm=team.project_manager)
                pm_share = total_salary * (share_obj.share_percentage / Decimal("100"))
            except PMSalaryShare.DoesNotExist:
                pm_share = total_salary / 2

            admin_share = total_salary - pm_share

            teams.append(
                {
                    "pm": team.project_manager,
                    "total_salary_usd": total_salary,
                    "paid_usd": paid_usd,
                    "pm_share": pm_share,
                    "admin_share": admin_share,
                    "remaining_pm_usd": pm_share - paid_usd,
                }
            )

        remaining_pkr = (salaries["total_pkr"] or Decimal("0")) - (
            paid["total_pkr"] or Decimal("0")
        ) - (expenses["total_pkr"] or Decimal("0"))

        # Monthly + yearly summaries
        salary_months = (
            salary_qs.annotate(m=TruncMonth("salary_month"))
            .values("m")
            .annotate(salary_pkr=Sum("monthly_salary_pkr"))
        )
        paid_months = (
            payment_qs.annotate(m=TruncMonth("date_paid"))
            .values("m")
            .annotate(paid_pkr=Sum("amount_pkr"))
        )
        exp_months = (
            expense_qs.annotate(m=TruncMonth("date"))
            .values("m")
            .annotate(exp_pkr=Sum("amount_pkr"))
        )

        month_map = {}
        for row in salary_months:
            if row["m"]:
                month_map.setdefault(row["m"], {})["salary_pkr"] = row["salary_pkr"] or Decimal("0")
        for row in paid_months:
            if row["m"]:
                month_map.setdefault(row["m"], {})["paid_pkr"] = row["paid_pkr"] or Decimal("0")
        for row in exp_months:
            if row["m"]:
                month_map.setdefault(row["m"], {})["exp_pkr"] = row["exp_pkr"] or Decimal("0")

        month_rows = []
        month_labels = []
        month_salary = []
        month_paid = []
        month_exp = []
        for m in sorted(month_map.keys()):
            vals = month_map[m]
            month_labels.append(m.strftime("%b %Y"))
            month_salary.append(float(vals.get("salary_pkr", Decimal("0"))))
            month_paid.append(float(vals.get("paid_pkr", Decimal("0"))))
            month_exp.append(float(vals.get("exp_pkr", Decimal("0"))))
            month_rows.append(
                {
                    "label": m.strftime("%b %Y"),
                    "salary_pkr": vals.get("salary_pkr", Decimal("0")),
                    "paid_pkr": vals.get("paid_pkr", Decimal("0")),
                    "exp_pkr": vals.get("exp_pkr", Decimal("0")),
                }
            )

        salary_years = (
            salary_qs.annotate(y=TruncYear("salary_month"))
            .values("y")
            .annotate(salary_pkr=Sum("monthly_salary_pkr"))
        )
        paid_years = (
            payment_qs.annotate(y=TruncYear("date_paid"))
            .values("y")
            .annotate(paid_pkr=Sum("amount_pkr"))
        )
        exp_years = (
            expense_qs.annotate(y=TruncYear("date"))
            .values("y")
            .annotate(exp_pkr=Sum("amount_pkr"))
        )

        year_map = {}
        for row in salary_years:
            if row["y"]:
                year_map.setdefault(row["y"].year, {})["salary_pkr"] = row["salary_pkr"] or Decimal("0")
        for row in paid_years:
            if row["y"]:
                year_map.setdefault(row["y"].year, {})["paid_pkr"] = row["paid_pkr"] or Decimal("0")
        for row in exp_years:
            if row["y"]:
                year_map.setdefault(row["y"].year, {})["exp_pkr"] = row["exp_pkr"] or Decimal("0")

        year_rows = []
        year_labels = []
        year_salary = []
        year_paid = []
        year_exp = []
        for y in sorted(year_map.keys()):
            vals = year_map[y]
            year_labels.append(str(y))
            year_salary.append(float(vals.get("salary_pkr", Decimal("0"))))
            year_paid.append(float(vals.get("paid_pkr", Decimal("0"))))
            year_exp.append(float(vals.get("exp_pkr", Decimal("0"))))
            year_rows.append(
                {
                    "year": y,
                    "salary_pkr": vals.get("salary_pkr", Decimal("0")),
                    "paid_pkr": vals.get("paid_pkr", Decimal("0")),
                    "exp_pkr": vals.get("exp_pkr", Decimal("0")),
                }
            )

        context = dict(
            self.admin_site.each_context(request),
            title="Payroll Dashboard",
            salaries=salaries,
            paid=paid,
            expenses=expenses,
            expense_boxes=expense_boxes,
            month_rows=month_rows,
            year_rows=year_rows,
            month_labels=month_labels,
            month_salary=month_salary,
            month_paid=month_paid,
            month_exp=month_exp,
            year_labels=year_labels,
            year_salary=year_salary,
            year_paid=year_paid,
            year_exp=year_exp,
            teams=teams,
            remaining_pkr=remaining_pkr,
            rate=GlobalSetting.current_rate(),
            settlement=_settlement_for_records(payment_qs, expense_qs),
        )
        return render(request, "admin/payroll_dashboard.html", context)

    def summary_view(self, request):
        salaries = EmployeeSalary.objects.aggregate(
            total_usd=Sum("monthly_salary_usd"),
            total_pkr=Sum("monthly_salary_pkr"),
        )
        paid = SalaryPayment.objects.aggregate(
            total_usd=Sum("amount_usd"),
            total_pkr=Sum("amount_pkr"),
            total_pm_usd=Sum("pm_share_usd"),
            total_admin_usd=Sum("admin_share_usd"),
        )
        expenses = Expense.objects.aggregate(
            total_usd=Sum("amount_usd"),
            total_pkr=Sum("amount_pkr"),
        )

        cat_breakdown = (
            Expense.objects.values("category")
            .annotate(usd=Sum("amount_usd"), pkr=Sum("amount_pkr"))
            .order_by("category")
        )

        remaining_pkr = (salaries["total_pkr"] or Decimal("0")) - (
            paid["total_pkr"] or Decimal("0")
        ) - (expenses["total_pkr"] or Decimal("0"))

        context = dict(
            self.admin_site.each_context(request),
            title="Payroll Summary",
            now=now(),
            rate=GlobalSetting.current_rate(),
            salaries=salaries,
            paid=paid,
            expenses=expenses,
            cat_breakdown=cat_breakdown,
            remaining_pkr=remaining_pkr,
        )
        return render(request, "admin/payroll_company_summary.html", context)

    def _allowed_employees(self, request):
        role = getattr(request.user, "role", None)
        if request.user.is_superuser or role == "admin":
            return Employee.objects.all()
        if role == "pm":
            return Employee.objects.filter(teams__project_manager=request.user).distinct()
        return Employee.objects.none()

    def monthly_invoices_view(self, request):
        month_value = request.GET.get("month")
        month_start = _parse_month(month_value) or localdate().replace(day=1)
        month_end = _next_month_start(month_start)

        employees_qs = self._allowed_employees(request).order_by("full_name", "email")
        employee_ids = list(employees_qs.values_list("id", flat=True))
        employee_id = request.GET.get("employee")
        selected_employee = None
        if employee_id and employee_id.isdigit():
            employee_id = int(employee_id)
            if employee_id in employee_ids:
                selected_employee = employees_qs.filter(id=employee_id).first()

        salary_totals = (
            EmployeeSalary.objects.filter(
                employee_id__in=employee_ids,
                salary_month__gte=month_start,
                salary_month__lt=month_end,
            )
            .values("employee_id")
            .annotate(salary_usd=Sum("monthly_salary_usd"), salary_pkr=Sum("monthly_salary_pkr"))
        )
        salary_map = {r["employee_id"]: r for r in salary_totals}

        payment_totals = (
            SalaryPayment.objects.filter(
                employee_id__in=employee_ids,
                date_paid__gte=month_start,
                date_paid__lt=month_end,
            )
            .values("employee_id")
            .annotate(paid_usd=Sum("amount_usd"), paid_pkr=Sum("amount_pkr"))
        )
        payment_map = {r["employee_id"]: r for r in payment_totals}

        expense_totals = (
            Expense.objects.filter(
                employee_id__in=employee_ids,
                date__gte=month_start,
                date__lt=month_end,
            )
            .values("employee_id")
            .annotate(exp_usd=Sum("amount_usd"), exp_pkr=Sum("amount_pkr"))
        )
        expense_map = {r["employee_id"]: r for r in expense_totals}

        summary_rows = []
        for emp in employees_qs:
            s = salary_map.get(emp.id, {})
            p = payment_map.get(emp.id, {})
            e = expense_map.get(emp.id, {})
            salary_pkr = s.get("salary_pkr") or Decimal("0")
            paid_pkr = p.get("paid_pkr") or Decimal("0")
            exp_pkr = e.get("exp_pkr") or Decimal("0")
            summary_rows.append(
                {
                    "employee": emp,
                    "salary_pkr": salary_pkr,
                    "salary_usd": s.get("salary_usd") or Decimal("0"),
                    "paid_pkr": paid_pkr,
                    "paid_usd": p.get("paid_usd") or Decimal("0"),
                    "exp_pkr": exp_pkr,
                    "exp_usd": e.get("exp_usd") or Decimal("0"),
                    "due_pkr": salary_pkr - paid_pkr - exp_pkr,
                }
            )
        if selected_employee:
            summary_rows = [r for r in summary_rows if r["employee"].id == selected_employee.id]

        salary_entries = []
        payment_entries = []
        expense_entries = []
        if selected_employee:
            salary_entries = (
                EmployeeSalary.objects.filter(
                    employee=selected_employee,
                    salary_month__gte=month_start,
                    salary_month__lt=month_end,
                )
                .select_related("paid_by")
                .order_by("salary_month")
            )
            payment_entries = (
                SalaryPayment.objects.filter(
                    employee=selected_employee,
                    date_paid__gte=month_start,
                    date_paid__lt=month_end,
                )
                .select_related("paid_by")
                .order_by("date_paid")
            )
            expense_entries = (
                Expense.objects.filter(
                    employee=selected_employee,
                    date__gte=month_start,
                    date__lt=month_end,
                )
                .select_related("paid_by")
                .order_by("date")
            )

        export_url = ""
        if selected_employee:
            export_url = reverse("admin:payroll_monthly_invoice_export") + "?" + urlencode(
                {"employee": selected_employee.id, "month": month_start.strftime("%Y-%m")}
            )

        context = dict(
            self.admin_site.each_context(request),
            title="Monthly Invoices",
            month_start=month_start,
            month_end=month_end,
            employees=list(employees_qs),
            selected_employee=selected_employee,
            summary_rows=summary_rows,
            salary_entries=salary_entries,
            payment_entries=payment_entries,
            expense_entries=expense_entries,
            export_url=export_url,
        )
        return render(request, "admin/payroll/monthly_invoices.html", context)

    def monthly_invoice_export(self, request):
        employee_id = request.GET.get("employee")
        month_value = request.GET.get("month")
        month_start = _parse_month(month_value) or localdate().replace(day=1)
        month_end = _next_month_start(month_start)

        employees_qs = self._allowed_employees(request)
        if not employee_id or not employee_id.isdigit():
            raise Http404("Employee required.")
        employee_id = int(employee_id)
        emp = employees_qs.filter(id=employee_id).first()
        if not emp:
            raise Http404("Employee not found.")

        salary_entries = EmployeeSalary.objects.filter(
            employee=emp,
            salary_month__gte=month_start,
            salary_month__lt=month_end,
        )
        payment_entries = SalaryPayment.objects.filter(
            employee=emp,
            date_paid__gte=month_start,
            date_paid__lt=month_end,
        )
        expense_entries = Expense.objects.filter(
            employee=emp,
            date__gte=month_start,
            date__lt=month_end,
        )

        salary_pkr = salary_entries.aggregate(total=Sum("monthly_salary_pkr"))["total"] or Decimal("0")
        salary_usd = salary_entries.aggregate(total=Sum("monthly_salary_usd"))["total"] or Decimal("0")
        paid_pkr = payment_entries.aggregate(total=Sum("amount_pkr"))["total"] or Decimal("0")
        paid_usd = payment_entries.aggregate(total=Sum("amount_usd"))["total"] or Decimal("0")
        exp_pkr = expense_entries.aggregate(total=Sum("amount_pkr"))["total"] or Decimal("0")
        exp_usd = expense_entries.aggregate(total=Sum("amount_usd"))["total"] or Decimal("0")

        def _list_lines_salary(qs):
            lines = []
            for item in qs.order_by("salary_month"):
                payer = getattr(item.paid_by, "full_name", item.paid_by) if item.paid_by else "-"
                lines.append(
                    f"{item.salary_month} | Paid By: {payer} | {item.monthly_salary_pkr} PKR ({item.monthly_salary_usd} USD)"
                )
            return lines

        def _list_lines_payment(qs):
            lines = []
            for item in qs.order_by("date_paid"):
                payer = getattr(item.paid_by, "full_name", item.paid_by) if item.paid_by else "-"
                lines.append(
                    f"{item.date_paid} | Paid By: {payer} | {item.amount_pkr} PKR ({item.amount_usd} USD)"
                )
            return lines

        def _list_lines_expense(qs):
            lines = []
            for item in qs.order_by("date"):
                payer = getattr(item.paid_by, "full_name", item.paid_by) if item.paid_by else "-"
                lines.append(
                    f"{item.date} | {item.get_category_display()} | Paid By: {payer} | {item.amount_pkr} PKR ({item.amount_usd} USD)"
                )
            return lines

        rows = [
            ("Employee", getattr(emp, "full_name", emp)),
            ("Month", month_start.strftime("%B %Y")),
            ("Total Salary (PKR)", fmt_money(salary_pkr, "PKR")),
            ("Total Salary (USD)", fmt_money(salary_usd, "USD")),
            ("Total Paid (PKR)", fmt_money(paid_pkr, "PKR")),
            ("Total Paid (USD)", fmt_money(paid_usd, "USD")),
            ("Total Expenses (PKR)", fmt_money(exp_pkr, "PKR")),
            ("Total Expenses (USD)", fmt_money(exp_usd, "USD")),
        ]
        salary_lines = _list_lines_salary(salary_entries)
        payment_lines = _list_lines_payment(payment_entries)
        expense_lines = _list_lines_expense(expense_entries)
        if salary_lines:
            rows.append(("Salary Entries", "\n".join(salary_lines), True))
        else:
            rows.append(("Salary Entries", "-", True))
        if payment_lines:
            rows.append(("Payments", "\n".join(payment_lines), True))
        else:
            rows.append(("Payments", "-", True))
        if expense_lines:
            rows.append(("Expenses", "\n".join(expense_lines), True))
        else:
            rows.append(("Expenses", "-", True))

        pdf = _invoice_pdf("Monthly Invoice", rows)
        response = HttpResponse(pdf, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="monthly_invoice_{emp.pk}_{month_start:%Y_%m}.pdf"'
        return response

    @admin.action(
        description="Recalculate PKR for all salaries/payments/expenses using the latest USD rate"
    )
    def recalculate_all_pkr(self, request, queryset):
        rate = GlobalSetting.current_rate()

        for obj in EmployeeSalary.objects.all():
            obj.save(request=request)
        for obj in SalaryPayment.objects.all():
            obj.save(request=request)
        for obj in Expense.objects.all():
            obj.save(request=request)

        self.message_user(
            request,
            f"Recalculated PKR amounts with USD→PKR rate {rate}.",
            level=messages.SUCCESS,
        )


# -----------------------------
# EmployeeSalary
# -----------------------------
@admin.register(EmployeeSalary)
class EmployeeSalaryAdmin(ModelAdmin):
    form = EmployeeSalaryPkrForm
    list_display = (
        "employee",
        "paid_by",
        "monthly_salary_usd_fmt",
        "monthly_salary_pkr_fmt",
        "effective_from",
        "active",
        "paid_so_far_usd_fmt",
        "paid_so_far_pkr_fmt",
        "paid_pm_usd_fmt",
        "paid_admin_usd_fmt",
        "expenses_usd_fmt",
        "expenses_pkr_fmt",
        "remaining_pkr_fmt",
        "preview_btn",
    )
    list_filter = ("active", "effective_from")
    search_fields = ("employee__full_name",  "employee__email")
    autocomplete_fields = ("employee",)

    change_list_template = "admin/payroll/salary_changelist.html"
    change_form_template = "admin/payroll/salary_change_form.html"
    date_hierarchy = "salary_month"

    def get_autocomplete_fields(self, request):
        if getattr(request.user, "role", None) == "pm":
            return []
        return super().get_autocomplete_fields(request)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "employee" and getattr(request.user, "role", None) == "pm":
            member_ids = Team.objects.filter(project_manager=request.user).values_list("members__id", flat=True)
            kwargs["queryset"] = Employee.objects.filter(id__in=member_ids).distinct().order_by("full_name", "email")
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def change_view(self, request, object_id, form_url="", extra_context=None):
        obj = self.get_object(request, object_id)
        extra_context = extra_context or {}

        if obj:
            history = (
                EmployeeSalary.objects.filter(employee=obj.employee)
                .order_by("-salary_month", "-id")
            )

            totals = history.aggregate(
                total_usd=Sum("monthly_salary_usd"),
                total_pkr=Sum("monthly_salary_pkr"),
            )

            salary_history_url = (
                reverse("admin:payroll_employeesalary_changelist")
                + "?"
                + urlencode({"employee__id__exact": obj.employee_id})
            )
            payments_url = (
                reverse("admin:payroll_salarypayment_changelist")
                + "?"
                + urlencode({"employee__id__exact": obj.employee_id})
            )
            expenses_url = (
                reverse("admin:payroll_expense_changelist")
                + "?"
                + urlencode({"employee__id__exact": obj.employee_id})
            )
            add_new_month_url = (
                reverse("admin:payroll_employeesalary_add")
                + "?"
                + urlencode({"employee": obj.employee_id})
            )

            extra_context.update(
                {
                    "salary_obj": obj,
                    "employee_obj": obj.employee,
                    "salary_history": history,
                    "history_totals": totals,
                    "salary_history_url": salary_history_url,
                    "payments_url": payments_url,
                    "expenses_url": expenses_url,
                    "add_new_month_url": add_new_month_url,
                    "export_monthly_pdf_url": reverse(
                        "admin:payroll_employeesalary_export_monthly_pdf",
                        args=[obj.id],
                    ),
                    "rate": GlobalSetting.current_rate(),
                    "today": localdate(),
                }
            )

            # --- Last 12 months summary (payments/expenses/salary) ---
            today = localdate()
            this_month = today.replace(day=1)
            # compute start at 12 months ago (inclusive)
            cursor = this_month
            for _ in range(11):
                if cursor.month == 1:
                    cursor = cursor.replace(year=cursor.year - 1, month=12, day=1)
                else:
                    cursor = cursor.replace(month=cursor.month - 1, day=1)
            range_start = cursor
            range_end = _next_month_start(this_month)

            emp = obj.employee

            settlement = _settlement_for_records(
                SalaryPayment.objects.filter(employee=emp, date_paid__gte=range_start, date_paid__lt=range_end),
                Expense.objects.filter(employee=emp, date__gte=range_start, date__lt=range_end),
            )
            extra_context["settlement"] = settlement

            salary_qs = EmployeeSalary.objects.filter(
                employee=emp, salary_month__gte=range_start, salary_month__lt=range_end
            )
            salary_map = {}
            for s in salary_qs:
                m = s.salary_month.replace(day=1)
                salary_map[m] = {
                    "usd": s.monthly_salary_usd or Decimal("0"),
                    "pkr": s.monthly_salary_pkr or Decimal("0"),
                }

            payments_qs = SalaryPayment.objects.filter(
                employee=emp, date_paid__gte=range_start, date_paid__lt=range_end
            )
            payments_monthly = (
                payments_qs.annotate(m=TruncMonth("date_paid"))
                .values("m")
                .annotate(usd=Sum("amount_usd"), pkr=Sum("amount_pkr"))
            )
            payments_map = {
                (row["m"].date() if hasattr(row["m"], "date") else row["m"]): {
                    "usd": row["usd"] or Decimal("0"),
                    "pkr": row["pkr"] or Decimal("0"),
                }
                for row in payments_monthly
                if row.get("m")
            }

            expenses_qs = Expense.objects.filter(
                employee=emp, date__gte=range_start, date__lt=range_end
            )
            expenses_monthly = (
                expenses_qs.annotate(m=TruncMonth("date"))
                .values("m")
                .annotate(usd=Sum("amount_usd"), pkr=Sum("amount_pkr"))
            )
            expenses_map = {
                (row["m"].date() if hasattr(row["m"], "date") else row["m"]): {
                    "usd": row["usd"] or Decimal("0"),
                    "pkr": row["pkr"] or Decimal("0"),
                }
                for row in expenses_monthly
                if row.get("m")
            }

            month_labels = []
            salary_usd_series = []
            salary_pkr_series = []
            paid_usd_series = []
            paid_pkr_series = []
            exp_usd_series = []
            exp_pkr_series = []
            due_pkr_series = []
            rows = []

            yearly = {}
            cursor = range_start
            while cursor < range_end:
                label = cursor.strftime("%b %Y")
                month_labels.append(label)

                sal = salary_map.get(cursor, {"usd": Decimal("0"), "pkr": Decimal("0")})
                pay = payments_map.get(cursor, {"usd": Decimal("0"), "pkr": Decimal("0")})
                exp = expenses_map.get(cursor, {"usd": Decimal("0"), "pkr": Decimal("0")})

                salary_usd_series.append(float(sal["usd"]))
                salary_pkr_series.append(float(sal["pkr"]))
                paid_usd_series.append(float(pay["usd"]))
                paid_pkr_series.append(float(pay["pkr"]))
                exp_usd_series.append(float(exp["usd"]))
                exp_pkr_series.append(float(exp["pkr"]))

                due_pkr = (sal["pkr"] or Decimal("0")) - (pay["pkr"] or Decimal("0")) - (exp["pkr"] or Decimal("0"))
                due_pkr_series.append(float(due_pkr))

                rows.append(
                    {
                        "label": label,
                        "salary_usd": sal["usd"],
                        "salary_pkr": sal["pkr"],
                        "paid_usd": pay["usd"],
                        "paid_pkr": pay["pkr"],
                        "exp_usd": exp["usd"],
                        "exp_pkr": exp["pkr"],
                        "due_pkr": due_pkr,
                    }
                )

                y = cursor.year
                yearly.setdefault(y, {"salary_pkr": Decimal("0"), "paid_pkr": Decimal("0"), "exp_pkr": Decimal("0")})
                yearly[y]["salary_pkr"] += sal["pkr"] or Decimal("0")
                yearly[y]["paid_pkr"] += pay["pkr"] or Decimal("0")
                yearly[y]["exp_pkr"] += exp["pkr"] or Decimal("0")

                cursor = _next_month_start(cursor)

            yearly_rows = []
            for y in sorted(yearly.keys()):
                vals = yearly[y]
                yearly_rows.append(
                    {
                        "year": y,
                        "salary_pkr": vals["salary_pkr"],
                        "paid_pkr": vals["paid_pkr"],
                        "exp_pkr": vals["exp_pkr"],
                        "due_pkr": vals["salary_pkr"] - vals["paid_pkr"] - vals["exp_pkr"],
                    }
                )

            total_salary_pkr_12 = sum((r["salary_pkr"] or Decimal("0")) for r in rows)
            total_salary_usd_12 = sum((r["salary_usd"] or Decimal("0")) for r in rows)
            total_paid_pkr_12 = sum((r["paid_pkr"] or Decimal("0")) for r in rows)
            total_paid_usd_12 = sum((r["paid_usd"] or Decimal("0")) for r in rows)
            total_exp_pkr_12 = sum((r["exp_pkr"] or Decimal("0")) for r in rows)
            total_exp_usd_12 = sum((r["exp_usd"] or Decimal("0")) for r in rows)
            total_due_pkr_12 = total_salary_pkr_12 - total_paid_pkr_12 - total_exp_pkr_12

            extra_context.update(
                {
                    "month_labels": month_labels,
                    "salary_usd_series": salary_usd_series,
                    "salary_pkr_series": salary_pkr_series,
                    "paid_usd_series": paid_usd_series,
                    "paid_pkr_series": paid_pkr_series,
                    "exp_usd_series": exp_usd_series,
                    "exp_pkr_series": exp_pkr_series,
                    "due_pkr_series": due_pkr_series,
                    "month_rows": rows,
                    "yearly_rows": yearly_rows,
                    "range_start": range_start,
                    "range_end": range_end,
                    "total_salary_pkr_12": total_salary_pkr_12,
                    "total_salary_usd_12": total_salary_usd_12,
                    "total_paid_pkr_12": total_paid_pkr_12,
                    "total_paid_usd_12": total_paid_usd_12,
                "total_exp_pkr_12": total_exp_pkr_12,
                "total_exp_usd_12": total_exp_usd_12,
                "total_due_pkr_12": total_due_pkr_12,
                "settlement": settlement,
            }
        )

        return super().change_view(
            request, object_id, form_url, extra_context=extra_context
        )

    # ---------------------------
    # Export: last 12 months PDF
    # ---------------------------
    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "export/<int:pk>/monthly-pdf/",
                self.admin_site.admin_view(self.export_monthly_pdf),
                name="payroll_employeesalary_export_monthly_pdf",
            )
        ]
        return custom + urls

    def export_monthly_pdf(self, request, pk):
        obj = self.get_queryset(request).filter(pk=pk).select_related("employee").first()
        if not obj:
            raise Http404("Salary record not found.")

        # Build last 12 months rows
        today = localdate()
        this_month = today.replace(day=1)
        cursor = this_month
        for _ in range(11):
            if cursor.month == 1:
                cursor = cursor.replace(year=cursor.year - 1, month=12, day=1)
            else:
                cursor = cursor.replace(month=cursor.month - 1, day=1)
        range_start = cursor
        range_end = _next_month_start(this_month)

        emp = obj.employee

        salary_qs = EmployeeSalary.objects.filter(
            employee=emp, salary_month__gte=range_start, salary_month__lt=range_end
        )
        salary_map = {}
        for s in salary_qs:
            m = s.salary_month.replace(day=1)
            salary_map[m] = {
                "usd": s.monthly_salary_usd or Decimal("0"),
                "pkr": s.monthly_salary_pkr or Decimal("0"),
            }

        payments_qs = SalaryPayment.objects.filter(
            employee=emp, date_paid__gte=range_start, date_paid__lt=range_end
        )
        payments_monthly = (
            payments_qs.annotate(m=TruncMonth("date_paid"))
            .values("m")
            .annotate(usd=Sum("amount_usd"), pkr=Sum("amount_pkr"))
        )
        payments_map = {
            (row["m"].date() if hasattr(row["m"], "date") else row["m"]): {
                "usd": row["usd"] or Decimal("0"),
                "pkr": row["pkr"] or Decimal("0"),
            }
            for row in payments_monthly
            if row.get("m")
        }

        expenses_qs = Expense.objects.filter(
            employee=emp, date__gte=range_start, date__lt=range_end
        )
        expenses_monthly = (
            expenses_qs.annotate(m=TruncMonth("date"))
            .values("m")
            .annotate(usd=Sum("amount_usd"), pkr=Sum("amount_pkr"))
        )
        expenses_map = {
            (row["m"].date() if hasattr(row["m"], "date") else row["m"]): {
                "usd": row["usd"] or Decimal("0"),
                "pkr": row["pkr"] or Decimal("0"),
            }
            for row in expenses_monthly
            if row.get("m")
        }

        rows = []
        cursor = range_start
        while cursor < range_end:
            sal = salary_map.get(cursor, {"usd": Decimal("0"), "pkr": Decimal("0")})
            pay = payments_map.get(cursor, {"usd": Decimal("0"), "pkr": Decimal("0")})
            exp = expenses_map.get(cursor, {"usd": Decimal("0"), "pkr": Decimal("0")})
            due_pkr = (sal["pkr"] or Decimal("0")) - (pay["pkr"] or Decimal("0")) - (exp["pkr"] or Decimal("0"))
            rows.append(
                [
                    cursor.strftime("%b %Y"),
                    f"{sal['pkr']:.0f}",
                    f"{pay['pkr']:.0f}",
                    f"{exp['pkr']:.0f}",
                    f"{due_pkr:.0f}",
                ]
            )
            cursor = _next_month_start(cursor)

        total_salary_pkr = sum(Decimal(r[1]) for r in rows)
        total_paid_pkr = sum(Decimal(r[2]) for r in rows)
        total_exp_pkr = sum(Decimal(r[3]) for r in rows)
        total_due_pkr = total_salary_pkr - total_paid_pkr - total_exp_pkr

        pdf_bytes = self._build_styled_pdf(
            title="IMA Sales Solution",
            subtitle="Employee Salary Summary (Last 12 Months)",
            employee=f"{emp.full_name or emp.email or emp.cnic}",
            note=f"Range: {range_start} to {range_end - timedelta(days=1)}",
            headers=["Month", "Salary PKR", "Paid PKR", "Expenses PKR", "Due PKR"],
            rows=rows,
            totals={
                "salary": total_salary_pkr,
                "paid": total_paid_pkr,
                "exp": total_exp_pkr,
                "due": total_due_pkr,
            },
        )

        filename = "salary_summary_last_12_months.pdf"
        resp = HttpResponse(pdf_bytes, content_type="application/pdf")
        resp["Content-Disposition"] = f'attachment; filename="{filename}"'
        return resp

    @staticmethod
    def _build_styled_pdf(title, subtitle, employee, note, headers, rows, totals):
        """
        Styled PDF with header bar and table (ASCII-safe).
        """
        def esc(text):
            return (
                str(text)
                .replace("\\", "\\\\")
                .replace("(", "\\(")
                .replace(")", "\\)")
            )

        def to_latin1(text):
            return esc(text).encode("latin-1", "replace").decode("latin-1")

        def text_cmd(x, y, size, text, font="F1"):
            return f"BT /{font} {size} Tf {x} {y} Td ({to_latin1(text)}) Tj ET"

        def rect_cmd(x, y, w, h, stroke=True, fill=False):
            ops = [f"{x} {y} {w} {h} re"]
            if stroke and fill:
                ops.append("B")
            elif fill:
                ops.append("f")
            else:
                ops.append("S")
            return "\n".join(ops)

        def rgb_fill(r, g, b):
            return f"{r} {g} {b} rg"

        def rgb_stroke(r, g, b):
            return f"{r} {g} {b} RG"

        def fmt_num(v):
            try:
                return f"{int(v):,}"
            except Exception:
                return str(v)

        # Layout
        page_w, page_h = 595, 842
        margin = 40
        table_w = page_w - margin * 2
        col_w = [90, 105, 100, 110, 95]
        if sum(col_w) > table_w:
            scale = table_w / sum(col_w)
            col_w = [w * scale for w in col_w]

        # Colors (primary orange, base dark, light gray)
        primary = (1.0, 0.4, 0.0)
        base = (0.09, 0.09, 0.09)
        soft = (0.96, 0.96, 0.96)
        line = (0.86, 0.88, 0.90)
        muted = (0.35, 0.37, 0.40)

        y = page_h - margin
        content = []

        # Title block
        content.append(rgb_fill(*base))
        content.append(text_cmd(margin, y - 10, 16, title, font="F2"))
        y -= 22
        content.append(rgb_fill(*muted))
        content.append(text_cmd(margin, y - 8, 10, subtitle, font="F2"))
        y -= 14
        content.append(text_cmd(margin, y - 8, 9, employee))
        y -= 14
        content.append(text_cmd(margin, y - 8, 9, note))
        y -= 22

        # Divider
        content.append(rgb_stroke(*line))
        content.append(rect_cmd(margin, y, table_w, 0.5, stroke=True, fill=False))
        y -= 10

        # Totals row
        content.append(rgb_fill(*primary))
        content.append(rect_cmd(margin, y - 20, table_w, 20, stroke=False, fill=True))
        content.append(rgb_fill(1, 1, 1))
        totals_text = (
            f"Total Salary: {fmt_num(totals['salary'])} PKR   "
            f"Paid: {fmt_num(totals['paid'])} PKR   "
            f"Expenses: {fmt_num(totals['exp'])} PKR   "
            f"Due: {fmt_num(totals['due'])} PKR"
        )
        content.append(text_cmd(margin + 8, y - 14, 9, totals_text, font="F2"))
        y -= 28

        # Header bar
        content.append(rgb_fill(*primary))
        content.append(rect_cmd(margin, y - 22, table_w, 22, stroke=False, fill=True))
        content.append(rgb_fill(1, 1, 1))
        x = margin + 6
        for i, h in enumerate(headers):
            content.append(text_cmd(x, y - 16, 9, h, font="F2"))
            x += col_w[i]
        y -= 26

        # Rows
        content.append(rgb_stroke(*line))
        for idx, r in enumerate(rows):
            if idx % 2 == 0:
                content.append(rgb_fill(*soft))
                content.append(rect_cmd(margin, y - 20, table_w, 20, stroke=False, fill=True))
            content.append(rgb_fill(*base))
            x = margin + 6
            content.append(text_cmd(x, y - 14, 9, r[0]))
            x += col_w[0]

            def right_text(col_idx, text):
                w = col_w[col_idx]
                # crude width estimate (5.6 px per char at 9pt)
                est = min(w - 10, len(text) * 5.6)
                return x + w - 8 - est

            for col_idx, val in enumerate(r[1:], start=1):
                val = fmt_num(val)
                tx = right_text(col_idx, val)
                content.append(text_cmd(tx, y - 14, 9, val))
                x += col_w[col_idx]

            y -= 20

        # Outline
        content.append(rgb_stroke(*line))
        content.append(rect_cmd(margin, y, table_w, (page_h - margin) - y - 22, stroke=True, fill=False))

        stream = "\n".join(content)

        # PDF objects
        objects = []

        def add_obj(s):
            objects.append(s)

        add_obj("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")        # 1
        add_obj("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>")   # 2
        add_obj(f"<< /Length {len(stream.encode('latin-1'))} >>\nstream\n{stream}\nendstream")  # 3
        add_obj(
            "<< /Type /Page /Parent 5 0 R /MediaBox [0 0 595 842] "
            "/Resources << /Font << /F1 1 0 R /F2 2 0 R >> >> "
            "/Contents 3 0 R >>"
        )  # 4
        add_obj("<< /Type /Pages /Kids [4 0 R] /Count 1 >>")  # 5
        add_obj("<< /Type /Catalog /Pages 5 0 R >>")  # 6

        pdf = ["%PDF-1.4"]
        offsets = []
        for i, obj in enumerate(objects, start=1):
            offsets.append(sum(len(x.encode("latin-1")) + 1 for x in pdf))
            pdf.append(f"{i} 0 obj\n{obj}\nendobj")
        xref_offset = sum(len(x.encode("latin-1")) + 1 for x in pdf)
        xref = ["xref", f"0 {len(objects)+1}", "0000000000 65535 f "]
        for off in offsets:
            xref.append(f"{off:010d} 00000 n ")
        pdf.extend(xref)
        pdf.append(f"trailer << /Size {len(objects)+1} /Root 6 0 R >>")
        pdf.append(f"startxref\n{xref_offset}\n%%EOF")
        return "\n".join(pdf).encode("latin-1")

    @staticmethod
    def _parse_salary_month_range(base_get):
        year = base_get.get("salary_month__year")
        month = base_get.get("salary_month__month")
        day = base_get.get("salary_month__day")

        if year:
            try:
                y = int(year)
                if month and day:
                    m = int(month)
                    d = int(day)
                    start = date(y, m, d)
                    end = start + timedelta(days=1)
                    return start, end
                if month:
                    m = int(month)
                    start = date(y, m, 1)
                    return start, _next_month_start(start)
                start = date(y, 1, 1)
                return start, date(y + 1, 1, 1)
            except (TypeError, ValueError):
                pass

        def _parse_iso(value):
            try:
                return date.fromisoformat(value)
            except (TypeError, ValueError):
                return None

        start = _parse_iso(base_get.get("salary_month__gte"))
        end = _parse_iso(base_get.get("salary_month__lt"))
        if not end:
            end_lte = _parse_iso(base_get.get("salary_month__lte"))
            if end_lte:
                end = end_lte + timedelta(days=1)
        return start, end

    @staticmethod
    def _salary_month_qs(base_get, start, end):
        return _safe_querystring(
            base_get,
            salary_month__year=None,
            salary_month__month=None,
            salary_month__day=None,
            salary_month__lte=None,
            salary_month__gte=str(start),
            salary_month__lt=str(end),
        )

    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related("employee")
        if request.user.is_superuser:
            return qs
        if getattr(request.user, "role", None) == "pm":
            try:
                team = Team.objects.get(project_manager=request.user)
                return qs.filter(employee__in=team.members.all())
            except Team.DoesNotExist:
                return qs.none()
        return qs.none()

    def changelist_view(self, request, extra_context=None):
        cl = self.get_changelist_instance(request)
        qs = cl.get_queryset(request).select_related("employee")

        base_get = request.GET

        latest_by_emp = {}
        for obj in qs.order_by("employee_id", "-salary_month", "-id"):
            if obj.employee_id not in latest_by_emp:
                latest_by_emp[obj.employee_id] = obj

        employee_ids = list(latest_by_emp.keys())
        totals_map = per_employee_totals(employee_ids)

        total_salary_usd = sum(
            (totals_map.get(eid, {}).get("salary_usd") or Decimal("0"))
            for eid in employee_ids
        )
        total_salary_pkr = sum(
            (totals_map.get(eid, {}).get("salary_pkr") or Decimal("0"))
            for eid in employee_ids
        )
        total_paid_usd = sum(
            (totals_map.get(eid, {}).get("paid_usd") or Decimal("0"))
            for eid in employee_ids
        )
        total_paid_pkr = sum(
            (totals_map.get(eid, {}).get("paid_pkr") or Decimal("0"))
            for eid in employee_ids
        )
        total_exp_usd = sum(
            (totals_map.get(eid, {}).get("exp_usd") or Decimal("0"))
            for eid in employee_ids
        )
        total_exp_pkr = sum(
            (totals_map.get(eid, {}).get("exp_pkr") or Decimal("0"))
            for eid in employee_ids
        )
        total_due_usd = total_salary_usd - total_paid_usd - total_exp_usd
        total_due_pkr = total_salary_pkr - total_paid_pkr - total_exp_pkr

        cards = []
        for obj in latest_by_emp.values():
            t = totals_map.get(obj.employee_id, {})
            remaining = (t.get("salary_pkr") or Decimal("0")) - (
                t.get("paid_pkr") or Decimal("0")
            ) - (t.get("exp_pkr") or Decimal("0"))

            cards.append(
                {
                    "id": obj.id,
                    "employee": obj.employee,
                    "active": bool(obj.active),
                    "salary_month": obj.salary_month,
                    "effective_from": obj.effective_from,
                    "monthly_usd": obj.monthly_salary_usd or Decimal("0"),
                    "monthly_pkr": obj.monthly_salary_pkr or Decimal("0"),
                    "total_salary_usd": t.get("salary_usd") or Decimal("0"),
                    "total_salary_pkr": t.get("salary_pkr") or Decimal("0"),
                    "paid_usd": t.get("paid_usd") or Decimal("0"),
                    "paid_pkr": t.get("paid_pkr") or Decimal("0"),
                    "exp_usd": t.get("exp_usd") or Decimal("0"),
                    "exp_pkr": t.get("exp_pkr") or Decimal("0"),
                    "remaining_pkr": remaining,
                }
            )

        cards.sort(key=lambda r: (getattr(r["employee"], "full_name", "") or ""))

        salary_qs_base = self.get_queryset(request)
        employee_filter = base_get.get("employee__id__exact")
        if employee_filter:
            salary_qs_base = salary_qs_base.filter(employee__id=employee_filter)
        active_filter = base_get.get("active__exact")
        if active_filter in ("0", "1"):
            salary_qs_base = salary_qs_base.filter(active=bool(int(active_filter)))

        month_rows = (
            salary_qs_base.annotate(m=TruncMonth("salary_month"))
            .values("m")
            .distinct()
            .order_by("m")
        )
        available_months = []
        for row in month_rows:
            m = row["m"]
            if not m:
                continue
            m_start = m.date() if hasattr(m, "date") else m
            m_next = _next_month_start(m_start)
            available_months.append(
                {
                    "label": m_start.strftime("%b %Y"),
                    "start": m_start,
                    "url": self._salary_month_qs(base_get, m_start, m_next),
                }
            )

        extra_context = extra_context or {}
        extra_context["summary"] = {
            "title": "Total Monthly Salaries",
            "total_salary_usd": total_salary_usd,
            "total_salary_pkr": total_salary_pkr,
            "total_paid_usd": total_paid_usd,
            "total_paid_pkr": total_paid_pkr,
            "total_exp_usd": total_exp_usd,
            "total_exp_pkr": total_exp_pkr,
            "total_due_usd": total_due_usd,
            "total_due_pkr": total_due_pkr,
            "available_months": available_months,
            "quick_filters": {
                "clear": "?",
            },
            "settlement": _settlement_for_records(
                SalaryPayment.objects.filter(employee_id__in=employee_ids),
                Expense.objects.filter(employee_id__in=employee_ids),
            ),
        }
        extra_context["cards"] = cards
        return super().changelist_view(request, extra_context=extra_context)

    def save_model(self, request, obj, form, change):
        pkr = form.cleaned_data.get("monthly_salary_pkr_input")
        if pkr is not None:
            obj.monthly_salary_usd = _pkr_to_usd(pkr)
            obj.monthly_salary_pkr = pkr
        if not obj.paid_by_id:
            obj.paid_by = request.user
        obj.save(request=request)

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if "paid_by" in form.base_fields:
            if getattr(request.user, "role", None) == "pm":
                form.base_fields["paid_by"].queryset = Employee.objects.filter(pk=request.user.pk)
                form.base_fields["paid_by"].initial = request.user.pk
                form.base_fields["paid_by"].disabled = True
            else:
                form.base_fields["paid_by"].queryset = Employee.objects.all().order_by("full_name", "email")
                if not form.base_fields["paid_by"].initial:
                    form.base_fields["paid_by"].initial = request.user.pk
        return form

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        extra_context = extra_context or {}
        extra_context["pkr_rate"] = GlobalSetting.current_rate()
        return super().changeform_view(request, object_id, form_url, extra_context=extra_context)

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "preview/<int:pk>/",
                self.admin_site.admin_view(self.preview_salary),
                name="payroll_employeesalary_preview",
            ),
            path(
                "export/<int:pk>/monthly-pdf/",
                self.admin_site.admin_view(self.export_monthly_pdf),
                name="payroll_employeesalary_export_monthly_pdf",
            ),
        ]
        return custom + urls

    def preview_salary(self, request, pk):
        obj = self.get_queryset(request).filter(pk=pk).select_related("employee", "paid_by").first()
        if not obj:
            return JsonResponse({"ok": False}, status=404)
        data = {
            "ok": True,
            "employee": getattr(obj.employee, "full_name", str(obj.employee)),
            "paid_by": getattr(obj.paid_by, "full_name", str(obj.paid_by)) if obj.paid_by else "-",
            "salary_month": str(obj.salary_month),
            "effective_from": str(obj.effective_from),
            "monthly_salary_usd": fmt_money(obj.monthly_salary_usd, "USD"),
            "monthly_salary_pkr": fmt_money(obj.monthly_salary_pkr, "PKR"),
            "active": "Yes" if obj.active else "No",
        }
        return JsonResponse(data)

    @admin.display(description="Preview")
    def preview_btn(self, obj):
        return format_html(
            '<button type="button" class="preview-btn" data-preview-id="{}">Preview</button>',
            obj.pk,
        )

    def has_module_permission(self, request):
        if not request.user.is_authenticated:
            return False
        if request.user.is_superuser or getattr(request.user, "role", None) == "admin":
            return True
        return request.user.has_perm("payroll.view_employeesalary")

    def has_view_permission(self, request, obj=None):
        return self.has_module_permission(request)

    # formatters
    def monthly_salary_usd_fmt(self, obj):
        return fmt_money(obj.monthly_salary_usd, "USD")

    def monthly_salary_pkr_fmt(self, obj):
        return fmt_money(obj.monthly_salary_pkr, "PKR")

    def _get_totals(self, obj):
        return per_employee_totals([obj.employee_id]).get(obj.employee_id, {})

    def paid_so_far_usd_fmt(self, obj):
        return fmt_money(self._get_totals(obj).get("paid_usd"), "USD")

    def paid_so_far_pkr_fmt(self, obj):
        return fmt_money(self._get_totals(obj).get("paid_pkr"), "PKR")

    def paid_pm_usd_fmt(self, obj):
        return fmt_money(self._get_totals(obj).get("paid_pm_usd"), "USD")

    def paid_admin_usd_fmt(self, obj):
        return fmt_money(self._get_totals(obj).get("paid_admin_usd"), "USD")

    def expenses_usd_fmt(self, obj):
        return fmt_money(self._get_totals(obj).get("exp_usd"), "USD")

    def expenses_pkr_fmt(self, obj):
        return fmt_money(self._get_totals(obj).get("exp_pkr"), "PKR")

    def remaining_pkr_fmt(self, obj):
        t = self._get_totals(obj)
        remaining = (t.get("salary_pkr") or Decimal("0")) - (
            t.get("paid_pkr") or Decimal("0")
        ) - (t.get("exp_pkr") or Decimal("0"))
        return format_html("<b>{}</b>", fmt_money(remaining, "PKR"))

    monthly_salary_usd_fmt.short_description = "Monthly Salary (USD)"
    monthly_salary_pkr_fmt.short_description = "Monthly Salary (PKR)"
    paid_so_far_usd_fmt.short_description = "Paid Salary (USD)"
    paid_so_far_pkr_fmt.short_description = "Paid Salary (PKR)"
    paid_pm_usd_fmt.short_description = "PM Share (USD)"
    paid_admin_usd_fmt.short_description = "Admin Share (USD)"
    expenses_usd_fmt.short_description = "Expenses (USD)"
    expenses_pkr_fmt.short_description = "Expenses (PKR)"
    remaining_pkr_fmt.short_description = "Remaining (PKR)"

    class Media:
        css = {
            "all": (
                "css/admin/payroll_salary_cards.css",
                "css/admin/payroll_salary_detail.css",
            )
        }


# -----------------------------
# SalaryPayment
# -----------------------------
@admin.register(SalaryPayment)
class SalaryPaymentAdmin(ModelAdmin):
    form = SalaryPaymentPkrForm
    list_display = (
        "employee",
        "paid_by",
        "amount_usd_fmt",
        "amount_pkr_fmt",
        "pm_share_fmt",
        "admin_share_fmt",
        "date_paid",
        "reference",
        "preview_btn",
    )

    # ✅ Inline editing for common field
    list_editable = ("reference",)

    list_filter = ("date_paid",)
    search_fields = (
        "employee__full_name",
        "employee__email",
        "reference",
        "note",
    )
    autocomplete_fields = ("employee",)
    date_hierarchy = "date_paid"

    change_list_template = "admin/payroll/payment_changelist.html"
    change_form_template = "admin/payroll/payment_change_form.html"


    actions = [
        "recalculate_pkr",
        "recalculate_pm_shares",
        "export_selected_csv",
        "autofill_missing_reference",
    ]

    # performance
    list_select_related = ("employee",)

    def save_model(self, request, obj, form, change):
        pkr = form.cleaned_data.get("amount_pkr_input")
        if pkr is not None:
            obj.amount_usd = _pkr_to_usd(pkr)
            obj.amount_pkr = pkr
        if not obj.paid_by_id:
            obj.paid_by = request.user
        obj.save(request=request)

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if "paid_by" in form.base_fields:
            if getattr(request.user, "role", None) == "pm":
                form.base_fields["paid_by"].queryset = Employee.objects.filter(pk=request.user.pk)
                form.base_fields["paid_by"].initial = request.user.pk
                form.base_fields["paid_by"].disabled = True
            else:
                form.base_fields["paid_by"].queryset = Employee.objects.all().order_by("full_name", "email")
                if not form.base_fields["paid_by"].initial:
                    form.base_fields["paid_by"].initial = request.user.pk
        return form
    def _pm_percentage_for_employee(self, employee):
        pm_id = Team.objects.filter(members=employee).values_list("project_manager", flat=True).first()
        if not pm_id:
            return Decimal("0")
        try:
            return PMSalaryShare.objects.get(pm_id=pm_id).share_percentage
        except PMSalaryShare.DoesNotExist:
            try:
                return PMResponsibility.objects.get(pm_id=pm_id).percentage
            except PMResponsibility.DoesNotExist:
                return Decimal("50.00")

    @admin.action(description="Recalculate PM/Admin shares for selected payments")
    def recalculate_pm_shares(self, request, queryset):
        updated = 0
        for obj in queryset.select_related("employee"):
            pm_percentage = self._pm_percentage_for_employee(obj.employee)
            obj.pm_share_usd = quantize2(obj.amount_usd * pm_percentage / 100)
            obj.admin_share_usd = quantize2(obj.amount_usd - obj.pm_share_usd)
            obj.save(update_fields=["pm_share_usd", "admin_share_usd"])
            updated += 1
        self.message_user(request, f"Updated PM/Admin shares for {updated} payments.", level=messages.SUCCESS)

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        extra_context = extra_context or {}
        extra_context["pkr_rate"] = GlobalSetting.current_rate()
        return super().changeform_view(request, object_id, form_url, extra_context=extra_context)

    def get_autocomplete_fields(self, request):
        if getattr(request.user, "role", None) == "pm":
            return []
        return super().get_autocomplete_fields(request)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "employee" and getattr(request.user, "role", None) == "pm":
            member_ids = Team.objects.filter(project_manager=request.user).values_list("members__id", flat=True)
            kwargs["queryset"] = Employee.objects.filter(id__in=member_ids).distinct().order_by("full_name", "email")
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related("employee")
        if request.user.is_superuser:
            return qs
        if getattr(request.user, "role", None) == "pm":
            try:
                team = Team.objects.get(project_manager=request.user)
                return qs.filter(employee__in=team.members.all())
            except Team.DoesNotExist:
                return qs.none()
        return qs.none()

    def _salary_queryset_for_user(self, request):
        qs = EmployeeSalary.objects.select_related("employee")
        if request.user.is_superuser:
            return qs
        if getattr(request.user, "role", None) == "pm":
            try:
                team = Team.objects.get(project_manager=request.user)
                return qs.filter(employee__in=team.members.all())
            except Team.DoesNotExist:
                return qs.none()
        return qs.none()

    @staticmethod
    def _parse_date_range(base_get):
        """
        Derive an inclusive/exclusive date range from admin GET params.
        Supports date_paid__year/month/day and date_paid__gte/lt/lte.
        """
        year = base_get.get("date_paid__year")
        month = base_get.get("date_paid__month")
        day = base_get.get("date_paid__day")

        if year:
            try:
                y = int(year)
                if month and day:
                    m = int(month)
                    d = int(day)
                    start = date(y, m, d)
                    end = start + timedelta(days=1)
                    return start, end
                if month:
                    m = int(month)
                    start = date(y, m, 1)
                    return start, _next_month_start(start)
                start = date(y, 1, 1)
                return start, date(y + 1, 1, 1)
            except (TypeError, ValueError):
                pass

        def _parse_iso(value):
            try:
                return date.fromisoformat(value)
            except (TypeError, ValueError):
                return None

        start = _parse_iso(base_get.get("date_paid__gte"))
        end = _parse_iso(base_get.get("date_paid__lt"))
        if not end:
            end_lte = _parse_iso(base_get.get("date_paid__lte"))
            if end_lte:
                end = end_lte + timedelta(days=1)
        return start, end

    # ---------------------------
    # Custom URLs (Export + Preview)
    # ---------------------------
    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "export/csv/",
                self.admin_site.admin_view(self.export_current_csv),
                name="payroll_salarypayment_export_csv",
            ),
            path(
                "preview/<int:pk>/",
                self.admin_site.admin_view(self.preview_payment),
                name="payroll_salarypayment_preview",
            ),
            path(
                "invoice/<int:pk>/",
                self.admin_site.admin_view(self.invoice_payment_pdf),
                name="payroll_salarypayment_invoice",
            ),
        ]
        return custom + urls

    # ---------------------------
    # Export (current filtered view)
    # ---------------------------
    def export_current_csv(self, request):
        """
        Exports the *current changelist queryset* (respects search, filters, date_hierarchy, etc).
        """
        cl = self.get_changelist_instance(request)
        qs = cl.get_queryset(request)

        resp = HttpResponse(content_type="text/csv")
        resp["Content-Disposition"] = 'attachment; filename="salary_payments.csv"'
        w = csv.writer(resp)

        w.writerow(
            [
                "Employee",
                "Employee Email",
                "Amount USD",
                "Amount PKR",
                "PM Share USD",
                "Admin Share USD",
                "Date Paid",
                "Reference",
                "Created At",
            ]
        )
        for obj in qs:
            w.writerow(
                [
                    getattr(obj.employee, "full_name", str(obj.employee)),
                    getattr(obj.employee, "email", ""),
                    obj.amount_usd or 0,
                    obj.amount_pkr or 0,
                    obj.pm_share_usd or 0,
                    obj.admin_share_usd or 0,
                    obj.date_paid,
                    obj.reference or "",
                    obj.created_at,
                ]
            )
        return resp

    # ---------------------------
    # Quick preview JSON
    # ---------------------------
    def preview_payment(self, request, pk):
        obj = self.get_queryset(request).filter(pk=pk).first()
        if not obj:
            return JsonResponse({"ok": False}, status=404)

        pm_share_pkr = Decimal("0")
        admin_share_pkr = Decimal("0")
        if obj.amount_usd and obj.amount_pkr:
            ratio = (obj.pm_share_usd or Decimal("0")) / obj.amount_usd
            pm_share_pkr = obj.amount_pkr * ratio
            admin_share_pkr = (obj.amount_pkr or Decimal("0")) - pm_share_pkr

        data = {
            "ok": True,
            "employee": getattr(obj.employee, "full_name", str(obj.employee)),
            "paid_by": getattr(obj.paid_by, "full_name", str(obj.paid_by)) if obj.paid_by else "-",
            "email": getattr(obj.employee, "email", ""),
            "amount_usd": fmt_money(obj.amount_usd, "USD"),
            "amount_pkr": fmt_money(obj.amount_pkr, "PKR"),
            "pm_share": fmt_money(pm_share_pkr, "PKR"),
            "admin_share": fmt_money(admin_share_pkr, "PKR"),
            "date_paid": str(obj.date_paid),
            "reference": obj.reference or "—",
            "note": getattr(obj, "note", "") or "—",
            "created_at": str(obj.created_at),
        }
        return JsonResponse(data)

    def invoice_payment_pdf(self, request, pk):
        obj = self.get_queryset(request).filter(pk=pk).select_related("employee", "paid_by").first()
        if not obj:
            return JsonResponse({"ok": False}, status=404)

        pm_share_pkr = Decimal("0")
        admin_share_pkr = Decimal("0")
        if obj.amount_usd and obj.amount_pkr:
            ratio = (obj.pm_share_usd or Decimal("0")) / obj.amount_usd
            pm_share_pkr = obj.amount_pkr * ratio
            admin_share_pkr = (obj.amount_pkr or Decimal("0")) - pm_share_pkr

        rows = [
            ("Employee", getattr(obj.employee, "full_name", obj.employee)),
            ("Paid By", getattr(obj.paid_by, "full_name", obj.paid_by) if obj.paid_by else "-"),
            ("Amount PKR", fmt_money(obj.amount_pkr, "PKR")),
            ("Amount USD", fmt_money(obj.amount_usd, "USD")),
            ("PM Share (PKR)", fmt_money(pm_share_pkr, "PKR")),
            ("Admin Share (PKR)", fmt_money(admin_share_pkr, "PKR")),
            ("Date Paid", obj.date_paid),
            ("Reference", obj.reference or "-", True),
        ]
        pdf = _invoice_pdf("Salary Payment Invoice", rows)
        response = HttpResponse(pdf, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="salary_payment_{obj.pk}.pdf"'
        return response

    @admin.display(description="Preview")
    def preview_btn(self, obj):
        return format_html(
            '<button type="button" class="preview-btn" data-preview-id="{}">Preview</button>',
            obj.pk,
        )

    # ---------------------------
    # Dashboard context + modern quick filters
    # ---------------------------
    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        cl = self.get_changelist_instance(request)
        qs = cl.get_queryset(request)

        totals = qs.aggregate(
            total_usd=Sum("amount_usd"),
            total_pkr=Sum("amount_pkr"),
            total_pm_usd=Sum("pm_share_usd"),
            total_admin_usd=Sum("admin_share_usd"),
        )

        base_get = request.GET
        salary_qs_base = self._salary_queryset_for_user(request)

        # Optional employee filter alignment (if user uses admin filters)
        employee_id = base_get.get("employee__id__exact")
        if employee_id:
            salary_qs_base = salary_qs_base.filter(employee__id=employee_id)

        range_start, range_end = self._parse_date_range(base_get)
        salary_qs = salary_qs_base
        if range_start:
            salary_qs = salary_qs.filter(salary_month__gte=range_start)
        if range_end:
            salary_qs = salary_qs.filter(salary_month__lt=range_end)

        salary_totals = salary_qs.aggregate(
            total_usd=Sum("monthly_salary_usd"),
            total_pkr=Sum("monthly_salary_pkr"),
        )

        total_salary_usd = salary_totals["total_usd"] or Decimal("0")
        total_salary_pkr = salary_totals["total_pkr"] or Decimal("0")
        total_paid_usd = totals["total_usd"] or Decimal("0")
        total_paid_pkr = totals["total_pkr"] or Decimal("0")
        total_due_usd = total_salary_usd - total_paid_usd
        total_due_pkr = total_salary_pkr - total_paid_pkr

        # Anomalies
        missing_ref = qs.filter(reference__isnull=True).count() + qs.filter(reference="").count()
        high_threshold = Decimal("500")
        high_count = qs.filter(amount_usd__gte=high_threshold).count()

        # helper: keep existing GET params + apply updates
        def _qs(base_get, **updates):
            q = base_get.copy()
            for k, v in updates.items():
                if v is None:
                    q.pop(k, None)
                else:
                    q[k] = v
            return "?" + urlencode(q, doseq=True) if q else "?"

        today = localdate()
        tomorrow = today + timedelta(days=1)

        this_month_start = today.replace(day=1)
        if this_month_start.month == 12:
            next_month_start = this_month_start.replace(year=this_month_start.year + 1, month=1)
        else:
            next_month_start = this_month_start.replace(month=this_month_start.month + 1)

        last_30_start = today - timedelta(days=30)

        quick_filters = {
            "today": _qs(base_get, date_paid__gte=str(today), date_paid__lt=str(tomorrow)),
            "this_month": _qs(base_get, date_paid__gte=str(this_month_start), date_paid__lt=str(next_month_start)),
            "last_30": _qs(base_get, date_paid__gte=str(last_30_start), date_paid__lt=str(tomorrow)),
            "clear": "?",
        }

        # Month chips based on available salary months
        month_rows = (
            salary_qs_base.annotate(m=TruncMonth("salary_month"))
            .values("m")
            .distinct()
            .order_by("m")
        )
        available_months = []
        for row in month_rows:
            m = row["m"]
            if not m:
                continue
            m_start = m.date() if hasattr(m, "date") else m
            m_next = _next_month_start(m_start)
            available_months.append(
                {
                    "label": m_start.strftime("%b %Y"),
                    "start": m_start,
                    "url": _qs(base_get, date_paid__gte=str(m_start), date_paid__lt=str(m_next)),
                }
            )


        # Export URL (keeps query string)
        export_url = "export/csv/" + (("?" + base_get.urlencode()) if base_get.urlencode() else "")

        extra_context["summary"] = {
            "title": "Salary Payments",
            "total_salary_usd": total_salary_usd,
            "total_salary_pkr": total_salary_pkr,
            "total_paid_usd": total_paid_usd,
            "total_paid_pkr": total_paid_pkr,
            "total_due_usd": total_due_usd,
            "total_due_pkr": total_due_pkr,
            "pm_usd": totals["total_pm_usd"] or Decimal("0"),
            "admin_usd": totals["total_admin_usd"] or Decimal("0"),
            "rate": GlobalSetting.current_rate() if hasattr(GlobalSetting, "current_rate") else None,
            "quick_filters": quick_filters,
            "available_months": available_months,
            "export_url": export_url,
            "alerts": {
                "missing_ref": missing_ref,
                "high_count": high_count,
                "high_threshold": str(high_threshold),
            },
            "settlement": _settlement_for_records(qs),
        }

        return super().changelist_view(request, extra_context=extra_context)

    # ---------------------------
    # Actions
    # ---------------------------
    @admin.action(description="Recalculate PKR for selected payments")
    def recalculate_pkr(self, request, queryset):
        for obj in queryset:
            obj.save(request=request)
        self.message_user(request, "PKR recalculated for selected payments.", level=messages.SUCCESS)

    @admin.action(description="Export selected as CSV")
    def export_selected_csv(self, request, queryset):
        resp = HttpResponse(content_type="text/csv")
        resp["Content-Disposition"] = 'attachment; filename="salary_payments_selected.csv"'
        w = csv.writer(resp)
        w.writerow(["Employee", "Amount USD", "Amount PKR", "Date Paid", "Reference", "Created At"])
        for obj in queryset.select_related("employee"):
            w.writerow(
                [
                    getattr(obj.employee, "full_name", str(obj.employee)),
                    obj.amount_usd or 0,
                    obj.amount_pkr or 0,
                    obj.date_paid,
                    obj.reference or "",
                    obj.created_at,
                ]
            )
        return resp

    @admin.action(description="Auto-fill empty reference with employee name (selected)")
    def autofill_missing_reference(self, request, queryset):
        updated = 0
        for obj in queryset.select_related("employee"):
            if not obj.reference:
                obj.reference = getattr(obj.employee, "full_name", "Payment")
                obj.save(update_fields=["reference"])
                updated += 1
        self.message_user(request, f"Updated {updated} payments with missing reference.", level=messages.SUCCESS)

    # ---------------------------
    # Formatters
    # ---------------------------
    def amount_usd_fmt(self, obj):
        return fmt_money(obj.amount_usd, "USD")

    def amount_pkr_fmt(self, obj):
        return fmt_money(obj.amount_pkr, "PKR")

    def pm_share_fmt(self, obj):
        if not obj.amount_usd or not obj.amount_pkr:
            return fmt_money(Decimal("0"), "PKR")
        ratio = (obj.pm_share_usd or Decimal("0")) / obj.amount_usd
        pm_share_pkr = obj.amount_pkr * ratio
        return fmt_money(pm_share_pkr, "PKR")

    def admin_share_fmt(self, obj):
        if not obj.amount_usd or not obj.amount_pkr:
            return fmt_money(Decimal("0"), "PKR")
        ratio = (obj.pm_share_usd or Decimal("0")) / obj.amount_usd
        pm_share_pkr = obj.amount_pkr * ratio
        admin_share_pkr = (obj.amount_pkr or Decimal("0")) - pm_share_pkr
        return fmt_money(admin_share_pkr, "PKR")

    amount_usd_fmt.short_description = "Amount (USD)"
    amount_pkr_fmt.short_description = "Amount (PKR)"
    pm_share_fmt.short_description = "PM Share (PKR)"
    admin_share_fmt.short_description = "Admin Share (PKR)"
# -----------------------------
# Expense
# -----------------------------
@admin.register(Expense)
class ExpenseAdmin(ModelAdmin):
    form = ExpensePkrForm
    list_display = (
        "employee",
        "paid_by",
        "category",
        "amount_usd_fmt",
        "amount_pkr_fmt",
        "date",
        "short_notes",
        "preview_btn",
    )
    list_filter = ("category", "date")
    search_fields = (
        "employee__full_name",
        "employee__email",
        "category",
        "notes",
    )
    autocomplete_fields = ("employee",)
    date_hierarchy = "date"

    change_list_template = "admin/payroll/expense_changelist.html"
    change_form_template = "admin/payroll/expense/change_form.html"

    def get_autocomplete_fields(self, request):
        if getattr(request.user, "role", None) == "pm":
            return []
        return super().get_autocomplete_fields(request)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "employee" and getattr(request.user, "role", None) == "pm":
            member_ids = Team.objects.filter(project_manager=request.user).values_list("members__id", flat=True)
            kwargs["queryset"] = Employee.objects.filter(id__in=member_ids).distinct().order_by("full_name", "email")
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related("employee")
        if request.user.is_superuser:
            return qs
        if getattr(request.user, "role", None) == "pm":
            try:
                team = Team.objects.get(project_manager=request.user)
                return qs.filter(employee__in=team.members.all())
            except Team.DoesNotExist:
                return qs.none()
        return qs.none()

    def _filtered_queryset(self, request):
        """
        ✅ IMPORTANT:
        The admin changelist applies search/filter/date hierarchy at the ChangeList level.
        If we want dashboard numbers to match what's on screen, we must use that queryset.
        """
        cl = self.get_changelist_instance(request)
        return cl.get_queryset(request)

    def changelist_view(self, request, extra_context=None):
        # ✅ Use filtered queryset (respects q=, category filter, date_hierarchy, etc.)
        qs = self._filtered_queryset(request)

        # Totals
        totals = qs.aggregate(
            total_usd=Sum("amount_usd"),
            total_pkr=Sum("amount_pkr"),
        )
        total_usd = totals["total_usd"] or Decimal("0")
        total_pkr = totals["total_pkr"] or Decimal("0")
        count = qs.count()

        # Breakdown by category (USD/PKR + count)
        breakdown = (
            qs.values("category")
            .annotate(
                usd=Sum("amount_usd"),
                pkr=Sum("amount_pkr"),
                cnt=Count("id"),
            )
            .order_by("-usd")
        )

        top = breakdown.first()
        top_category = top["category"] if top else "—"
        top_usd = (top.get("usd") or Decimal("0")) if top else Decimal("0")
        top_pkr = (top.get("pkr") or Decimal("0")) if top else Decimal("0")

        breakdown_rows = []
        for row in breakdown:
            usd_val = row["usd"] or Decimal("0")
            pkr_val = row["pkr"] or Decimal("0")
            pct = (usd_val / total_usd * 100) if total_usd > 0 else Decimal("0")
            breakdown_rows.append(
                {
                    "category": row["category"],
                    "usd": usd_val,
                    "pkr": pkr_val,
                    "pct": pct,
                    "cnt": row["cnt"] or 0,
                }
            )

        # Monthly trend (based on current filters)
        monthly = (
            qs.annotate(m=TruncMonth("date"))
            .values("m")
            .annotate(
                usd=Sum("amount_usd"),
                pkr=Sum("amount_pkr"),
                cnt=Count("id"),
            )
            .order_by("m")
        )

        trend_labels, trend_usd, trend_pkr, trend_cnt = [], [], [], []
        for r in monthly:
            m = r["m"]
            trend_labels.append(m.strftime("%b %Y") if m else "—")
            trend_usd.append(float(r["usd"] or 0))
            trend_pkr.append(float(r["pkr"] or 0))
            trend_cnt.append(int(r["cnt"] or 0))

        # Top spenders
        top_employees = (
            qs.values("employee__full_name", "employee__email")
            .annotate(
                usd=Sum("amount_usd"),
                pkr=Sum("amount_pkr"),
                cnt=Count("id"),
            )
            .order_by("-usd")[:7]
        )

        # Recent (as dicts so template is predictable)
        recent_qs = qs.order_by("-date", "-created_at")[:7]
        recent = []
        for r in recent_qs:
            recent.append(
                {
                    "employee": getattr(r.employee, "full_name", str(r.employee)),
                    "category": r.category,
                    "date": r.date,
                    "amount_usd": r.amount_usd,
                    "amount_pkr": r.amount_pkr,
                    "notes": r.notes,
                }
            )

        # Quick filters (date ranges)
        today = localdate()
        tomorrow = today + timedelta(days=1)
        this_month_start = today.replace(day=1)
        next_month_start = _next_month_start(this_month_start)
        last_30_start = today - timedelta(days=30)

        # ✅ Preserve existing query params (like q, category, etc.) while changing date range
        base_get = request.GET

        quick_filters = {
            "today": _safe_querystring(base_get, date__gte=str(today), date__lt=str(tomorrow)),
            "this_month": _safe_querystring(
                base_get, date__gte=str(this_month_start), date__lt=str(next_month_start)
            ),
            "last_30": _safe_querystring(base_get, date__gte=str(last_30_start), date__lt=str(tomorrow)),
            "clear": "?",  # full clear
        }

        # Month options (last 12 months) for "Pick month" UI in template
        month_options = []
        cursor = this_month_start
        for _ in range(12):
            m_start = cursor
            m_next = _next_month_start(m_start)
            month_options.append(
                {
                    "label": m_start.strftime("%b %Y"),
                    "year": m_start.year,
                    "month": m_start.month,
                    "url": _safe_querystring(base_get, date__gte=str(m_start), date__lt=str(m_next)),
                }
            )
            # go back one month
            if cursor.month == 1:
                cursor = cursor.replace(year=cursor.year - 1, month=12, day=1)
            else:
                cursor = cursor.replace(month=cursor.month - 1, day=1)

        extra_context = extra_context or {}
        extra_context["summary"] = {
            "title": "Total Expenses",
            "usd": total_usd,
            "pkr": total_pkr,
            "count": count,
            "top_category": top_category,
            "top_usd": top_usd,
            "top_pkr": top_pkr,
            "breakdown": breakdown_rows,
            # charts
            "trend_labels": trend_labels,
            "trend_usd": trend_usd,
            "trend_pkr": trend_pkr,
            "trend_cnt": trend_cnt,
            # widgets
            "top_employees": list(top_employees),
            "recent": recent,
            # quick links
            "quick_filters": quick_filters,
            "month_options": month_options,
            # helper for pick date default
            "today_iso": str(today),
            "settlement": _settlement_for_records(None, qs),
        }

        return super().changelist_view(request, extra_context=extra_context)

    def save_model(self, request, obj, form, change):
        pkr = form.cleaned_data.get("amount_pkr_input")
        if pkr is not None:
            obj.amount_usd = _pkr_to_usd(pkr)
            obj.amount_pkr = pkr
        if not obj.paid_by_id:
            obj.paid_by = request.user
        obj.save(request=request)

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if "paid_by" in form.base_fields:
            if getattr(request.user, "role", None) == "pm":
                form.base_fields["paid_by"].queryset = Employee.objects.filter(pk=request.user.pk)
                form.base_fields["paid_by"].initial = request.user.pk
                form.base_fields["paid_by"].disabled = True
            else:
                form.base_fields["paid_by"].queryset = Employee.objects.all().order_by("full_name", "email")
                if not form.base_fields["paid_by"].initial:
                    form.base_fields["paid_by"].initial = request.user.pk
        return form

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "preview/<int:pk>/",
                self.admin_site.admin_view(self.preview_expense),
                name="payroll_expense_preview",
            ),
            path(
                "invoice/<int:pk>/",
                self.admin_site.admin_view(self.invoice_expense_pdf),
                name="payroll_expense_invoice",
            ),
        ]
        return custom + urls

    def preview_expense(self, request, pk):
        obj = self.get_queryset(request).filter(pk=pk).select_related("employee", "paid_by").first()
        if not obj:
            return JsonResponse({"ok": False}, status=404)
        data = {
            "ok": True,
            "employee": getattr(obj.employee, "full_name", str(obj.employee)),
            "paid_by": getattr(obj.paid_by, "full_name", str(obj.paid_by)) if obj.paid_by else "-",
            "category": obj.get_category_display(),
            "amount_usd": fmt_money(obj.amount_usd, "USD"),
            "amount_pkr": fmt_money(obj.amount_pkr, "PKR"),
            "date": str(obj.date),
            "notes": obj.notes or "-",
        }
        return JsonResponse(data)

    def invoice_expense_pdf(self, request, pk):
        obj = self.get_queryset(request).filter(pk=pk).select_related("employee", "paid_by").first()
        if not obj:
            return JsonResponse({"ok": False}, status=404)
        rows = [
            ("Employee", getattr(obj.employee, "full_name", obj.employee)),
            ("Paid By", getattr(obj.paid_by, "full_name", obj.paid_by) if obj.paid_by else "-"),
            ("Category", obj.get_category_display()),
            ("Amount PKR", fmt_money(obj.amount_pkr, "PKR")),
            ("Amount USD", fmt_money(obj.amount_usd, "USD")),
            ("Date", obj.date),
            ("Notes", obj.notes or "-", True),
        ]
        pdf = _invoice_pdf("Expense Invoice", rows)
        response = HttpResponse(pdf, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="expense_{obj.pk}.pdf"'
        return response

    @admin.display(description="Preview")
    def preview_btn(self, obj):
        return format_html(
            '<button type="button" class="preview-btn" data-preview-id="{}">Preview</button>',
            obj.pk,
        )
    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        extra_context = extra_context or {}
        extra_context["pkr_rate"] = GlobalSetting.current_rate()
        return super().changeform_view(request, object_id, form_url, extra_context=extra_context)

    def has_module_permission(self, request):
        if not request.user.is_authenticated:
            return False
        if request.user.is_superuser or getattr(request.user, "role", None) == "admin":
            return True
        return request.user.has_perm("payroll.view_expense")

    def has_view_permission(self, request, obj=None):
        return self.has_module_permission(request)

    def amount_usd_fmt(self, obj):
        return fmt_money(obj.amount_usd, "USD")

    def amount_pkr_fmt(self, obj):
        return fmt_money(obj.amount_pkr, "PKR")

    def short_notes(self, obj):
        return (
            (obj.notes[:60] + "…")
            if obj.notes and len(obj.notes) > 60
            else (obj.notes or "—")
        )

    amount_usd_fmt.short_description = "Amount (USD)"
    amount_pkr_fmt.short_description = "Amount (PKR)"
    short_notes.short_description = "Notes"
