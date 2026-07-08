from django.conf import settings
from django.db import models
from django.utils import timezone


class Project(models.Model):
    STATUS_CHOICES = [
        ("active", "Active"),
        ("completed", "Completed"),
        ("on_hold", "On Hold"),
    ]

    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    upwork_profile_url = models.URLField(max_length=300, blank=True)
    upwork_profile_name = models.CharField(max_length=150, blank=True)
    hourly_rate_usd = models.DecimalField("Hourly rate from client (USD)", max_digits=8, decimal_places=2, null=True, blank=True)
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
