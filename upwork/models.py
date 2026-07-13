from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models

DEFAULT_CONNECT_RATE = Decimal("0.15")


class UpworkSetting(models.Model):
    """Admin-controlled price of a single Upwork connect (USD)."""

    connect_rate = models.DecimalField(
        max_digits=8,
        decimal_places=4,
        default=DEFAULT_CONNECT_RATE,
        validators=[MinValueValidator(Decimal("0"))],
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Upwork Setting"
        verbose_name_plural = "Upwork Settings"

    def __str__(self):
        return f"Connect rate: ${self.connect_rate}"

    @classmethod
    def current_rate(cls):
        setting = cls.objects.order_by("-updated_at").first()
        return setting.connect_rate if setting else DEFAULT_CONNECT_RATE


class UpworkProfile(models.Model):
    """An Upwork profile created by admin and assigned to one PM.

    A profile (and all its tracking data) is visible only to its PM and to admins.
    """

    name = models.CharField(max_length=150, unique=True)
    project_manager = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="upwork_profiles",
        limit_choices_to={"role": "pm"},
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class UpworkJobEntry(models.Model):
    """One row of daily bidding stats per profile (one entry per profile per date)."""

    profile = models.ForeignKey(UpworkProfile, on_delete=models.CASCADE, related_name="entries")
    date = models.DateField()

    jobs_applied = models.PositiveIntegerField(default=0)
    proposal_views = models.PositiveIntegerField(default=0)
    responses = models.PositiveIntegerField(default=0)
    offers = models.PositiveIntegerField(default=0)
    hired = models.PositiveIntegerField(default=0)
    connects_used = models.PositiveIntegerField(default=0)

    # Rate snapshotted when the entry is first saved so historical spend
    # never changes when the admin updates the global rate.
    connect_rate = models.DecimalField(max_digits=8, decimal_places=4, default=DEFAULT_CONNECT_RATE)
    amount_spent = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="upwork_entries_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date"]
        constraints = [
            models.UniqueConstraint(fields=["profile", "date"], name="unique_profile_date_entry"),
        ]
        verbose_name = "Upwork Job Entry"
        verbose_name_plural = "Upwork Job Entries"

    def __str__(self):
        return f"{self.profile.name} — {self.date}"

    def save(self, *args, **kwargs):
        if self._state.adding:
            self.connect_rate = UpworkSetting.current_rate()
        self.amount_spent = (Decimal(self.connects_used) * self.connect_rate).quantize(Decimal("0.01"))
        super().save(*args, **kwargs)
