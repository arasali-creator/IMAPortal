from django.conf import settings
from django.db import models
from django.utils import timezone


class Project(models.Model):
    STATUS_CHOICES = [
        ("active", "Active"),
        ("completed", "Completed"),
        ("on_hold", "On Hold"),
    ]
    BILLING_CHOICES = [
        ("hourly", "Hourly"),
        ("fixed", "Fixed Price"),
    ]

    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    upwork_profile_url = models.URLField(max_length=300, blank=True)
    upwork_profile_name = models.CharField(max_length=150, blank=True)
    billing_type = models.CharField("Project type", max_length=10, choices=BILLING_CHOICES, default="hourly")
    hourly_rate_usd = models.DecimalField("Hourly rate from client (USD)", max_digits=8, decimal_places=2, null=True, blank=True)
    fixed_price_usd = models.DecimalField("Fixed price (USD)", max_digits=10, decimal_places=2, null=True, blank=True)
    allowed_hours = models.DecimalField(
        "Allowed hours (budget)", max_digits=7, decimal_places=2, null=True, blank=True,
        help_text="Total hours the team may log on this project. Leave blank for unlimited.",
    )
    client_joined_date = models.DateField("Date of joining the client", null=True, blank=True)
    entries_required = models.PositiveIntegerField("Number of entries to do", default=0)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default="active")

    project_manager = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="managed_projects",
        limit_choices_to={"role__in": ["pm", "admin"]},
    )
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="assigned_projects",
        blank=True,
        limit_choices_to={"role": "employee"},
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.name

    def total_seconds_logged(self):
        return sum(log.duration_seconds() for log in self.time_logs.all())

    def budget_seconds(self):
        """Hours budget in seconds, or None when unlimited."""
        if self.allowed_hours is None:
            return None
        return int(self.allowed_hours * 3600)

    def remaining_seconds(self):
        """Seconds left in the budget (can be negative), or None when unlimited."""
        budget = self.budget_seconds()
        if budget is None:
            return None
        return budget - self.total_seconds_logged()


class ProjectTimeLog(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="time_logs")
    employee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="project_time_logs")
    started_at = models.DateTimeField(default=timezone.now)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        return f"{self.employee} on {self.project} @ {self.started_at:%Y-%m-%d %H:%M}"

    @property
    def is_running(self):
        return self.ended_at is None

    def duration_seconds(self):
        end = self.ended_at or timezone.now()
        return int((end - self.started_at).total_seconds())


class ExtraHoursRequest(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("approved", "Approved"),
        ("declined", "Declined"),
    ]

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="extra_hours_requests")
    employee = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="extra_hours_requests"
    )
    hours = models.DecimalField("Extra hours requested", max_digits=6, decimal_places=2)
    reason = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="pending")
    created_at = models.DateTimeField(auto_now_add=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.employee} requests {self.hours}h on {self.project} ({self.status})"
