from decimal import Decimal, ROUND_HALF_UP
from django.db import models
from django.utils import timezone
from django.core.validators import MinValueValidator
from django.core.exceptions import PermissionDenied

# IMPORTANT: adjust if your Employee model path is different
from accounts.models import Employee, Team


def quantize2(value: Decimal) -> Decimal:
    if value is None:
        return None
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ---------------------------
# Global USD→PKR Rate
# ---------------------------
class GlobalSetting(models.Model):
    """
    Single row table storing global USD→PKR rate.
    Keep multiple rows (history) — always use the latest.
    """
    usd_to_pkr_rate = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        default=280.0000,
        validators=[MinValueValidator(Decimal("0.0001"))],
        help_text="How many PKR in 1 USD (e.g., 277.0000)."
    )
    note = models.CharField(max_length=255, blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return f"USD→PKR {self.usd_to_pkr_rate} (updated {self.updated_at:%Y-%m-%d %H:%M})"

    @classmethod
    def current_rate(cls) -> Decimal:
        obj = cls.objects.order_by("-updated_at").first()
        return obj.usd_to_pkr_rate if obj else Decimal("1.0000")


# ---------------------------
# Employee Salary
# ---------------------------
class EmployeeSalary(models.Model):
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="salary_profiles",   # (not salary_profile)
    )
    paid_by = models.ForeignKey(
        Employee,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="paid_employee_salaries",
    )

    # store which month this salary is for (recommended)
    salary_month = models.DateField(default="2024-01-01")
    effective_from = models.DateField() # Or DateTimeField()
    monthly_salary_usd = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    monthly_salary_pkr = models.DecimalField(max_digits=14, decimal_places=2, default=0.00, editable=False)

    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Employee Monthly Salary"
        verbose_name_plural = "Employee Monthly Salaries"
        ordering = ["-salary_month", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "salary_month"],
                name="uniq_employee_salary_month"
            )
        ]

    def __str__(self):
        return f"{self.employee} — {self.salary_month:%b %Y} — {self.monthly_salary_usd} USD"

    def save(self, *args, **kwargs):
        rate = GlobalSetting.current_rate()
        self.monthly_salary_pkr = quantize2(Decimal(self.monthly_salary_usd) * rate)

        request = kwargs.pop("request", None)
        if request and hasattr(request, "user") and not self.paid_by_id:
            self.paid_by = request.user
        if request and hasattr(request, "user") and request.user.role == "pm":
            teams = Team.objects.filter(project_manager=request.user)
            allowed_ids = teams.values_list("members__id", flat=True)
            if self.employee.id not in allowed_ids:
                raise PermissionDenied("You can only manage salaries for your own team.")

        super().save(*args, **kwargs)

# ---------------------------
# PM Responsibility %
# ---------------------------
class PMResponsibility(models.Model):
    """
    Stores salary responsibility % per PM.
    """
    pm = models.OneToOneField(
        Employee,
        on_delete=models.CASCADE,
        limit_choices_to={'role': 'pm'},
        related_name="responsibility_profile"
    )
    percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=50.00,  # default 50%
        validators=[MinValueValidator(Decimal("0.01"))]
    )

    def __str__(self):
        return f"{self.pm} — {self.percentage}% responsibility"


# ---------------------------
# Salary Payment (Credits)
# ---------------------------
class SalaryPayment(models.Model):
    """
    Actual salary payments made to an employee.
    """
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="salary_payments",
        default=1
    )
    paid_by = models.ForeignKey(
        Employee,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="paid_salary_payments",
    )
    amount_usd = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0.00,
        validators=[MinValueValidator(Decimal("0.01"))]
    )
    amount_pkr = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=0.00,
        editable=False
    )
    admin_share_usd = models.DecimalField(max_digits=12, decimal_places=2, default=0.00, editable=False)
    pm_share_usd = models.DecimalField(max_digits=12, decimal_places=2, default=0.00, editable=False)
    date_paid = models.DateField(default=timezone.now)
    reference = models.CharField(max_length=120, blank=True, default="")
    note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date_paid", "-id"]

    def __str__(self):
        return f"{self.employee} — paid {self.amount_usd} USD on {self.date_paid}"

    def save(self, *args, **kwargs):
        rate = GlobalSetting.current_rate()
        self.amount_pkr = quantize2(Decimal(self.amount_usd) * rate)

        request = kwargs.pop("request", None)
        pm_percentage = Decimal("0.00")
        if request and hasattr(request, "user") and not self.paid_by_id:
            self.paid_by = request.user
        pm_user = None

        if request and hasattr(request, "user") and request.user.role == "pm":
            pm_user = request.user
            # PM can only pay their team members
            teams = Team.objects.filter(project_manager=request.user)
            allowed_ids = teams.values_list("members__id", flat=True)
            if self.employee.id not in allowed_ids:
                raise PermissionDenied("You can only manage salary payments for your own team.")
        else:
            pm_user = (
                Team.objects.filter(members=self.employee)
                .values_list("project_manager", flat=True)
                .first()
            )

        if pm_user:
            try:
                pm_percentage = PMSalaryShare.objects.get(pm_id=pm_user).share_percentage
            except PMSalaryShare.DoesNotExist:
                try:
                    pm_percentage = PMResponsibility.objects.get(pm_id=pm_user).percentage
                except PMResponsibility.DoesNotExist:
                    pm_percentage = Decimal("50.00")

        self.pm_share_usd = quantize2(self.amount_usd * pm_percentage / 100)
        self.admin_share_usd = quantize2(self.amount_usd - self.pm_share_usd)

        super().save(*args, **kwargs)


# ---------------------------
# Employee Expenses (Debits)
# ---------------------------
class Expense(models.Model):
    """
    Employee-linked expenses (debits)
    """
    ADVANCE = "ADVANCE"
    UPWORK_CONNECTS = "UPWORK_CONNECTS"
    UPWORK_JOB = "UPWORK_JOB"
    OTHER = "OTHER"

    CATEGORY_CHOICES = [
        (ADVANCE, "Advance Taken"),
        (UPWORK_CONNECTS, "Upwork Connects"),
        (UPWORK_JOB, "Paid Upwork Jobs"),
        (OTHER, "Other Expense"),
    ]

    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="expenses",
        default=1
    )
    paid_by = models.ForeignKey(
        Employee,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="paid_expenses",
    )
    category = models.CharField(
        max_length=32,
        choices=CATEGORY_CHOICES,
        default=OTHER
    )
    amount_usd = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0.00,
        validators=[MinValueValidator(Decimal("0.01"))]
    )
    amount_pkr = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=0.00,
        editable=False
    )
    notes = models.TextField(blank=True, default="")
    date = models.DateField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return f"{self.employee} — {self.get_category_display()} — {self.amount_usd} USD"

    def save(self, *args, **kwargs):
        rate = GlobalSetting.current_rate()
        self.amount_pkr = quantize2(Decimal(self.amount_usd) * rate)

        # PM restriction
        request = kwargs.pop("request", None)
        if request and hasattr(request, "user") and not self.paid_by_id:
            self.paid_by = request.user
        if request and hasattr(request, "user") and request.user.role == "pm":
            teams = Team.objects.filter(project_manager=request.user)
            allowed_ids = teams.values_list("members__id", flat=True)
            if self.employee.id not in allowed_ids:
                raise PermissionDenied("You can only manage expenses for your own team.")

        super().save(*args, **kwargs)
class PMSalaryShare(models.Model):
    """
    Admin sets the percentage of salary responsibility for each PM.
    """
    pm = models.ForeignKey(
        Employee,
        limit_choices_to={"role": "pm"},
        on_delete=models.CASCADE,
        related_name="salary_shares"
    )
    share_percentage = models.DecimalField(
        max_digits=5, decimal_places=2,
        default=50.00,
        help_text="Percentage of salary responsibility for this PM (0-100%)."
    )
    note = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        unique_together = ("pm",)
    def __str__(self):
        return f"{self.pm.full_name} — {self.share_percentage}%"
