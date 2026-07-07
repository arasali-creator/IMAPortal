from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


DEFAULT_USD_TO_PKR = Decimal("280.00")


class PayrollGlobalSetting(models.Model):
    usd_to_pkr_rate = models.DecimalField(max_digits=10, decimal_places=2, default=DEFAULT_USD_TO_PKR)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Payroll Global Setting"
        verbose_name_plural = "Payroll Global Settings"

    def __str__(self):
        return f"USD to PKR: {self.usd_to_pkr_rate}"

    @classmethod
    def current_rate(cls):
        setting = cls.objects.order_by("-updated_at").first()
        return setting.usd_to_pkr_rate if setting else DEFAULT_USD_TO_PKR


class PMSplitSetting(models.Model):
    pm = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="pm_split_setting",
        limit_choices_to={"role": "pm"},
    )
    pm_share_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("50.00"),
        validators=[MinValueValidator(Decimal("0.00")), MaxValueValidator(Decimal("100.00"))],
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "PM Split Setting"
        verbose_name_plural = "PM Split Settings"

    def __str__(self):
        return f"{self.pm} - {self.pm_share_percent}%"

    @property
    def ceo_share_percent(self):
        return Decimal("100.00") - self.pm_share_percent


class PMIncome(models.Model):
    SOURCE_CHOICES = [
        ("upwork", "Upwork"),
    ]

    pm = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="pm_incomes",
        limit_choices_to={"role": "pm"},
    )
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default="upwork")
    description = models.CharField(max_length=255, blank=True)
    amount_usd = models.DecimalField(max_digits=12, decimal_places=2)
    rate_usd_to_pkr = models.DecimalField(max_digits=10, decimal_places=2, default=DEFAULT_USD_TO_PKR)
    pm_share_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("50.00"),
        validators=[MinValueValidator(Decimal("0.00")), MaxValueValidator(Decimal("100.00"))],
    )
    income_date = models.DateField(default=timezone.localdate)
    withdrawn_by_ceo = models.BooleanField(default=True)
    withdrawn_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pm_income_withdrawn_by",
        limit_choices_to={"role__in": ["pm", "admin"]},
    )
    withdrawn_at = models.DateField(blank=True, null=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_pm_incomes",
        limit_choices_to={"role": "admin"},
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-income_date", "-created_at"]

    def __str__(self):
        return f"{self.pm} - {self.amount_usd} USD"

    @property
    def amount_pkr(self):
        return (self.amount_usd or Decimal("0.00")) * (self.rate_usd_to_pkr or Decimal("0.00"))

    @property
    def pm_share_usd(self):
        return (self.amount_usd or Decimal("0.00")) * (self.pm_share_percent or Decimal("0.00")) / Decimal("100.00")

    @property
    def ceo_share_usd(self):
        return (self.amount_usd or Decimal("0.00")) - self.pm_share_usd

    @property
    def pm_share_pkr(self):
        return self.pm_share_usd * (self.rate_usd_to_pkr or Decimal("0.00"))

    @property
    def ceo_share_pkr(self):
        return self.ceo_share_usd * (self.rate_usd_to_pkr or Decimal("0.00"))

    def save(self, *args, **kwargs):
        if self.pm_share_percent is None:
            setting = getattr(self.pm, "pm_split_setting", None)
            if setting:
                self.pm_share_percent = setting.pm_share_percent
        if self.withdrawn_by_ceo and not self.withdrawn_at:
            self.withdrawn_at = self.income_date
        super().save(*args, **kwargs)


class PMAdvance(models.Model):
    ADVANCE_TYPE_CHOICES = [
        ("upwork_job_paid", "Upwork job paid"),
        ("upwork_connects", "Upwork connects"),
        ("cash_taken", "Cash taken"),
        ("online_taken", "Online taken"),
    ]

    pm = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="pm_advances",
        limit_choices_to={"role": "pm"},
    )
    advance_type = models.CharField(max_length=30, choices=ADVANCE_TYPE_CHOICES)
    amount_pkr = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    advance_date = models.DateField(default=timezone.localdate)
    notes = models.CharField(max_length=255, blank=True)
    paid_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pm_advances_paid_by",
        limit_choices_to={"role__in": ["pm", "admin"]},
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_pm_advances",
        limit_choices_to={"role": "admin"},
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-advance_date", "-created_at"]

    def __str__(self):
        return f"{self.pm} - {self.get_advance_type_display()} - {self.amount_pkr} PKR"

    @property
    def amount_usd(self):
        rate = PayrollGlobalSetting.current_rate()
        if not rate:
            return Decimal("0.00")
        return (self.amount_pkr or Decimal("0.00")) / rate


class Branch(models.Model):
    name = models.CharField(max_length=150, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class FixedExpense(models.Model):
    branch = models.ForeignKey(
        "Branch", on_delete=models.CASCADE, related_name="fixed_expenses", null=True, blank=True
    )
    name = models.CharField(max_length=150)
    EXPENSE_TYPE_CHOICES = [
        ("fixed", "Fixed"),
        ("other", "Other expense"),
    ]
    amount_pkr = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    expense_type = models.CharField(max_length=10, choices=EXPENSE_TYPE_CHOICES, default="fixed")
    day_of_month = models.PositiveSmallIntegerField(default=1)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        unique_together = ("branch", "name")

    def __str__(self):
        return f"{self.branch} - {self.name} ({self.amount_pkr} PKR)"


class BranchExpense(models.Model):
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="expenses")
    note = models.CharField(max_length=255)
    amount_pkr = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    paid_date = models.DateField(default=timezone.localdate)
    paid_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="branch_expenses_paid",
        limit_choices_to={"role__in": ["pm", "admin"]},
    )
    fixed_expense = models.ForeignKey(
        FixedExpense, on_delete=models.SET_NULL, null=True, blank=True, related_name="payments"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-paid_date", "-created_at"]

    def __str__(self):
        return f"{self.branch} - {self.amount_pkr} PKR"


class EmployeeSalary(models.Model):
    SALARY_TYPE_CHOICES = [
        ("fixed_budget", "Fix Budget"),
        ("timer", "Timer"),
    ]

    pm = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="employee_salary_records",
        limit_choices_to={"role": "pm"},
    )
    employee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="salary_records",
        limit_choices_to={"role": "employee"},
    )
    salary_type = models.CharField(max_length=20, choices=SALARY_TYPE_CHOICES)
    upwork_profile_name = models.CharField(max_length=150)
    project_name = models.CharField(max_length=150)
    entries_email = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    per_entry_rate = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    number_of_hours = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    per_hour_rate = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    work_date = models.DateField(default=timezone.localdate)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_employee_salary_records",
        limit_choices_to={"role__in": ["pm", "admin"]},
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-work_date", "-created_at"]
        db_table = "payroll_pm_employee_salary"

    def __str__(self):
        return f"{self.employee} - {self.get_salary_type_display()} - {self.income_amount} PKR"

    @property
    def income_amount(self):
        if self.salary_type == "fixed_budget":
            return (self.entries_email or Decimal("0.00")) * (self.per_entry_rate or Decimal("0.00"))
        return (self.number_of_hours or Decimal("0.00")) * (self.per_hour_rate or Decimal("0.00"))

    def clean(self):
        from accounts.models import Team

        if self.pm_id and self.employee_id:
            is_team_member = Team.objects.filter(project_manager_id=self.pm_id, members=self.employee_id).exists()
            if not is_team_member:
                raise ValidationError({"employee": "Selected employee is not part of this PM's team."})

        if self.salary_type == "fixed_budget":
            if self.entries_email is None or self.per_entry_rate is None:
                raise ValidationError("Entries/Email and Per Entry Rate are required for Fix Budget.")
            self.number_of_hours = None
            self.per_hour_rate = None
        elif self.salary_type == "timer":
            if self.number_of_hours is None or self.per_hour_rate is None:
                raise ValidationError("Number of Hours and Per Hour Rate are required for Timer.")
            self.entries_email = None
            self.per_entry_rate = None
        else:
            raise ValidationError({"salary_type": "Invalid salary type."})


class EmployeeSalaryExpense(models.Model):
    EXPENSE_TYPE_CHOICES = [
        ("mess_hostel", "Mess + Hostel Expenses"),
        ("advance_taken", "Advance taken"),
        ("fines", "Fines"),
        ("other", "Other expenses"),
    ]

    pm = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="employee_salary_expenses",
        limit_choices_to={"role": "pm"},
    )
    employee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="salary_expenses",
        limit_choices_to={"role": "employee"},
    )
    expense_type = models.CharField(max_length=20, choices=EXPENSE_TYPE_CHOICES)
    note = models.CharField(max_length=255, blank=True)
    amount_pkr = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    paid_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employee_salary_expenses_paid_by",
        limit_choices_to={"role__in": ["pm", "admin"]},
    )
    paid_date = models.DateField(default=timezone.localdate)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_employee_salary_expenses",
        limit_choices_to={"role__in": ["pm", "admin"]},
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-paid_date", "-created_at"]
        db_table = "payroll_pm_employee_salary_expense"

    def __str__(self):
        return f"{self.employee} - {self.get_expense_type_display()} - {self.amount_pkr} PKR"

    def clean(self):
        from accounts.models import Team

        if self.pm_id and self.employee_id:
            is_team_member = Team.objects.filter(project_manager_id=self.pm_id, members=self.employee_id).exists()
            if not is_team_member:
                raise ValidationError({"employee": "Selected employee is not part of this PM's team."})


class EmployeeSalaryPayment(models.Model):
    pm = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="employee_salary_payments",
        limit_choices_to={"role": "pm"},
    )
    employee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="salary_payments",
        limit_choices_to={"role": "employee"},
    )
    amount_pkr = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    note = models.CharField(max_length=255, blank=True)
    paid_date = models.DateField(default=timezone.localdate)
    paid_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employee_salary_paid_by",
        limit_choices_to={"role__in": ["pm", "admin"]},
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_employee_salary_payments",
        limit_choices_to={"role__in": ["pm", "admin"]},
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-paid_date", "-created_at"]
        db_table = "payroll_pm_employee_salary_payment"

    def __str__(self):
        return f"{self.employee} - Salary Paid - {self.amount_pkr} PKR"

    def clean(self):
        from accounts.models import Team

        if self.pm_id and self.employee_id:
            is_team_member = Team.objects.filter(project_manager_id=self.pm_id, members=self.employee_id).exists()
            if not is_team_member:
                raise ValidationError({"employee": "Selected employee is not part of this PM's team."})
